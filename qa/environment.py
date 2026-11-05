# -*- coding: utf-8 -*-
"""W2 environment capability detection for Office Skill v4.0.

Declarative expectations live in ``config/environment_capabilities.yaml``; when
PyYAML is not installed, ``config/environment_capabilities.json`` is the
machine-readable source and declares the same values.  This module never lets a
declaration stand in for a verdict: ``required`` comes from the config, while
``status``/``available``/``evidence`` always come from a live probe.  A probe
that cannot run is ``UNVERIFIED``; it is never promoted to ``AVAILABLE``.
"""

from __future__ import annotations

import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List

ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "config" / "environment_capabilities.yaml"
JSON_PATH = ROOT / "config" / "environment_capabilities.json"

STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_UNVERIFIED = "UNVERIFIED"
_STATUSES = (STATUS_AVAILABLE, STATUS_UNAVAILABLE, STATUS_UNVERIFIED)

_DEFAULT_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "docx_parse": {
        "required": True,
        "probe": "python_docx_import",
        "description": "python-docx can import and read .docx packages",
    },
    "docx_write": {
        "required": True,
        "probe": "writable_temp_dir_and_python_docx",
        "description": "a writable temp directory and python-docx are available for staged output",
    },
    "wps_pdf_render": {
        "required": True,
        "probe": "engine.pdf_backend.find_pdf_backend",
        "description": "a DOCX to PDF converter (WPS kwpsconvert or LibreOffice) is installed",
    },
    "pdf_page_analysis": {
        "required": True,
        "probe": "pymupdf_import_or_wps_pdfinfo",
        "description": "PDF page counts can be measured (PyMuPDF or WPS pdfinfo)",
    },
    "pixel_visual_diff": {
        "required": False,
        "probe": "pymupdf_import",
        "description": "PyMuPDF pixmap comparison for page-level pixel diff",
    },
    "ocr": {
        "required": False,
        "probe": "engine.ocr_engine.detect_ocr_backend",
        "description": "an OCR backend (rapidocr / paddleocr / pytesseract + tesseract) is installed",
    },
    "chart_render": {
        "required": False,
        "probe": "engine.chart_render.backend_status",
        "description": "matplotlib can render chart images",
    },
}


def _try_import(module_name: str) -> Any:
    """Import seam so probes can be exercised without touching the real interpreter."""
    return importlib.import_module(module_name)


def _record(probe: str, available: bool, status: str, evidence: str) -> Dict[str, Any]:
    return {
        "probe": probe,
        "available": bool(available),
        "status": status,
        "evidence": evidence,
    }


def _available(probe: str, evidence: str) -> Dict[str, Any]:
    return _record(probe, True, STATUS_AVAILABLE, evidence)


def _unavailable(probe: str, evidence: str) -> Dict[str, Any]:
    return _record(probe, False, STATUS_UNAVAILABLE, evidence)


def _unverified(probe: str, evidence: str) -> Dict[str, Any]:
    return _record(probe, False, STATUS_UNVERIFIED, evidence)


def _probe_docx_parse() -> Dict[str, Any]:
    probe = "python_docx_import"
    try:
        module = _try_import("docx")
    except Exception as exc:
        return _unavailable(probe, "python-docx import failed: %s: %s" % (type(exc).__name__, exc))
    if not hasattr(module, "Document"):
        return _unavailable(probe, "python-docx import ok but it exposes no Document class")
    version = str(getattr(module, "__version__", "") or "unknown")
    return _available(probe, "python-docx %s import ok" % version)


def _probe_docx_write() -> Dict[str, Any]:
    probe = "writable_temp_dir_and_python_docx"
    try:
        with tempfile.TemporaryDirectory(prefix="officecli-capability-") as directory:
            probe_path = os.path.join(directory, "probe.txt")
            with open(probe_path, "w", encoding="utf-8") as handle:
                handle.write("ok")
            os.remove(probe_path)
    except Exception as exc:
        return _unavailable(probe, "temp directory is not writable: %s: %s" % (type(exc).__name__, exc))
    try:
        _try_import("docx")
    except Exception as exc:
        return _unavailable(
            probe,
            "temp directory writable but python-docx import failed: %s: %s" % (type(exc).__name__, exc),
        )
    return _available(probe, "temp directory writable; python-docx import ok")


