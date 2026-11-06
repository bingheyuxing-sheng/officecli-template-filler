# -*- coding: utf-8 -*-
"""Error codes and exceptions for the Template Understanding Gate."""

from __future__ import annotations

from typing import Any, Dict, Optional

TEMPLATE_GATE_REQUIRED = "TEMPLATE_GATE_REQUIRED"
TEMPLATE_GATE_BLOCKED = "TEMPLATE_GATE_BLOCKED"
TEMPLATE_GATE_STALE = "TEMPLATE_GATE_STALE"
TEMPLATE_GATE_CONFIRMATION_REQUIRED = "TEMPLATE_GATE_CONFIRMATION_REQUIRED"
TEMPLATE_EVIDENCE_CONFLICT = "TEMPLATE_EVIDENCE_CONFLICT"
TEMPLATE_EVIDENCE_INCOMPLETE = "TEMPLATE_EVIDENCE_INCOMPLETE"
TEMPLATE_GATE_ILLEGAL_TRANSITION = "TEMPLATE_GATE_ILLEGAL_TRANSITION"

GATE_ERROR_CODES = (
    TEMPLATE_GATE_REQUIRED,
    TEMPLATE_GATE_BLOCKED,
    TEMPLATE_GATE_STALE,
    TEMPLATE_GATE_CONFIRMATION_REQUIRED,
    TEMPLATE_EVIDENCE_CONFLICT,
    TEMPLATE_EVIDENCE_INCOMPLETE,
    TEMPLATE_GATE_ILLEGAL_TRANSITION,
)


class TemplateGateError(RuntimeError):
    """Raised when a gate check refuses to let an execution continue."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        verdict: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.verdict = verdict or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "verdict": dict(self.verdict),
        }


class GateStateError(TemplateGateError):
    """Raised for an illegal gate state transition."""

    def __init__(
        self,
        message: str,
        *,
        current: str = "",
        target: str = "",
    ) -> None:
        super().__init__(
            TEMPLATE_GATE_ILLEGAL_TRANSITION,
            message,
            details={"current": current, "target": target},
        )
