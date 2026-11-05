# -*- coding: utf-8 -*-
"""DOCX -> PDF conversion and page-count probing.

The visual QA used to depend on LibreOffice alone. On Windows, WPS Office ships a
command-line converter (`kwpsconvert.exe word2pdf`) and a `pdfinfo` probe that return
real page counts, which makes pagination verification possible without PyMuPDF.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Optional, Tuple

_BACKEND_WPS = "wps"
_BACKEND_LIBREOFFICE = "libreoffice"
_BACKEND_NONE = "none"

_WPS_PATTERNS = (
    r"C:\Program Files\WPS Office\*\office6\kwpsconvert.exe",
    r"C:\Program Files (x86)\WPS\WPS Office\*\office6\kwpsconvert.exe",
    r"C:\Program Files (x86)\Kingsoft\WPS Office\*\office6\kwpsconvert.exe",
    r"C:\Program Files\Kingsoft\WPS Office\*\office6\kwpsconvert.exe",
    os.path.expanduser(r"~\AppData\Local\Kingsoft\WPS Office\*\office6\kwpsconvert.exe"),
    os.path.expanduser(r"~\AppData\Local\WPS Office\*\office6\kwpsconvert.exe"),
)


def _version_key(path: str):
    return [int(part) if part.isdigit() else part for part in re.split(r"[\\/.\-_ ]", path)]


def find_wps_converter() -> Optional[str]:
    env = os.environ.get("OFFICECLI_WPS_CONVERTER") or os.environ.get("WPS_CONVERTER")
    candidates = [env, shutil.which("kwpsconvert.exe"), shutil.which("kwpsconvert")]
    for pattern in _WPS_PATTERNS:
        candidates.extend(glob.glob(pattern))
    existing = [path for path in candidates if path and os.path.isfile(path)]
    if not existing:
        return None
    return sorted(existing, key=_version_key)[-1]


def find_pdf_backend() -> Dict[str, Any]:
    """Prefer WPS (real pagination + pdfinfo) over LibreOffice; allow an explicit override."""
    requested = str(os.environ.get("OFFICECLI_PDF_BACKEND") or "auto").strip().lower()
    if requested in ("none", "off", "disabled"):
        return {"name": _BACKEND_NONE, "executable": None}

    wps = find_wps_converter()
    soffice = shutil.which("soffice") or shutil.which("libreoffice")

    if requested == _BACKEND_WPS:
        return {"name": _BACKEND_WPS, "executable": wps} if wps else {"name": _BACKEND_NONE, "executable": None}
    if requested == _BACKEND_LIBREOFFICE:
        return (
            {"name": _BACKEND_LIBREOFFICE, "executable": soffice}
            if soffice
            else {"name": _BACKEND_NONE, "executable": None}
        )
    if wps:
        return {"name": _BACKEND_WPS, "executable": wps}
    if soffice:
        return {"name": _BACKEND_LIBREOFFICE, "executable": soffice}
    return {"name": _BACKEND_NONE, "executable": None}


def _error_from_process(returncode: int, stdout: str, stderr: str) -> str:
    detail = (stderr or stdout or "").strip().splitlines()
    message = detail[-1] if detail else ""
    if returncode in (100, 101):
        return f"WPS_VIP_REQUIRED (exit={returncode}) {message}".strip()
    return f"exit={returncode}: {message}".strip()


def _run(command, timeout: int) -> Tuple[int, str, str]:
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _convert_with_wps(executable: str, source: str, pdf_path: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        os.remove(pdf_path)
    except OSError:
        pass
    try:
        returncode, stdout, stderr = _run(
            [executable, "word2pdf", source, "-o", pdf_path, "--json"], timeout=240
        )
    except subprocess.TimeoutExpired:
        return None, "WPS word2pdf timed out after 240s"
    except OSError as exc:
        return None, f"WPS word2pdf failed to start: {exc}"
    if returncode == 0 and os.path.isfile(pdf_path):
        return pdf_path, None
    return None, _error_from_process(returncode, stdout, stderr)


def libreoffice_user_installation_arg(profile_dir: str) -> str:
    """`-env:UserInstallation` startup arg pinning soffice to a private profile.

    Concurrent or back-to-back LibreOffice invocations share one default user
    profile; the profile lock then serializes or hangs them (audit P2-04
    stall). Each conversion gets its own profile directory, removed by the
    caller's TemporaryDirectory when done.
    """
    import pathlib

    return "-env:UserInstallation=" + pathlib.Path(profile_dir).as_uri()


def _convert_with_libreoffice(executable: str, source: str, out_dir: str, pdf_path: str) -> Tuple[Optional[str], Optional[str]]:
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory(prefix="lo-profile-") as profile_dir:
        try:
            returncode, stdout, stderr = _run(
                [
                    executable,
                    libreoffice_user_installation_arg(profile_dir),
                    "--headless", "--convert-to", "pdf", "--outdir", out_dir, source,
                ],
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return None, "LibreOffice PDF conversion timed out after 180s"
        except OSError as exc:
            return None, f"LibreOffice failed to start: {exc}"
    candidate = os.path.join(out_dir, os.path.splitext(os.path.basename(source))[0] + ".pdf")
    if returncode == 0 and os.path.isfile(candidate):
        if os.path.normcase(candidate) != os.path.normcase(pdf_path):
            try:
                os.replace(candidate, pdf_path)
            except OSError as exc:
                return None, f"LibreOffice produced {candidate} but it could not be moved: {exc}"
        return pdf_path, None
    return None, _error_from_process(returncode, stdout, stderr)


def convert_docx_to_pdf(
    docx_path: str,
    out_dir: str,
    backend: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str], str]:
    """Convert a DOCX to PDF using the selected backend. Returns `(pdf, error, backend_name)`."""
    backend = backend or find_pdf_backend()
    name = backend.get("name") or _BACKEND_NONE
    executable = backend.get("executable")
    if name == _BACKEND_NONE or not executable:
        return None, "NO_PDF_BACKEND", _BACKEND_NONE

    os.makedirs(out_dir, exist_ok=True)
    # Convert a private copy: a preview process can hold the original path locked.
    # The copy holds the FULL source document, so every return path (success, WPS
    # failure, LibreOffice failure, timeout, unknown backend) must remove it: a
    # leftover copy inside the output directory can be synced, packaged or
    # delivered and would extend the document's lifetime beyond the task (W3-1).
    source_dir = tempfile.mkdtemp(prefix="pdf-src-", dir=out_dir)
    try:
        source = os.path.join(source_dir, os.path.basename(docx_path))
        try:
            shutil.copy2(docx_path, source)
        except OSError as exc:
            return None, f"SOURCE_COPY_FAILED: {exc}", name
        pdf_path = os.path.join(out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")

        if name == _BACKEND_WPS:
            return (*_convert_with_wps(executable, source, pdf_path), name)
        if name == _BACKEND_LIBREOFFICE:
            return (*_convert_with_libreoffice(executable, source, out_dir, pdf_path), name)
        return None, f"UNKNOWN_PDF_BACKEND: {name}", name
    finally:
        # ignore_errors keeps cleanup failures from masking the conversion result;
        # the conversion (or its exception) is always what the caller observes.
        shutil.rmtree(source_dir, ignore_errors=True)


def pdf_page_count(pdf_path: str, backend: Optional[Dict[str, Any]] = None) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Return `(page_count, source, error)`; tries PyMuPDF, then WPS pdfinfo, then poppler."""
    try:
        import fitz  # PyMuPDF, optional

        document = fitz.open(pdf_path)
        try:
            return int(document.page_count), "pymupdf", None
        finally:
            document.close()
    except Exception:
        pass

    backend = backend or find_pdf_backend()
    if backend.get("name") == _BACKEND_WPS and backend.get("executable"):
        try:
            returncode, stdout, stderr = _run(
                [backend["executable"], "pdfinfo", pdf_path, "--json"], timeout=60
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, "wps_pdfinfo", f"{type(exc).__name__}: {exc}"
        if returncode == 0:
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
                count = payload.get("page_count")
                if isinstance(count, int):
                    return count, "wps_pdfinfo", None
        return None, "wps_pdfinfo", _error_from_process(returncode, stdout, stderr)

    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        try:
            returncode, stdout, stderr = _run([pdfinfo, pdf_path], timeout=30)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, "pdfinfo", f"{type(exc).__name__}: {exc}"
        if returncode == 0:
            match = re.search(r"Pages:\s*(\d+)", stdout)
            if match:
                return int(match.group(1)), "pdfinfo", None
        return None, "pdfinfo", _error_from_process(returncode, stdout, stderr)

    return None, None, "NO_PDF_PAGE_COUNT_BACKEND"
