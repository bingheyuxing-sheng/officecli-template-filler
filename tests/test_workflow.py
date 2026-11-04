# -*- coding: utf-8 -*-
"""Tests for the deterministic workflow helpers (gate, profiles, checkpoints, TOC)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from engine import (
    CONFIRMATION_FULL,
    CONFIRMATION_HOLD,
    CONFIRMATION_LIGHT,
    CONFIRMATION_SKIP,
    CHECKPOINT_STAGES,
    TOC_MISSING,
    TOC_STALE,
    WorkflowCheckpointStore,
    assess_toc,
    build_proofread_plan,
    profile_requirements,
    resolve_confirmation_gate,
    resolve_execution_profile,
    run_visual_qa_rounds,
    toc_degradation_chain,
)


class ConfirmationGateTests(unittest.TestCase):
    def test_no_open_decisions_skips(self) -> None:
        gate = resolve_confirmation_gate()
        self.assertEqual(gate["tier"], CONFIRMATION_SKIP)
        self.assertEqual(gate["must_ask_count"], 0)

    def test_must_ask_slot_forces_full_confirm(self) -> None:
        gate = resolve_confirmation_gate(
            slots=[{"confirmation_tier": "MUST_ASK_USER", "matched_text": "项目负责人"}],
            user_requested_skip=True,
        )
        self.assertEqual(gate["tier"], CONFIRMATION_FULL)
        self.assertEqual(gate["must_ask_count"], 1)

    def test_l4_or_blocking_conflict_holds(self) -> None:
        self.assertEqual(
            resolve_confirmation_gate(compatibility_level="L4")["tier"],
            CONFIRMATION_HOLD,
        )
        self.assertEqual(
            resolve_confirmation_gate(blocking_conflicts=["smartart"])["tier"],
            CONFIRMATION_HOLD,
        )

    def test_optional_choices_light_confirm(self) -> None:
        self.assertEqual(
            resolve_confirmation_gate(optional_choices=["页眉样式"])["tier"],
            CONFIRMATION_LIGHT,
        )


class ExecutionProfileTests(unittest.TestCase):
    def test_default_and_explicit_profiles(self) -> None:
        self.assertEqual(resolve_execution_profile(), "STANDARD")
        self.assertEqual(resolve_execution_profile("fast"), "FAST")

    def test_placeholder_images_force_full(self) -> None:
        self.assertEqual(
            resolve_execution_profile("FAST", has_placeholder_images=True),
            "FULL",
        )

    def test_requirements_and_unknown_profile(self) -> None:
        self.assertEqual(profile_requirements("FULL")["visual_qa_rounds"], 2)
        with self.assertRaises(ValueError):
            resolve_execution_profile("TURBO")
        with self.assertRaises(ValueError):
            profile_requirements("TURBO")


class CheckpointStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = WorkflowCheckpointStore(self._tmp.name, "task-1")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_resume_skips_failed_stage(self) -> None:
        self.assertEqual(self.store.resume_stage(), CHECKPOINT_STAGES[0])

        self.store.record("content", qa_status="PASSED")
        self.assertEqual(self.store.resume_stage(), "tables")

        self.store.record("tables", qa_status="FAILED")
        self.assertEqual(self.store.latest_valid()["stage"], "content")
        self.assertEqual(self.store.resume_stage(), "tables")

    def test_all_stages_pass_returns_deliver(self) -> None:
        for stage in CHECKPOINT_STAGES:
            self.store.record(stage, qa_status="PASSED")
        self.assertEqual(self.store.resume_stage(), "deliver")

    def test_invalid_stage_or_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.record("unknown", qa_status="PASSED")
        with self.assertRaises(ValueError):
            self.store.record("content", qa_status="MAYBE")

    def test_checkpoint_file_is_atomic_and_readable(self) -> None:
        self.store.record("content", qa_status="PENDING_HUMAN_REVIEW")
        self.assertTrue(os.path.isfile(self.store.path))
        self.assertFalse(os.path.isfile(self.store.path + ".tmp"))


class TocAssessmentTests(unittest.TestCase):
    def test_missing_toc(self) -> None:
        document = docx.Document()
        document.add_heading("第一章 总则", level=1)
        report = assess_toc(document)
        self.assertEqual(report["status"], TOC_MISSING)
        self.assertEqual(len(toc_degradation_chain(report["status"])), 3)

    def test_stale_toc_error_marker(self) -> None:
        document = docx.Document()
        document.add_heading("第一章 总则", level=1)
        paragraph = document.add_paragraph()
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), 'TOC \\o "1-3" \\h')
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "错误！未定义书签。"
        run.append(text)
        field.append(run)
        paragraph._p.append(field)

        self.assertEqual(assess_toc(document)["status"], TOC_STALE)


class VisualQaRoundTests(unittest.TestCase):
    def test_single_round_when_no_high_issues(self) -> None:
        with mock.patch(
            "engine.qa_engine.run_visual_layout_qa",
            return_value={"issues": [], "coverage_gaps": [], "unverified_count": 0},
        ):
            result = run_visual_qa_rounds("unused.docx", max_rounds=3)
        self.assertEqual(len(result["rounds"]), 1)
        self.assertTrue(result["converged"])


class ProofreadLogicCheckTests(unittest.TestCase):
    def test_duplicate_heading_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dup.docx")
            document = docx.Document()
            document.add_heading("第一章 总则", level=1)
            document.add_paragraph("正文一。")
            document.add_heading("第一章 总则", level=1)
            document.add_paragraph("正文二。")
            document.save(path)

            plan = build_proofread_plan(path)
            comments = [a.get("comment", "") for a in plan["actions"]]
            self.assertTrue(any("PROOFREAD_DUPLICATE_HEADING" in text for text in comments))


if __name__ == "__main__":
    unittest.main()
