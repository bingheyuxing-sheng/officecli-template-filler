# -*- coding: utf-8 -*-
"""W5-B1 — Minimal abstract backend interface (base.py).

The interface is shaped by the FillPlan 4.0 operation model (contract 03),
not by the officecli verb list. Key consequences:

* There is **no** ``add``/``remove``/``move``/``swap``: FillPlan sets
  ``global_policy.allow_structure_change=false``, so structure verbs have
  no legal caller inside a fill task.
* :meth:`DocumentBackend.batch` is the **only** mutation entry. Backends
  never widen scope on their own: every :class:`BackendOp` is a
  projection of an executor-authorized FillPlan operation, and the backend
  has no way to express "also touch the neighbour" (W5-C requirements 1–3).
* :class:`BackendTarget` carries the read-only template baseline and the
  single writable staging path. A backend writing ``template_path`` is a
  contract violation.
* :class:`CapabilityRecord` makes "unverified must never be reported as
  supported" a construction-time invariant (W5-B1 requirement 7), so a
  lying registry entry cannot even be built.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence, Tuple

from .result import BackendResult, ValidationResult

__all__ = [
    "OPERATION_KINDS",
    "BACKEND_FORMATS",
    "BackendTarget",
    "BackendOp",
    "CapabilityRecord",
    "CapabilityReport",
    "DocumentBackend",
]

#: FillPlan 4.0 operation types (contract 03; produced by plan_builder).
OPERATION_KINDS: Tuple[str, ...] = ("replace_text", "fill_paragraph", "fill_cell", "replace_image")

#: Container formats a backend session may target.
BACKEND_FORMATS: Tuple[str, ...] = ("docx", "xlsx")

_CAPABILITY_ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9_]+)+$")
_RISK_LEVELS: Tuple[str, ...] = ("low", "medium", "high")


def _validate_verified_at(value: object) -> str:
    """Parse ``verified_at`` as a real ISO-8601 datetime with a timezone (R4).

    A regex only proves the shape; :func:`datetime.fromisoformat` also
    rejects impossible dates (month 13, day 32), impossible times
    (hour 24) and out-of-range UTC offsets. A timestamp without a
    timezone is rejected because evidence must be comparable across
    machines.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(
            "verified_at must be a non-empty ISO-8601 timestamp string, got %r"
            % (value,)
        )
    # ``fromisoformat`` accepts 'Z' from Python 3.11 on; normalise so the
    # check behaves identically on the project's older interpreters.
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    # ``fromisoformat`` accepts the ISO-8601 end-of-day form 24:00:00 on some
    # interpreters (3.11+) but rejects it on others (3.12). Normalize it before
    # parsing so the validation verdict is identical across the supported
    # Python range; the stored value keeps the caller's original spelling.
    candidate = candidate.replace("T24:00:00", "T00:00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(
            "verified_at is not a valid ISO-8601 date-time: %r" % (value,)
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError(
            "verified_at must carry an explicit timezone offset or 'Z', got %r"
            % (value,)
        )
    return value


@dataclass(frozen=True)
class BackendTarget:
    """One backend session: read-only template + the single writable stage.

    ``template_path`` is the byte-stable baseline used for normalisation
    (w14 identity restore) and fingerprint comparison. ``staged_path`` is
    the only path any backend may write, and it always lives inside the
    DocumentTransaction staging area — backends never publish.
    """

    template_path: str
    staged_path: str
    fmt: str

    def __post_init__(self) -> None:
        if not isinstance(self.template_path, str) or not self.template_path:
            raise ValueError("template_path must be a non-empty string")
        if not isinstance(self.staged_path, str) or not self.staged_path:
            raise ValueError("staged_path must be a non-empty string")
        if self.template_path == self.staged_path:
            raise ValueError(
                "template_path and staged_path must differ: the template is a "
                "read-only baseline (AGENTS.md §1.1.1)"
            )
        if self.fmt not in BACKEND_FORMATS:
            raise ValueError("fmt must be one of %s, got %r" % (BACKEND_FORMATS, self.fmt))


@dataclass(frozen=True)
class BackendOp:
    """A backend execution unit projected from one FillPlan operation.

    The backend has no authorization vocabulary: preconditions, protected
    regions and capacity were already checked by the executor, which is
    why this object carries no policy fields at all.
    """

    op_id: str
    slot_id: str
    kind: str
    location_id: str
    token: Optional[str] = None
    value: str = ""

    def __post_init__(self) -> None:
        for name in ("op_id", "slot_id", "location_id"):
            raw = getattr(self, name)
            if not isinstance(raw, str) or not raw:
                raise ValueError("%s must be a non-empty string" % name)
        if self.kind not in OPERATION_KINDS:
            raise ValueError("kind must be one of %s, got %r" % (OPERATION_KINDS, self.kind))
        if self.token is not None and not isinstance(self.token, str):
            raise ValueError("token must be a string or None")
        if self.token is None and self.kind != "replace_image":
            raise ValueError(
                "text operations require the slot's matched token; only "
                "replace_image may omit it"
            )
        if not isinstance(self.value, str):
            raise ValueError("value must be a string")


@dataclass(frozen=True)
class CapabilityRecord:
    """One registry entry stating what a backend can do (W5-B1 requirement 7).

    Construction invariants:

    * ``available=True`` requires ``verified=True`` **and** a non-empty
      ``verified_by`` evidence trail — an unverified capability can never
      be reported as supported;
    * ``verified=True`` requires ``verified_by`` — "trust me" is not
      verification;
    * ``capability_id`` follows the matrix namespace
      (``docx.text.replace_single_run``), ``risk_level`` is one of the
      three audit levels.
    """

    capability_id: str
    backend: str
    available: bool
    verified: bool
    verified_by: Tuple[str, ...] = ()
    verified_at: Optional[str] = None
    risk_level: str = "high"
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not _CAPABILITY_ID_RE.match(self.capability_id):
            raise ValueError(
                "capability_id must look like 'docx.text.replace_single_run', got %r"
                % (self.capability_id,)
            )
        if not isinstance(self.backend, str) or not self.backend:
            raise ValueError("backend must be a non-empty string")
        if not isinstance(self.verified_by, tuple):
            raise ValueError("verified_by must be a tuple of evidence strings")
        for item in self.verified_by:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    "verified_by entries must be non-empty, non-whitespace strings"
                )
        if len(self.verified_by) != len(set(self.verified_by)):
            raise ValueError(
                "verified_by entries must be unique: duplicate evidence is not proof"
            )
        if self.verified_at is not None:
            object.__setattr__(self, "verified_at", _validate_verified_at(self.verified_at))
        if self.verified and not self.verified_by:
            raise ValueError("a verified capability requires verified_by evidence")
        if self.available and not (self.verified and self.verified_by):
            raise ValueError(
                "an unverified capability must never be marked available "
                "(W5-B1 requirement 7)"
            )
        if self.risk_level not in _RISK_LEVELS:
            raise ValueError("risk_level must be one of %s, got %r" % (_RISK_LEVELS, self.risk_level))


