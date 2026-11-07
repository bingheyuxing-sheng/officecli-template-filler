# -*- coding: utf-8 -*-
"""W5 document backend adapter layer (B1 skeleton).

**STATUS: EXPERIMENTAL — this package is not wired into the execution chain.**
The production fill path still uses ``engine.officecli_writer`` directly from
``document_engine.fill_executor``; see ``PACKAGE_STATUS`` below.  The interface,
result model and reason-code vocabulary are frozen for the B2–B5 migration, but
nothing in ``scripts/`` or ``document_engine/`` imports this package yet.

The package separates *what may change* (the executor + FillPlan) from
*how it is written* (officecli subprocess vs python-docx). B1 delivers the
interface, the result model and the reason-code vocabulary only — no
router, no probe infrastructure, no backend implementations.

Layout:

* :mod:`document_backends.base` — abstract ``DocumentBackend`` plus the
  ``BackendTarget``/``BackendOp``/``CapabilityRecord`` models;
* :mod:`document_backends.result` — ``BackendResult``/``OpOutcome`` and the
  registry-backed ``ReasonCode`` vocabulary (E6/E7 semantics);
* ``officecli_backend`` / ``python_backend`` / ``capability_registry`` /
  ``operation_router`` land in B2–B5 and are not importable yet.
"""

from .base import (
    BACKEND_FORMATS,
    OPERATION_KINDS,
    BackendOp,
    BackendTarget,
    CapabilityRecord,
    CapabilityReport,
    DocumentBackend,
)
from .result import (
    DETAIL_MAX_CHARS,
    OP_STATUSES,
    BackendError,
    BackendResult,
    ErrorCategory,
    OFFICECLI_BACKEND_NAME,
    OFFICECLI_ENVELOPE_ALIASES,
    OpOutcome,
    ReasonCode,
    ReasonSpec,
    REASON_CODE_CATALOG,
    VALIDATION_UNVERIFIED_REASONS,
    ValidationStatus,
    ValidationResult,
    envelope_code_for,
    reason_category,
)

#: Machine-readable status consumed by the disclosure test and by callers that
#: need to distinguish "available API" from "integrated backend".
PACKAGE_STATUS = "EXPERIMENTAL_NOT_WIRED"

__all__ = [
    "PACKAGE_STATUS",
    "BACKEND_FORMATS",
    "OPERATION_KINDS",
    "BackendError",
    "BackendOp",
    "BackendResult",
    "BackendTarget",
    "CapabilityRecord",
    "CapabilityReport",
    "DETAIL_MAX_CHARS",
    "DocumentBackend",
    "ErrorCategory",
    "OFFICECLI_BACKEND_NAME",
    "OFFICECLI_ENVELOPE_ALIASES",
    "OP_STATUSES",
    "OpOutcome",
    "ReasonCode",
    "ReasonSpec",
    "REASON_CODE_CATALOG",
    "VALIDATION_UNVERIFIED_REASONS",
    "ValidationStatus",
    "ValidationResult",
    "envelope_code_for",
    "reason_category",
]
