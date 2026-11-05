# -*- coding: utf-8 -*-
"""W2 defect regressions found by the fixture matrix (Agent 03 / Document Engine).

Each test reproduces one production defect and proves the fix through the real
planner/executor/QA chain:

1. a slot in a physical column after a horizontal merge resolves to that cell;
2. a slot inside a nested table produces a FillPlan that targets the nested
   table, not the outer cell that contains it;
3. a ``replace_image`` slot whose text token is still present loses that token
   so QA FORMAT does not report ``TEMPLATE_TEXT_RESIDUAL``;
4. an authorized ``fit_image`` extent change only moves ``layout_hash`` and no
   longer reports ``UNAUTHORIZED_TEMPLATE_CHANGE``, while an unauthorized
   paragraph/structure change still fails FIDELITY.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from docx.shared import Emu
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_intelligence import build_content_plan, build_fill_plan, validate_fill_plan  # noqa: E402
from document_engine import execute_fill_plan  # noqa: E402
from engine.ooxml_utils import LogicalParagraphView  # noqa: E402
from qa.pipeline import run_full_qa  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402
from template_intelligence.fingerprint import compute_four_hashes  # noqa: E402
from template_intelligence.spec_validator import validate_document_spec  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PX_EMU = 9525  # one pixel at 96 DPI


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_slot(spec: dict, matched_text: str) -> dict:
    matches = [
        slot for slot in spec.get("slots", [])
        if slot.get("matched_text") == matched_text
        and slot.get("protection_status") == "FILLABLE"
    ]
    if not matches:
        raise AssertionError(
            "slot not produced for %r: %r" % (
                matched_text, [slot.get("matched_text") for slot in spec.get("slots", [])]
            )
        )
    return matches[0]


def _single_slot_plans(spec: dict, slot: dict, *, task_id: str,
                       values_by_slot=None, images_by_slot=None) -> tuple:
    content = build_content_plan(
        spec,
        plan_id="CP_" + task_id,
        sections=[{
            "section_id": "SEC_001",
            "purpose": "W2 defect regression",
            "target_slots": [slot["slot_id"]],
        }],
        facts=[],
        required_slots=[slot["slot_id"]],
    )
    plan = build_fill_plan(
        spec,
        content,
        task_id=task_id,
        mode="STANDARD",
        values_by_slot=values_by_slot or {},
        images_by_slot=images_by_slot or {},
    )
    return content, plan


def _make_merged_row_template(directory: Path) -> Path:
    """Three grid columns, row 0 merges columns 0-1; the token sits in column 2."""
    path = directory / "merged_row.docx"
    document = docx.Document()
    document.add_paragraph("横向合并单元格模板")
    table = document.add_table(rows=1, cols=3)
    table.cell(0, 0).text = "固定值"
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 2).text = "{{尾列}}"
    document.save(str(path))
    return path


def _make_image_document(directory: Path, name: str, width_px: int, height_px: int) -> Path:
    source = directory / "source_box.png"
    if not source.exists():
        Image.new("RGB", (420, 300), (180, 40, 40)).save(str(source))
    path = directory / name
    document = docx.Document()
    document.add_paragraph("图片指纹模板")
    document.add_picture(
        str(source),
        width=Emu(int(width_px * _PX_EMU)),
        height=Emu(int(height_px * _PX_EMU)),
    )
    document.save(str(path))
    return path


def _make_image_token_template(directory: Path) -> tuple:
    """A paragraph carrying both an image token and a 420x300 picture."""
    template = directory / "image_token.docx"
    source = directory / "token_source.png"
    Image.new("RGB", (420, 300), (180, 120, 40)).save(str(source))
    document = docx.Document()
    document.add_paragraph("图片说明")
    paragraph = document.add_paragraph()
    paragraph.add_run("{{图1}}")
    paragraph.add_run().add_picture(str(source))

    replacement = directory / "token_replacement.png"
    Image.new("RGB", (300, 300), (40, 40, 180)).save(str(replacement))
    document.save(str(template))
    return template, replacement


class MergedCellColumnTests(unittest.TestCase):
    """Defect 1: physical column indexes after a horizontal merge."""

    def test_slot_in_column_after_horizontal_merge_is_filled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            template = _make_merged_row_template(directory)
            before = _sha256(template)

            spec = build_document_spec_from_path(str(template))
            self.assertTrue(validate_document_spec(spec)["passed"], spec["errors"][:3])
            slot = _find_slot(spec, "{{尾列}}")
            self.assertEqual(slot["location_id"], "body.tbl[0].r[0].c[2].p[0]")

            content, plan = _single_slot_plans(
                spec, slot, task_id="TASK_W2_MERGE",
                values_by_slot={slot["slot_id"]: "尾列值"},
            )
            self.assertTrue(validate_fill_plan(plan, spec, content)["passed"])
            target = plan["operations"][0]["target"]
            self.assertEqual(target["table_id"], "body.tbl[0]")
            self.assertEqual(target["row"], 0)
            self.assertEqual(target["col"], 2)

            output = directory / "merged_out.docx"
            result = execute_fill_plan(
                str(template), spec, plan, str(output),
                content_plan=content, allow_unverified=True,
            )
            self.assertIn(result["status"], ("SUCCESS", "UNVERIFIED"), result["errors"])
            self.assertTrue(result["transaction"]["committed"])
            self.assertEqual(_sha256(template), before, "template bytes must stay unchanged")

            written = docx.Document(str(output))
            self.assertEqual(written.tables[0].cell(0, 0).text, "固定值")
            self.assertEqual(written.tables[0].cell(0, 2).text, "尾列值")
            self.assertEqual(len(written.tables[0]._tbl.xpath(".//w:gridSpan")), 1,
                             "the template's horizontal merge must survive the fill")


class NestedTableTargetTests(unittest.TestCase):
    """Defect 2: a nested-table slot must target the nested table."""

    def test_generated_plan_fills_nested_cell_not_outer_cell(self) -> None:
        class_dir = FIXTURES / "class_05_nested_structure"
        template = class_dir / "template.docx"
        content = json.loads((class_dir / "content_plan.json").read_text(encoding="utf-8"))

        spec = build_document_spec_from_path(str(template))
        self.assertTrue(validate_document_spec(spec)["passed"], spec["errors"][:3])
        slots = [
            slot for slot in spec["slots"]
            if slot.get("matched_text") in ("{{子项名称}}", "{{子项金额}}")
        ]
        self.assertEqual(len(slots), 2)
        for slot in slots:
            self.assertIn(".tbl[0].r[", slot["location_id"])

        plan = build_fill_plan(spec, content, task_id="TASK_W2_NESTED", mode="STANDARD")
        self.assertTrue(validate_fill_plan(plan, spec, content)["passed"])

        nested_id = "body.tbl[0].r[1].c[1].tbl[0]"
        for operation, expected_value in zip(plan["operations"], ("设备采购", "5000")):
            self.assertEqual(operation["type"], "fill_cell")
            self.assertEqual(operation["target"]["table_id"], nested_id)
            self.assertIn("tbl[0]", operation["target"]["location_id"])
            self.assertEqual(operation["value"], expected_value)

        self.assertEqual(
            [(operation["target"]["row"], operation["target"]["col"]) for operation in plan["operations"]],
            [(0, 0), (0, 1)],
        )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested_out.docx"
            result = execute_fill_plan(
                str(template), spec, plan, str(output),
                content_plan=content, allow_unverified=True,
            )
            self.assertIn(result["status"], ("SUCCESS", "UNVERIFIED"), result["errors"])
            self.assertTrue(result["transaction"]["committed"])

            written = docx.Document(str(output))
            outer = written.tables[0]
            self.assertEqual(outer.cell(1, 0).text, "明细", "outer cell text must not change")
            self.assertEqual(len(outer.cell(1, 1).tables), 1, "nested table must survive")
            inner = outer.cell(1, 1).tables[0]
            self.assertEqual(inner.cell(0, 0).text, "设备采购")
            self.assertEqual(inner.cell(0, 1).text, "5000")
            self.assertNotIn("{{子项名称}}", inner.cell(0, 0).text)
            self.assertNotIn("{{子项金额}}", inner.cell(0, 1).text)


class ReplaceImageResidualTests(unittest.TestCase):
    """Defect 3: replace_image must not leave the slot's placeholder token."""

    def test_replace_image_removes_placeholder_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            template, replacement = _make_image_token_template(directory)
            before = _sha256(template)

            spec = build_document_spec_from_path(str(template))
            self.assertTrue(validate_document_spec(spec)["passed"], spec["errors"][:3])
            slot = _find_slot(spec, "{{图1}}")
            self.assertEqual(slot["location_id"], "body.p[1]")

            content, plan = _single_slot_plans(
                spec, slot, task_id="TASK_W2_IMG",
                images_by_slot={slot["slot_id"]: str(replacement)},
            )
            self.assertTrue(validate_fill_plan(plan, spec, content)["passed"])
            self.assertEqual([operation["type"] for operation in plan["operations"]],
                             ["replace_image"])

            output = directory / "image_out.docx"
            result = execute_fill_plan(
                str(template), spec, plan, str(output),
                content_plan=content, allow_unverified=True,
            )
            self.assertIn(result["status"], ("SUCCESS", "UNVERIFIED"), result["errors"])
            self.assertTrue(result["transaction"]["committed"])
            self.assertEqual(_sha256(template), before, "template bytes must stay unchanged")

            error_codes = [error.get("code") for error in result["errors"]]
            self.assertNotIn("TEMPLATE_TEXT_RESIDUAL", error_codes)
            self.assertNotIn("UNAUTHORIZED_TEMPLATE_CHANGE", error_codes)

            written = docx.Document(str(output))
            paragraph = written.paragraphs[1]
            logical = LogicalParagraphView(paragraph._p).logical_text
            self.assertNotIn("{{图1}}", logical, "the image token survived the replacement")

            media = [
                part for part in written.part.package.iter_parts()
                if "/media/" in str(part.partname)
            ]
            self.assertEqual(len(media), 1)
            self.assertEqual(hashlib.sha256(media[0].blob).hexdigest(), _sha256(replacement))


