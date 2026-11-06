# -*- coding: utf-8 -*-
"""W4-2 tests: deterministic gate state machine and illegal transitions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from template_gate import GateState, GateStateError, GateStateMachine  # noqa: E402
from template_gate.errors import TEMPLATE_GATE_ILLEGAL_TRANSITION  # noqa: E402


class GateStateMachineTests(unittest.TestCase):
    def test_legal_path_to_execution(self) -> None:
        machine = GateStateMachine()
        machine.transition(GateState.ANALYZING)
        machine.transition(GateState.VALIDATING)
        machine.transition(GateState.READY_FOR_REVIEW)
        machine.transition(GateState.CONFIRMED)
        machine.begin_execution()
        self.assertEqual(machine.status, GateState.EXECUTING)
        self.assertEqual(len(machine.history), 5)

    def test_blocked_cannot_execute(self) -> None:
        blocked = GateStateMachine()
        for target in (GateState.ANALYZING, GateState.VALIDATING, GateState.BLOCKED):
            blocked.transition(target)
        with self.assertRaises(GateStateError) as raised:
            blocked.transition(GateState.EXECUTING)
        self.assertEqual(raised.exception.code, TEMPLATE_GATE_ILLEGAL_TRANSITION)

    def test_waiting_and_ready_cannot_execute(self) -> None:
        waiting = GateStateMachine()
        for target in (
            GateState.ANALYZING,
            GateState.VALIDATING,
            GateState.BLOCKED,
            GateState.WAITING_USER_INPUT,
        ):
            waiting.transition(target)
        with self.assertRaises(GateStateError):
            waiting.transition(GateState.EXECUTING)

        ready = GateStateMachine()
        for target in (
            GateState.ANALYZING,
            GateState.VALIDATING,
            GateState.READY_FOR_REVIEW,
        ):
            ready.transition(target)
        with self.assertRaises(GateStateError):
            ready.begin_execution()

    def test_invalidated_can_resume_analysis(self) -> None:
        machine = GateStateMachine()
        for target in (
            GateState.ANALYZING,
            GateState.VALIDATING,
            GateState.READY_FOR_REVIEW,
            GateState.CONFIRMED,
            GateState.INVALIDATED,
            GateState.ANALYZING,
        ):
            machine.transition(target)
        self.assertEqual(machine.status, GateState.ANALYZING)

    def test_rejected_is_terminal(self) -> None:
        machine = GateStateMachine()
        machine.transition(GateState.ANALYZING)
        machine.transition(GateState.REJECTED)
        with self.assertRaises(GateStateError):
            machine.transition(GateState.ANALYZING)

    def test_only_confirmed_can_begin_execution(self) -> None:
        machine = GateStateMachine(GateState.READY_FOR_REVIEW)
        with self.assertRaises(GateStateError):
            machine.begin_execution()


if __name__ == "__main__":
    unittest.main()
