# -*- coding: utf-8 -*-
"""Template Understanding Gate public API."""

from .analyzer import build_analysis, load_policy
from .errors import (
    GATE_ERROR_CODES,
    TEMPLATE_EVIDENCE_CONFLICT,
    TEMPLATE_EVIDENCE_INCOMPLETE,
    TEMPLATE_GATE_BLOCKED,
    TEMPLATE_GATE_CONFIRMATION_REQUIRED,
    TEMPLATE_GATE_ILLEGAL_TRANSITION,
    TEMPLATE_GATE_REQUIRED,
    TEMPLATE_GATE_STALE,
    GateStateError,
    TemplateGateError,
)
from .evidence import EvidenceRegistry
from .state import GateStateMachine, allowed_targets, can_transition
from .store import GateStore, resolve_gate_home
from .validator import require_confirmed_gate, validate_gate
from .models import (
    ANALYSIS_VERSION,
    SCHEMA_VERSION,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
    GateRecord,
    GateState,
    ResolutionType,
    SupplementRecord,
    TaskType,
    canonical_json,
    sha256_text,
    stable_evidence_id,
)

__all__ = [
    "ANALYSIS_VERSION",
    "SCHEMA_VERSION",
    "EvidenceRecord",
    "EvidenceRegistry",
    "EvidenceStatus",
    "EvidenceType",
    "GateRecord",
    "GateState",
    "GateStateMachine",
    "GateStore",
    "resolve_gate_home",
    "require_confirmed_gate",
    "validate_gate",
    "allowed_targets",
    "can_transition",
    "ResolutionType",
    "SupplementRecord",
    "TaskType",
    "build_analysis",
    "load_policy",
    "canonical_json",
    "sha256_text",
    "stable_evidence_id",
    "GATE_ERROR_CODES",
    "TEMPLATE_EVIDENCE_CONFLICT",
    "TEMPLATE_EVIDENCE_INCOMPLETE",
    "TEMPLATE_GATE_BLOCKED",
    "TEMPLATE_GATE_CONFIRMATION_REQUIRED",
    "TEMPLATE_GATE_ILLEGAL_TRANSITION",
    "TEMPLATE_GATE_REQUIRED",
    "TEMPLATE_GATE_STALE",
    "GateStateError",
    "TemplateGateError",
]
