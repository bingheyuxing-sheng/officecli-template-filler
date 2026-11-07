# -*- coding: utf-8 -*-
"""W3-7: pre-parse resource quotas for untrusted Office ZIP containers (audit P2-03).

DOCX/XLSX are ZIP containers. python-docx/openpyxl/lxml parse whatever they are
given, so a hostile or corrupted package (zip bomb, millions of entries, one
gigantic part, huge embedded images) can exhaust memory/CPU/disk before any of
our own limits apply. This guard reads ONLY the ZIP central directory (plus a
few header bytes per media entry) and rejects over-budget packages BEFORE any
document parser touches the file.

It is deliberately applied to USER INPUT paths only; staged transaction
artifacts produced by this engine are not re-quota-checked here.
"""

from __future__ import annotations

import json
import os
import zipfile
from typing import Any, Dict, List, Optional

DEFAULT_LIMITS: Dict[str, int] = {
    "max_input_bytes": 64 * 1024 * 1024,               # 64 MB file on disk
    "max_entries": 4096,                               # central-directory entries
    "max_entry_bytes": 64 * 1024 * 1024,              # single member uncompressed
    "max_total_uncompressed_bytes": 256 * 1024 * 1024,  # sum of uncompressed sizes
    "max_compression_ratio": 200,                      # per-entry, above min size
    "ratio_min_entry_bytes": 1024 * 1024,              # tiny entries are not ratio evidence
    "max_total_image_pixels": 200_000_000,             # sum of w:h over media images
}

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_ROOT, "config", "package_limits.json")

_MEDIA_MARKERS = ("/media/",)


def load_limits(path: Optional[str] = None) -> Dict[str, int]:
    """Merge the optional config file over the built-in defaults."""
    limits = dict(DEFAULT_LIMITS)
    config_path = path or CONFIG_PATH
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        overrides = payload.get("limits") or {}
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                if key in limits and isinstance(value, int) and value > 0:
                    limits[key] = value
    except (OSError, ValueError):
        pass  # config is an override, not a requirement
    return limits


def _image_pixels(zf: zipfile.ZipFile) -> int:
    total = 0
    try:
        from PIL import Image
        import io
    except Exception:
        return 0
    for info in zf.infolist():
        name = info.filename
        if not any(marker in name for marker in _MEDIA_MARKERS):
            continue
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff")):
            continue
        try:
            with zf.open(info) as handle:
                head = handle.read(64)
            with Image.open(io.BytesIO(_pad_for_header(head, info))) as image:
                width, height = image.size
            total += int(width) * int(height)
        except Exception:
            continue  # undecodable media is reported by package QA, not here
    return total


def _pad_for_header(head: bytes, info: zipfile.ZipInfo) -> bytes:
    # Some formats (PNG/JPEG/GIF/BMP) expose dimensions inside the first bytes;
    # Image.open only needs the header, and BytesIO keeps it from seeking the zip.
    return head


def check_package(path: str, limits: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Return {"ok", "code", "violations": [{"limit","observed","maximum"}]}.

    Never raises for hostile input: unreadable/oversized packages are verdicts.
    """
    budget = dict(DEFAULT_LIMITS)
    if limits:
        budget.update({k: v for k, v in limits.items() if k in budget})
    violations: List[Dict[str, Any]] = []

    def _violate(name: str, observed: int, maximum: int) -> None:
        violations.append({"limit": name, "observed": int(observed), "maximum": int(maximum)})

    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return {"ok": False, "code": "PACKAGE_NOT_READABLE",
                "violations": [{"limit": "open", "observed": 0, "maximum": 0,
                                "detail": str(exc)}]}
    if size > budget["max_input_bytes"]:
        _violate("max_input_bytes", size, budget["max_input_bytes"])
        return {"ok": False, "code": "PACKAGE_LIMIT_EXCEEDED", "violations": violations}

    if not zipfile.is_zipfile(path):
        return {"ok": False, "code": "PACKAGE_NOT_READABLE",
                "violations": [{"limit": "zip_container", "observed": 0, "maximum": 0,
                                "detail": "not a ZIP container"}]}

    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        return {"ok": False, "code": "PACKAGE_NOT_READABLE",
                "violations": [{"limit": "zip_container", "observed": 0, "maximum": 0,
                                "detail": str(exc)}]}

    if len(infos) > budget["max_entries"]:
        _violate("max_entries", len(infos), budget["max_entries"])
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > budget["max_entry_bytes"]:
            _violate("max_entry_bytes", info.file_size, budget["max_entry_bytes"])
        if (info.file_size >= budget["ratio_min_entry_bytes"] and info.compress_size > 0
                and info.file_size > info.compress_size * budget["max_compression_ratio"]):
            _violate("max_compression_ratio", info.file_size // max(info.compress_size, 1),
                     budget["max_compression_ratio"])
    if total > budget["max_total_uncompressed_bytes"]:
        _violate("max_total_uncompressed_bytes", total, budget["max_total_uncompressed_bytes"])
    if not violations:
        pixels = _image_pixels(_zf_lazy(path, infos))
        if pixels > budget["max_total_image_pixels"]:
            _violate("max_total_image_pixels", pixels, budget["max_total_image_pixels"])
    if violations:
        return {"ok": False, "code": "PACKAGE_LIMIT_EXCEEDED", "violations": violations}
    return {"ok": True, "code": None, "violations": []}


class _zf_lazy:
    """Adapter so _image_pixels can iterate infos and open headers on demand."""

    def __init__(self, path: str, infos: List[zipfile.ZipInfo]) -> None:
        self._path = path
        self._infos = infos

    def infolist(self) -> List[zipfile.ZipInfo]:
        return self._infos

    def open(self, info: zipfile.ZipInfo):
        self._zf = zipfile.ZipFile(self._path)
        handle = self._zf.open(info)
        data = handle.read(64)
        handle.close()
        self._zf.close()
        import io
        return io.BytesIO(data)


class PackageRejected(RuntimeError):
    """Raised when an untrusted package exceeds a pre-parse quota."""

    def __init__(self, verdict: Dict[str, Any], what: str = "document") -> None:
        self.verdict = verdict
        self.what = what
        super().__init__(
            "%s rejected: %s %s"
            % (what, verdict.get("code"), verdict.get("violations") or [])
        )


def require_package(
    path: str,
    limits: Optional[Dict[str, int]] = None,
    what: str = "document",
) -> Dict[str, Any]:
    """Fail closed unless ``path`` passes the pre-parse quota.

    Every entrypoint that hands a user-supplied .docx/.xlsx to python-docx or
    openpyxl must call this first; the quota check only reads the ZIP central
    directory, so it is cheap relative to parsing the document.
    """
    verdict = check_package(path, load_limits() if limits is None else limits)
    if not verdict.get("ok"):
        raise PackageRejected(verdict, what)
    return verdict


def reject_first_package(
    paths: Dict[str, Optional[str]],
    limits: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """Return a JSON-ready rejection payload for the first over-budget input.

    ``paths`` maps an input label to its path (empty paths are skipped).  A
    ``None`` return means every supplied input passed.  CLI entrypoints print
    the payload and exit 2, which keeps their error surface consistent.
    """
    for label, path in paths.items():
        if not path:
            continue
        verdict = check_package(str(path), load_limits() if limits is None else limits)
        if not verdict.get("ok"):
            payload = dict(verdict)
            payload["input"] = label
            payload["path"] = str(path)
            return {"error": payload.get("code"), "package_guard": payload}
    return None


__all__ = [
    "DEFAULT_LIMITS",
    "load_limits",
    "check_package",
    "PackageRejected",
    "require_package",
    "reject_first_package",
]
