# -*- coding: utf-8 -*-
"""Deterministic state machine for the Template Understanding Gate."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .errors import GateStateError
from .models import GateState

TRANSITIONS: Dict[GateState, Tuple[GateState, ...]] = {
    GateState.DISCOVERING: (GateState.ANALYZING,),
    GateState.ANALYZING: (GateState.VALIDATING, GateState.REJECTED),
    GateState.VALIDATING: (GateState.BLOCKED, GateState.READY_FOR_REVIEW, GateState.REJECTED),
    GateState.BLOCKED: (GateState.WAITING_USER_INPUT, GateState.REJECTED),
    GateState.WAITING_USER_INPUT: (GateState.ANALYZING, GateState.REJECTED),
    GateState.READY_FOR_REVIEW: (GateState.CONFIRMED, GateState.ANALYZING, GateState.REJECTED),
    GateState.CONFIRMED: (GateState.EXECUTING, GateState.INVALIDATED),
    GateState.EXECUTING: (GateState.INVALIDATED,),
    GateState.INVALIDATED: (GateState.ANALYZING,),
    GateState.REJECTED: (),
}


def allowed_targets(status: GateState) -> Tuple[GateState, ...]:
    return TRANSITIONS.get(status, ())


def can_transition(current: GateState, target: GateState) -> bool:
    return target in allowed_targets(current)


class GateStateMachine:
    """Pure in-memory state machine; persistence is handled by ``store.py``."""

    def __init__(self, status: Optional[GateState] = None) -> None:
        self._status = status or GateState.DISCOVERING
        self.history: list = []

    @property
    def status(self) -> GateState:
        return self._status

    def transition(self, target: GateState, *, reason: str = "") -> GateState:
        if not isinstance(target, GateState):
            target = GateState(str(target).strip().upper())
        current = self._status
        if target not in allowed_targets(current):
            raise GateStateError(
                "illegal template gate transition: %s -> %s" % (current.value, target.value),
                current=current.value,
                target=target.value,
            )
        self.history.append(
            {"from": current.value, "to": target.value, "reason": str(reason or "")}
        )
        self._status = target
        return self._status

    def assert_can_execute(self) -> None:
        """Only CONFIRMED may enter formal execution."""
        if self._status != GateState.CONFIRMED:
            raise GateStateError(
                "formal execution requires CONFIRMED, current=%s" % self._status.value,
                current=self._status.value,
                target=GateState.EXECUTING.value,
            )

    def begin_execution(self, *, reason: str = "") -> GateState:
        self.assert_can_execute()
        return self.transition(GateState.EXECUTING, reason=reason)

    def mark_invalidated(self, *, reason: str) -> GateState:
        return self.transition(GateState.INVALIDATED, reason=reason)
