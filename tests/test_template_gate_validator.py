# -*- coding: utf-8 -*-
"""W4-6 tests: Gate Validator checks and error-code mapping."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from template_gate import (  # noqa: E402
    TemplateGateError,
    build_analysis,
    require_confirmed_gate,
    validate_gate,
)
from template_gate.report import build_report  # noqa: E402
from template_gate.store import GateStore  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402


def _template(directory: str) -> str:
    path = os.path.join(directory, "template.docx")
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    document.save(path)
    return path


def _confirmed(template: str, gate_home: str) -> tuple:
    analysis = build_analysis(template, "GENERATE")
    report = build_report(analysis)
    store = GateStore(gate_home)
    record = store.confirm(analysis, report, user_statement="确认", ttl_seconds=3600)
    spec = build_document_spec_from_path(template)
    return store, record, analysis, spec


class GateValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.gate_home = os.path.join(self._tmp.name, "gates")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_record_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            store, record, _analysis, spec = _confirmed(template, self.gate_home)
            verdict = validate_gate(template, "GENERATE", gate_record=record, spec=spec, gate_home=self.gate_home)
        self.assertTrue(verdict["passed"])
        self.assertIsNone(verdict["code"])
        self.assertTrue(all(item["ok"] for item in verdict["checks"]))

    def test_missing_record_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            verdict = validate_gate(template, "GENERATE", gate_home=self.gate_home)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["code"], "TEMPLATE_GATE_REQUIRED")

    def test_tampered_record_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            _store, record, _analysis, spec = _confirmed(template, self.gate_home)
            tampered = dict(record)
            tampered["user_statement"] = "篡改"
            verdict = validate_gate(template, "GENERATE", gate_record=tampered, spec=spec, gate_home=self.gate_home)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["code"], "TEMPLATE_GATE_CONFIRMATION_REQUIRED")

    def test_expired_record_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            store, record, _analysis, spec = _confirmed(template, self.gate_home)
            expired = dict(record)
            expired["expires_at"] = "2000-01-01T00:00:00+00:00"
            store.save(expired)
            expired = store.load(record["gate_id"]) or expired
            verdict = validate_gate(template, "GENERATE", gate_record=expired, spec=spec, gate_home=self.gate_home)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["code"], "TEMPLATE_GATE_STALE")

    def test_template_change_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            _store, record, _analysis, spec = _confirmed(template, self.gate_home)
            document = docx.Document(template)
            document.add_paragraph("追加内容")
            document.save(template)
            verdict = validate_gate(template, "GENERATE", gate_record=record, spec=spec, gate_home=self.gate_home)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["code"], "TEMPLATE_GATE_STALE")

    def test_spec_change_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            _store, record, _analysis, spec = _confirmed(template, self.gate_home)
            mutated = copy.deepcopy(spec)
            mutated.setdefault("warnings", []).append(
                {"code": "TEST_ONLY", "severity": "low", "detail": "spec changed"}
            )
            verdict = validate_gate(template, "GENERATE", gate_record=record, spec=mutated, gate_home=self.gate_home)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["code"], "TEMPLATE_GATE_STALE")

    def test_task_type_change_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            _store, record, _analysis, spec = _confirmed(template, self.gate_home)
            verdict = validate_gate(template, "REVIEW", gate_record=record, spec=spec, gate_home=self.gate_home)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["code"], "TEMPLATE_GATE_STALE")

    def test_blocking_count_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            store, record, _analysis, spec = _confirmed(template, self.gate_home)
            changed = dict(record)
            changed["blocking_count"] = 1
            store.save(changed)
            changed = store.load(record["gate_id"]) or changed
            verdict = validate_gate(template, "GENERATE", gate_record=changed, spec=spec, gate_home=self.gate_home)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["code"], "TEMPLATE_EVIDENCE_INCOMPLETE")

    def test_evidence_digest_change_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            store, record, _analysis, spec = _confirmed(template, self.gate_home)
            changed = dict(record)
            changed["evidence_digest"] = "0" * 64
            store.save(changed)
            changed = store.load(record["gate_id"]) or changed
            verdict = validate_gate(template, "GENERATE", gate_record=changed, spec=spec, gate_home=self.gate_home)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["code"], "TEMPLATE_GATE_STALE")

    def test_require_confirmed_gate_raises_with_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            with self.assertRaises(TemplateGateError) as raised:
                require_confirmed_gate(template, "GENERATE", gate_home=self.gate_home)
        self.assertEqual(raised.exception.code, "TEMPLATE_GATE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