def _probe_wps_pdf_render() -> Dict[str, Any]:
    probe = "engine.pdf_backend.find_pdf_backend"
    try:
        from engine.pdf_backend import find_pdf_backend
    except Exception as exc:
        return _unverified(probe, "pdf backend module unavailable: %s: %s" % (type(exc).__name__, exc))
    try:
        backend = find_pdf_backend()
    except Exception as exc:
        return _unverified(probe, "pdf backend probe failed: %s: %s" % (type(exc).__name__, exc))
    backend = backend if isinstance(backend, dict) else {}
    name = str(backend.get("name") or "none")
    executable = backend.get("executable")
    if name == "none" or not executable:
        return _unavailable(probe, "NO_PDF_BACKEND: neither WPS kwpsconvert nor LibreOffice was found")
    return _available(probe, "%s backend: %s" % (name, executable))


def _probe_pdf_page_analysis() -> Dict[str, Any]:
    probe = "pymupdf_import_or_wps_pdfinfo"
    try:
        _try_import("fitz")
    except Exception as exc:
        pymupdf_error = "%s: %s" % (type(exc).__name__, exc)
    else:
        return _available(probe, "PyMuPDF import ok (page counts readable)")
    try:
        from engine.pdf_backend import find_pdf_backend
    except Exception as exc:
        return _unverified(
            probe,
            "page-count probe failed: %s: %s (PyMuPDF unavailable: %s)"
            % (type(exc).__name__, exc, pymupdf_error),
        )
    try:
        backend = find_pdf_backend()
    except Exception as exc:
        return _unverified(
            probe,
            "page-count probe failed: %s: %s (PyMuPDF unavailable: %s)"
            % (type(exc).__name__, exc, pymupdf_error),
        )
    backend = backend if isinstance(backend, dict) else {}
    if backend.get("name") == "wps" and backend.get("executable"):
        return _available(
            probe,
            "wps pdfinfo via %s (PyMuPDF unavailable: %s)" % (backend["executable"], pymupdf_error),
        )
    return _unavailable(
        probe, "NO_PDF_PAGE_COUNT_BACKEND (PyMuPDF unavailable: %s)" % pymupdf_error
    )


def _probe_pixel_visual_diff() -> Dict[str, Any]:
    probe = "pymupdf_import"
    try:
        _try_import("fitz")
    except Exception as exc:
        return _unavailable(probe, "PyMuPDF (fitz) import failed: %s: %s" % (type(exc).__name__, exc))
    return _available(probe, "PyMuPDF import ok (pixmap page diff)")


def _probe_ocr() -> Dict[str, Any]:
    probe = "engine.ocr_engine.detect_ocr_backend"
    try:
        from engine.ocr_engine import detect_ocr_backend
    except Exception as exc:
        return _unverified(probe, "OCR module unavailable: %s: %s" % (type(exc).__name__, exc))
    try:
        backend = detect_ocr_backend()
    except Exception as exc:
        return _unverified(probe, "OCR backend probe failed: %s: %s" % (type(exc).__name__, exc))
    backend = backend if isinstance(backend, dict) else {}
    name = str(backend.get("name") or "none")
    if name == "none" or backend.get("reader") is None:
        return _unavailable(probe, "NO_OCR_BACKEND: tried rapidocr, paddleocr, pytesseract+tesseract")
    return _available(probe, "OCR backend: %s" % name)


def _probe_chart_render() -> Dict[str, Any]:
    probe = "engine.chart_render.backend_status"
    try:
        from engine.chart_render import backend_status
    except Exception as exc:
        return _unverified(probe, "chart render module unavailable: %s: %s" % (type(exc).__name__, exc))
    try:
        status = backend_status()
    except Exception as exc:
        return _unverified(probe, "chart render probe failed: %s: %s" % (type(exc).__name__, exc))
    status = status if isinstance(status, dict) else {}
    if not status.get("available"):
        return _unavailable(
            probe,
            "%s: %s" % (status.get("reason") or "RENDER_BACKEND_UNAVAILABLE", status.get("detail") or "matplotlib unavailable"),
        )
    return _available(probe, "matplotlib import ok; CJK font: %s" % (status.get("cjk_font") or "none"))


_PROBES: Dict[str, Callable[[], Dict[str, Any]]] = {
    "docx_parse": _probe_docx_parse,
    "docx_write": _probe_docx_write,
    "wps_pdf_render": _probe_wps_pdf_render,
    "pdf_page_analysis": _probe_pdf_page_analysis,
    "pixel_visual_diff": _probe_pixel_visual_diff,
    "ocr": _probe_ocr,
    "chart_render": _probe_chart_render,
}


