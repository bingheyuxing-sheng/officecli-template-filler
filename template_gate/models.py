# -*- coding: utf-8 -*-
"""Data models for the Template Understanding Gate.

The gate is deliberately independent from DocumentSpec 4.0: evidence, gate
records and analysis reports have their own schema/version surface.  Existing
contracts are read-only inputs to this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0"
ANALYSIS_VERSION = "2.0"


class EvidenceStatus(str, Enum):
    """Four-state evidence model required by W4."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"


class EvidenceType(str, Enum):
    XML_NODE = "xml_node"
    STYLE_DEFINITION = "style_definition"
    COMPUTED_PROPERTY = "computed_property"
    PARSER_RULE = "parser_rule"
    USER_STATEMENT = "user_statement"
    REFERENCE_DOCUMENT = "reference_document"


class ResolutionType(str, Enum):
    PROVIDE_VALUE = "PROVIDE_VALUE"
    USE_REFERENCE = "USE_REFERENCE"
    PRESERVE_AS_IS = "PRESERVE_AS_IS"
    USER_STATEMENT = "USER_STATEMENT"


class TaskType(str, Enum):
    GENERATE = "GENERATE"
    REPAIR = "REPAIR"
    REFORMAT = "REFORMAT"
    REVIEW = "REVIEW"
    PROOFREAD = "PROOFREAD"
    EXCEL_GENERATE = "EXCEL_GENERATE"
    POLISH = "POLISH"
    MERGE = "MERGE"


class GateState(str, Enum):
    DISCOVERING = "DISCOVERING"
    ANALYZING = "ANALYZING"
    VALIDATING = "VALIDATING"
    BLOCKED = "BLOCKED"
    WAITING_USER_INPUT = "WAITING_USER_INPUT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    CONFIRMED = "CONFIRMED"
    EXECUTING = "EXECUTING"
    INVALIDATED = "INVALIDATED"
    REJECTED = "REJECTED"


SEVERITIES = frozenset({"blocking", "warning", "info"})


