# -*- coding: utf-8 -*-
"""Deterministic, file-backed caches for template analysis and reference PDFs.

Every cache entry is keyed by content digests plus engine/schema versions, so
a changed template, upgraded engine or changed policy can never reuse a stale
analysis.  The cache is opt-out via ``OFFICECLI_DISABLE_CACHE=1`` and lives
under ``%USERPROFILE%\\.officecli-template-filler\\cache`` by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

CACHE_FORMAT_VERSION = "1"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def cache_enabled() -> bool:
    value = str(os.environ.get("OFFICECLI_DISABLE_CACHE") or "").strip().lower()
    return value not in _TRUE_VALUES


def cache_root() -> str:
    override = str(os.environ.get("OFFICECLI_CACHE_HOME") or "").strip()
    if override:
        return os.path.abspath(override)
    return str(Path.home() / ".officecli-template-filler" / "cache")


def key_from_parts(*parts: Any) -> str:
    """Return a stable SHA-256 key for arbitrary JSON-serialisable parts."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_path(namespace: str, key: str, suffix: str) -> str:
    safe_namespace = "".join(ch for ch in str(namespace) if ch.isalnum() or ch in ("_", "-")) or "misc"
    safe_key = "".join(ch for ch in str(key) if ch.isalnum() or ch in ("_", "-")) or "empty"
    if not suffix.startswith("."):
        suffix = "." + suffix
    return os.path.join(cache_root(), safe_namespace, safe_key + suffix)


def read_json(namespace: str, key: str) -> Optional[Dict[str, Any]]:
    if not cache_enabled():
        return None
    path = cache_path(namespace, key, ".json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_json(namespace: str, key: str, payload: Dict[str, Any]) -> None:
    if not cache_enabled():
        return
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(cache_path(namespace, key, ".json"), data)


def write_bytes(namespace: str, key: str, payload: bytes, suffix: str = ".bin") -> None:
    if not cache_enabled():
        return
    _atomic_write(cache_path(namespace, key, suffix), payload)


def delete(namespace: str, key: str, suffix: str) -> None:
    try:
        os.remove(cache_path(namespace, key, suffix))
    except OSError:
        pass


def _atomic_write(path: str, payload: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=directory, prefix=".tmp-", suffix=".part", delete=False
    )
    temp_path = handle.name
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


__all__ = [
    "CACHE_FORMAT_VERSION",
    "cache_enabled",
    "cache_path",
    "cache_root",
    "delete",
    "key_from_parts",
    "read_json",
    "write_bytes",
    "write_json",
]