def detect_environment() -> Dict[str, Any]:
    """Run every probe and return ``{capability: {available, status, evidence, probe}}``."""
    detected: Dict[str, Any] = {}
    for name, probe in _PROBES.items():
        try:
            detected[name] = probe()
        except Exception as exc:
            detected[name] = _unverified(
                "probe_crash", "%s probe crashed: %s: %s" % (name, type(exc).__name__, exc)
            )
    return detected


def _load_payload() -> Dict[str, Any]:
    """Read the YAML declaration when PyYAML exists, else the JSON mirror."""
    if YAML_PATH.is_file():
        try:
            import yaml  # type: ignore
        except Exception:
            yaml = None  # type: ignore
        if yaml is not None:
            try:
                with open(YAML_PATH, "r", encoding="utf-8") as handle:
                    payload = yaml.safe_load(handle)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                return {"payload": payload, "source": "yaml"}

    if JSON_PATH.is_file():
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return {"payload": payload, "source": "json"}

    return {"payload": None, "source": "built_in_defaults"}


def load_environment_capabilities() -> Dict[str, Any]:
    """Return ``{schema_version, capabilities, source}`` from the declarative config."""
    loaded = _load_payload()
    payload = loaded["payload"]
    declared: Dict[str, Any] = {}
    schema_version = "4.0"
    if isinstance(payload, dict):
        schema_version = str(payload.get("schema_version") or "4.0")
        capabilities = payload.get("capabilities")
        if isinstance(capabilities, dict):
            declared = capabilities

    merged: Dict[str, Dict[str, Any]] = {}
    for name, default in _DEFAULT_CAPABILITIES.items():
        entry = dict(default)
        override = declared.get(name) if isinstance(declared.get(name), dict) else {}
        entry.update({key: value for key, value in override.items() if value is not None})
        entry["required"] = bool(entry.get("required"))
        merged[name] = entry
    for name, override in declared.items():
        if name in merged or not isinstance(override, dict):
            continue
        entry = dict(override)
        entry["required"] = bool(entry.get("required"))
        merged[name] = entry

    return {
        "schema_version": schema_version,
        "capabilities": merged,
        "source": loaded["source"],
    }


def capability_matrix() -> Dict[str, Dict[str, Any]]:
    """Merge declarative ``required`` with live detection into one capability matrix.

    Each entry is ``{required, available, status, evidence}``; ``available`` is
    true only when the probe returned ``AVAILABLE``.
    """
    config = load_environment_capabilities()
    detected = detect_environment()
    matrix: Dict[str, Dict[str, Any]] = {}
    for name, declaration in config["capabilities"].items():
        required = bool(declaration.get("required"))
        detection = detected.get(name)
        if not isinstance(detection, dict):
            matrix[name] = {
                "required": required,
                "available": False,
                "status": STATUS_UNVERIFIED,
                "evidence": "NO_PROBE_IMPLEMENTED: %s" % name,
            }
            continue
        status = str(detection.get("status") or STATUS_UNVERIFIED).upper()
        if status not in _STATUSES:
            status = STATUS_UNVERIFIED
        available = bool(detection.get("available")) and status == STATUS_AVAILABLE
        if available and status != STATUS_AVAILABLE:
            status = STATUS_UNVERIFIED
        if not available and status == STATUS_AVAILABLE:
            status = STATUS_UNVERIFIED
        matrix[name] = {
            "required": required,
            "available": available,
            "status": status,
            "evidence": str(detection.get("evidence") or ""),
        }
    return matrix


def missing_capabilities() -> List[str]:
    """Required capabilities that are not ``AVAILABLE`` (probe failed or inconclusive)."""
    matrix = capability_matrix()
    return [
        name
        for name, entry in matrix.items()
        if entry.get("required") and entry.get("status") != STATUS_AVAILABLE
    ]


def required_capabilities_ok() -> bool:
    """True only when every required capability is ``AVAILABLE``."""
    return not missing_capabilities()


__all__ = [
    "STATUS_AVAILABLE",
    "STATUS_UNAVAILABLE",
    "STATUS_UNVERIFIED",
    "detect_environment",
    "load_environment_capabilities",
    "capability_matrix",
    "missing_capabilities",
    "required_capabilities_ok",
]
