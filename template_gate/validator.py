# -*- coding: utf-8 -*-
"""Pre-execution Gate Validation.

The validator never repairs evidence and never downgrades a failure.  Every
check returns a named record so a caller can show exactly why execution was
refused.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import docx
from jsonschema import Draft202012Validator

from engine import __version__ as ENGINE_VERSION
from engine.ooxml_utils import iter_all_document_paragraphs_with_Wait_context
from template_intelligence import build_document_spec_from_path
from template_intelligence.fingerprint import compute_four_hashes

from .analyzer import _spec_digest, build_analysis, load_policy
from .errors import (
    TEMPLATE_EVIDENCE_CONFLICT,
    TEMPLATE_EVIDENCE_INCOMPLETE,
    TEMPLATE_GATE_BLOCKED,
    TEMPLATE_GATE_CONFIRMATION_REQUIRED,
    TEMPLATE_GATE_REQUIRED,
    TEMPLATE_GATE_STALE,
    TemplateGateError,
)
from .models import ANALYSIS_VERSION, GateState
from .store import GateStore

ROOT = Path(__file__).resolve().parents[1]
RECORD_SCHEMA_PATH = ROOT / "schemas" / "template_gate_record-1.0.schema.json"

_HASH_KEYS = ("structural_hash", "style_hash", "protected_hash", "layout_hash")
_PROTECTED_KINDS = ("header", "footer", "logo", "stamp")


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_texts(doc, spec: Dict[str, Any]) -> list:
    locations = {
        str(region.get("location_id"))
        for region in spec.get("protected_regions") or []
        if isinstance(region, dict) and region.get("kind") in _PROTECTED_KINDS
    }
    texts = []
    for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
        if ctx.get("location_id") in locations:
            text = (ctx.get("paragraph").text or "").strip()
            if text:
                texts.append(text)
    return texts


def _check(name: str, ok: bool, detail: str = "", code: Optional[str] = None) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "code": code if not ok else None}


def _load_record_schema() -> Dict[str, Any]:
    with open(RECORD_SCHEMA_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_record(
    template_sha: str,
    task_type: str,
    gate_record: Any,
    gate_home: Optional[str],
    store: GateStore,
) -> Optional[Dict[str, Any]]:
    if isinstance(gate_record, dict):
        return dict(gate_record)
    if isinstance(gate_record, str) and gate_record:
        if os.path.isfile(gate_record):
            try:
                with open(gate_record, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                return None
            return payload if isinstance(payload, dict) else None
        return store.load(gate_record)
    return store.find(template_sha, task_type)


def validate_gate(
    template_path: str,
    task_type: str,
    *,
    gate_record: Any = None,
    spec: Optional[Dict[str, Any]] = None,
    gate_home: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a Gate Record against the current template and analysis."""
    task = str(task_type or "").strip().upper()
    store = GateStore(gate_home)
    try:
        actual_sha = _file_sha256(template_path)
    except OSError as exc:
        return {
            "passed": False,
            "code": TEMPLATE_GATE_REQUIRED,
            "checks": [_check("template_readable", False, str(exc), TEMPLATE_GATE_REQUIRED)],
            "record": None,
        }

    record = _resolve_record(actual_sha, task, gate_record, gate_home, store)
    if record is None:
        return {
            "passed": False,
            "code": TEMPLATE_GATE_REQUIRED,
            "checks": [_check("record_present", False, "no gate record for this template", TEMPLATE_GATE_REQUIRED)],
            "record": None,
        }

    checks: list = []
    checks.append(_check("record_present", True, record.get("gate_id") or ""))

    schema_errors = sorted(
        Draft202012Validator(_load_record_schema()).iter_errors(record),
        key=lambda item: list(item.absolute_path),
    )
    checks.append(
        _check(
            "record_schema",
            not schema_errors,
            "; ".join(error.message for error in schema_errors[:4]),
            TEMPLATE_GATE_CONFIRMATION_REQUIRED,
        )
    )

    status = str(record.get("status") or "")
    if status == GateState.INVALIDATED.value:
        checks.append(_check("status_confirmed", False, status, TEMPLATE_GATE_STALE))
    else:
        checks.append(
            _check(
                "status_confirmed",
                status == GateState.CONFIRMED.value,
                status or "missing",
                TEMPLATE_GATE_BLOCKED,
            )
        )
    checks.append(
        _check(
            "user_confirmed",
            bool(record.get("user_confirmed")),
            "explicit user confirmation required",
            TEMPLATE_GATE_CONFIRMATION_REQUIRED,
        )
    )
    checks.append(
        _check(
            "confirmation_token",
            store.verify(record),
            "HMAC token mismatch",
            TEMPLATE_GATE_CONFIRMATION_REQUIRED,
        )
    )
    checks.append(
        _check(
            "not_expired",
            not store.is_expired(record),
            str(record.get("expires_at") or ""),
            TEMPLATE_GATE_STALE,
        )
    )
    checks.append(
        _check(
            "template_sha256",
            record.get("template_sha256") == actual_sha,
            "record=%s actual=%s" % (record.get("template_sha256"), actual_sha),
            TEMPLATE_GATE_STALE,
        )
    )

    try:
        resolved_spec = spec or build_document_spec_from_path(template_path)
    except Exception as exc:
        resolved_spec = None
        spec_detail = "spec unavailable: %s: %s" % (type(exc).__name__, exc)
    else:
        spec_detail = ""

    if resolved_spec is None:
        checks.append(_check("spec_binding", False, spec_detail, TEMPLATE_GATE_STALE))
    else:
        spec_sha = str((resolved_spec.get("template") or {}).get("template_sha256") or "")
        checks.append(
            _check(
                "spec_schema_version",
                str(resolved_spec.get("schema_version")) == "4.0",
                str(resolved_spec.get("schema_version")),
                TEMPLATE_GATE_STALE,
            )
        )
        checks.append(
            _check(
                "spec_template_sha256",
                spec_sha == actual_sha,
                "spec=%s actual=%s" % (spec_sha, actual_sha),
                TEMPLATE_GATE_STALE,
            )
        )
        checks.append(
            _check(
                "spec_digest",
                _spec_digest(resolved_spec) == record.get("spec_digest"),
                "spec digest differs from the confirmed record",
                TEMPLATE_GATE_STALE,
            )
        )

        try:
            document = docx.Document(template_path)
            hashes = compute_four_hashes(document, protected_texts=_protected_texts(document, resolved_spec))
        except Exception as exc:
            checks.append(
                _check("fingerprint_ref", False, "fingerprint unavailable: %s" % type(exc).__name__, TEMPLATE_GATE_STALE)
            )
            hashes = {}
        else:
            recorded = record.get("fingerprint_ref") or {}
            mismatched = [key for key in _HASH_KEYS if recorded.get(key) != hashes.get(key)]
            checks.append(
                _check(
                    "fingerprint_ref",
                    not mismatched,
                    "mismatched: %s" % ", ".join(mismatched) if mismatched else "all four hashes match",
                    TEMPLATE_GATE_STALE,
                )
            )

    checks.append(
        _check(
            "analysis_version",
            record.get("analysis_version") == ANALYSIS_VERSION,
            "record=%s current=%s" % (record.get("analysis_version"), ANALYSIS_VERSION),
            TEMPLATE_GATE_STALE,
        )
    )
    checks.append(
        _check(
            "parser_version",
            record.get("parser_version") == ENGINE_VERSION,
            "record=%s current=%s" % (record.get("parser_version"), ENGINE_VERSION),
            TEMPLATE_GATE_STALE,
        )
    )
    checks.append(
        _check(
            "policy_version",
            record.get("policy_version") == str(load_policy().get("version") or "1.0"),
            "record=%s current=%s" % (record.get("policy_version"), load_policy().get("version")),
            TEMPLATE_GATE_STALE,
        )
    )
    checks.append(
        _check(
            "task_type",
            record.get("task_type") == task,
            "record=%s current=%s" % (record.get("task_type"), task),
            TEMPLATE_GATE_STALE,
        )
    )

    supplemented = bool(record.get("supplements"))
    fresh: Optional[Dict[str, Any]] = None
    if supplemented:
        checks.append(
            _check(
                "evidence_digest",
                bool(record.get("evidence_digest")),
                "supplemented analysis is bound by the confirmed evidence digest",
            )
        )
    elif resolved_spec is not None:
        try:
            fresh = build_analysis(template_path, task, spec=resolved_spec)
        except Exception as exc:
            checks.append(
                _check(
                    "evidence_digest",
                    False,
                    "analysis rebuild failed: %s: %s" % (type(exc).__name__, exc),
                    TEMPLATE_GATE_STALE,
                )
            )
        else:
            resolved_evidence = record.get("resolved_evidence") or []
            if resolved_evidence and isinstance(fresh, dict):
                from template_gate.models import EvidenceRecord
                from template_gate.supplements import _finalize

                by_id = {
                    str(item.get("evidence_id")): EvidenceRecord.from_dict(item)
                    for item in fresh.get("evidence") or []
                    if isinstance(item, dict) and item.get("evidence_id")
                }
                for item in resolved_evidence:
                    if not isinstance(item, dict) or not item.get("evidence_id"):
                        continue
                    by_id[str(item["evidence_id"])] = EvidenceRecord.from_dict(item)
                fresh = _finalize(fresh, by_id.values(), task)
            checks.append(
                _check(
                    "evidence_digest",
                    fresh.get("evidence_digest") == record.get("evidence_digest"),
                    "evidence digest differs from the confirmed record",
                    TEMPLATE_GATE_STALE,
                )
            )
    else:
        checks.append(_check("evidence_digest", False, "analysis unavailable", TEMPLATE_GATE_STALE))

    record_blocking = int(record.get("blocking_count") or 0)
    checks.append(
        _check(
            "blocking_count",
            record_blocking == 0,
            "record blocking_count=%d" % record_blocking,
            TEMPLATE_EVIDENCE_INCOMPLETE,
        )
    )
    if fresh is not None:
        summary = fresh.get("summary") or {}
        checks.append(
            _check(
                "fresh_blocking_count",
                int(summary.get("blocking") or 0) == 0,
                "fresh blocking=%d" % int(summary.get("blocking") or 0),
                TEMPLATE_EVIDENCE_INCOMPLETE,
            )
        )
        conflict_blocking = any(
            item.get("blocking") and item.get("verification_status") == "CONFLICT"
            for item in fresh.get("evidence") or []
            if isinstance(item, dict)
        )
        checks.append(
            _check(
                "evidence_conflict",
                not conflict_blocking,
                "fresh analysis contains a blocking CONFLICT",
                TEMPLATE_EVIDENCE_CONFLICT,
            )
        )
    else:
        checks.append(_check("fresh_blocking_count", True, "supplemented record"))
        checks.append(_check("evidence_conflict", True, "supplemented record"))

    failure = next((item for item in checks if not item["ok"]), None)
    return {
        "passed": failure is None,
        "code": failure.get("code") if failure else None,
        "checks": checks,
        "record": record,
    }


def require_confirmed_gate(
    template_path: str,
    task_type: str,
    *,
    gate_record: Any = None,
    spec: Optional[Dict[str, Any]] = None,
    gate_home: Optional[str] = None,
) -> Dict[str, Any]:
    """Raise :class:`TemplateGateError` unless the gate validates."""
    verdict = validate_gate(
        template_path,
        task_type,
        gate_record=gate_record,
        spec=spec,
        gate_home=gate_home,
    )
    if not verdict["passed"]:
        failed = [item for item in verdict["checks"] if not item["ok"]]
        detail = "; ".join("%s: %s" % (item["name"], item["detail"]) for item in failed[:4])
        raise TemplateGateError(
            str(verdict["code"] or TEMPLATE_GATE_BLOCKED),
            "template understanding gate refused execution: %s" % detail,
            details={"checks": verdict["checks"]},
            verdict=verdict,
        )
    return verdict


__all__ = ["validate_gate", "require_confirmed_gate"]
