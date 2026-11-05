# -*- coding: utf-8 -*-
"""DocumentSpec 4.0 producer tests (W1-A).

Builds real .docx fixtures with python-docx and asserts schema conformance, Contract 01
slot identity, protected/fill semantics and that no capacity is fabricated.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Cm, RGBColor
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from template_intelligence import (  # noqa: E402
    build_document_spec_from_path,
    make_slot_id,
    make_slot_key,
)

SCHEMA_PATH = ROOT / "schemas" / "document_spec-4.0.schema.json"
ANALYZE_SCRIPT = ROOT / "scripts" / "analyze_template.py"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _validator():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
        return Draft202012Validator(json.load(handle))


def _schema_errors(payload):
    return sorted(error.message for error in _validator().iter_errors(payload))


def _make_template(directory: Path, duplicate_tokens: bool = False) -> Path:
    path = directory / "template.docx"
    doc = docx.Document()
    doc.add_paragraph("{{项目名称}}")
    if duplicate_tokens:
        doc.add_paragraph("{{项目名称}} 与 {{项目名称}}")
    split = doc.add_paragraph()
    split.add_run("{{项")
    split.add_run("目名称}}")
    doc.add_paragraph("项目负责人：____")

    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "【合计金额】"
    table.cell(1, 1).text = ""

    image_path = directory / "pixel.png"
    Image.new("RGB", (8, 8), (200, 30, 30)).save(image_path)
    doc.add_picture(str(image_path), width=Cm(2))

    header = doc.sections[0].header
    header.is_linked_to_previous = False
    header.paragraphs[0].text = "内部资料"

    doc.save(str(path))
    return path


def _make_control_template(directory: Path) -> Path:
    path = directory / "control.docx"
    doc = docx.Document()
    paragraph = doc.add_paragraph()
    sdt = (
        f"<w:sdt {nsdecls('w')}><w:sdtPr/><w:sdtContent>"
        "<w:r><w:t>项目名称</w:t></w:r></w:sdtContent></w:sdt>"
    )
    paragraph._p.append(parse_xml(sdt))
    doc.add_paragraph("{{项目名称}}")
    doc.save(str(path))
    return path


class _SpecCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls._tmp.name)
        cls.path = _make_template(cls.directory)
        cls.spec = build_document_spec_from_path(str(cls.path))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def slot(self, location):
        return next(slot for slot in self.spec["slots"] if slot["location_id"] == location)


class SchemaTests(_SpecCase):
    def test_spec_passes_document_spec_4_schema(self) -> None:
        self.assertEqual(_schema_errors(self.spec), [])

    def test_required_arrays_are_present_even_when_empty(self) -> None:
        for key in (
            "slots", "protected_regions", "capacity_profiles",
            "layout_constraints", "unsupported_features", "warnings", "errors",
        ):
            self.assertIn(key, self.spec)
            self.assertIsInstance(self.spec[key], list)


class SlotIdentityTests(_SpecCase):
    def test_slot_ids_equal_contract_reference_formula(self) -> None:
        sha = self.spec["template"]["template_sha256"]
        for slot in self.spec["slots"]:
            location = slot["location_id"]
            normalized = slot["matched_text"].strip()
            occurrence = slot["occurrence"]
            canonical = f"v1|{sha}|{location}|{normalized}|{occurrence}"
            expected = "S_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
            expected_key = hashlib.sha256(
                f"v1|{location}|{normalized}|{occurrence}".encode("utf-8")
            ).hexdigest()[:16]
            self.assertEqual(slot["slot_id"], expected)
            self.assertEqual(slot["slot_key"], expected_key)

    def test_published_contract_vector(self) -> None:
        self.assertEqual(
            make_slot_id("0" * 64, "body.p[0]", "{{项目名称}}", 1), "S_d6df35f1e6cd"
        )
        self.assertEqual(
            make_slot_key("body.p[0]", "{{项目名称}}", 1), "57c748583854c867"
        )
        self.assertEqual(
            make_slot_id("0" * 64, "body.tbl[1].r[2].c[1].p[0]", "【合计金额】", 1),
            "S_42824f695c11",
        )

    def test_slot_ids_are_stable_across_two_builds(self) -> None:
        second = build_document_spec_from_path(str(self.path))
        self.assertEqual(
            [(s["slot_id"], s["slot_key"], s["location_id"]) for s in self.spec["slots"]],
            [(s["slot_id"], s["slot_key"], s["location_id"]) for s in second["slots"]],
        )

    def test_occurrence_disambiguates_duplicate_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_template(Path(tmp), duplicate_tokens=True)
            spec = build_document_spec_from_path(str(path))
        repeated = [
            slot for slot in spec["slots"] if slot["location_id"] == "body.p[1]"
        ]
        self.assertEqual([slot["occurrence"] for slot in repeated], [1, 2])
        self.assertEqual(len({slot["slot_id"] for slot in repeated}), 2)

    def test_token_split_across_runs_is_found(self) -> None:
        slot = self.slot("body.p[1]")
        self.assertEqual(slot["candidate_type"], "explicit_token")
        self.assertEqual(slot["matched_text"], "{{项目名称}}")
        self.assertEqual(slot["span"], {"start": 0, "end": 8})


class StructureTests(_SpecCase):
    def test_table_cell_token_is_a_slot_inside_structure(self) -> None:
        locations = {p["location_id"] for p in self.spec["structure"]["paragraphs"]}
        slot = self.slot("body.tbl[0].r[1].c[0].p[0]")
        self.assertEqual(slot["matched_text"], "【合计金额】")
        self.assertEqual(slot["scope"], "table")
        self.assertIn(slot["location_id"], locations)

    def test_every_slot_location_exists_in_structure(self) -> None:
        paragraph_locations = {p["location_id"] for p in self.spec["structure"]["paragraphs"]}
        table_locations = {t["table_id"] for t in self.spec["structure"]["tables"]}
        for slot in self.spec["slots"]:
            self.assertIn(slot["location_id"], paragraph_locations | table_locations)

    def test_table_and_image_inventory(self) -> None:
        table = next(t for t in self.spec["structure"]["tables"] if t["table_id"] == "body.tbl[0]")
        self.assertEqual((table["rows"], table["cols"]), (2, 2))
        self.assertEqual(table["headers"], ["项目", "金额"])
        self.assertIsInstance(table["cell_type_counts"], dict)

        images = self.spec["structure"]["images"]
        self.assertTrue(any(image["object_type"] == "inline_blip" for image in images))
        self.assertTrue(all(image["location_id"].startswith("body") for image in images))

    def test_document_sections_use_twips(self) -> None:
        section = self.spec["document"]["sections"][0]
        self.assertEqual(section["section_index"], 0)
        self.assertIsInstance(section["margins"], dict)


class ProtectedAndFactTests(_SpecCase):
    def test_header_is_a_protected_region(self) -> None:
        kinds = {region["kind"] for region in self.spec["protected_regions"]}
        self.assertIn("header", kinds)
        location = next(
            region["location_id"] for region in self.spec["protected_regions"]
            if region["kind"] == "header"
        )
        self.assertTrue(location.startswith("sec[0].header."))

    def test_internal_fact_slot_requires_user_confirmation(self) -> None:
        slot = self.slot("body.p[2]")
        self.assertEqual(slot["candidate_type"], "internal_fact")
        self.assertEqual(slot["confirmation_tier"], "MUST_ASK_USER")
        self.assertEqual(slot["matched_text"], "项目负责人")
        self.assertEqual(slot["protection_status"], "CONDITIONAL")

    def test_control_or_field_slot_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_control_template(Path(tmp))
            spec = build_document_spec_from_path(str(path))
        self.assertEqual(_schema_errors(spec), [])
        control = next(
            slot for slot in spec["slots"] if slot["candidate_type"] == "control_or_field"
        )
        self.assertEqual(control["protection_status"], "PROTECTED")
        self.assertEqual(control["confirmation_tier"], "PROTECTED_DO_NOT_TOUCH")
        self.assertIn("sdt", {region["kind"] for region in spec["protected_regions"]})


class ClueAndLayoutTests(unittest.TestCase):
    def test_red_run_is_reported_as_a_red_run_clue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "red.docx"
            doc = docx.Document()
            paragraph = doc.add_paragraph()
            run = paragraph.add_run("待填写内容")
            run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
            doc.save(str(path))
            spec = build_document_spec_from_path(str(path))
        self.assertEqual(_schema_errors(spec), [])
        slot = next(
            item for item in spec["slots"] if item["candidate_type"] == "red_run_clue"
        )
        self.assertEqual(slot["matched_text"], "待填写内容")
        self.assertEqual(slot["confirmation_tier"], "DEFAULT_FILL_WITH_NOTICE")

    def test_repeated_header_row_is_protected_and_constrained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "repeat.docx"
            doc = docx.Document()
            table = doc.add_table(rows=2, cols=2)
            table.cell(0, 0).text = "项目"
            table.cell(1, 0).text = "金额"
            tr_pr = table.rows[0]._tr.get_or_add_trPr()
            tr_pr.append(OxmlElement("w:tblHeader"))
            tr_pr.append(OxmlElement("w:cantSplit"))
            doc.save(str(path))
            spec = build_document_spec_from_path(str(path))
        self.assertEqual(_schema_errors(spec), [])
        repeated = [
            region for region in spec["protected_regions"]
            if region["kind"] == "repeated_header"
        ]
        self.assertEqual([region["location_id"] for region in repeated], ["body.tbl[0]"])
        kinds = {constraint["kind"] for constraint in spec["layout_constraints"]}
        self.assertEqual(kinds, {"repeated_header", "cant_split"})


class CapacityTests(_SpecCase):
    def test_no_hard_capacity_is_fabricated(self) -> None:
        for slot in self.spec["slots"]:
            capacity = slot.get("capacity")
            if capacity is None:
                continue
            self.assertIsNone(capacity.get("hard_limit"))
            self.assertIn(capacity["confidence"], ("low", "medium"))
            self.assertTrue(capacity["method"])

    def test_capacity_profiles_never_claim_high_confidence(self) -> None:
        self.assertTrue(self.spec["capacity_profiles"])
        for profile in self.spec["capacity_profiles"]:
            self.assertIn(profile["confidence"], ("low", "medium"))
            self.assertGreaterEqual(profile["available_width_twips"], 0)


class FingerprintTests(_SpecCase):
    def test_four_hashes_are_canonical_and_stable(self) -> None:
        fingerprint = self.spec["fingerprint_ref"]
        self.assertEqual(fingerprint["fingerprint_id"], "FP_001")
        for key in ("structural_hash", "style_hash", "protected_hash", "layout_hash"):
            value = fingerprint[key]
            self.assertRegex(value, HEX64)
            self.assertNotEqual(set(value), {"0"})
        second = build_document_spec_from_path(str(self.path))
        self.assertEqual(fingerprint, second["fingerprint_ref"])

    def test_fingerprint_is_not_a_zip_hash(self) -> None:
        raw = hashlib.sha256(self.path.read_bytes()).hexdigest()
        fingerprint = self.spec["fingerprint_ref"]
        for key in ("structural_hash", "style_hash", "protected_hash", "layout_hash"):
            self.assertNotEqual(fingerprint[key], raw)

    def test_template_id_derives_from_sha256(self) -> None:
        template = self.spec["template"]
        self.assertRegex(template["template_sha256"], HEX64)
        self.assertEqual(template["template_id"], "T_" + template["template_sha256"][:12])


class CliTests(_SpecCase):
    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, str(ANALYZE_SCRIPT), "--input", str(self.path), *extra],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_default_cli_output_keeps_legacy_keys(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            set(payload),
            {
                "file_path", "compatibility", "paragraphs_count", "candidate_hits_count",
                "candidate_hits", "table_profiles", "image_profiles",
            },
        )

    def test_spec_version_4_cli_output_is_document_spec(self) -> None:
        result = self._run("--spec-version", "4")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(_schema_errors(payload), [])
        self.assertEqual(payload["schema_version"], "4.0")

    def test_spec_version_4_writes_requested_output_file(self) -> None:
        target = self.directory / "spec_v4.json"
        result = self._run("--spec-version", "4", "--output", str(target))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(_schema_errors(payload), [])


class UnreadableInputTests(unittest.TestCase):
    def test_corrupt_file_yields_blocking_error_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.docx"
            path.write_bytes(b"not a zip")
            spec = build_document_spec_from_path(str(path))
        self.assertEqual(_schema_errors(spec), [])
        self.assertTrue(spec["errors"])
        self.assertEqual(spec["errors"][0]["code"], "DOCUMENT_UNREADABLE")
        self.assertEqual(spec["slots"], [])


if __name__ == "__main__":
    unittest.main()
