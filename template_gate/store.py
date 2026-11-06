# -*- coding: utf-8 -*-
"""Persistent Gate Record store with HMAC integrity and expiry."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import GateState, SCHEMA_VERSION, canonical_json

_DEFAULT_TTL_SECONDS = 30 * 24 * 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_gate_home(explicit: Optional[str] = None) -> str:
    if explicit:
        return os.path.abspath(os.path.expanduser(str(explicit)))
    env = os.environ.get("OFFICECLI_GATE_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.abspath(os.path.expanduser("~/.officecli-template-filler/gates"))


def _safe(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in str(value))


def _token_payload(record: Dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("confirmation_token", None)
    return canonical_json(payload)


class GateStore:
    """One JSON file per confirmation record; no writes to the repository."""

    def __init__(self, gate_home: Optional[str] = None) -> None:
        self.home = resolve_gate_home(gate_home)
        os.makedirs(self.home, exist_ok=True)
        self.secret_path = os.path.join(self.home, "secret.key")

    # ------------------------------------------------------------------ secret

    def _secret(self) -> bytes:
        if os.path.isfile(self.secret_path):
            with open(self.secret_path, "rb") as handle:
                secret = handle.read()
            if secret:
                return secret
        secret = secrets.token_bytes(32)
        with open(self.secret_path, "wb") as handle:
            handle.write(secret)
        try:
            os.chmod(self.secret_path, 0o600)
        except OSError:
            pass
        return secret

    def sign(self, record: Dict[str, Any]) -> str:
        return hmac.new(self._secret(), _token_payload(record).encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(self, record: Dict[str, Any]) -> bool:
        token = record.get("confirmation_token")
        if not isinstance(token, str) or not token:
            return False
        expected = self.sign(record)
        return hmac.compare_digest(token, expected)

    # ------------------------------------------------------------------- files

    def _record_path(self, record: Dict[str, Any]) -> str:
        template_sha = str(record.get("template_sha256") or "")
        task_type = _safe(str(record.get("task_type") or ""))
        gate_id = _safe(str(record.get("gate_id") or ""))
        return os.path.join(
            self.home,
            "gate_%s_%s_%s.json" % (template_sha[:12], task_type, gate_id),
        )

    def _write_atomic(self, path: str, payload: Dict[str, Any]) -> None:
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temp, path)

    def save(self, record: Dict[str, Any]) -> str:
        if not isinstance(record, dict):
            raise TypeError("record must be a dict")
        record = dict(record)
        if not record.get("gate_id"):
            record["gate_id"] = "gate_" + secrets.token_hex(6)
        if not record.get("created_at"):
            record["created_at"] = _iso(_now())
        record["updated_at"] = _iso(_now())
        if record.get("status") == GateState.CONFIRMED.value and record.get("user_confirmed"):
            record["confirmation_token"] = self.sign(record)
        else:
            record.pop("confirmation_token", None)
        self._write_atomic(self._record_path(record), record)
        return str(record["gate_id"])

    def load(self, gate_id: str) -> Optional[Dict[str, Any]]:
        safe_id = _safe(gate_id)
        pattern = "gate_*_%s.json" % safe_id
        for name in sorted(Path(self.home).glob(pattern)):
            try:
                with open(name, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict) and payload.get("gate_id") == gate_id:
                return payload
        return None

    def list(self, *, template_sha256: Optional[str] = None) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for name in sorted(Path(self.home).glob("gate_*.json")):
            try:
                with open(name, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            if template_sha256 and payload.get("template_sha256") != template_sha256:
                continue
            records.append(payload)
        return records

    def find(
        self,
        template_sha256: str,
        task_type: str,
        *,
        status: str = GateState.CONFIRMED.value,
    ) -> Optional[Dict[str, Any]]:
        matches = [
            record
            for record in self.list(template_sha256=template_sha256)
            if record.get("task_type") == str(task_type).upper()
            and record.get("status") == status
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: str(item.get("confirmed_at") or item.get("updated_at") or ""), reverse=True)
        return matches[0]

    def invalidate(self, gate_id: str, reason: str) -> Dict[str, Any]:
        record = self.load(gate_id)
        if record is None:
            raise ValueError("unknown gate_id: %s" % gate_id)
        record["status"] = GateState.INVALIDATED.value
        record["invalidated_reason"] = str(reason)
        record["updated_at"] = _iso(_now())
        record["confirmation_token"] = self.sign(record)
        self._write_atomic(self._record_path(record), record)
        return record

    # ------------------------------------------------------------- review/confirm

    def review_token(self, analysis_id: str, report_digest: str) -> str:
        payload = "review|%s|%s" % (analysis_id, report_digest)
        return hmac.new(self._secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_review_token(self, analysis_id: str, report_digest: str, token: str) -> bool:
        expected = self.review_token(analysis_id, report_digest)
        return hmac.compare_digest(str(token or ""), expected)

    def confirm(
        self,
        analysis: Dict[str, Any],
        report: Dict[str, Any],
        *,
        user_statement: str,
        confirmed_by: str = "USER",
        ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        if int((report.get("quality") or {}).get("unresolved_blocking") or 0) != 0:
            raise ValueError("cannot confirm a report with unresolved blocking items")
        if not str(user_statement or "").strip():
            raise ValueError("explicit user statement is required")
        ttl = int(ttl_seconds if ttl_seconds is not None else os.environ.get("OFFICECLI_GATE_TTL_SECONDS", _DEFAULT_TTL_SECONDS))
        confirmed_at = _now()
        record = {
            "schema_version": SCHEMA_VERSION,
            "gate_id": "gate_" + secrets.token_hex(6),
            "template_sha256": analysis.get("template_sha256"),
            "template_name": analysis.get("template_name"),
            "spec_schema_version": analysis.get("spec_schema_version"),
            "spec_digest": analysis.get("spec_digest"),
            "fingerprint_ref": dict(analysis.get("fingerprint_ref") or {}),
            "analysis_version": analysis.get("analysis_version"),
            "parser_version": analysis.get("parser_version"),
            "policy_version": analysis.get("policy_version"),
            "task_type": analysis.get("task_type"),
            "evidence_digest": analysis.get("evidence_digest"),
            "evidence_summary": dict(analysis.get("summary") or {}),
            "blocking_count": int((analysis.get("summary") or {}).get("blocking") or 0),
            "status": GateState.CONFIRMED.value,
            "user_confirmed": True,
            "confirmed_at": _iso(confirmed_at),
            "confirmed_by": str(confirmed_by or "USER"),
            "user_statement": str(user_statement),
            "review_token_digest": report.get("report_digest"),
            "expires_at": _iso(confirmed_at + timedelta(seconds=ttl)),
            "supplements": list(analysis.get("supplements") or []),
            "resolved_evidence": [
                item
                for item in analysis.get("evidence") or []
                if isinstance(item, dict) and item.get("resolutions")
            ],
            "invalidated_reason": None,
            "created_at": _iso(confirmed_at),
            "updated_at": _iso(confirmed_at),
            "executions": [],
        }
        self.save(record)
        return self.load(record["gate_id"]) or record

    def reject(
        self,
        analysis: Dict[str, Any],
        *,
        user_statement: str = "",
    ) -> Dict[str, Any]:
        now = _now()
        record = {
            "schema_version": SCHEMA_VERSION,
            "gate_id": "gate_" + secrets.token_hex(6),
            "template_sha256": analysis.get("template_sha256"),
            "template_name": analysis.get("template_name"),
            "spec_schema_version": analysis.get("spec_schema_version"),
            "spec_digest": analysis.get("spec_digest"),
            "fingerprint_ref": dict(analysis.get("fingerprint_ref") or {}),
            "analysis_version": analysis.get("analysis_version"),
            "parser_version": analysis.get("parser_version"),
            "policy_version": analysis.get("policy_version"),
            "task_type": analysis.get("task_type"),
            "evidence_digest": analysis.get("evidence_digest"),
            "evidence_summary": dict(analysis.get("summary") or {}),
            "blocking_count": int((analysis.get("summary") or {}).get("blocking") or 0),
            "status": GateState.REJECTED.value,
            "user_confirmed": False,
            "confirmed_at": None,
            "confirmed_by": None,
            "user_statement": str(user_statement or ""),
            "review_token_digest": None,
            "expires_at": None,
            "supplements": [],
            "resolved_evidence": [],
            "invalidated_reason": None,
            "created_at": _iso(now),
            "updated_at": _iso(now),
            "executions": [],
        }
        self.save(record)
        return self.load(record["gate_id"]) or record

    def is_expired(self, record: Dict[str, Any]) -> bool:
        expires = _parse_time(record.get("expires_at"))
        return bool(expires and expires <= _now())


__all__ = ["GateStore", "resolve_gate_home"]
