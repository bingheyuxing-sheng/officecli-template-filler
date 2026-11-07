# -*- coding: utf-8 -*-
"""W5-B1 — Unified backend result model and reason-code vocabulary.

Every backend (officecli, python-docx) reports what it did through
:class:`BackendResult`. A result is either a success (``ok=True``, no
reason code) or a failure (``ok=False`` plus a structured
:class:`ReasonCode`). The fine-grained reason codes defined here are all
registered in ``config/error-codes.json`` (contract 05 §8/§9: an error code
absent from the registry is invalid), so no backend ever introduces a
private status vocabulary.

Error taxonomy (four families; W5-B1 requirement 5):

* ``BUSINESS`` — FillPlan-level authorization/validation refusals. Emitted
  by the executor *before* any backend is consulted; existing codes
  (``INVALID_FILL_PLAN``, ``UNAUTHORIZED_SLOT_TARGET`` ...) are unchanged
  and are not redefined here.
* ``DOCUMENT`` — the document's own structure prevents a faithful
  expression (cross-run token, ambiguous token, unaddressable story,
  multi-paragraph cell). These are *disclosed fallback* reasons: the
  capability group reroutes to python-docx and the reason appears in the
  routing record (E7); they are never envelope errors on their own.
* ``BACKEND`` — the chosen backend failed at its own job (batch rolled
  back, read-back mismatch, normalize failure, stage check, schema
  validation, single-writer violation). Each maps onto a *generic*
  ``BACKEND_*`` envelope code, so the common layer never depends on one
  backend family's naming; the officecli executor path resolves the
  B0-era ``OFFICECLI_*`` spellings through
  :data:`OFFICECLI_ENVELOPE_ALIASES` (E2 backward compatibility), while
  any other backend — python-docx included — keeps the generic code.
* ``INFRASTRUCTURE`` — environment/tooling unavailable (binary missing,
  version probe failed, validator absent). Disclosed fallback or
  ``UNVERIFIED`` semantics; never silently skipped (E6).

The vocabulary is *additive*: later stages (B2/B3/B5) may register new
reason codes through the same mechanism but may never rename or remove
the ones frozen here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional

__all__ = [
    "ErrorCategory",
    "ReasonCode",
    "ReasonSpec",
    "REASON_CODE_CATALOG",
    "OFFICECLI_BACKEND_NAME",
    "OFFICECLI_ENVELOPE_ALIASES",
    "VALIDATION_UNVERIFIED_REASONS",
    "OpOutcome",
    "BackendResult",
    "BackendError",
    "ValidationStatus",
    "ValidationResult",
    "envelope_code_for",
    "reason_category",
]

DETAIL_MAX_CHARS = 300

#: Operation statuses allowed inside :class:`OpOutcome`. ``SKIPPED`` is used
#: for operations a stage never attempted (for example after an abort), so
#: "not executed" is always distinguishable from "failed".
OP_STATUSES = ("SUCCESS", "FAILED", "SKIPPED")


class ErrorCategory(str, Enum):
    """Which of the four error families a reason belongs to."""

    BUSINESS = "BUSINESS"
    DOCUMENT = "DOCUMENT"
    BACKEND = "BACKEND"
    INFRASTRUCTURE = "INFRASTRUCTURE"


class ReasonCode(str, Enum):
    """Structured backend causes. Registry spellings, uppercase, stable.

    Fallback reasons (``is_failure=False``) surface only in the routing
    record (``data.routing``, E7); failure reasons map onto the coarse
    envelope error code the executor already emits.
    """

    # --- INFRASTRUCTURE ------------------------------------------------
    OFFICECLI_BINARY_MISSING = "OFFICECLI_BINARY_MISSING"
    OFFICECLI_VERSION_UNSUPPORTED = "OFFICECLI_VERSION_UNSUPPORTED"
    BACKEND_VALIDATE_UNAVAILABLE = "BACKEND_VALIDATE_UNAVAILABLE"
    # --- DOCUMENT (disclosed fallback, run boundaries preserved) ---------
    TOKEN_SPANS_RUNS = "TOKEN_SPANS_RUNS"
    TOKEN_NOT_UNIQUE = "TOKEN_NOT_UNIQUE"
    LOCATION_UNSUPPORTED = "LOCATION_UNSUPPORTED"
    CELL_MULTIPLE_PARAGRAPHS = "CELL_MULTIPLE_PARAGRAPHS"
    OPERATION_TYPE_UNSUPPORTED = "OPERATION_TYPE_UNSUPPORTED"
    # --- BACKEND, disclosed fallback ------------------------------------
    CAPABILITY_NOT_ROUTABLE = "CAPABILITY_NOT_ROUTABLE"
    # --- BACKEND, failures (map onto envelope error codes) ---------------
    BATCH_ROLLED_BACK = "BATCH_ROLLED_BACK"
    READBACK_MISMATCH = "READBACK_MISMATCH"
    NORMALIZE_FAILED = "NORMALIZE_FAILED"
    STAGE_CHECK_FAILED = "STAGE_CHECK_FAILED"
    BACKEND_VALIDATE_FAILED = "BACKEND_VALIDATE_FAILED"
    BACKEND_SINGLE_WRITER_VIOLATION = "BACKEND_SINGLE_WRITER_VIOLATION"


@dataclass(frozen=True)
class ReasonSpec:
    """Registry-backed semantics for one :class:`ReasonCode` member.

    ``envelope_code`` is the *backend-generic* coarse error code the
    executor puts into the ToolEnvelope ``errors[]``/``abort`` layer; the
    officecli path may resolve it through
    :data:`OFFICECLI_ENVELOPE_ALIASES` to keep the B0 spellings (E2).
    ``None`` means the reason is a disclosed fallback (or an UNVERIFIED
    disclosure) and must never be reported as an envelope error on its
    own.
    """

    category: ErrorCategory
    is_failure: bool
    envelope_code: Optional[str]
    description: str


REASON_CODE_CATALOG: Mapping[ReasonCode, ReasonSpec] = {
    ReasonCode.OFFICECLI_BINARY_MISSING: ReasonSpec(
        ErrorCategory.INFRASTRUCTURE, False, None,
        "officecli binary is not installed; the capability group reroutes to python-docx",
    ),
    ReasonCode.OFFICECLI_VERSION_UNSUPPORTED: ReasonSpec(
        ErrorCategory.INFRASTRUCTURE, False, None,
        "officecli failed the capability probe; the capability group reroutes to python-docx",
    ),
    ReasonCode.BACKEND_VALIDATE_UNAVAILABLE: ReasonSpec(
        ErrorCategory.INFRASTRUCTURE, False, None,
        "the backend has no OpenXML schema validator; the check stays UNVERIFIED",
    ),
    ReasonCode.TOKEN_SPANS_RUNS: ReasonSpec(
        ErrorCategory.DOCUMENT, False, None,
        "the placeholder token spans multiple runs; python-docx preserves the run structure",
    ),
    ReasonCode.TOKEN_NOT_UNIQUE: ReasonSpec(
        ErrorCategory.DOCUMENT, False, None,
        "the token is not unique at the location; a whole-scope replace would be unauthorized",
    ),
    ReasonCode.LOCATION_UNSUPPORTED: ReasonSpec(
        ErrorCategory.DOCUMENT, False, None,
        "the location's story is not addressable by this backend",
    ),
    ReasonCode.CELL_MULTIPLE_PARAGRAPHS: ReasonSpec(
        ErrorCategory.DOCUMENT, False, None,
        "the cell holds multiple paragraphs; this backend targets one paragraph",
    ),
    ReasonCode.OPERATION_TYPE_UNSUPPORTED: ReasonSpec(
        ErrorCategory.DOCUMENT, False, None,
        "the FillPlan operation type is not routable to this backend",
    ),
    ReasonCode.CAPABILITY_NOT_ROUTABLE: ReasonSpec(
        ErrorCategory.BACKEND, False, None,
        "the capability registry has no verified entry; the group reroutes to python-docx",
    ),
    ReasonCode.BATCH_ROLLED_BACK: ReasonSpec(
        ErrorCategory.BACKEND, True, "BACKEND_BATCH_FAILED",
        "the batch failed and was atomically rolled back",
    ),
    ReasonCode.READBACK_MISMATCH: ReasonSpec(
        ErrorCategory.BACKEND, True, "BACKEND_READBACK_FAILED",
        "the read-back found the staged text did not match what was written",
    ),
    ReasonCode.NORMALIZE_FAILED: ReasonSpec(
        ErrorCategory.BACKEND, True, "BACKEND_NORMALIZE_FAILED",
        "post-batch normalisation (w14 identity restore, red stripping) failed",
    ),
    ReasonCode.STAGE_CHECK_FAILED: ReasonSpec(
        ErrorCategory.BACKEND, True, "STAGE_CHECK_FAILED",
        "the E8 stage check rejected the state after a capability group",
    ),
    ReasonCode.BACKEND_VALIDATE_FAILED: ReasonSpec(
        ErrorCategory.BACKEND, True, "BACKEND_VALIDATE_FAILED",
        "OpenXML schema validation of the staged document failed",
    ),
    ReasonCode.BACKEND_SINGLE_WRITER_VIOLATION: ReasonSpec(
        ErrorCategory.BACKEND, True, "BACKEND_SINGLE_WRITER_VIOLATION",
        "a backend attempted to write a document another backend holds (E4)",
    ),
}


#: Backend name that keeps the B0-era OfficeCLI envelope spellings.
OFFICECLI_BACKEND_NAME = "officecli"

#: Generic envelope code -> the OfficeCLI spelling the B0 executor already
#: emits. Only the officecli path resolves these (E2 backward
#: compatibility); every other backend keeps the generic code, so a
#: python-docx failure is never reported as an OfficeCLI error.
OFFICECLI_ENVELOPE_ALIASES: Mapping[str, str] = {
    "BACKEND_BATCH_FAILED": "OFFICECLI_WRITE_FAILED",
    "BACKEND_READBACK_FAILED": "OFFICECLI_READBACK_FAILED",
    "BACKEND_NORMALIZE_FAILED": "OFFICECLI_NORMALIZE_FAILED",
}


def envelope_code_for(reason: ReasonCode, backend: Optional[str] = None) -> Optional[str]:
    """Return the envelope error code for ``reason`` (``None`` for fallbacks).

    The default mapping is backend-agnostic: every failure reason resolves
    to its generic ``BACKEND_*`` code. Passing ``backend="officecli"``
    resolves the B0-era ``OFFICECLI_*`` spellings for backward
    compatibility (E2); any other backend name — including python-docx —
    keeps the generic code, so failures are attributed to the backend
    family that actually produced them.
    """
    code = REASON_CODE_CATALOG[reason].envelope_code
    if code is not None and backend == OFFICECLI_BACKEND_NAME:
        return OFFICECLI_ENVELOPE_ALIASES.get(code, code)
    return code


def reason_category(reason: ReasonCode) -> ErrorCategory:
    """Return the error family ``reason`` belongs to."""
    return REASON_CODE_CATALOG[reason].category


_SHA256_HEX_LENGTH = 64


def _validate_sha256(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(
            "%s must be a %d-char SHA-256 hex digest or None, got %r"
            % (field_name, _SHA256_HEX_LENGTH, value)
        )
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            "%s must be hex: %r" % (field_name, value)
        ) from exc
    return value.lower()


@dataclass(frozen=True)
class OpOutcome:
    """Per-operation record inside a :class:`BackendResult`.

    ``before_sha256``/``after_sha256`` cover the W5-C requirement that every
    operation records its state before and after the mutation (E5).
    """

    status: str
    reason_code: Optional[ReasonCode] = None
    before_sha256: Optional[str] = None
    after_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in OP_STATUSES:
            raise ValueError("status must be one of %s, got %r" % (OP_STATUSES, self.status))
        if self.status == "FAILED":
            if self.reason_code is None:
                raise ValueError("a FAILED op outcome requires a reason_code")
        elif self.reason_code is not None:
            raise ValueError("reason_code is only allowed on FAILED outcomes")
        object.__setattr__(
            self, "before_sha256", _validate_sha256(self.before_sha256, "before_sha256")
        )
        object.__setattr__(
            self, "after_sha256", _validate_sha256(self.after_sha256, "after_sha256")
        )

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready view; the reason code serializes as its registry spelling."""
        return {
            "status": self.status,
            "reason_code": self.reason_code.value if self.reason_code is not None else None,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
        }


