# -*- coding: utf-8 -*-
"""W2 real-template fixture matrix: six classes, success/refusal/QA/rollback.

Each fixture class under ``tests/fixtures/`` is committed and self-contained:

* ``template.docx``        read-only template bytes (SHA-256 pinned in expected.json)
* ``content_plan.json``    ContentPlan 4.0 produced once by the real builder
* ``fill_plan.json``       FillPlan 4.0 for the class' primary scenario
* ``expected/expected.json`` slots, protected regions, unsupported features,
  expected text and expected status/outcome

The tests rebuild the DocumentSpec 4.0 twice from the committed template to prove
slot stability, compare it with the pinned expectation, validate both plans and
execute them through the real executor and QA pipeline.  Deliverable paths live
in a temporary directory, so the fixtures themselves are never modified.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gate_helpers import ensure_gate  # noqa: E402
from support import sha256_file  # noqa: E402

from content_intelligence import build_content_plan, build_fill_plan, validate_fill_plan  # noqa: E402
from document_engine import execute_fill_plan  # noqa: E402
from engine.ooxml_utils import LogicalParagraphView, iter_all_document_paragraphs_with_Wait_context  # noqa: E402
from qa.gate import resolve_required_checks  # noqa: E402
from qa.report_builder import build_qa_report, check_record  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402
from template_intelligence.spec_validator import validate_document_spec  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

CLASS_NAMES = (
    "class_01_basic_report",
    "class_02_complex_table",
    "class_03_header_footer",
    "class_04_images",
    "class_05_nested_structure",
    "class_06_complex_document",
)

_SLOT_FIELDS = (
    "slot_id",
    "slot_key",
    "location_id",
    "matched_text",
    "occurrence",
    "candidate_type",
    "protection_status",
    "confirmation_tier",
    "scope",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _text_map(document) -> dict:
    """location_id -> logical paragraph text (cross-run, cross-story)."""
    mapping: dict = {}
    for context in iter_all_document_paragraphs_with_Wait_context(document):
        mapping.setdefault(context["location_id"], LogicalParagraphView(context["p_el"]).logical_text)
    return mapping


def _slot_records(spec: dict) -> list:
    return [{field: slot.get(field) for field in _SLOT_FIELDS} for slot in spec["slots"]]


def _region_records(spec: dict) -> list:
    records = [
        {
            "kind": region.get("kind"),
            "location_id": region.get("location_id"),
            "severity": region.get("severity"),
        }
        for region in spec["protected_regions"]
    ]
    return sorted(records, key=lambda item: (item["kind"], item["location_id"], item["severity"]))


def _unsupported_records(spec: dict) -> list:
    records = [
        {"code": item.get("code"), "location_id": item.get("location_id")}
        for item in spec["unsupported_features"]
    ]
    return sorted(records, key=lambda item: (item["code"], item["location_id"] or ""))


def _leftovers(directory: Path) -> list:
    return sorted(
        item.name for item in directory.iterdir()
        if ".tmp-" in item.name or ".pending-" in item.name
    )


class FixtureMatrixTests(unittest.TestCase):
    """Six real-template classes exercised through the real execution chain."""

    # -- shared helpers -----------------------------------------------------

    def _expected(self, name: str) -> dict:
        return _load(FIXTURES / name / "expected" / "expected.json")

    def _prepare(self, name: str) -> tuple:
        class_dir = FIXTURES / name
        template = class_dir / "template.docx"
        expected = self._expected(name)

        self.assertEqual(sha256_file(template), expected["template_sha256"],
                         "%s: committed template bytes drifted from expectations" % name)

        spec_a = build_document_spec_from_path(str(template))
        spec_b = build_document_spec_from_path(str(template))
        for spec in (spec_a, spec_b):
            report = validate_document_spec(spec)
            self.assertTrue(report["passed"], "%s: %s" % (name, report["errors"][:3]))

        self.assertEqual(spec_a["template"]["compatibility"], expected["compatibility"])
        self.assertEqual(spec_a["template"]["capabilities"], expected["capabilities"])

        slots_a = _slot_records(spec_a)
        slots_b = _slot_records(spec_b)
        self.assertEqual(slots_a, slots_b, "%s: slot identity is not stable across analyses" % name)
        self.assertEqual(slots_a, expected["slots"], "%s: slot set drifted from expectations" % name)

        regions = _region_records(spec_a)
        expected_regions = sorted(
            [
                {"kind": item["kind"], "location_id": item["location_id"], "severity": item["severity"]}
                for item in expected["protected_regions"]
            ],
            key=lambda item: (item["kind"], item["location_id"], item["severity"]),
        )
        self.assertEqual(regions, expected_regions, "%s: protected regions drifted" % name)

        unsupported = _unsupported_records(spec_a)
        self.assertEqual(unsupported, expected["unsupported_features"],
                         "%s: unsupported_features drifted" % name)

        for region in spec_a["protected_regions"]:
            if region.get("severity") != "blocking":
                continue
            for slot in spec_a["slots"]:
                if slot.get("protection_status") != "FILLABLE":
                    continue
                location = slot["location_id"]
                forbidden = location == region["location_id"] or location.startswith(
                    region["location_id"] + "."
                )
                self.assertFalse(
                    forbidden,
                    "%s: fillable slot %s sits inside blocking region %s" % (
                        name, location, region["location_id"]
                    ),
                )
        return class_dir, expected, spec_a

    def _execute(self, name: str, class_dir: Path, expected: dict, spec: dict,
                 plan: dict, content: dict, directory: Path, qa_runner=None) -> tuple:
        template = class_dir / "template.docx"
        ensure_gate(str(template), "GENERATE")
        output = directory / "out.docx"
        before = sha256_file(template)
        self.assertEqual(before, expected["template_sha256"], "%s: template changed before run" % name)

        result = execute_fill_plan(
            str(template), spec, plan, str(output),
            content_plan=content, qa_runner=qa_runner, allow_unverified=True,
        )

        after = sha256_file(template)
        self.assertEqual(after, before, "%s: template bytes changed during the run" % name)
        self.assertEqual(_leftovers(directory), [], "%s: staged artifact was left behind" % name)

        committed = bool(result.get("transaction", {}).get("committed"))
        if not committed:
            self.assertFalse(output.exists(), "%s: failed run published an artifact" % name)
            self.assertEqual(result.get("artifacts") or [], [], "%s: failed run published artifacts" % name)
        return result, output

    def _assert_status(self, name: str, scenario: dict, result: dict) -> None:
        status = result.get("status")
        self.assertIn(status, scenario["allowed_status"],
                      "%s/%s: status %r not in %r (%r)" % (
                          name, scenario["name"], status, scenario["allowed_status"],
                          result.get("errors", [])[:3],
                      ))
        committed = bool(result.get("transaction", {}).get("committed"))
        self.assertEqual(committed, bool(scenario["committed"]),
                         "%s/%s: commit flag mismatch" % (name, scenario["name"]))
        if not scenario["committed"]:
            self.assertNotEqual(
                result.get("data", {}).get("qa_status"), "PASSED",
                "%s/%s: a non-committed run must not claim a QA pass" % (name, scenario["name"]),
            )

    def _assert_texts(self, name: str, scenario: dict, document) -> None:
        texts = _text_map(document)
        for item in scenario.get("expect_text", []):
            self.assertEqual(texts.get(item["location_id"]), item["text"],
                             "%s/%s: text at %s" % (name, scenario["name"], item["location_id"]))
        for item in scenario.get("expect_unchanged_text", []):
            self.assertEqual(texts.get(item["location_id"]), item["text"],
                             "%s/%s: fixed text at %s changed" % (
                                 name, scenario["name"], item["location_id"]))

    def _assert_qa_disclosed(self, name: str, result: dict) -> None:
        qa_status = result.get("data", {}).get("qa_status")
        if qa_status == "UNVERIFIED":
            self.assertTrue(result["data"]["missing_checks"],
                            "%s: UNVERIFIED must disclose missing checks" % name)

    # -- class 01 -----------------------------------------------------------

    def test_class_01_basic_report(self) -> None:
        name = "class_01_basic_report"
        class_dir, expected, spec = self._prepare(name)
        content = _load(class_dir / "content_plan.json")
        plan = _load(class_dir / "fill_plan.json")
        self.assertTrue(validate_fill_plan(plan, spec, content)["passed"])

        scenario = expected["scenarios"][0]
        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(name, class_dir, expected, spec, plan, content, Path(temporary))
            self._assert_status(name, scenario, result)
            self.assertIn(result["data"]["qa_status"], ("PASSED", "UNVERIFIED"))
            self._assert_qa_disclosed(name, result)
            records = result["data"]["ledger"]["records"]
            self.assertTrue(all(record["result"]["status"] == "SUCCESS" for record in records))
            self._assert_texts(name, scenario, docx.Document(str(output)))

    def test_class_01_qa_failure_rolls_back(self) -> None:
        name = "class_01_basic_report"
        class_dir, expected, spec = self._prepare(name)
        content = _load(class_dir / "content_plan.json")
        plan = _load(class_dir / "fill_plan.json")
        scenario = expected["scenarios"][1]
        self.assertEqual(scenario["build"], "qa_failure")

        policy = resolve_required_checks("GENERATE", "STANDARD")

        def failing_runner(staged_path: str) -> dict:
            checks = [
                check_record(check_id, "PASSED", "fixture_qa_stub", artifact_path=staged_path,
                             detail="stub evidence for the fixture matrix")
                for check_id in policy["required"]
                if check_id != "FORMAT"
            ]
            checks.append(
                check_record("FORMAT", "FAILED", "fixture_qa_stub", artifact_path=staged_path,
                             detail="forced FORMAT failure for the fixture matrix")
            )
            return build_qa_report(
                task_id=plan["task_id"],
                task_mode="GENERATE",
                gate_mode="STANDARD",
                checks=checks,
                issues=[{
                    "code": "FORMAT_CHECK_FAILED",
                    "severity": "high",
                    "location": "FORMAT",
                    "detail": "forced QA failure for the fixture matrix",
                    "blocking": True,
                    "check_id": "FORMAT",
                }],
            )

        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(
                name, class_dir, expected, spec, plan, content, Path(temporary),
                qa_runner=failing_runner,
            )
            self.assertEqual(result["status"], "FAILED", result.get("errors", [])[:3])
            self.assertFalse(result["transaction"]["committed"])
            self.assertEqual(result["data"]["qa_status"], "FAILED")
            self.assertFalse(output.exists())
            self.assertTrue(result["errors"])

    # -- class 02 -----------------------------------------------------------

    def test_class_02_complex_table(self) -> None:
        name = "class_02_complex_table"
        class_dir, expected, spec = self._prepare(name)
        content = _load(class_dir / "content_plan.json")
        plan = _load(class_dir / "fill_plan.json")
        self.assertTrue(validate_fill_plan(plan, spec, content)["passed"])

        scenario = expected["scenarios"][0]
        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(name, class_dir, expected, spec, plan, content, Path(temporary))
            self._assert_status(name, scenario, result)
            self._assert_qa_disclosed(name, result)
            document = docx.Document(str(output))
            self._assert_texts(name, scenario, document)

            table = document.tables[0]
            structure = expected["table_structure"]
            self.assertGreaterEqual(len(table._tbl.xpath(".//w:gridSpan")),
                                    structure["min_grid_span"], "gridSpan merge disappeared")
            self.assertGreaterEqual(len(table._tbl.xpath(".//w:vMerge")),
                                    structure["min_v_merge"], "vMerge disappeared")
            self.assertGreaterEqual(len(table._tbl.xpath(".//w:tblHeader")),
                                    structure["min_tbl_header"], "repeated header row disappeared")
            self.assertTrue(result["data"]["region_warnings"],
                            "repeated-header warning region was not reported")

    # -- class 03 -----------------------------------------------------------

    def test_class_03_header_footer(self) -> None:
        name = "class_03_header_footer"
        class_dir, expected, spec = self._prepare(name)
        content = _load(class_dir / "content_plan.json")
        plan = _load(class_dir / "fill_plan.json")
        self.assertTrue(validate_fill_plan(plan, spec, content)["passed"])

        scenario = expected["scenarios"][0]
        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(name, class_dir, expected, spec, plan, content, Path(temporary))
            self._assert_status(name, scenario, result)
            self._assert_qa_disclosed(name, result)
            document = docx.Document(str(output))
            self._assert_texts(name, scenario, document)

            fixed_header = next(
                region for region in spec["protected_regions"]
                if region["location_id"] == "sec[0].first_page_header.p[1]"
            )
            self.assertEqual(fixed_header["kind"], "header")
            self.assertEqual(fixed_header["severity"], "blocking")
            self.assertIn("first_page_header", fixed_header["evidence"])
            slot_location = "sec[0].first_page_header.p[0]"
            fillable = [slot for slot in spec["slots"] if slot["location_id"] == slot_location]
            self.assertEqual(len(fillable), 1)
            self.assertEqual(fillable[0]["protection_status"], "FILLABLE")
            self.assertNotIn(fillable[0]["location_id"], {
                region["location_id"] for region in spec["protected_regions"]
            })

            header_footer = expected["header_footer"]
            section = document.sections[0]
            self.assertEqual([p.text for p in section.first_page_header.paragraphs],
                             header_footer["first_page_header"])
            self.assertEqual([p.text for p in section.even_page_footer.paragraphs],
                             header_footer["even_page_footer"])
            self.assertEqual(
                bool(section.different_first_page_header_footer),
                header_footer["different_first_page_header_footer"],
            )
            self.assertEqual(
                bool(document.settings.odd_and_even_pages_header_footer),
                header_footer["odd_and_even_pages_header_footer"],
            )

    # -- class 04 -----------------------------------------------------------

    def test_class_04_images(self) -> None:
        name = "class_04_images"
        class_dir, expected, spec = self._prepare(name)
        content = _load(class_dir / "content_plan.json")
        plan = copy.deepcopy(_load(class_dir / "fill_plan.json"))
        image_path = class_dir / "replacement.png"
        for operation in plan["operations"]:
            if operation["type"] == "replace_image":
                operation["value"] = str(image_path)
        self.assertTrue(validate_fill_plan(plan, spec, content)["passed"])

        scenario = expected["scenarios"][0]
        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(name, class_dir, expected, spec, plan, content, Path(temporary))
            self._assert_status(name, scenario, result)
            self._assert_qa_disclosed(name, result)
            document = docx.Document(str(output))
            self._assert_texts(name, scenario, document)

            image = expected["image"]
            media = [
                part for part in document.part.package.iter_parts()
                if "/media/" in str(part.partname)
            ]
            self.assertEqual(len(media), 1, "image part count changed")
            self.assertEqual(hashlib.sha256(media[0].blob).hexdigest(), image["replacement_sha256"],
                             "image bytes were not replaced")
            extents = document.element.body.xpath(".//wp:extent")
            self.assertTrue(extents, "replaced image lost its display extent")
            self.assertEqual(int(extents[0].get("cx")), image["extent_cx"])
            self.assertEqual(int(extents[0].get("cy")), image["extent_cy"])

    # -- class 05 -----------------------------------------------------------

    def test_class_05_nested_structure(self) -> None:
        name = "class_05_nested_structure"
        class_dir, expected, spec = self._prepare(name)
        content = _load(class_dir / "content_plan.json")
        primary, alternate = expected["scenarios"][0], expected["scenarios"][1]
        self.assertEqual(primary["name"], "primary_builder_plan")
        self.assertIs(spec["template"]["capabilities"]["nested_table"], True,
                      "the producer must advertise nested-table capability")
        self.assertTrue(expected["known_production_gaps"])

        builder_plan = _load(class_dir / "fill_plan.json")
        self.assertTrue(validate_fill_plan(builder_plan, spec, content)["passed"])
        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(
                name, class_dir, expected, spec, builder_plan, content, Path(temporary)
            )
            self._assert_status(name, primary, result)
            self._assert_qa_disclosed(name, result)
            self._assert_texts(name, primary, docx.Document(str(output)))

        paragraph_plan = _load(class_dir / "fill_plan_paragraph_level.json")
        self.assertTrue(validate_fill_plan(paragraph_plan, spec, content)["passed"])
        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(
                name, class_dir, expected, spec, paragraph_plan, content, Path(temporary)
            )
            self._assert_status(name, alternate, result)
            self._assert_qa_disclosed(name, result)
            document = docx.Document(str(output))
            self._assert_texts(name, alternate, document)

            nested = expected["nested"]
            outer = document.tables[0]
            self.assertEqual(outer.cell(1, 0).text, nested["outer_cell_text"])
            inner_tables = outer.cell(1, 1).tables
            self.assertEqual(len(inner_tables), 1, "nested table was destroyed")
            self.assertEqual(len(inner_tables[0].rows), 1)
            self.assertEqual(len(inner_tables[0].columns), 2)

    # -- class 06 -----------------------------------------------------------

    def test_class_06_complex_document(self) -> None:
        name = "class_06_complex_document"
        class_dir, expected, spec = self._prepare(name)
        content = _load(class_dir / "content_plan.json")
        plan = _load(class_dir / "fill_plan.json")
        self.assertTrue(validate_fill_plan(plan, spec, content)["passed"])

        codes = {item["code"] for item in spec["unsupported_features"]}
        self.assertIn("SDT_EDIT_UNSUPPORTED", codes)
        self.assertIn("FIELD_UPDATE_UNSUPPORTED", codes)

        scenario = expected["scenarios"][0]
        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(name, class_dir, expected, spec, plan, content, Path(temporary))
            self._assert_status(name, scenario, result)
            self._assert_qa_disclosed(name, result)
            document = docx.Document(str(output))
            self._assert_texts(name, scenario, document)

            controls = expected["controls"]
            body = document.element.body
            self.assertEqual(len(body.xpath(".//w:sdt")), controls["sdt_count"])
            self.assertEqual(len(body.xpath(".//w:fldSimple")), controls["field_count"])
            self.assertEqual([text.text for text in body.xpath(".//w:sdt//w:t")],
                             controls["sdt_texts"])
            self.assertEqual([text.text for text in body.xpath(".//w:fldSimple//w:t")],
                             controls["field_texts"])

        # Refusal: a plan that targets the protected SDT slot must be blocked before
        # any mutation, and must never degrade into a PASSED/committed run.
        scenario = expected["scenarios"][1]
        self.assertEqual(scenario["build"], "protected_target")
        protected_slot = next(
            slot for slot in spec["slots"]
            if slot["protection_status"] == "PROTECTED" and "受控字段" in slot["matched_text"]
        )
        refusal_content = build_content_plan(
            spec,
            plan_id="CP_FIXTURE_06_REFUSAL",
            sections=[{
                "section_id": "SEC_REFUSAL",
                "purpose": "受控字段",
                "target_slots": [protected_slot["slot_id"]],
            }],
            facts=[],
            required_slots=[protected_slot["slot_id"]],
        )
        refusal_plan = build_fill_plan(
            spec, refusal_content, task_id="TASK_FIXTURE_06_REFUSAL",
            mode="STANDARD", values_by_slot={protected_slot["slot_id"]: "篡改值"},
        )
        validation = validate_fill_plan(refusal_plan, spec, refusal_content)
        self.assertFalse(validation["passed"])
        validation_codes = [error["code"] for error in validation["errors"]]
        for expected_code in scenario["expect_validation_errors"]:
            self.assertIn(expected_code, validation_codes)

        with tempfile.TemporaryDirectory() as temporary:
            result, output = self._execute(
                name, class_dir, expected, spec, refusal_plan, refusal_content, Path(temporary)
            )
            self.assertEqual(result["status"], "BLOCKED", result.get("errors", [])[:3])
            self.assertNotIn(result["status"], ("SUCCESS", "UNVERIFIED"))
            self.assertIsNone(result["data"]["qa_status"])
            self.assertFalse(output.exists())
            self.assertTrue(any(
                error.get("code") == "PROTECTED_SLOT_VIOLATION"
                for error in result["errors"]
            ))


if __name__ == "__main__":
    unittest.main()
