# -*- coding: utf-8 -*-
"""Fill ledger 4.0 (Contract 03 §3.8).

Every FillPlan operation leaves one ledger record so QA and a human can audit
exactly which slot was touched, with which source, and with which result. The
ledger stores only SHA-256 digests of the value and of the paragraph/cell text
before and after the mutation; raw values never leak into the artifact.

The writer is atomic: content is written to ``<path>.tmp`` and published with
``os.replace`` so a crash cannot leave a half-written ledger behind.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional


def _sha256_text(value: Any) -> Optional[str]:
    """SHA-256 of the UTF-8 text, or ``None`` when the caller supplied nothing."""
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _normalize_result(result: Any) -> Dict[str, Any]:
    """Keep failed results auditable: a failure always carries an error code."""
    if isinstance(result, dict):
        normalized = dict(result)
    else:
        normalized = {"status": "SUCCESS" if str(result).upper() in ("SUCCESS", "PASSED") else "FAILED",
                      "detail": None if result is None else str(result)}
    if str(normalized.get("status") or "").upper() == "FAILED" and not normalized.get("error_code"):
        # The executor always supplies a registry code; this default keeps a
        # caller-built ledger from silently recording a code-less failure.
        normalized["error_code"] = "INVALID_FILL_PLAN"
    return normalized


class FillLedger:
    """Append-only, serializable record of executed FillPlan operations."""

    SCHEMA_VERSION = "4.0"

    def __init__(self, task_id: Optional[str] = None) -> None:
        self.task_id = task_id
        self._records: List[Dict[str, Any]] = []

    def record(
        self,
        op_id: str,
        slot_id: str,
        location_id: str,
        source_ref: str,
        value: Any,
        result: Any,
        before_text: Optional[str] = None,
        after_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append one operation record and return the stored copy."""
        record = {
            "op_id": op_id,
            "slot_id": slot_id,
            "location_id": location_id,
            "source_ref": source_ref,
            "value_sha256": _sha256_text(value),
            "result": _normalize_result(result),
            "before_text_sha256": _sha256_text(before_text),
            "after_text_sha256": _sha256_text(after_text),
        }
        self._records.append(record)
        return dict(record)

    def __len__(self) -> int:
        return len(self._records)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready ledger payload; records are copied so callers cannot mutate state."""
        return {
            "schema_version": self.SCHEMA_VERSION,
            "task_id": self.task_id,
            "record_count": len(self._records),
            "records": [dict(record, result=dict(record["result"])) for record in self._records],
        }

    def write(self, path: str) -> str:
        """Atomically write the ledger JSON to ``path`` and return the final path."""
        target = os.path.abspath(path)
        directory = os.path.dirname(target)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp_path = target + ".tmp"
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, target)
        return target


__all__ = ["FillLedger"]