class AuthorizedExtentFingerprintTests(unittest.TestCase):
    """Defect 4: authorized image resizing belongs to layout_hash only."""

    def _fidelity_view(self, staged: Path, template: Path) -> tuple:
        report = run_full_qa(
            str(staged),
            template_path=str(template),
            task_id="TASK_W2_EXTENT",
            task_mode="GENERATE",
            gate_mode="STANDARD",
            fill_plan={"operations": [{"type": "replace_image"}]},
        )
        check = next(item for item in report["checks"] if item["check_id"] == "FIDELITY")
        codes = [
            issue["code"] for issue in report["issues"]
            if issue.get("check_id") == "FIDELITY"
        ]
        return check, codes

    def test_extent_change_keeps_structural_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            template = _make_image_document(directory, "extent_420.docx", 420, 300)
            resized = _make_image_document(directory, "extent_300.docx", 300, 300)

            template_hashes = compute_four_hashes(docx.Document(str(template)))
            resized_hashes = compute_four_hashes(docx.Document(str(resized)))

            self.assertEqual(template_hashes["structural_hash"], resized_hashes["structural_hash"],
                             "wp:extent must not enter structural_hash")
            self.assertNotEqual(template_hashes["layout_hash"], resized_hashes["layout_hash"],
                                "the extent change must still be visible in layout_hash")

            check, codes = self._fidelity_view(resized, template)
            self.assertNotEqual(check["status"], "FAILED",
                                "an authorized replace_image extent change failed FIDELITY")
            self.assertNotIn("UNAUTHORIZED_TEMPLATE_CHANGE", codes)
            self.assertIn("LAYOUT_IMAGE_FRAME_CHANGE",
                          [warning["code"] for warning in run_full_qa(
                              str(resized),
                              template_path=str(template),
                              task_id="TASK_W2_EXTENT",
                              task_mode="GENERATE",
                              gate_mode="STANDARD",
                              fill_plan={"operations": [{"type": "replace_image"}]},
                          )["warnings"]])

    def test_unauthorized_structure_change_still_fails_fidelity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            template = _make_image_document(directory, "extent_base.docx", 420, 300)
            changed = directory / "structure_changed.docx"
            document = docx.Document(str(template))
            document.add_paragraph("未授权新增段落")
            document.save(str(changed))

            check, codes = self._fidelity_view(changed, template)
            self.assertEqual(check["status"], "FAILED")
            self.assertIn("UNAUTHORIZED_TEMPLATE_CHANGE", codes)
            self.assertIn("fidelity.structural_hash",
                          [issue["location"] for issue in run_full_qa(
                              str(changed),
                              template_path=str(template),
                              task_id="TASK_W2_EXTENT",
                              task_mode="GENERATE",
                              gate_mode="STANDARD",
                              fill_plan={"operations": [{"type": "replace_image"}]},
                          )["issues"] if issue.get("check_id") == "FIDELITY"])


if __name__ == "__main__":
    unittest.main()