def canonical_json(value: Any) -> str:
    """Stable JSON used for digests and HMAC payloads."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_evidence_id(object_id: str, prop: str, source: str, occurrence: int = 1) -> str:
    """Stable id derived from the evidence address, not from list order."""
    digest = sha256_text("%s|%s|%s|%d" % (object_id, prop, source, occurrence))
    return "ev_" + digest[:12]


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().upper()
    if status not in {item.value for item in EvidenceStatus}:
        raise ValueError("unknown evidence status: %r" % (value,))
    return status


@dataclass
class EvidenceRecord:
    """One verifiable property of one document object."""

    evidence_id: str
    object_id: str
    location: str
    property: str
    value: Any
    source: str
    evidence_type: str
    verification_status: str
    task_relevant: bool = False
    blocking: bool = False
    severity: str = "info"
    detail: str = ""
    required_materials: List[str] = field(default_factory=list)
    resolutions: List[Dict[str, Any]] = field(default_factory=list)
    resolved_at: Optional[str] = None

    def __post_init__(self) -> None:
        self.verification_status = _normalize_status(self.verification_status)
        if self.severity not in SEVERITIES:
            raise ValueError("unknown severity: %r" % (self.severity,))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "object_id": self.object_id,
            "location": self.location,
            "property": self.property,
            "value": self.value,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "verification_status": self.verification_status,
            "task_relevant": bool(self.task_relevant),
            "blocking": bool(self.blocking),
            "severity": self.severity,
            "detail": self.detail,
            "required_materials": list(self.required_materials),
            "resolutions": list(self.resolutions),
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EvidenceRecord":
        return cls(
            evidence_id=str(payload["evidence_id"]),
            object_id=str(payload.get("object_id") or ""),
            location=str(payload.get("location") or ""),
            property=str(payload["property"]),
            value=payload.get("value"),
            source=str(payload["source"]),
            evidence_type=str(payload.get("evidence_type") or EvidenceType.COMPUTED_PROPERTY.value),
            verification_status=str(payload["verification_status"]),
            task_relevant=bool(payload.get("task_relevant")),
            blocking=bool(payload.get("blocking")),
            severity=str(payload.get("severity") or "info"),
            detail=str(payload.get("detail") or ""),
            required_materials=list(payload.get("required_materials") or []),
            resolutions=list(payload.get("resolutions") or []),
            resolved_at=payload.get("resolved_at"),
        )

    def canonical_dict(self) -> Dict[str, Any]:
        """Digest-stable view: no timestamps and no absolute file paths."""
        resolutions = []
        for item in self.resolutions:
            if not isinstance(item, dict):
                continue
            cleaned = {
                key: value
                for key, value in item.items()
                if key not in ("resolved_at", "resolution_id")
            }
            resolutions.append(cleaned)
        return {
            "evidence_id": self.evidence_id,
            "object_id": self.object_id,
            "location": self.location,
            "property": self.property,
            "value": self.value,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "verification_status": self.verification_status,
            "task_relevant": bool(self.task_relevant),
            "blocking": bool(self.blocking),
            "severity": self.severity,
            "detail": self.detail,
            "required_materials": sorted(self.required_materials),
            "resolutions": sorted(resolutions, key=canonical_json),
            "resolved": self.resolved_at is not None,
        }


@dataclass
class SupplementRecord:
    sha256: str
    kind: str
    name: str = ""
    claims: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sha256": self.sha256,
            "kind": self.kind,
            "name": self.name,
            "claims": list(self.claims),
        }


@dataclass
class GateRecord:
    """Persistent confirmation record; store/HMAC logic lives in store.py."""

    gate_id: str
    template_sha256: str
    template_name: str
    spec_schema_version: str
    spec_digest: str
    fingerprint_ref: Dict[str, Any]
    analysis_version: str
    parser_version: str
    policy_version: str
    task_type: str
    evidence_digest: str
    evidence_summary: Dict[str, Any]
    blocking_count: int
    status: str = GateState.DISCOVERING.value
    user_confirmed: bool = False
    confirmed_at: Optional[str] = None
    confirmed_by: Optional[str] = None
    user_statement: Optional[str] = None
    confirmation_token: Optional[str] = None
    review_token_digest: Optional[str] = None
    expires_at: Optional[str] = None
    supplements: List[Dict[str, Any]] = field(default_factory=list)
    resolved_evidence: List[Dict[str, Any]] = field(default_factory=list)
    invalidated_reason: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    executions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "gate_id": self.gate_id,
            "template_sha256": self.template_sha256,
            "template_name": self.template_name,
            "spec_schema_version": self.spec_schema_version,
            "spec_digest": self.spec_digest,
            "fingerprint_ref": dict(self.fingerprint_ref),
            "analysis_version": self.analysis_version,
            "parser_version": self.parser_version,
            "policy_version": self.policy_version,
            "task_type": self.task_type,
            "evidence_digest": self.evidence_digest,
            "evidence_summary": dict(self.evidence_summary),
            "blocking_count": int(self.blocking_count),
            "status": self.status,
            "user_confirmed": bool(self.user_confirmed),
            "confirmed_at": self.confirmed_at,
            "confirmed_by": self.confirmed_by,
            "user_statement": self.user_statement,
            "confirmation_token": self.confirmation_token,
            "review_token_digest": self.review_token_digest,
            "expires_at": self.expires_at,
            "supplements": list(self.supplements),
            "resolved_evidence": list(self.resolved_evidence),
            "invalidated_reason": self.invalidated_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "executions": list(self.executions),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "GateRecord":
        return cls(
            gate_id=str(payload["gate_id"]),
            template_sha256=str(payload["template_sha256"]),
            template_name=str(payload.get("template_name") or ""),
            spec_schema_version=str(payload["spec_schema_version"]),
            spec_digest=str(payload["spec_digest"]),
            fingerprint_ref=dict(payload.get("fingerprint_ref") or {}),
            analysis_version=str(payload["analysis_version"]),
            parser_version=str(payload["parser_version"]),
            policy_version=str(payload["policy_version"]),
            task_type=str(payload["task_type"]),
            evidence_digest=str(payload["evidence_digest"]),
            evidence_summary=dict(payload.get("evidence_summary") or {}),
            blocking_count=int(payload.get("blocking_count") or 0),
            status=str(payload.get("status") or GateState.DISCOVERING.value),
            user_confirmed=bool(payload.get("user_confirmed")),
            confirmed_at=payload.get("confirmed_at"),
            confirmed_by=payload.get("confirmed_by"),
            user_statement=payload.get("user_statement"),
            confirmation_token=payload.get("confirmation_token"),
            review_token_digest=payload.get("review_token_digest"),
            expires_at=payload.get("expires_at"),
            supplements=list(payload.get("supplements") or []),
            resolved_evidence=list(payload.get("resolved_evidence") or []),
            invalidated_reason=payload.get("invalidated_reason"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            executions=list(payload.get("executions") or []),
        )