@dataclass(frozen=True)
class CapabilityReport:
    """What one backend supports for one container format."""

    backend: str
    records: Tuple[CapabilityRecord, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.backend, str) or not self.backend:
            raise ValueError("backend must be a non-empty string")
        seen: dict = {}
        for record in self.records:
            if record.backend != self.backend:
                raise ValueError(
                    "record for %s declares backend %r but the report speaks for %r"
                    % (record.capability_id, record.backend, self.backend)
                )
            if record.capability_id in seen:
                raise ValueError(
                    "duplicate capability_id %r in one report" % (record.capability_id,)
                )
            seen[record.capability_id] = record
        object.__setattr__(self, "records", tuple(self.records))

    def lookup(self, capability_id: str) -> CapabilityRecord:
        """Return the record for ``capability_id`` or raise ``KeyError``."""
        for record in self.records:
            if record.capability_id == capability_id:
                return record
        raise KeyError(
            "backend %s declares no capability %r" % (self.backend, capability_id)
        )

    def available_capabilities(self) -> Tuple[str, ...]:
        """Ids of the records that are both available and verified."""
        return tuple(
            record.capability_id for record in self.records if record.available
        )


class DocumentBackend(ABC):
    """Abstract document mutation backend (B1 skeleton; B2/B3 implement).

    The five verbs, in the order a fill task uses them:

    1. :meth:`capabilities` — registry-backed statement of what this
       backend can do for a format;
    2. :meth:`batch` — the only mutation entry. One call applies a group of
       already-authorized operations to ``target.staged_path`` and returns
       one :class:`BackendResult`. Serial stages, single writer per stage
       (E4): a backend must refuse if it can detect another live writer.
    3. :meth:`readback` — batch read window over freshly written nodes
       (opens once, reads N paths, closes the resident before returning).
    4. :meth:`normalize` — pre-QA normalisation of the staged file against
       ``target.template_path`` (officecli: w14 identity restore + red
       placeholder stripping; python: no-op). A failure here must be
       reported, never skipped (E6).
    5. :meth:`validate` — OpenXML schema validation reported through a
       separate four-state :class:`ValidationResult`
       (PASSED / FAILED / UNAVAILABLE / UNVERIFIED), so "no validator" and
       "not executed" never masquerade as a pass (E6).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable backend name, e.g. ``officecli`` or ``python-docx``."""

    @abstractmethod
    def capabilities(self, fmt: str) -> CapabilityReport:
        """Return the capability report for container format ``fmt``."""

    @abstractmethod
    def batch(self, target: BackendTarget, ops: Sequence[BackendOp]) -> BackendResult:
        """Apply ``ops`` to ``target.staged_path``; never to ``template_path``."""

    @abstractmethod
    def readback(self, target: BackendTarget, paths: Sequence[str]) -> BackendResult:
        """Read back node texts after a batch, closing any resident process."""

    @abstractmethod
    def normalize(self, target: BackendTarget,
                  red_targets: Optional[Sequence[tuple]] = None) -> BackendResult:
        """Normalise the staged file against the template baseline before QA."""

    @abstractmethod
    def validate(self, target: BackendTarget) -> ValidationResult:
        """OpenXML schema validation as a four-state :class:`ValidationResult`.

        ``PASSED`` only when validation actually ran and found no error;
        no validator → ``UNAVAILABLE``; validator exists but could not run
        → ``UNVERIFIED``; problems found → ``FAILED`` with a reason. A
        backend without a validator must never fabricate a pass.
        """