@dataclass(frozen=True)
class BackendResult:
    """What one backend did (or why it refused).

    Invariants (enforced at construction):

    * ``ok=True`` requires ``reason_code is None`` — a success never
      carries a failure reason;
    * ``ok=False`` requires a :class:`ReasonCode` — a failure never
      surfaces as a bare boolean;
    * ``detail`` is truncated to :data:`DETAIL_MAX_CHARS` characters so
      log noise can never smuggle a document dump into a report;
    * ``backend`` is a non-empty name such as ``officecli`` or
      ``python-docx``.
    """

    backend: str
    ok: bool
    reason_code: Optional[ReasonCode] = None
    detail: str = ""
    per_op: Mapping[str, OpOutcome] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.backend, str) or not self.backend:
            raise ValueError("backend must be a non-empty string")
        if self.ok:
            if self.reason_code is not None:
                raise ValueError("a successful result must not carry a reason_code")
        elif self.reason_code is None:
            raise ValueError("a failed result requires a reason_code")
        if not isinstance(self.detail, str):
            raise ValueError("detail must be a string")
        object.__setattr__(self, "detail", self.detail[:DETAIL_MAX_CHARS])
        # R3: every per-op key must be a non-empty string and every value an
        # immutable OpOutcome. Copying into a fresh dict keeps construction
        # decoupled from the caller's mapping; the proxy then makes the result
        # read-only for everyone. Keys are never coerced: ``str(key)`` would
        # let ``{1: a, "1": b}`` collapse into one entry and silently drop an
        # operation outcome.
        if not isinstance(self.per_op, Mapping):
            raise ValueError("per_op must be a mapping of op_id -> OpOutcome")
        frozen_ops: Dict[str, OpOutcome] = {}
        for key, value in dict(self.per_op).items():
            if not isinstance(key, str) or not key:
                raise ValueError(
                    "per_op keys must be non-empty strings, got %r" % (key,)
                )
            if not isinstance(value, OpOutcome):
                raise ValueError(
                    "per_op[%r] must be an OpOutcome, got %r" % (key, type(value).__name__)
                )
            frozen_ops[key] = value
        object.__setattr__(self, "per_op", MappingProxyType(frozen_ops))

    @classmethod
    def success(cls, backend: str, per_op: Optional[Mapping[str, OpOutcome]] = None,
                detail: str = "") -> "BackendResult":
        """Build an ``ok=True`` result."""
        if per_op is None:
            per_op = {}
        return cls(backend=backend, ok=True, detail=detail, per_op=per_op)

    @classmethod
    def failure(cls, backend: str, reason_code: ReasonCode, detail: str = "",
                per_op: Optional[Mapping[str, OpOutcome]] = None) -> "BackendResult":
        """Build an ``ok=False`` result carrying a structured reason."""
        if per_op is None:
            per_op = {}
        return cls(backend=backend, ok=False, reason_code=reason_code,
                   detail=detail, per_op=per_op)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready view of the whole result, including per-op outcomes.

        :meth:`per_op` is a read-only proxy, so serialization must go
        through this method (or ``dict(result.per_op)``); the returned
        mapping is a plain dict copy that cannot corrupt the result.
        """
        return {
            "backend": self.backend,
            "ok": self.ok,
            "reason_code": self.reason_code.value if self.reason_code is not None else None,
            "detail": self.detail,
            "per_op": {key: value.to_dict() for key, value in self.per_op.items()},
        }


class BackendError(Exception):
    """Typed raise channel for backend implementations (B2/B3).

    The executor layer translates this into the envelope error code via
    :func:`envelope_code_for`; nothing about the raise itself is swallowed.
    """

    def __init__(self, reason_code: ReasonCode, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = str(detail)[:DETAIL_MAX_CHARS]
        super().__init__("%s: %s" % (reason_code.value, self.detail))


class ValidationStatus(str, Enum):
    """The four legal states of a backend validation run (R2 model).

    ``PASSED`` and ``FAILED`` mean validation *executed*; ``UNAVAILABLE``
    means this backend has no validator at all; ``UNVERIFIED`` means a
    validator exists but the run could not execute (tooling missing).
    "Did not validate" therefore has two explicit non-pass states and can
    never collapse into ``PASSED``.
    """

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED = "UNVERIFIED"


#: The only reasons that may explain a validation that did not execute
#: (R2.4). It must be tooling unavailability — not a document-structure
#: fallback (``TOKEN_SPANS_RUNS``), not a routing decision
#: (``CAPABILITY_NOT_ROUTABLE``) and not "no validator at all"
#: (``BACKEND_VALIDATE_UNAVAILABLE``, which is its own UNAVAILABLE state).
VALIDATION_UNVERIFIED_REASONS = frozenset({
    ReasonCode.OFFICECLI_BINARY_MISSING,
    ReasonCode.OFFICECLI_VERSION_UNSUPPORTED,
})


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of :meth:`DocumentBackend.validate` — deliberately NOT a
    :class:`BackendResult`.

    Validation needs four states that do not fit the ok/reason binary;
    keeping them here stops BackendResult from growing validation-only
    fields (R2 requirement 5). Invariants (enforced at construction):

    * ``PASSED`` — validation ran and found no schema error. No reason
      code. A backend that never executed validation must not build this.
    * ``FAILED`` — validation ran and found problems. Requires
      ``BACKEND_VALIDATE_FAILED`` plus a non-empty ``detail`` (R2 req. 3).
    * ``UNAVAILABLE`` — the backend has no validator. Requires
      ``BACKEND_VALIDATE_UNAVAILABLE`` plus a non-empty ``detail`` so the
      disclosure stays traceable (R2 req. 2/4).
    * ``UNVERIFIED`` — a validator exists but could not run. Requires one
      of :data:`VALIDATION_UNVERIFIED_REASONS` (tooling unavailability)
      plus a non-empty ``detail`` for traceability (R2 req. 1/4).
    """

    backend: str
    status: ValidationStatus
    reason_code: Optional[ReasonCode] = None
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.backend, str) or not self.backend:
            raise ValueError("backend must be a non-empty string")
        # R2.1/R2.2: a bare string must not bypass the four-state logic.
        # ValidationStatus is a str-Enum, so an isinstance check (not a
        # value comparison) is required here.
        if not isinstance(self.status, ValidationStatus):
            raise ValueError(
                "status must be a ValidationStatus member, got %r" % (self.status,)
            )
        # R2.3: same for the reason code — a string is not a valid reason.
        if self.reason_code is not None and not isinstance(self.reason_code, ReasonCode):
            raise ValueError(
                "reason_code must be a ReasonCode member or None, got %r"
                % (self.reason_code,)
            )
        if not isinstance(self.detail, str):
            raise ValueError("detail must be a string")
        object.__setattr__(self, "detail", self.detail[:DETAIL_MAX_CHARS])
        if self.status is ValidationStatus.PASSED:
            if self.reason_code is not None:
                raise ValueError("PASSED must not carry a reason_code")
        elif self.status is ValidationStatus.FAILED:
            if self.reason_code is not ReasonCode.BACKEND_VALIDATE_FAILED:
                raise ValueError("FAILED requires reason_code BACKEND_VALIDATE_FAILED")
            if not self.detail:
                raise ValueError("FAILED requires a non-empty detail naming the problem")
        elif self.status is ValidationStatus.UNAVAILABLE:
            if self.reason_code is not ReasonCode.BACKEND_VALIDATE_UNAVAILABLE:
                raise ValueError("UNAVAILABLE requires reason_code BACKEND_VALIDATE_UNAVAILABLE")
            if not self.detail:
                raise ValueError("UNAVAILABLE requires a non-empty detail for traceability")
        else:  # UNVERIFIED
            # R2.4/R2.5: only tooling-unavailability reasons; a failure
            # reason belongs to FAILED, and BACKEND_VALIDATE_UNAVAILABLE
            # belongs to UNAVAILABLE — the two states stay distinct.
            if self.reason_code not in VALIDATION_UNVERIFIED_REASONS:
                raise ValueError(
                    "UNVERIFIED requires a tooling-unavailability reason from %s, "
                    "got %r" % (sorted(r.value for r in VALIDATION_UNVERIFIED_REASONS),
                                self.reason_code,)
                )
            if not self.detail:
                raise ValueError("UNVERIFIED requires a non-empty detail for traceability")

    @classmethod
    def passed(cls, backend: str) -> "ValidationResult":
        """Validation executed and found no schema error."""
        return cls(backend=backend, status=ValidationStatus.PASSED)

    @classmethod
    def failed(cls, backend: str, detail: str) -> "ValidationResult":
        """Validation executed and found schema problems."""
        return cls(backend=backend, status=ValidationStatus.FAILED,
                   reason_code=ReasonCode.BACKEND_VALIDATE_FAILED, detail=detail)

    @classmethod
    def unavailable(cls, backend: str, detail: str) -> "ValidationResult":
        """This backend has no OpenXML validator; the check stays UNVERIFIED upstream."""
        return cls(backend=backend, status=ValidationStatus.UNAVAILABLE,
                   reason_code=ReasonCode.BACKEND_VALIDATE_UNAVAILABLE, detail=detail)

    @classmethod
    def unverified(cls, backend: str, reason_code: ReasonCode, detail: str) -> "ValidationResult":
        """A validator exists but the run could not execute (tooling missing)."""
        return cls(backend=backend, status=ValidationStatus.UNVERIFIED,
                   reason_code=reason_code, detail=detail)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready view; the reason code serializes as its registry spelling."""
        return {
            "backend": self.backend,
            "status": self.status.value,
            "reason_code": self.reason_code.value if self.reason_code is not None else None,
            "detail": self.detail,
        }
