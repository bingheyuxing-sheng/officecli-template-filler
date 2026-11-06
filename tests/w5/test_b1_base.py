# -*- coding: utf-8 -*-
"""W5-B1 unit tests: abstract backend interface and capability invariants.

The core invariant under test is W5-B1 requirement 7: a capability that is
not verified can never be constructed as available, so the registry cannot
lie even by accident.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from document_backends.base import (  # noqa: E402
    BACKEND_FORMATS,
    OPERATION_KINDS,
    BackendOp,
    BackendTarget,
    CapabilityRecord,
    CapabilityReport,
    DocumentBackend,
)
from document_backends.result import BackendResult, OpOutcome, ValidationResult  # noqa: E402

EVIDENCE = ("test:test_officecli_writer",)


def _verified_record(**overrides) -> CapabilityRecord:
    values = {
        "capability_id": "docx.text.replace_single_run",
        "backend": "officecli",
        "available": True,
        "verified": True,
        "verified_by": EVIDENCE,
        "verified_at": "2026-11-06T23:00:00+08:00",
        "risk_level": "low",
    }
    values.update(overrides)
    return CapabilityRecord(**values)


class BackendTargetTests(unittest.TestCase):
    def test_valid_target(self) -> None:
        target = BackendTarget(template_path="tpl.docx", staged_path="stage.docx", fmt="docx")
        self.assertEqual(target.fmt, "docx")

    def test_format_must_be_known(self) -> None:
        with self.assertRaises(ValueError):
            BackendTarget(template_path="a.pptx", staged_path="b.pptx", fmt="pptx")

    def test_empty_paths_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BackendTarget(template_path="", staged_path="stage.docx", fmt="docx")

    def test_template_and_stage_must_differ(self) -> None:
        with self.assertRaises(ValueError):
            BackendTarget(template_path="same.docx", staged_path="same.docx", fmt="docx")

    def test_xlsx_is_a_valid_format(self) -> None:
        self.assertIn("xlsx", BACKEND_FORMATS)
        BackendTarget(template_path="t.xlsx", staged_path="s.xlsx", fmt="xlsx")


class BackendOpTests(unittest.TestCase):
    def _text_op(self, **overrides) -> BackendOp:
        values = {
            "op_id": "OP_001",
            "slot_id": "SLOT_1",
            "kind": "replace_text",
            "location_id": "body.p[0]",
            "token": "{{name}}",
            "value": "Alice",
        }
        values.update(overrides)
        return BackendOp(**values)

    def test_valid_text_op(self) -> None:
        op = self._text_op()
        self.assertEqual(op.kind, "replace_text")
        self.assertEqual(op.value, "Alice")

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._text_op(kind="delete_paragraph")

    def test_kinds_mirror_contract_03(self) -> None:
        self.assertEqual(OPERATION_KINDS,
                         ("replace_text", "fill_paragraph", "fill_cell", "replace_image"))

    def test_missing_ids_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._text_op(op_id="")
        with self.assertRaises(ValueError):
            self._text_op(slot_id="")
        with self.assertRaises(ValueError):
            self._text_op(location_id="")

    def test_text_op_requires_token(self) -> None:
        with self.assertRaises(ValueError):
            self._text_op(token=None)

    def test_image_op_may_omit_token(self) -> None:
        op = self._text_op(kind="replace_image", token=None, value="media/logo.png")
        self.assertIsNone(op.token)

    def test_non_string_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._text_op(value=42)


class CapabilityRecordTests(unittest.TestCase):
    def test_verified_available_record_round_trips(self) -> None:
        record = _verified_record()
        self.assertTrue(record.available)
        self.assertEqual(record.verified_by, EVIDENCE)

    def test_unverified_capability_cannot_be_available(self) -> None:
        with self.assertRaises(ValueError):
            _verified_record(verified=False, available=True)

    def test_verified_without_evidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _verified_record(verified_by=())

    def test_available_without_evidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _verified_record(verified_by=())

    def test_unavailable_unverified_record_is_fine(self) -> None:
        record = _verified_record(available=False, verified=False, verified_by=(),
                                  risk_level="high")
        self.assertFalse(record.available)

    def test_unknown_risk_level_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _verified_record(risk_level="extreme")

    def test_capability_id_namespace_is_enforced(self) -> None:
        with self.assertRaises(ValueError):
            _verified_record(capability_id="docx text replace")
        with self.assertRaises(ValueError):
            _verified_record(capability_id="docx")
        _verified_record(capability_id="docx.text.replace_single_run")

    def test_empty_backend_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _verified_record(backend="")


class CapabilityEvidenceTests(unittest.TestCase):
    """R4: evidence quality rules for CapabilityRecord/CapabilityReport."""

    def test_verified_by_entries_must_be_non_empty_strings(self) -> None:
        with self.assertRaises(ValueError):
            _verified_record(verified_by=("",))
        with self.assertRaises(ValueError):
            _verified_record(verified_by=("probe:P2", 42))  # type: ignore[arg-type]

    def test_verified_by_rejects_duplicate_evidence(self) -> None:
        with self.assertRaises(ValueError):
            _verified_record(verified_by=("probe:P2", "probe:P2"))

    def test_verified_at_requires_iso8601_with_timezone(self) -> None:
        _verified_record(verified_at="2026-11-06T23:00:00+08:00")
        _verified_record(verified_at="2026-11-06T15:00:00Z")
        for bad in ("2026-11-06 23:00", "2026-11-06T23:00:00", 12345):
            with self.assertRaises(ValueError):
                _verified_record(verified_at=bad)

    def test_verified_at_rejects_impossible_dates(self) -> None:
        # R4: a real parser, not a shape regex, rejects month 13 / Feb 30.
        for bad in ("2026-13-01T00:00:00+08:00", "2026-02-30T00:00:00+08:00",
                    "2026-00-10T00:00:00+08:00"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    _verified_record(verified_at=bad)

    def test_verified_at_rejects_impossible_times(self) -> None:
        # 24:00:00 is legal ISO-8601 (end-of-day) and the real parser
        # accepts it; 24:00:01 and out-of-range minutes/seconds are not.
        for bad in ("2026-11-06T24:00:01+08:00", "2026-11-06T23:60:00+08:00",
                    "2026-11-06T23:00:61+08:00"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    _verified_record(verified_at=bad)
        _verified_record(verified_at="2026-11-06T24:00:00+08:00")

    def test_verified_at_rejects_out_of_range_offsets(self) -> None:
        for bad in ("2026-11-06T23:00:00+99:00", "2026-11-06T23:00:00-25:00"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    _verified_record(verified_at=bad)

    def test_verified_at_rejects_missing_timezone(self) -> None:
        for bad in ("2026-11-06T23:00:00", "2026-11-06", "2026-11-06T23:00"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    _verified_record(verified_at=bad)

    def test_verified_at_accepts_utc_and_offset_forms(self) -> None:
        for good in ("2026-11-06T15:00:00Z", "2026-11-06T23:00:00+08:00",
                     "2026-11-06T10:00:00-05:00", "2026-11-06T23:00:00.123456+08:00"):
            with self.subTest(value=good):
                self.assertEqual(_verified_record(verified_at=good).verified_at, good)

    def test_verified_by_rejects_whitespace_only_evidence(self) -> None:
        for bad in ("   ", "\t", "\n", " \t\n "):
            with self.subTest(value=repr(bad)):
                with self.assertRaises(ValueError):
                    _verified_record(verified_by=(bad,))

    def test_report_rejects_foreign_backend_records(self) -> None:
        foreign = _verified_record(backend="python-docx")
        with self.assertRaises(ValueError):
            CapabilityReport(backend="officecli", records=[foreign])

    def test_report_rejects_duplicate_capability_ids(self) -> None:
        with self.assertRaises(ValueError):
            CapabilityReport(backend="officecli",
                             records=[_verified_record(), _verified_record()])


class CapabilityReportTests(unittest.TestCase):
    def test_lookup_finds_declared_capability(self) -> None:
        record = _verified_record()
        report = CapabilityReport(backend="officecli", records=[record])
        self.assertEqual(report.lookup("docx.text.replace_single_run"), record)

    def test_lookup_unknown_raises_key_error(self) -> None:
        report = CapabilityReport(backend="officecli", records=[])
        with self.assertRaises(KeyError):
            report.lookup("xlsx.row.clone")

    def test_available_capabilities_lists_only_available(self) -> None:
        available = _verified_record()
        absent = _verified_record(capability_id="docx.header_footer.text_replace",
                                  available=False, verified=False, verified_by=())
        report = CapabilityReport(backend="officecli", records=[available, absent])
        self.assertEqual(report.available_capabilities(),
                         ("docx.text.replace_single_run",))

    def test_records_are_copied_into_a_tuple(self) -> None:
        records = [_verified_record()]
        report = CapabilityReport(backend="officecli", records=records)
        records.clear()
        self.assertEqual(len(report.records), 1)


class _FakeBackend(DocumentBackend):
    """Smallest legal implementation: proves the ABC is implementable."""

    @property
    def name(self) -> str:
        return "fake"

    def capabilities(self, fmt: str) -> CapabilityReport:
        return CapabilityReport(backend=self.name, records=[_verified_record(backend=self.name)])

    def batch(self, target, ops) -> BackendResult:  # noqa: ANN001
        return BackendResult.success(
            self.name,
            per_op={op.op_id: OpOutcome(status="SUCCESS") for op in ops},
        )

    def readback(self, target, paths) -> BackendResult:  # noqa: ANN001
        return BackendResult.success(self.name)

    def normalize(self, target, red_targets=None) -> BackendResult:  # noqa: ANN001
        return BackendResult.success(self.name)

    def validate(self, target) -> ValidationResult:  # noqa: ANN001
        return ValidationResult.passed(self.name)


class DocumentBackendAbcTests(unittest.TestCase):
    def test_abstract_class_cannot_be_instantiated(self) -> None:
        with self.assertRaises(TypeError):
            DocumentBackend()  # type: ignore[abstract]

    def test_full_implementation_is_instantiable(self) -> None:
        backend = _FakeBackend()
        self.assertEqual(backend.name, "fake")
        self.assertEqual(backend.capabilities("docx").backend, "fake")

    def test_batch_returns_a_structured_result(self) -> None:
        backend = _FakeBackend()
        target = BackendTarget(template_path="t.docx", staged_path="s.docx", fmt="docx")
        ops = [BackendOp(op_id="OP_001", slot_id="S1", kind="replace_text",
                         location_id="body.p[0]", token="{{x}}", value="v")]
        result = backend.batch(target, ops)
        self.assertTrue(result.ok)
        self.assertEqual(result.per_op["OP_001"].status, "SUCCESS")


if __name__ == "__main__":
    unittest.main()
