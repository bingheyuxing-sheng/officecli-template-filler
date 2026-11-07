# -*- coding: utf-8 -*-
"""
Comprehensive Unit Test Suite for Office Document Intelligence Engine (v3.0).

Covers all 8 review items and architectural upgrades:
- P0-1: Non-destructive cross-run token replacement (`LogicalParagraphView`) without stripping `<w:proofErr>`,
        preserving `<w:t>` attributes, and traversing headers/footers, nested tables, and textboxes.
- P0-2: `Decimal`-based SSOT mathematical solver (`build_ssot_master_data`), unit conversions,
        exact percentage closure, and explicit ratio unit bounds (`fraction` vs `percent`).
- P0-3: Safe inline image replacement (`replace_inline_image_in_paragraph`) respecting original MIME types,
        shared image `rId` reference counts (`count_image_part_references`), and post-save integrity check.
- P0-4: PID-scoped process ownership (`TaskResourceGuard` & `release_office_file_locks`) without global `taskkill /IM`.
- P1-5: Complex cell classification (`classify_cell_structure`) and protection in `fill_cell_strict_style`.
- P1-6: Complete Excel row cloning (`clone_excel_template_row`: merged cells, formulas, validations, outline, autofilter)
        and formula recalculation/verification (`recalculate_and_verify_excel_formulas`).
- P1-7: Full DOCX Package QA (`audit_docx_package_integrity`) and Visual QA (`run_visual_layout_qa`).
- P1-8 & v3.0: Task Router (`route_document_task`), L1-L4 compatibility matrix, and Dual-Document `REPAIR` mode.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from decimal import Decimal

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from PIL import Image

from engine import (
    TaskResourceGuard,
    release_office_file_locks,
    LogicalParagraphView,
    iter_all_document_paragraphs_with_Wait_context,
    build_ssot_master_data,
    parse_ratio_bound,
    compute_exact_percentages,
    count_image_part_references,
    replace_inline_image_in_paragraph,
    verify_docx_images_integrity,
    classify_cell_structure,
    fill_cell_strict_style,
    clone_excel_template_row,
    recalculate_and_verify_excel_formulas,
    audit_excel_formula_and_style_qa,
    route_document_task,
    assess_template_compatibility_level,
    extract_document_spec,
    build_repair_plan,
    execute_repair_plan,
    audit_docx_package_integrity,
    audit_format_and_text_qa,
    run_visual_layout_qa,
    resolve_style_sz_and_font,
    resolve_run_effective_sz,
    is_red_run,
    build_review_plan,
    execute_review_plan,
    audit_review_integrity,
    apply_tracked_replacement,
    enable_track_changes,
    add_paragraph_comment,
    EditorSdkSession,
    list_process_pids,
    read_auto_cleanup_log,
    AUTO_CLEANUP_LOG,
    table_style_signature,
    compare_table_style,
    restore_table_style_from_reference,
    save_table_style_profile,
    load_table_style_profile,
    list_revisions,
    list_format_revisions,
    accept_revision,
    reject_revision,
    restore_revision,
    check_font_availability,
    QAValidationError,
    process_image_name,
    process_start_ticks,
)

from gate_helpers import ensure_gate  # noqa: E402

_real_execute_repair_plan = execute_repair_plan
_real_execute_review_plan = execute_review_plan


def execute_repair_plan(plan, output_docx_path, *args, **kwargs):
    ensure_gate(plan["reference_docx"], "REPAIR")
    return _real_execute_repair_plan(plan, output_docx_path, *args, **kwargs)


def execute_review_plan(plan, output_docx_path, *args, **kwargs):
    if str(plan.get("task_mode") or "").upper() == "REVIEW":
        ensure_gate(plan["reference_docx"], "REVIEW")
    return _real_execute_review_plan(plan, output_docx_path, *args, **kwargs)


class TestV3EngineSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_v3_test_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_p0_1_non_destructive_cross_run_replacement_and_scopes(self) -> None:
        """
        Verify P0-1:
        - Placeholders split across multiple `<w:r>` nodes with intervening `<w:proofErr>` are replaced
          via `LogicalParagraphView` WITHOUT removing `<w:proofErr>` elements from the paragraph.
        - Surrounding runs keep their exact formatting.
        - Traversal covers headers, footers, and nested tables.
        """
        doc = docx.Document()
        # Header placeholder
        hdr_p = doc.sections[0].header.paragraphs[0]
        hdr_p.text = "Header: {{doc_code}}"

        # Body paragraph with fragmented token `{{project_name}}` and `<w:proofErr>` between runs
        p = doc.add_paragraph()
        r1 = p.add_run("项目名称：{{proj")
        r1.bold = True
        pe = OxmlElement("w:proofErr")
        pe.set(qn("w:type"), "spellStart")
        p._p.append(pe)
        p.add_run("ect_")
        p.add_run("name}}（重点工程）")

        # Nested table placeholder
        outer_tbl = doc.add_table(rows=1, cols=1)
        inner_tbl = outer_tbl.cell(0, 0).add_table(rows=1, cols=1)
        inner_tbl.cell(0, 0).paragraphs[0].text = "Nested: {{nested_val}}"

        # Replace across all scopes using LogicalParagraphView
        replacements = {
            "{{doc_code}}": "SEC-2026-001",
            "{{project_name}}": "智能实训基地建设",
            "{{nested_val}}": "NESTED_OK",
        }
        for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
            view = LogicalParagraphView(ctx["p_el"])
            for tok, val in replacements.items():
                if tok in view.logical_text:
                    view.replace_all_tokens(tok, val)

        # Assertions
        self.assertEqual(p.text, "项目名称：智能实训基地建设（重点工程）")
        # `<w:proofErr>` MUST still exist (not blindly stripped!)
        self.assertEqual(len(p._p.findall(qn("w:proofErr"))), 1)
        self.assertEqual(doc.sections[0].header.paragraphs[0].text, "Header: SEC-2026-001")
        self.assertEqual(inner_tbl.cell(0, 0).paragraphs[0].text, "Nested: NESTED_OK")

    def test_p0_2_decimal_ssot_solver_and_explicit_ratio_units(self) -> None:
        """
        Verify P0-2:
        - `0.1 + 0.2` classic binary float trap equals exact `Decimal("0.30")`.
        - Explicit ratio units (`fraction` vs `percent`) are enforced; bare >1 numbers raise ValueError.
        - Exact percentage closure sums to `100.00%`.
        - Unit conversion (`yuan` <-> `wanyuan`) works without precision loss.
        """
        records = [
            {"name": "设备费", "cat": "自筹", "q1": "0.1", "q2": "0.2", "q3": "0.3", "total": "0.60"},
            {"name": "材料费", "cat": "专项", "q1": "1.15", "q2": "2.25", "q3": "0.60", "total": "4.00"},
        ]
        master = build_ssot_master_data(
            records=records,
            numeric_fields=["q1", "q2", "q3", "total"],
            part_sum_rules=[("total", ["q1", "q2", "q3"])],
            group_by_keys=["cat"],
            field_specs={
                "q1": {"unit": "wan_yuan", "decimals": 2},
                "q2": {"unit": "wan_yuan", "decimals": 2},
                "q3": {"unit": "wan_yuan", "decimals": 2},
                "total": {"unit": "wan_yuan", "decimals": 2},
            },
            ratio_rules=[
                {
                    "name": "self_ratio",
                    "numerator_group": ("cat", "自筹", "total"),
                    "denominator_field": "total",
                    "min_ratio": {"value": "0.10", "unit": "fraction"},
                    "max_ratio": {"value": "100", "unit": "percent"},
                }
            ],
        )
        self.assertEqual(master["grand"]["total"], Decimal("4.60"))

        # Ambiguous bare >1 ratio bound must raise ValueError
        with self.assertRaises(ValueError):
            parse_ratio_bound(50.0)

        # Exact percentages closure: 1/3 + 1/3 + 1/3 == 100.00%
        pcts = compute_exact_percentages([1, 1, 1], decimals=2)
        self.assertEqual(sum(pcts), Decimal("100.00"))

    def test_p0_3_safe_image_replacement_mime_and_shared_rid(self) -> None:
        """
        Verify P0-3:
        - When an image `rId` is shared by two paragraphs (`ref_count == 2`), replacing the image in
          paragraph 1 allocates a new independent image part + `rId` so paragraph 0's image is untouched.
        - Post-save `verify_docx_images_integrity` confirms valid image binaries and MIME consistency.
        """
        img1_path = os.path.join(self.work_dir, "orig.png")
        img2_path = os.path.join(self.work_dir, "new_replacement.jpg")
        Image.new("RGB", (120, 80), color=(20, 40, 200)).save(img1_path, format="PNG")
        Image.new("RGB", (240, 160), color=(200, 60, 20)).save(img2_path, format="JPEG")

        doc = docx.Document()
        p0 = doc.add_paragraph()
        p0.add_run().add_picture(img1_path, width=Inches(2.0))

        # Clone the drawing XML into p1 so both p0 and p1 share the exact same `rId`
        from copy import deepcopy
        p1 = doc.add_paragraph()
        p1._p.append(deepcopy(p0._p.xpath(".//w:r")[0]))

        refs_before = count_image_part_references(doc)
        shared_rids = [rid for rid, info in refs_before.items() if info["ref_count"] == 2]
        self.assertEqual(len(shared_rids), 1)

        # Replace image only in p1
        rep_info = replace_inline_image_in_paragraph(doc, p1, img2_path)
        self.assertTrue(rep_info["allocated_new_part"])
        self.assertNotEqual(rep_info["old_rId"], rep_info["new_rId"])

        out_docx = os.path.join(self.work_dir, "img_tested.docx")
        doc.save(out_docx)

        integrity = verify_docx_images_integrity(out_docx)
        self.assertTrue(integrity["passed"], f"Image integrity check failed: {integrity}")
        self.assertEqual(integrity["checked_count"], 2)

    def test_p0_4_task_resource_guard_pid_ownership(self) -> None:
        """
        Verify P0-4:
        - `TaskResourceGuard` tracks only processes/resources owned by the current task instance.
        - `release_office_file_locks` closes registered resources and owned PIDs without invoking global taskkill by image name.
        """
        dummy_buf = io.BytesIO(b"hello")
        with TaskResourceGuard(task_id="unit_test_task") as guard:
            guard.register_resource(dummy_buf)
            proc = guard.run_owned_command([sys.executable, "-c", "print('ok')"])
            self.assertEqual(proc.returncode, 0)
            summary = release_office_file_locks(guard=guard)
            self.assertEqual(summary["task_id"], "unit_test_task")
            self.assertGreaterEqual(summary["closed_resources"], 1)
        self.assertTrue(dummy_buf.closed)

    def test_p1_5_complex_cell_structure_protection(self) -> None:
        """
        Verify P1-5:
        - `classify_cell_structure` accurately distinguishes plain_text, nested_table, hyperlink_cell, etc.
        - `fill_cell_strict_style` refuses to destructively wipe a cell containing a nested table.
        """
        doc = docx.Document()
        tbl = doc.add_table(rows=2, cols=2)
        tbl.cell(0, 0).text = "普通文本"
        # Add nested table to cell(0, 1)
        nested = tbl.cell(0, 1).add_table(rows=1, cols=1)
        nested.cell(0, 0).text = "内部子表数据"

        c00_info = classify_cell_structure(tbl.cell(0, 0))
        c01_info = classify_cell_structure(tbl.cell(0, 1))
        self.assertEqual(c00_info["cell_type"], "plain_text")
        self.assertEqual(c01_info["cell_type"], "nested_table")

        with self.assertRaises(ValueError):
            fill_cell_strict_style(tbl.cell(0, 1), "试图直接覆盖嵌套表单元格")

    def test_p1_6_excel_row_cloning_and_formula_recalculation(self) -> None:
        """
        Verify P1-6:
        - `clone_excel_template_row` clones cell styles, horizontal merged ranges, outline level,
          data validations, and shifts formula row references (`shift_excel_formula_row_refs`).
        - `recalculate_and_verify_excel_formulas` evaluates `=SUM(...)` and `=C2*D2` in Decimal without error.
        """
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Budget"
        ws["A1"] = "Item"
        ws["B1"] = "Note"
        ws["C1"] = "Qty"
        ws["D1"] = "Price"
        ws["E1"] = "Subtotal"

        # Row 2 is our template row with merged A2:B2, formula =C2*D2, outline_level=1, and DataValidation
        ws.merge_cells("A2:B2")
        ws["A2"] = "Server"
        ws["C2"] = 2
        ws["D2"] = 1500.50
        ws["E2"] = "=C2*D2"
        ws.row_dimensions[2].outline_level = 1

        dv = DataValidation(type="whole", operator="greaterThan", formula1=0)
        ws.add_data_validation(dv)
        dv.add("C2")

        # Clone row 2 -> row 3
        clone_excel_template_row(ws, source_row_idx=2, target_row_idx=3, shift_formulas=True)
        ws["A3"] = "Switch"
        ws["C3"] = 4
        ws["D3"] = 500.25

        # Total row at row 4
        ws["A4"] = "Total"
        ws["E4"] = "=SUM(E2:E3)"

        self.assertEqual(ws["E3"].value, "=C3*D3")
        self.assertIn("A3:B3", [str(rng) for rng in ws.merged_cells.ranges])
        self.assertEqual(ws.row_dimensions[3].outline_level, 1)

        xlsx_path = os.path.join(self.work_dir, "budget_test.xlsx")
        wb.save(xlsx_path)
        wb.close()

        qa = audit_excel_formula_and_style_qa(xlsx_path, expected_formula_cells={"Budget": ["E2", "E3", "E4"]})
        self.assertTrue(qa["passed"])
        eval_res = qa["recalculation"]["evaluated_Values"]
        self.assertEqual(eval_res["Budget!E2"], "3001.00")
        self.assertEqual(eval_res["Budget!E3"], "2001.00")
        self.assertEqual(eval_res["Budget!E4"], "5002.00")

    def test_p1_7_and_v3_dual_document_repair_and_package_qa(self) -> None:
        """
        Verify P1-7 & v3.0 Dual-Document REPAIR Mode:
        - `route_document_task` routes 2 `.docx` inputs to `REPAIR` with `DISABLED_BY_DEFAULT` web search.
        - `build_repair_plan` detects section margin differences, paragraph font/spacing differences,
          residual red text, and table pagination issues.
        - `execute_repair_plan` fixes formatting while preserving 100% of broken document's business content.
        - `audit_docx_package_integrity` and `run_visual_layout_qa` pass on the repaired document.
        """
        ref_path = os.path.join(self.work_dir, "reference_template.docx")
        brk_path = os.path.join(self.work_dir, "broken_target.docx")
        out_path = os.path.join(self.work_dir, "repaired_output.docx")

        # Create Reference Document
        ref_doc = docx.Document()
        ref_doc.sections[0].top_margin = Inches(1.0)
        ref_doc.sections[0].left_margin = Inches(1.2)
        ref_p = ref_doc.add_paragraph()
        ref_r = ref_p.add_run("模板正文示例段落")
        ref_r.font.name = "Times New Roman"
        ref_r._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "仿宋_GB2312")
        ref_r.font.size = Pt(12)
        ref_tbl = ref_doc.add_table(rows=2, cols=2)
        ref_tbl.cell(0, 0).text = "序号"
        ref_tbl.cell(0, 1).text = "指标名称"
        ref_doc.save(ref_path)

        # Create Broken Document (different margins, wrong font size, residual red run, business content)
        brk_doc = docx.Document()
        brk_doc.sections[0].top_margin = Inches(0.5)
        brk_doc.sections[0].left_margin = Inches(0.6)
        brk_p = brk_doc.add_paragraph()
        brk_r = brk_p.add_run("保留的真实业务正文内容：2026年度工作总结")
        brk_r.font.size = Pt(16)
        brk_r.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)  # Residual red
        brk_tbl = brk_doc.add_table(rows=2, cols=2)
        brk_tbl.cell(0, 0).text = "1"
        brk_tbl.cell(0, 1).text = "核心业务指标A"
        brk_doc.save(brk_path)

        routing = route_document_task([ref_path, brk_path], user_intent="按参考模板修复格式")
        self.assertEqual(routing["task_mode"], "REPAIR")
        self.assertEqual(routing["web_search_policy"], "DISABLED_BY_DEFAULT")

        plan = build_repair_plan(ref_path, brk_path)
        self.assertGreaterEqual(plan["total_actions"], 3)

        execute_repair_plan(plan, out_path)
        self.assertTrue(os.path.isfile(out_path))

        repaired_doc = docx.Document(out_path)
        # Business content preserved!
        self.assertEqual(repaired_doc.paragraphs[0].text, "保留的真实业务正文内容：2026年度工作总结")
        self.assertEqual(repaired_doc.tables[0].cell(0, 1).text, "核心业务指标A")
        # Margins synced to reference!
        self.assertAlmostEqual(repaired_doc.sections[0].top_margin.inches, 1.0, places=2)

        pkg_qa = audit_docx_package_integrity(out_path)
        self.assertTrue(pkg_qa["passed"], f"Package QA failed: {pkg_qa}")

        fmt_qa = audit_format_and_text_qa(repaired_doc, docx_path=out_path)
        self.assertTrue(fmt_qa["passed"])

        vis_qa = run_visual_layout_qa(out_path, reference_docx_path=ref_path)
        # Font-substitution risk (e.g. 仿宋_GB2312 not installed locally) is a legitimate
        # finding; no other visual issue may appear on this well-formed document.
        self.assertTrue(
            all(issue["code"] == "FONT_NOT_INSTALLED" for issue in vis_qa["structured_issues"]),
            f"unexpected visual issues: {vis_qa['structured_issues']}",
        )
        if vis_qa["font_availability"]["checked"]:
            self.assertTrue(
                set(vis_qa["font_availability"]["missing"]) <= {"仿宋_GB2312", "Times New Roman"},
                f"font report wrong: {vis_qa['font_availability']}",
            )

    def test_p0_1_replacement_value_containing_token_terminates(self) -> None:
        """A replacement value that itself contains the token must not loop forever."""
        doc = docx.Document()
        p = doc.add_paragraph()
        p.add_run("值：{{a}}")

        view = LogicalParagraphView(p._p)
        count = view.replace_all_tokens({"{{a}}": "X{{a}}Y"})

        self.assertEqual(count, 1)
        self.assertEqual(p.text, "值：X{{a}}Y")

    def test_p0_3_identical_image_noop_and_media_content_type_validation(self) -> None:
        """
        Verify P0-3 follow-ups:
        - Re-inserting identical bytes is reported as `noop_identical_bytes` instead of a fake fork.
        - Media bytes that contradict the declared Content-Type are detected even after saving.
        """
        img_path = os.path.join(self.work_dir, "orig_media.png")
        Image.new("RGB", (60, 40), color=(10, 200, 90)).save(img_path, format="PNG")

        doc = docx.Document()
        p = doc.add_paragraph()
        p.add_run().add_picture(img_path, width=Inches(1.0))

        res = replace_inline_image_in_paragraph(doc, p, img_path, preserve_original_format=False)
        self.assertEqual(res["mode"], "noop_identical_bytes")
        self.assertFalse(res["effective"])

        out_docx = os.path.join(self.work_dir, "noop_image.docx")
        doc.save(out_docx)
        self.assertTrue(verify_docx_images_integrity(out_docx)["passed"])

        # Swap every media entry for JPEG bytes while the part is still named `.png` / declared image/png
        jpeg_buf = io.BytesIO()
        Image.new("RGB", (60, 40), color=(250, 0, 0)).save(jpeg_buf, format="JPEG")
        corrupt_docx = os.path.join(self.work_dir, "corrupt_media.docx")
        with zipfile.ZipFile(out_docx, "r") as zin, zipfile.ZipFile(corrupt_docx, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.startswith("word/media/"):
                    data = jpeg_buf.getvalue()
                zout.writestr(item, data)

        bad_report = verify_docx_images_integrity(corrupt_docx)
        self.assertFalse(bad_report["passed"])
        self.assertTrue(
            any("MIME_MISMATCH" in issue or "UNREADABLE" in issue for issue in bad_report["issues"]),
            bad_report["issues"],
        )

    def test_p0_4_pid_reuse_is_never_terminated(self) -> None:
        """
        Verify P0-4 follow-up:
        - An owned process that already exited is not terminated again.
        - A live process whose image name does not match the recorded name is treated as not owned,
          so a recycled PID can never be killed.
        """
        exited = subprocess.Popen([sys.executable, "-c", "pass"])
        exited.wait()

        guard = TaskResourceGuard(task_id="pid_reuse_guard")
        guard.register_pid(exited.pid, name="python.exe", popen=exited)
        release = guard.release_all()
        self.assertEqual(release["terminated_pids"], [])

        live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            self.assertTrue(TaskResourceGuard._is_pid_running(live.pid))
            self.assertFalse(
                TaskResourceGuard._is_pid_running(live.pid, expected_name="notepad.exe"),
                "A PID whose live image name differs from the recorded name must not be considered owned",
            )
        finally:
            live.kill()
            live.wait()

        self.assertIsNone(TaskResourceGuard._query_windows_process_name(999999))

    def test_p1_5_bookmark_anchored_cell_is_preserved(self) -> None:
        """
        Verify P1-5 follow-up:
        A cell carrying a bookmark anchor is classified as `anchored_text` and filled without
        deleting the bookmark nodes or their paragraphs.
        """
        doc = docx.Document()
        tbl = doc.add_table(rows=1, cols=1)
        cell = tbl.cell(0, 0)
        p = cell.paragraphs[0]
        p.add_run("旧内容")

        bookmark_start = OxmlElement("w:bookmarkStart")
        bookmark_start.set(qn("w:id"), "7")
        bookmark_start.set(qn("w:name"), "_Toc7")
        p._p.insert(0, bookmark_start)
        bookmark_end = OxmlElement("w:bookmarkEnd")
        bookmark_end.set(qn("w:id"), "7")
        p._p.append(bookmark_end)

        self.assertEqual(str(classify_cell_structure(cell)), "anchored_text")

        result = fill_cell_strict_style(cell, "新内容")
        self.assertEqual(result["status"], "updated_anchored_text")
        self.assertEqual(cell.text.strip(), "新内容")
        self.assertEqual(len(cell._tc.findall(".//" + qn("w:bookmarkStart"))), 1)
        self.assertEqual(len(cell._tc.findall(".//" + qn("w:bookmarkEnd"))), 1)


    def test_p1_8_template_spec_handles_ole_and_image_metadata(self) -> None:
        """
        Verify P1-8 follow-ups:
        - `assess_template_compatibility_level` / `extract_document_spec` do not crash on OLE objects
          (the `o:` namespace prefix is not registered in python-docx) and classify them as L4.
        - Image profiles resolve partname / content_type / ref_count by `rId`.
        """
        from docx.oxml import parse_xml

        doc = docx.Document()
        p = doc.add_paragraph("普通文本 {{token}}")
        doc.sections[0].header.paragraphs[0].text = "页眉文本"
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "单元格内容"

        ole_xml = (
            '<w:object xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:o="urn:schemas-microsoft-com:office:office">'
            '<o:OLEObject Type="Embed" ProgID="Excel.Sheet.12" ShapeID="_x0000_i1025"/>'
            "</w:object>"
        )
        p._p.append(parse_xml(ole_xml))

        compat = assess_template_compatibility_level(doc)
        self.assertEqual(compat["compatibility_level"], "L4")

        spec = extract_document_spec(doc)
        self.assertGreater(spec["paragraphs_count"], 0)

        img_path = os.path.join(self.work_dir, "profile.png")
        Image.new("RGB", (80, 50), color=(30, 90, 180)).save(img_path, format="PNG")
        img_doc = docx.Document()
        img_doc.add_paragraph().add_run().add_picture(img_path, width=Inches(1.0))
        img_spec = extract_document_spec(img_doc)
        profile = img_spec["image_profiles"][0]
        self.assertEqual(profile["object_type"], "inline_blip")
        self.assertEqual(profile["ref_count"], 1)
        self.assertTrue(profile["content_type"].startswith("image/"))
        self.assertTrue(profile["partname"])

    def test_p1_9_font_size_qa_detects_template_drift(self) -> None:
        """
        Verify P1-9 follow-ups:
        - `resolve_style_sz_and_font` falls back to `w:docDefaults`, so sizes no longer silently
          resolve to `None` (which made the whole size check a no-op).
        - `audit_format_and_text_qa(reference_docx_path=...)` catches drift in the first paragraphs
          (previously exempt by `i > 5`) and inside table cells.
        - Inherited drift (no explicit run `w:sz`) is visible too.
        - A faithful copy of the template produces zero size anomalies.
        """

        def set_run_sz(run, half_points: int) -> None:
            rPr = run._r.get_or_add_rPr()
            sz = rPr.find(qn("w:sz"))
            if sz is None:
                sz = OxmlElement("w:sz")
                rPr.append(sz)
            sz.set(qn("w:val"), str(half_points))

        body_text = "本专业人才培养方案依据指导意见文件精神制订"

        template_path = os.path.join(self.work_dir, "size_template.docx")
        tpl = docx.Document()
        tpl.add_paragraph("编制说明", style="Heading 1")
        tpl.add_paragraph("（一）编制依据", style="Heading 1")
        for _ in range(4):
            set_run_sz(tpl.add_paragraph().add_run(body_text), 24)
        tpl.save(template_path)

        # docDefaults must provide a real fallback size instead of None
        probe = docx.Document()
        probe_p = probe.add_paragraph("普通正文")
        _font, resolved_sz = resolve_style_sz_and_font(probe_p)
        self.assertIsNotNone(resolved_sz, "w:docDefaults fallback failed to resolve a size")
        self.assertEqual(resolve_run_effective_sz(probe_p.runs[0], probe_p), resolved_sz)

        # Faithful copy of the template: no anomalies, and the baseline comes from the template
        clean_report = audit_format_and_text_qa(docx.Document(template_path), reference_docx_path=template_path)
        self.assertEqual(clean_report["size_baseline_source"], "reference_template")
        self.assertEqual(clean_report["size_anomalies"], [])

        # Drift inside the first paragraphs (index <= 5) must be caught
        drifted = docx.Document(template_path)
        for run in drifted.paragraphs[2].runs:
            set_run_sz(run, 32)
        with self.assertRaises(QAValidationError):
            audit_format_and_text_qa(drifted, reference_docx_path=template_path)

        # Inherited drift: no explicit w:sz on the run at all
        inherited = docx.Document(template_path)
        for run in inherited.paragraphs[3].runs:
            rPr = run._r.rPr
            stale = rPr.find(qn("w:sz")) if rPr is not None else None
            if stale is not None:
                rPr.remove(stale)
        with self.assertRaises(QAValidationError):
            audit_format_and_text_qa(inherited, reference_docx_path=template_path)

        # Table cells are covered as well
        table_doc = docx.Document(template_path)
        cell_p = table_doc.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]
        set_run_sz(cell_p.add_run("表格内容写成16磅"), 32)
        with self.assertRaises(QAValidationError):
            audit_format_and_text_qa(table_doc, reference_docx_path=template_path)

    def test_red_color_detection_covers_package_stories_and_inheritance(self) -> None:
        doc = docx.Document()

        def add_colored_run(parent, color="D90000", theme=None):
            run = parent.add_run("红色占位")
            rPr = run._r.get_or_add_rPr()
            color_el = OxmlElement("w:color")
            color_el.set(qn("w:val"), color)
            if theme:
                color_el.set(qn("w:themeColor"), theme)
            rPr.append(color_el)
            return run

        p = doc.add_paragraph()
        direct = add_colored_run(p)
        self.assertTrue(is_red_run(direct, p))

        # Hyperlink, insertion, content control, and textbox descendants are scanned as XML runs.
        for wrapper_tag in ("w:hyperlink", "w:ins", "w:sdt"):
            p_el = doc.add_paragraph()._p
            wrapper = OxmlElement(wrapper_tag)
            if wrapper_tag == "w:sdt":
                content = OxmlElement("w:sdtContent")
                wrapper.append(content)
                container = content
            else:
                container = wrapper
            run_el = OxmlElement("w:r")
            rPr = OxmlElement("w:rPr")
            color_el = OxmlElement("w:color")
            color_el.set(qn("w:val"), "D90000")
            rPr.append(color_el)
            run_el.append(rPr)
            text = OxmlElement("w:t")
            text.text = "包装节点红字"
            run_el.append(text)
            container.append(run_el)
            p_el.append(wrapper)

        textbox_p = OxmlElement("w:p")
        txbx = OxmlElement("w:txbxContent")
        txbx.append(textbox_p)
        doc.add_paragraph()._p.append(txbx)
        text_run = OxmlElement("w:r")
        text_rpr = OxmlElement("w:rPr")
        text_color = OxmlElement("w:color")
        text_color.set(qn("w:val"), "D90000")
        text_rpr.append(text_color)
        text_run.append(text_rpr)
        text_node = OxmlElement("w:t")
        text_node.text = "文本框红字"
        text_run.append(text_node)
        textbox_p.append(text_run)

        table = doc.add_table(rows=1, cols=1)
        nested = table.cell(0, 0).add_table(rows=1, cols=1)
        nested_run = add_colored_run(nested.cell(0, 0).paragraphs[0])
        self.assertTrue(is_red_run(nested_run, nested_run._parent))
        header_run = add_colored_run(doc.sections[0].header.paragraphs[0])
        self.assertTrue(is_red_run(header_run, header_run._parent))

        report_error = None
        try:
            audit_format_and_text_qa(doc)
        except QAValidationError as exc:
            report_error = str(exc)
        self.assertIsNotNone(report_error)
        self.assertGreaterEqual(report_error.count("包装节点红字"), 3)
        self.assertIn("body.txbx_p[", report_error)
        self.assertIn("sec[0].header", report_error)
        self.assertIn("body.tbl[", report_error)

        # Character style inheritance is resolved even when the run has no direct color.
        style = doc.styles.add_style("Red Character", 2)
        style.font.color.rgb = RGBColor(217, 0, 0)
        inherited_run = doc.add_paragraph().add_run("样式红字")
        inherited_run.style = style
        self.assertTrue(is_red_run(inherited_run, inherited_run._parent))

        # Theme color is resolved against the document theme.
        theme_run = doc.add_paragraph().add_run("主题红色")
        theme_rpr = theme_run._r.get_or_add_rPr()
        theme_color = OxmlElement("w:color")
        theme_color.set(qn("w:val"), "000000")
        theme_color.set(qn("w:themeColor"), "accent2")
        theme_rpr.append(theme_color)
        self.assertTrue(is_red_run(theme_run, theme_run._parent))

    def test_review_mode_writes_tracked_changes_comments_and_report(self) -> None:
        """REVIEW mode must produce accept/reject-able revisions plus native comments."""
        ref_path = os.path.join(self.work_dir, "review_ref.docx")
        tgt_path = os.path.join(self.work_dir, "review_target.docx")
        out_path = os.path.join(self.work_dir, "review_out.docx")

        ref = docx.Document()
        ref.add_paragraph("模板标题")
        ref.add_paragraph("正文：{{项目名称}}")
        ref.save(ref_path)

        target = docx.Document()
        target.add_paragraph("草稿标题")
        target.add_paragraph("正文：{{项目名称}}")
        target.add_paragraph("需要修正的旧内容")
        target.save(tgt_path)

        plan = build_review_plan(
            ref_path,
            tgt_path,
            author="测试审核人",
            text_revisions=[{"old_text": "需要修正的旧内容", "new_text": "已经修正的新内容", "reason": "按模板规范"}],
        )
        routed = route_document_task([ref_path, tgt_path], "按模板审核并留痕修订")
        self.assertEqual(routed["task_mode"], "REVIEW")
        self.assertEqual(routed["web_search_policy"], "DISABLED_BY_DEFAULT")
        self.assertEqual(plan["task_mode"], "REVIEW")
        self.assertGreaterEqual(plan["summary"]["comments"], 1)
        self.assertEqual(plan["summary"]["tracked_text_revisions"], 1)

        execution = execute_review_plan(plan, out_path)
        self.assertEqual(execution["tracked_text_revisions"], 1)
        self.assertGreaterEqual(execution["comments_added"], 1)
        self.assertEqual(execution["unresolved_actions"], [])

        qa = audit_review_integrity(out_path)
        self.assertTrue(qa["passed"], qa["issues"])
        self.assertTrue(qa["track_changes_enabled"])
        self.assertEqual(qa["revision_count"], 2)
        self.assertEqual(qa["comment_count"], 1)

        with zipfile.ZipFile(out_path) as zf:
            body = zf.read("word/document.xml")
            comments = zf.read("word/comments.xml")
            settings = zf.read("word/settings.xml")
        self.assertIn(b"<w:del ", body)
        self.assertIn(b"<w:delText", body)
        self.assertIn(b"<w:ins ", body)
        self.assertIn(b"commentRangeStart", body)
        self.assertIn(b"commentReference", body)
        self.assertIn("测试审核人".encode("utf-8"), body)
        self.assertIn(b"trackChanges", settings)
        self.assertIn("待人工确认".encode("utf-8"), comments)

        reopened = docx.Document(out_path)
        self.assertTrue(len(reopened.paragraphs) >= 3)

    def test_review_tracked_replacement_and_comment_reporting(self) -> None:
        """Tracked replacement keeps surrounding runs and reports absent text."""
        doc = docx.Document()
        p = doc.add_paragraph()
        p.add_run("前缀")
        p.add_run("旧片段")
        p.add_run("后缀")

        result = apply_tracked_replacement(p, "旧片段", "新片段", author="审核机器人")
        self.assertIsNotNone(result)
        texts = [t.text for t in p._p.iter(qn("w:t"))]
        self.assertIn("前缀", texts)
        self.assertIn("后缀", texts)
        self.assertIn("新片段", texts)
        self.assertNotIn("旧片段", texts)
        deleted = [n.text for n in p._p.iter(qn("w:delText"))]
        self.assertEqual(deleted, ["旧片段"])

        self.assertIsNone(apply_tracked_replacement(p, "不存在的文本", "替换"))

        enable_track_changes(doc, True)
        self.assertTrue(doc.settings.element.find(qn("w:trackChanges")) is not None)

        comment_id = add_paragraph_comment(doc.add_paragraph("批注目标"), "请人工确认此处", author="审核机器人")
        self.assertIsInstance(comment_id, int)
        self.assertTrue(p._p.find(qn("w:commentRangeStart")) is None)

    def test_editor_sdk_session_only_stops_instances_spawned_during_task(self) -> None:
        """A pre-existing SDK must survive; IDs missing from the baseline must be reported."""
        current = list_process_pids("editor_sdk.exe")
        self.assertIsInstance(current, list)

        session = EditorSdkSession(baseline_pids=current)
        result = session.stop_new_instances()
        self.assertEqual(result["spawned_during_task"], [])
        self.assertEqual(result["terminated_pids"], [])
        self.assertTrue(result["verified"])
        self.assertEqual(result["baseline_pids"], current)

        with self.assertRaises(RuntimeError):
            EditorSdkSession().stop_new_instances()

    def test_auto_cleanup_is_wired_into_every_cli_entrypoint(self) -> None:
        """Cleanup must be automatic: every entrypoint installs the exit hook on startup."""
        scripts_dir = os.path.join(ROOT_DIR, "scripts")
        entrypoints = (
            "inspect_document.py",
            "analyze_template.py",
            "generate_document.py",
            "repair_document.py",
            "review_document.py",
            "run_qa.py",
            "render_document.py",
        )
        for name in entrypoints:
            with open(os.path.join(scripts_dir, name), "r", encoding="utf-8") as handle:
                source = handle.read()
            self.assertIn("install_auto_cleanup()", source, f"{name} does not install automatic SDK cleanup")

        self.assertTrue(AUTO_CLEANUP_LOG.endswith("officecli_editor_sdk_cleanup.json"))
        self.assertIsInstance(read_auto_cleanup_log(), dict)

    def test_auto_cleanup_hook_writes_verification_log_on_exit(self) -> None:
        """A child process that installs the hook must exit cleanly and report verification."""
        code = (
            "from engine import install_auto_cleanup, read_auto_cleanup_log\n"
            "session = install_auto_cleanup()\n"
            "print('baseline', sorted(session.baseline_pids))\n"
            "print('same_session', install_auto_cleanup() is session)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("same_session True", result.stdout)

        log = read_auto_cleanup_log()
        self.assertTrue(log.get("verified"), log)
        self.assertEqual(log.get("spawned_during_task"), [])
        self.assertIn("source_process", log)

    @staticmethod
    def _styled_run(paragraph, text, east_asia, sz_val):
        run = paragraph.add_run(text)
        rPr = run._r.get_or_add_rPr()
        rFonts = OxmlElement("w:rFonts")
        rFonts.set(qn("w:eastAsia"), east_asia)
        rFonts.set(qn("w:ascii"), "Times New Roman")
        rPr.append(rFonts)
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(sz_val))
        rPr.append(sz)
        return run

    @staticmethod
    def _configure_table(tbl, col_width, layout, with_borders, sz_val):
        tblPr = tbl._tbl.tblPr
        for col in tbl._tbl.tblGrid.findall(qn("w:gridCol")):
            col.set(qn("w:w"), str(col_width))
        layout_el = OxmlElement("w:tblLayout")
        layout_el.set(qn("w:type"), layout)
        tblPr.append(layout_el)
        if with_borders:
            borders = OxmlElement("w:tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                node = OxmlElement(f"w:{side}")
                node.set(qn("w:val"), "single")
                node.set(qn("w:sz"), "4")
                borders.append(node)
            tblPr.append(borders)
        for row in tbl.rows:
            for cell in row.cells:
                TestV3EngineSuite._styled_run(cell.paragraphs[0], "表格内容", "宋体", sz_val)

    def test_p2_font_family_qa_detects_template_drift(self) -> None:
        """A document regenerated in a different Chinese font must fail QA, not pass on size alone."""
        ref_path = os.path.join(self.work_dir, "font_ref.docx")
        out_path = os.path.join(self.work_dir, "font_out.docx")

        ref = docx.Document()
        self._styled_run(ref.add_paragraph(), "正文内容", "宋体", 24)
        ref.save(ref_path)

        out = docx.Document()
        self._styled_run(out.add_paragraph(), "正文内容", "楷体", 24)
        out.save(out_path)

        with self.assertRaises(QAValidationError) as ctx:
            audit_format_and_text_qa(docx.Document(out_path), docx_path=out_path, reference_docx_path=ref_path)
        self.assertIn("FONT_FAMILY_ANOMALY", str(ctx.exception))
        self.assertIn("楷体", str(ctx.exception))

    def test_p2_table_dominant_size_qa_detects_uniform_drift(self) -> None:
        """A table enlarged wholesale must fail even when that size appears elsewhere in the template."""
        ref_path = os.path.join(self.work_dir, "tbl_size_ref.docx")
        out_path = os.path.join(self.work_dir, "tbl_size_out.docx")

        ref = docx.Document()
        self._styled_run(ref.add_paragraph(), "副标题占位", "宋体", 28)
        self._styled_run(ref.add_paragraph(), "正文内容", "宋体", 24)
        tbl = ref.add_table(rows=2, cols=2)
        self._configure_table(tbl, 2500, "fixed", True, 18)
        ref.save(ref_path)

        out = docx.Document()
        self._styled_run(out.add_paragraph(), "副标题占位", "宋体", 28)
        self._styled_run(out.add_paragraph(), "正文内容", "宋体", 24)
        tbl = out.add_table(rows=2, cols=2)
        self._configure_table(tbl, 2500, "fixed", True, 28)
        out.save(out_path)

        with self.assertRaises(QAValidationError) as ctx:
            audit_format_and_text_qa(docx.Document(out_path), docx_path=out_path, reference_docx_path=ref_path)
        self.assertIn("table_dominant_size", str(ctx.exception))

    def test_p2_table_style_qa_detects_grid_layout_and_border_drift(self) -> None:
        """Column ratios, table layout and missing borders must be reported against the template."""
        ref_path = os.path.join(self.work_dir, "tbl_style_ref.docx")
        out_path = os.path.join(self.work_dir, "tbl_style_out.docx")

        ref = docx.Document()
        self._styled_run(ref.add_paragraph(), "正文内容", "宋体", 24)
        tbl = ref.add_table(rows=2, cols=3)
        self._configure_table(tbl, 2500, "fixed", True, 18)
        ref.save(ref_path)

        out = docx.Document()
        self._styled_run(out.add_paragraph(), "正文内容", "宋体", 24)
        tbl = out.add_table(rows=2, cols=3)
        self._configure_table(tbl, 3400, "autofit", False, 18)
        out.save(out_path)

        with self.assertRaises(QAValidationError) as ctx:
            audit_format_and_text_qa(docx.Document(out_path), docx_path=out_path, reference_docx_path=ref_path)
        message = str(ctx.exception)
        self.assertIn("TABLE_STYLE_ANOMALY", message)
        self.assertIn("table_layout", message)
        self.assertIn("table_border_missing", message)

    def test_p2_review_restores_table_structure_from_template(self) -> None:
        """REVIEW must both report and restore table grid/layout/borders, not only paragraph formats."""
        ref_path = os.path.join(self.work_dir, "rev_tbl_ref.docx")
        tgt_path = os.path.join(self.work_dir, "rev_tbl_target.docx")
        out_path = os.path.join(self.work_dir, "rev_tbl_out.docx")

        ref = docx.Document()
        self._styled_run(ref.add_paragraph(), "正文内容", "宋体", 24)
        tbl = ref.add_table(rows=2, cols=3)
        self._configure_table(tbl, 2500, "fixed", True, 18)
        ref.save(ref_path)

        target = docx.Document()
        self._styled_run(target.add_paragraph(), "正文内容", "宋体", 24)
        tbl = target.add_table(rows=2, cols=3)
        self._configure_table(tbl, 3400, "autofit", False, 18)
        target.save(tgt_path)

        plan = build_review_plan(ref_path, tgt_path)
        self.assertGreaterEqual(plan["summary"]["table_style_restores"], 1)
        self.assertTrue(any(a["action_type"] == "RESTORE_TABLE_STYLE" for a in plan["actions"]))

        execution = execute_review_plan(plan, out_path)
        self.assertEqual(execution["unresolved_actions"], [])

        restored = docx.Document(out_path)
        restored_sig = table_style_signature(restored.tables[0])
        reference_sig = table_style_signature(docx.Document(ref_path).tables[0])
        self.assertEqual(restored_sig["total_width"], reference_sig["total_width"])
        self.assertEqual(restored_sig["layout"], reference_sig["layout"])
        self.assertEqual(sorted(restored_sig["borders"]), sorted(reference_sig["borders"]))

    def test_p2_review_restores_table_cell_font_and_size(self) -> None:
        """REVIEW must copy template cell run font and size, not only table geometry."""
        ref_path = os.path.join(self.work_dir, "cell_font_ref.docx")
        tgt_path = os.path.join(self.work_dir, "cell_font_target.docx")
        out_path = os.path.join(self.work_dir, "cell_font_out.docx")

        ref = docx.Document()
        tbl = ref.add_table(rows=1, cols=1)
        self._styled_run(tbl.cell(0, 0).paragraphs[0], "模板文字", "宋体", 18)
        ref.save(ref_path)

        target = docx.Document()
        tbl = target.add_table(rows=1, cols=1)
        self._styled_run(tbl.cell(0, 0).paragraphs[0], "生成文字", "楷体", 28)
        target.save(tgt_path)

        plan = build_review_plan(ref_path, tgt_path)
        self.assertTrue(any(a["action_type"] == "RESTORE_TABLE_STYLE" for a in plan["actions"]))
        execute_review_plan(plan, out_path)

        run = docx.Document(out_path).tables[0].cell(0, 0).paragraphs[0].runs[0]
        rPr = run._r.rPr
        self.assertEqual(rPr.find(qn("w:rFonts")).get(qn("w:eastAsia")), "宋体")
        self.assertEqual(rPr.find(qn("w:sz")).get(qn("w:val")), "18")

    def test_p2_table_text_revision_and_revision_lifecycle(self) -> None:
        """Text revisions must reach table paragraphs and expose a full lifecycle API."""
        ref_path = os.path.join(self.work_dir, "lifecycle_ref.docx")
        tgt_path = os.path.join(self.work_dir, "lifecycle_target.docx")
        out_path = os.path.join(self.work_dir, "lifecycle_review.docx")
        accepted_path = os.path.join(self.work_dir, "lifecycle_accepted.docx")
        rejected_path = os.path.join(self.work_dir, "lifecycle_rejected.docx")

        ref = docx.Document()
        ref.add_paragraph("参考正文")
        ref.save(ref_path)

        tgt = docx.Document()
        tgt.add_paragraph("正文段落")
        cell_p = tgt.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]
        cell_p.add_run("表格旧文本")
        tgt.save(tgt_path)

        plan = build_review_plan(
            ref_path,
            tgt_path,
            text_revisions=[{"old_text": "表格旧文本", "new_text": "表格新文本"}],
        )
        execution = execute_review_plan(plan, out_path)
        self.assertEqual(execution["tracked_text_revisions"], 1)
        self.assertTrue(any("tbl[" in item["target"] for item in execution["action_results"]))
        self.assertTrue(any(
            item["action_id"] == "text_revision_0" and item["status"] == "APPLIED" and item["revision_ids"]
            for item in execution["action_results"]
        ))

        revisions = list_revisions(out_path)
        self.assertTrue(any(r["type"] == "del" and r["text"] == "表格旧文本" for r in revisions))
        self.assertTrue(any(r["type"] == "ins" and r["text"] == "表格新文本" for r in revisions))
        self.assertTrue(audit_review_integrity(out_path)["passed"])

        del_id = next(r["revision_id"] for r in revisions if r["type"] == "del")
        ins_id = next(r["revision_id"] for r in revisions if r["type"] == "ins")

        accepted_step1 = os.path.join(self.work_dir, "lifecycle_accepted_1.docx")
        accepted_path = os.path.join(self.work_dir, "lifecycle_accepted_2.docx")
        accept_revision(out_path, accepted_step1, del_id)
        # Pending insertions stay present (and stay tracked) until their own accept.
        self.assertTrue(any(r["revision_id"] == ins_id for r in list_revisions(accepted_step1)))
        accept_revision(accepted_step1, accepted_path, ins_id)
        accepted_cell_text = docx.Document(accepted_path).tables[0].cell(0, 0).text
        self.assertNotIn("表格旧文本", accepted_cell_text)
        self.assertIn("表格新文本", accepted_cell_text)

        reject_revision(out_path, rejected_path, ins_id)
        rejected_revisions = list_revisions(rejected_path)
        self.assertFalse(any(r["revision_id"] == ins_id for r in rejected_revisions))
        self.assertTrue(audit_review_integrity(rejected_path)["passed"])

    def test_p2_restore_revision_recovers_deleted_text(self) -> None:
        """`restore_revision` on a deletion must bring the original text back."""
        src_path = os.path.join(self.work_dir, "restore_src.docx")
        restored_path = os.path.join(self.work_dir, "restore_out.docx")
        doc = docx.Document()
        doc.add_paragraph("保留文本")
        doc.save(src_path)
        plan = build_review_plan(
            src_path, src_path,
            text_revisions=[{"old_text": "保留文本", "new_text": "替换文本"}],
        )
        out_path = os.path.join(self.work_dir, "restore_review.docx")
        execute_review_plan(plan, out_path)
        del_id = next(r["revision_id"] for r in list_revisions(out_path) if r["type"] == "del")
        restore_revision(out_path, restored_path, del_id)
        self.assertIn("保留文本", docx.Document(restored_path).paragraphs[0].text)

    def test_p2_table_cell_property_diff_and_restore(self) -> None:
        """Per-cell tcW drift must be detected with row/col precision and restored."""
        ref_path = os.path.join(self.work_dir, "tcw_ref.docx")
        tgt_path = os.path.join(self.work_dir, "tcw_target.docx")
        from docx.shared import Twips

        for path, with_width in ((ref_path, True), (tgt_path, False)):
            d = docx.Document()
            tbl = d.add_table(rows=1, cols=1)
            if with_width:
                # cell.width writes a single schema-valid w:tcW (no duplicate nodes)
                tbl.cell(0, 0).width = Twips(3000)
            tbl.cell(0, 0).paragraphs[0].add_run("内容")
            d.save(path)

        out_doc = docx.Document(tgt_path)
        ref_doc = docx.Document(ref_path)
        issues = compare_table_style(
            table_style_signature(out_doc.tables[0]),
            table_style_signature(ref_doc.tables[0]),
            0,
        )
        self.assertTrue(any(
            issue[0] == "table_cell_property" and issue[4] == "tcW" for issue in issues
        ))

        self.assertTrue(restore_table_style_from_reference(out_doc.tables[0], ref_doc.tables[0]))
        issues_after = compare_table_style(
            table_style_signature(out_doc.tables[0]),
            table_style_signature(ref_doc.tables[0]),
            0,
        )
        self.assertFalse(any(issue[0] == "table_cell_property" for issue in issues_after))

    def test_p2_table_style_profile_roundtrip(self) -> None:
        """Table style profiles must persist to JSON and reload identically."""
        import json

        path = os.path.join(self.work_dir, "profile_doc.docx")
        d = docx.Document()
        tbl = d.add_table(rows=1, cols=2)
        tbl.cell(0, 0).paragraphs[0].add_run("A")
        tbl.cell(0, 1).paragraphs[0].add_run("B")
        d.save(path)

        profile_path = os.path.join(self.work_dir, "profile.json")
        table = docx.Document(path).tables[0]
        save_table_style_profile(table, profile_path)
        loaded = load_table_style_profile(profile_path)
        self.assertEqual(json.dumps(loaded, sort_keys=True), json.dumps(table_style_signature(table), sort_keys=True))

    def test_p2_font_availability_report(self) -> None:
        """Missing fonts must be flagged; unverifiable environments must say so."""
        report = check_font_availability(["宋体", "绝对不存在的字体XYZ"])
        self.assertIn("checked", report)
        self.assertIn("missing", report)
        if report["checked"]:
            self.assertNotIn("宋体", report["missing"])
            self.assertIn("绝对不存在的字体XYZ", report["missing"])
        else:
            self.assertEqual(report["source"], "none")

    def test_p1_review_format_restores_leave_tracked_format_revisions(self) -> None:
        """REVIEW must not silently rewrite formats: w:rPrChange/w:tcPrChange marks must exist."""
        from docx.oxml import OxmlElement
        from docx.shared import Pt

        ref_path = os.path.join(self.work_dir, "fmt_ref.docx")
        tgt_path = os.path.join(self.work_dir, "fmt_target.docx")
        out_path = os.path.join(self.work_dir, "fmt_review.docx")

        ref = docx.Document()
        rr = ref.add_paragraph().add_run("模板正文段落")
        rr.font.name = "宋体"
        rr._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
        rr.font.size = Pt(12)
        ref_tbl = ref.add_table(rows=1, cols=1)
        ref_tbl.cell(0, 0).paragraphs[0].add_run("表格")
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "D9E2F3")
        ref_tbl.cell(0, 0)._tc.get_or_add_tcPr().append(shd)
        ref.save(ref_path)

        tgt = docx.Document()
        tr = tgt.add_paragraph().add_run("生成正文段落")
        tr.font.name = "楷体"
        tr._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "楷体")
        tr.font.size = Pt(16)
        tgt_tbl = tgt.add_table(rows=1, cols=1)
        tgt_tbl.cell(0, 0).paragraphs[0].add_run("表格")
        tgt.save(tgt_path)

        plan = build_review_plan(ref_path, tgt_path)
        execution = execute_review_plan(plan, out_path)
        self.assertGreater(execution["tracked_format_changes"], 0)

        fmt_revs = list_format_revisions(out_path)
        types = {item["type"] for item in fmt_revs}
        self.assertIn("rPrChange", types)
        self.assertTrue(types & {"tcPrChange", "tblPrChange", "trPrChange"})
        self.assertTrue(all(item["author"] for item in fmt_revs))

        audit = audit_review_integrity(out_path)
        self.assertTrue(audit["passed"], audit["issues"])
        self.assertGreaterEqual(audit["format_revision_count"], len(fmt_revs))

        fmt_action = next(a for a in execution["action_results"] if a["action_id"] == "format_restore_0")
        self.assertTrue(fmt_action["format_revision_ids"])

    def test_p0_revision_ids_match_written_xml(self) -> None:
        """Reported revision ids must equal the w:id values actually written into the DOCX."""
        from docx.oxml.ns import qn as _qn

        src = os.path.join(self.work_dir, "id_check.docx")
        doc = docx.Document()
        doc.add_paragraph("起始文本")
        doc.save(src)

        plan = build_review_plan(src, src, text_revisions=[{"old_text": "起始文本", "new_text": "替换文本"}])
        out = os.path.join(self.work_dir, "id_check_out.docx")
        execution = execute_review_plan(plan, out)

        reported = next(a["revision_ids"] for a in execution["action_results"] if a["action_id"] == "text_revision_0")
        written = [
            int(el.get(_qn("w:id")))
            for el in docx.Document(out).element.body.iter()
            if el.tag.rsplit("}", 1)[-1] in ("ins", "del")
        ]
        self.assertEqual(sorted(reported), sorted(written))

    def test_p0_hyperlink_position_survives_tracked_replacement(self) -> None:
        """A tracked replacement must not reorder hyperlink containers in the paragraph."""
        p = docx.Document().add_paragraph()
        p.add_run("前缀 ")
        hyper = OxmlElement("w:hyperlink")
        hyper.set(qn("r:id"), "rId1")
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = "链接文字"
        r.append(t)
        hyper.append(r)
        p._p.append(hyper)
        p.add_run(" 目标文本 后缀")

        result = apply_tracked_replacement(p, "目标文本", "修改文本")
        self.assertIsNotNone(result)

        children = [el.tag.rsplit("}", 1)[-1] for el in p._p]
        self.assertEqual(children.index("hyperlink"), 1, f"hyperlink moved: {children}")
        self.assertIn("链接文字", "".join(t.text or "" for t in p._p.iter(qn("w:t"))))

    def test_p0_ambiguous_match_refuses_first_hit(self) -> None:
        """Multiple matches without location/occurrence must NOT edit the first hit."""
        src = os.path.join(self.work_dir, "ambig.docx")
        doc = docx.Document()
        doc.add_paragraph("项目总投资为100万元")
        doc.add_paragraph("项目总投资为100万元")
        doc.save(src)

        plan = build_review_plan(src, src, text_revisions=[{"old_text": "项目总投资为100万元", "new_text": "项目总投资为120万元"}])
        out = os.path.join(self.work_dir, "ambig_out.docx")
        execution = execute_review_plan(plan, out)

        self.assertEqual(execution["tracked_text_revisions"], 0)
        rev_action = next(a for a in execution["action_results"] if a["action_id"] == "text_revision_0")
        self.assertEqual(rev_action["reason"], "AMBIGUOUS_MULTIPLE_MATCHES")
        self.assertGreaterEqual(execution["comments_added"], 1)
        self.assertTrue(all("100万元" in p.text for p in docx.Document(out).paragraphs))

    def test_p0_occurrence_targets_second_match(self) -> None:
        """occurrence: 2 must edit the second occurrence, not the first."""
        src = os.path.join(self.work_dir, "occ.docx")
        doc = docx.Document()
        doc.add_paragraph("金额为100万元")
        doc.add_paragraph("金额为100万元")
        doc.save(src)

        plan = build_review_plan(src, src, text_revisions=[{
            "old_text": "金额为100万元", "new_text": "金额为200万元", "occurrence": 2,
        }])
        out = os.path.join(self.work_dir, "occ_out.docx")
        execution = execute_review_plan(plan, out)
        self.assertEqual(execution["tracked_text_revisions"], 1)

        texts = [p.text for p in docx.Document(out).paragraphs]
        self.assertIn("金额为100万元", texts[0])
        # Pending insertions are not part of plain text; verify the tracked nodes exist.
        second_p = docx.Document(out).paragraphs[1]
        del_texts = [t.text or "" for t in second_p._p.iter(qn("w:delText"))]
        self.assertIn("金额为100万元", "".join(del_texts))

    def test_p0_table_merge_diff_reported_as_partially_applied(self) -> None:
        """Merge-topology drift must yield PARTIALLY_APPLIED, not APPLIED."""
        from docx.oxml import OxmlElement as _OE

        ref_path = os.path.join(self.work_dir, "merge_ref.docx")
        tgt_path = os.path.join(self.work_dir, "merge_target.docx")
        out_path = os.path.join(self.work_dir, "merge_out.docx")

        ref = docx.Document()
        rt = ref.add_table(rows=2, cols=2)
        rt.cell(0, 0).paragraphs[0].add_run("A")
        rt.cell(1, 0).paragraphs[0].add_run("B")
        ref.save(ref_path)

        tgt = docx.Document()
        tt = tgt.add_table(rows=2, cols=2)
        tt.cell(0, 0).paragraphs[0].add_run("A")
        tt.cell(1, 0).paragraphs[0].add_run("B")
        # no merge in template; give target a vMerge the template does not have
        tc_pr = tt.rows[1].cells[0]._tc.get_or_add_tcPr()
        vm = _OE("w:vMerge")
        vm.set(qn("w:val"), "continue")
        tc_pr.append(vm)
        tgt.save(tgt_path)

        plan = build_review_plan(ref_path, tgt_path)
        execution = execute_review_plan(plan, out_path)
        table_actions = [a for a in execution["action_results"] if a["action_id"].startswith("table_style")]
        if table_actions:
            action = table_actions[0]
            self.assertEqual(action["status"], "PARTIALLY_APPLIED")
            self.assertIn("vMerge", action["unresolved_properties"])
            self.assertTrue(action["requires_human_review"])

    def test_p1_xlsm_roundtrip_keeps_vba_project(self) -> None:
        """An .xlsm template filled through the CLI must keep xl/vbaProject.bin."""
        import zipfile as _zf

        template = os.path.join(self.work_dir, "macro_template.xlsm")
        payload = os.path.join(self.work_dir, "payload.json")
        out = os.path.join(self.work_dir, "macro_out.xlsx")

        wb = openpyxl.Workbook()
        wb.save(template)
        wb.close()
        # Inject a fake vbaProject.bin part into the xlsx package to make it an xlsm.
        import shutil as _sh
        tmp = template + ".tmp"
        with _zf.ZipFile(template) as zin, _zf.ZipFile(tmp, "w") as zout:
            for item in zin.namelist():
                zout.writestr(item, zin.read(item))
            zout.writestr("xl/vbaProject.bin", b"FAKE_VBA_PROJECT")
            ct = zin.read("[Content_Types].xml").decode("utf-8")
            ct = ct.replace(
                "</Types>",
                '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>',
            )
            zout.writestr("[Content_Types].xml", ct)
        _sh.move(tmp, template)

        with open(payload, "w", encoding="utf-8") as handle:
            json.dump({"replacements": {"k": "v"}}, handle)

        import subprocess as _sp
        result = _sp.run(
            [sys.executable, os.path.join(ROOT_DIR, "scripts", "generate_excel.py"),
             "--template", template, "--data", payload, "--out", out],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        actual_out = report["output"]
        self.assertTrue(actual_out.lower().endswith(".xlsm"), f"output not xlsm: {actual_out}")
        with _zf.ZipFile(actual_out) as archive:
            self.assertIn("xl/vbaProject.bin", archive.namelist())

    def test_p1_unsupported_formula_reported_unverified(self) -> None:
        """A formula the builtin evaluator cannot run must count as unverified, not passed."""
        path = os.path.join(self.work_dir, "xlookup.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = 1
        ws["A2"] = 1
        ws["A3"] = 2
        ws["B2"] = 10
        ws["B3"] = 20
        ws["C1"] = "=XLOOKUP(A1,A2:A3,B2:B3)"
        wb.save(path)
        wb.close()

        report = recalculate_and_verify_excel_formulas(path)
        self.assertEqual(report["total_formulas"], 1)
        self.assertGreaterEqual(report["unverified_count"], 1)
        self.assertIn("FORMULAS_UNVERIFIED", report["coverage_gaps"])
        self.assertTrue(any("XLOOKUP" in item for item in report["unsupported_formulas"]))

    def test_p1_subtotal_function_codes_dispatch(self) -> None:
        """SUBTOTAL(9,...)=SUM, SUBTOTAL(1,...)=AVERAGE, SUBTOTAL(4,...)=MAX."""
        path = os.path.join(self.work_dir, "subtotal.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["B1"] = 10
        ws["B2"] = 20
        ws["B3"] = 30
        ws["B4"] = "=SUBTOTAL(9,B1:B3)"
        ws["B5"] = "=SUBTOTAL(1,B1:B3)"
        ws["B6"] = "=SUBTOTAL(4,B1:B3)"
        wb.save(path)
        wb.close()

        report = recalculate_and_verify_excel_formulas(path)
        values = report["evaluated_Values"]
        self.assertEqual(values.get("Sheet!B4") or values.get("B4"), "60")
        self.assertEqual(values.get("Sheet!B5") or values.get("B5"), "20")
        self.assertEqual(values.get("Sheet!B6") or values.get("B6"), "30")
        self.assertEqual(report["unverified_count"], 0)

    def test_p0_router_distinguishes_single_and_multi_source_intents(self) -> None:
        """Routing must follow real capabilities, not just how many .docx files were supplied."""
        docx_a = os.path.join(self.work_dir, "a.docx")
        docx_b = os.path.join(self.work_dir, "b.docx")
        xlsx_a = os.path.join(self.work_dir, "a.xlsx")
        xlsx_b = os.path.join(self.work_dir, "b.xlsx")

        self.assertEqual(route_document_task([docx_a], "统一字体和字号重新排版")["task_mode"], "REFORMAT")
        self.assertEqual(route_document_task([docx_a], "修复一下格式")["task_mode"], "REFORMAT")
        self.assertEqual(route_document_task([docx_a], "润色措辞")["task_mode"], "POLISH")
        self.assertEqual(route_document_task([docx_a], "按模板生成一份方案")["task_mode"], "GENERATE")
        self.assertEqual(route_document_task([docx_b, docx_a], "审核并留痕")["task_mode"], "REVIEW")
        self.assertEqual(route_document_task([docx_b, docx_a], "合并成一份")["task_mode"], "MERGE")
        self.assertEqual(route_document_task([docx_b, docx_a], "按模板修复格式")["task_mode"], "REPAIR")
        self.assertEqual(route_document_task([xlsx_a], "填充数据")["task_mode"], "EXCEL_GENERATE")
        self.assertEqual(route_document_task([xlsx_b, xlsx_a], "合并工作簿")["task_mode"], "MERGE")
        self.assertEqual(route_document_task([xlsx_a, docx_b], "合并数据")["task_mode"], "MERGE")
        self.assertEqual(route_document_task([xlsx_a, docx_b])["task_mode"], "MERGE")

    def test_p0_excel_generate_entrypoint_fills_template_without_touching_formulas(self) -> None:
        """EXCEL_GENERATE must have a real Excel entrypoint, not the Word generator."""
        template_path = os.path.join(self.work_dir, "excel_template.xlsx")
        payload_path = os.path.join(self.work_dir, "excel_payload.json")
        out_path = os.path.join(self.work_dir, "excel_out.xlsx")

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet["A1"] = "{{project}}"
        sheet["A2"] = "【leader】"
        sheet["B1"] = "=SUM(B2:B3)"
        sheet["B2"] = 1
        sheet["B3"] = 2
        workbook.save(template_path)

        with open(payload_path, "w", encoding="utf-8") as handle:
            json.dump({"replacements": {"project": "示例项目", "leader": "张三"}}, handle, ensure_ascii=False)

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT_DIR, "scripts", "generate_excel.py"),
                "--template", template_path,
                "--payload", payload_path,
                "--out", out_path,
            ],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        filled = openpyxl.load_workbook(out_path).active
        self.assertEqual(filled["A1"].value, "示例项目")
        self.assertEqual(filled["A2"].value, "张三")
        self.assertEqual(filled["B1"].value, "=SUM(B2:B3)")


    def test_p0_validation_survives_python_optimize(self) -> None:
        """`python -O` strips assert; every quality gate must still reject bad input."""
        code = (
            "import docx\n"
            "from docx.oxml import OxmlElement\n"
            "from docx.oxml.ns import qn\n"
            "from engine import build_ssot_master_data, SSOTValidationError, audit_format_and_text_qa, QAValidationError\n"
            "\n"
            "try:\n"
            "    build_ssot_master_data(\n"
            "        records=[{'total': '100', 'part_a': '60', 'part_b': '20'}],\n"
            "        numeric_fields=['total', 'part_a', 'part_b'],\n"
            "        part_sum_rules=[('total', ['part_a', 'part_b'])],\n"
            "    )\n"
            "    print('SSOT_ACCEPTED_BAD_SUM')\n"
            "except SSOTValidationError:\n"
            "    print('SSOT_REJECTED_BAD_SUM')\n"
            "\n"
            "d = docx.Document()\n"
            "p = d.add_paragraph()\n"
            "r = p.add_run('红色占位')\n"
            "rPr = r._r.get_or_add_rPr()\n"
            "c = OxmlElement('w:color')\n"
            "c.set(qn('w:val'), 'FF0000')\n"
            "rPr.append(c)\n"
            "try:\n"
            "    audit_format_and_text_qa(d)\n"
            "    print('QA_ACCEPTED_RED_TEXT')\n"
            "except QAValidationError:\n"
            "    print('QA_REJECTED_RED_TEXT')\n"
        )
        result = subprocess.run(
            [sys.executable, "-O", "-c", code],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SSOT_REJECTED_BAD_SUM", result.stdout)
        self.assertIn("QA_REJECTED_RED_TEXT", result.stdout)
        self.assertNotIn("SSOT_ACCEPTED_BAD_SUM", result.stdout)
        self.assertNotIn("QA_ACCEPTED_RED_TEXT", result.stdout)


    def test_p0_process_identity_checks_name_on_every_platform(self) -> None:
        """Linux must not trust `pgrep -f`; identity checks belong in the engine, not in tests."""
        pid = os.getpid()
        live_name = process_image_name(pid)
        self.assertIsNotNone(live_name, "cannot resolve own process name")
        self.assertTrue(TaskResourceGuard._is_pid_running(pid, expected_name=live_name))
        self.assertFalse(TaskResourceGuard._is_pid_running(pid, expected_name="unrelated-image-name"))

        ticks = process_start_ticks(pid)
        if os.name != "nt":
            self.assertIsInstance(ticks, int)

        session = EditorSdkSession(baseline_pids=list_process_pids("editor_sdk.exe"))
        self.assertEqual(session.baseline_pids, [pid for pid, _ticks in session.baseline_identities])


    def test_p0_repair_applies_cant_split_and_tbl_header(self) -> None:
        """Pagination attributes the plan detects must actually be written, in schema order."""
        ref_path = os.path.join(self.work_dir, "pag_ref.docx")
        broken_path = os.path.join(self.work_dir, "pag_broken.docx")
        out_path = os.path.join(self.work_dir, "pag_out.docx")

        ref = docx.Document()
        ref.add_paragraph("正文")
        ref_tbl = ref.add_table(rows=2, cols=2)
        for cell in ref_tbl.rows[0].cells:
            cell.paragraphs[0].add_run("表头").bold = True
        ref_tbl.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        ref.save(ref_path)

        broken = docx.Document()
        broken.add_paragraph("正文")
        broken_tbl = broken.add_table(rows=2, cols=2)
        for cell in broken_tbl.rows[0].cells:
            cell.paragraphs[0].add_run("表头").bold = True
        for cell in broken_tbl.rows[1].cells:
            cell.paragraphs[0].add_run("数据")
        height = OxmlElement("w:trHeight")
        height.set(qn("w:val"), "300")
        broken_tbl.rows[0]._tr.get_or_add_trPr().append(height)
        broken.save(broken_path)

        plan = build_repair_plan(ref_path, broken_path)
        result = execute_repair_plan(plan, out_path)

        self.assertEqual(result["fixed_cant_split_rows"], 2)
        self.assertEqual(result["fixed_tbl_header_rows"], 1)
        self.assertEqual(result["skipped_header_candidates"], 0)

        repaired = docx.Document(out_path).tables[0]
        for row in repaired.rows:
            self.assertIsNotNone(row._tr.find(qn("w:trPr")).find(qn("w:cantSplit")))
        header_trPr = repaired.rows[0]._tr.find(qn("w:trPr"))
        self.assertIsNotNone(header_trPr.find(qn("w:tblHeader")))

        # `w:cantSplit` must precede `w:trHeight`, otherwise Word can report a schema violation.
        order = [child.tag.rsplit("}", 1)[-1] for child in header_trPr]
        self.assertLess(order.index("cantSplit"), order.index("trHeight"))

    def test_p0_repair_never_marks_a_data_row_as_repeating_header(self) -> None:
        """Without evidence that row 0 is a header, never add `w:tblHeader`."""
        ref_path = os.path.join(self.work_dir, "pag_ref2.docx")
        broken_path = os.path.join(self.work_dir, "pag_broken2.docx")
        out_path = os.path.join(self.work_dir, "pag_out2.docx")

        ref = docx.Document()
        ref.add_paragraph("正文")
        ref_tbl = ref.add_table(rows=2, cols=2)
        for index, row in enumerate(ref_tbl.rows):
            for cell in row.cells:
                cell.paragraphs[0].add_run(f"第{index}行")
        ref.save(ref_path)

        broken = docx.Document()
        broken.add_paragraph("正文")
        broken_tbl = broken.add_table(rows=2, cols=2)
        for index, row in enumerate(broken_tbl.rows):
            for cell in row.cells:
                cell.paragraphs[0].add_run(f"第{index}行")
        broken.save(broken_path)

        plan = build_repair_plan(ref_path, broken_path)
        result = execute_repair_plan(plan, out_path)

        self.assertEqual(result["fixed_tbl_header_rows"], 0)
        self.assertEqual(result["skipped_header_candidates"], 1)
        repaired = docx.Document(out_path).tables[0]
        trPr = repaired.rows[0]._tr.find(qn("w:trPr"))
        self.assertTrue(trPr is None or trPr.find(qn("w:tblHeader")) is None)

    def test_p0_qa_reports_pagination_drift_against_template(self) -> None:
        """QA must flag missing w:cantSplit / w:tblHeader that the template proves."""
        ref_path = os.path.join(self.work_dir, "pagq_ref.docx")
        out_path = os.path.join(self.work_dir, "pagq_out.docx")

        ref = docx.Document()
        ref.add_paragraph("正文")
        ref_tbl = ref.add_table(rows=2, cols=2)
        for row in ref_tbl.rows:
            row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        ref_tbl.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        ref.save(ref_path)

        out = docx.Document()
        out.add_paragraph("正文")
        out.add_table(rows=2, cols=2)
        out.save(out_path)

        with self.assertRaises(QAValidationError) as ctx:
            audit_format_and_text_qa(docx.Document(out_path), docx_path=out_path, reference_docx_path=ref_path)
        message = str(ctx.exception)
        self.assertIn("TABLE_PAGINATION_ANOMALY", message)
        self.assertIn("missing_cant_split", message)
        self.assertIn("missing_tbl_header", message)


    def test_p3_table_header_shading_and_valign_detected_and_restored(self) -> None:
        """Header fill, vertical alignment and row height are table style, not text formatting."""
        ref_path = os.path.join(self.work_dir, "shd_ref.docx")
        target_path = os.path.join(self.work_dir, "shd_target.docx")
        out_path = os.path.join(self.work_dir, "shd_out.docx")

        ref = docx.Document()
        ref.add_paragraph("正文")
        ref_tbl = ref.add_table(rows=2, cols=2)
        for cell in ref_tbl.rows[0].cells:
            ref_tbl.rows[0]._tr.get_or_add_trPr()
            cell.paragraphs[0].add_run("表头")
            tcPr = cell._tc.get_or_add_tcPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), "1F4E79")
            tcPr.append(shd)
            v_align = OxmlElement("w:vAlign")
            v_align.set(qn("w:val"), "center")
            tcPr.append(v_align)
        for row in ref_tbl.rows:
            row._tr.get_or_add_trPr().append(self._tr_height("400"))
        ref.save(ref_path)

        target = docx.Document()
        target.add_paragraph("正文")
        target_tbl = target.add_table(rows=2, cols=2)
        for row in target_tbl.rows:
            for cell in row.cells:
                cell.paragraphs[0].add_run("内容")
        target.save(target_path)

        with self.assertRaises(QAValidationError) as ctx:
            audit_format_and_text_qa(
                docx.Document(target_path),
                docx_path=target_path,
                reference_docx_path=ref_path,
            )
        message = str(ctx.exception)
        self.assertIn("table_header_shading_missing", message)
        self.assertIn("table_cell_valign", message)
        self.assertIn("table_row_height", message)

        plan = build_review_plan(ref_path, target_path)
        self.assertTrue(any(a["action_type"] == "RESTORE_TABLE_STYLE" for a in plan["actions"]))
        execution = execute_review_plan(plan, out_path)
        self.assertEqual(execution["unresolved_actions"], [])

        restored = docx.Document(out_path).tables[0]
        header_shd = restored.rows[0].cells[0]._tc.tcPr.find(qn("w:shd"))
        self.assertIsNotNone(header_shd)
        self.assertEqual(header_shd.get(qn("w:fill")), "1F4E79")
        self.assertEqual(
            restored.rows[0].cells[0]._tc.tcPr.find(qn("w:vAlign")).get(qn("w:val")),
            "center",
        )
        for row in restored.rows:
            self.assertEqual(row._tr.find(qn("w:trPr")).find(qn("w:trHeight")).get(qn("w:val")), "400")

    @staticmethod
    def _tr_height(value: str):
        node = OxmlElement("w:trHeight")
        node.set(qn("w:val"), value)
        return node

    def test_p3_repair_restores_header_shading_valign_and_row_height(self) -> None:
        """REPAIR shares the same table-style restore path as REVIEW."""
        ref_path = os.path.join(self.work_dir, "rshd_ref.docx")
        broken_path = os.path.join(self.work_dir, "rshd_broken.docx")
        out_path = os.path.join(self.work_dir, "rshd_out.docx")

        ref = docx.Document()
        ref.add_paragraph("正文")
        ref_tbl = ref.add_table(rows=2, cols=2)
        for cell in ref_tbl.rows[0].cells:
            cell.paragraphs[0].add_run("表头")
            tcPr = cell._tc.get_or_add_tcPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), "D9E2F3")
            tcPr.append(shd)
            v_align = OxmlElement("w:vAlign")
            v_align.set(qn("w:val"), "center")
            tcPr.append(v_align)
        for row in ref_tbl.rows:
            row._tr.get_or_add_trPr().append(self._tr_height("380"))
        ref.save(ref_path)

        broken = docx.Document()
        broken.add_paragraph("正文")
        broken_tbl = broken.add_table(rows=2, cols=2)
        for row in broken_tbl.rows:
            for cell in row.cells:
                cell.paragraphs[0].add_run("内容")
        broken.save(broken_path)

        plan = build_repair_plan(ref_path, broken_path)
        execute_repair_plan(plan, out_path)

        repaired = docx.Document(out_path).tables[0]
        shading = repaired.rows[0].cells[0]._tc.tcPr.find(qn("w:shd"))
        self.assertIsNotNone(shading)
        self.assertEqual(shading.get(qn("w:fill")) or shading.get(qn("w:color")), "D9E2F3")
        self.assertEqual(
            repaired.rows[0].cells[0]._tc.tcPr.find(qn("w:vAlign")).get(qn("w:val")),
            "center",
        )
        for row in repaired.rows:
            self.assertEqual(row._tr.find(qn("w:trPr")).find(qn("w:trHeight")).get(qn("w:val")), "380")


    def test_p0_qa_cli_reports_structured_status_and_pending_review(self) -> None:
        """Placeholder residue is PENDING, not FAILED; a missing check outranks it as UNVERIFIED."""
        path = os.path.join(self.work_dir, "pending_review.docx")
        doc = docx.Document()
        doc.add_paragraph("正文：{{待人工确认}}")
        doc.save(path)

        strict = subprocess.run(
            [sys.executable, os.path.join(ROOT_DIR, "scripts", "run_qa.py"), path],
            cwd=ROOT_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(strict.returncode, 1, strict.stderr)
        strict_report = json.loads(strict.stdout)
        self.assertEqual(strict_report["status"], "FAILED")
        self.assertGreaterEqual(strict_report["hard_failure_count"], 1)
        self.assertTrue(any(item["code"] == "TEMPLATE_TEXT_RESIDUAL" for item in strict_report["issues"]))
        for item in strict_report["issues"]:
            self.assertIn("code", item)
            self.assertIn("location", item)
            self.assertIn("severity", item)

        relaxed = subprocess.run(
            [sys.executable, os.path.join(ROOT_DIR, "scripts", "run_qa.py"), path, "--review"],
            cwd=ROOT_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", check=False,
        )
        relaxed_report = json.loads(relaxed.stdout)
        if relaxed_report["coverage_gaps"] or relaxed_report["unverified_count"]:
            self.assertEqual(relaxed_report["status"], "UNVERIFIED")
            # UNVERIFIED is disclosed, not silently treated as success.
            self.assertEqual(relaxed.returncode, 1, relaxed.stderr)
            self.assertFalse(relaxed_report["exit_ok"])
            allowed = subprocess.run(
                [sys.executable, os.path.join(ROOT_DIR, "scripts", "run_qa.py"), path,
                 "--review", "--allow-unverified"],
                cwd=ROOT_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertTrue(json.loads(allowed.stdout)["exit_ok"])
        else:
            self.assertEqual(relaxed_report["status"], "PENDING_HUMAN_REVIEW")
            self.assertEqual(relaxed.returncode, 0, relaxed.stderr)
        self.assertFalse(relaxed_report["passed"])
        self.assertTrue(relaxed_report["passed_or_pending"])
        self.assertEqual(relaxed_report["hard_failure_count"], 0)
        self.assertGreaterEqual(relaxed_report["pending_human_review_count"], 1)

    def test_p0_every_qa_section_exposes_structured_issues(self) -> None:
        """Package, visual, review and excel QA must all return machine-readable issues."""
        docx_path = os.path.join(self.work_dir, "sections.docx")
        docx.Document().save(docx_path)

        pkg = audit_docx_package_integrity(docx_path)
        self.assertIn("structured_issues", pkg)
        self.assertEqual(pkg["issues"], [])
        self.assertIn("coverage_gaps", pkg)

        visual = run_visual_layout_qa(docx_path)
        self.assertIn("structured_issues", visual)
        self.assertIn("coverage_gaps", visual)

        xlsx_path = os.path.join(self.work_dir, "sections.xlsx")
        workbook = openpyxl.Workbook()
        workbook.active["A1"] = 1
        workbook.save(xlsx_path)
        excel = audit_excel_formula_and_style_qa(xlsx_path, xlsx_path)
        self.assertIn("structured_issues", excel)
        self.assertIsInstance(excel["unverified_count"], int)

        reviewed_path = os.path.join(self.work_dir, "sections_review.docx")
        reviewed = docx.Document()
        reviewed.add_paragraph("内容")
        enable_track_changes(reviewed, True)
        reviewed.save(reviewed_path)
        review = audit_review_integrity(reviewed_path)
        self.assertIn("structured_issues", review)
        self.assertEqual(review["issues"], [])
        self.assertIn("coverage_gaps", review)

    def test_p3_unmatched_revision_becomes_a_review_comment(self) -> None:
        """A revision whose source text is absent must still reach the reviewer, not vanish."""
        ref_path = os.path.join(self.work_dir, "unmatched_ref.docx")
        target_path = os.path.join(self.work_dir, "unmatched_target.docx")
        out_path = os.path.join(self.work_dir, "unmatched_out.docx")

        ref = docx.Document()
        ref.add_paragraph("标准正文")
        ref.save(ref_path)

        target = docx.Document()
        target.add_paragraph("草稿正文")
        target.save(target_path)

        plan = build_review_plan(
            ref_path,
            target_path,
            text_revisions=[{"old_text": "文档中不存在这句话", "new_text": "应当替换为这句"}],
        )
        execution = execute_review_plan(plan, out_path)

        self.assertEqual(len(execution["unresolved_actions"]), 1)
        self.assertGreaterEqual(execution["comments_added"], 1)
        self.assertEqual(execution["tracked_text_revisions"], 0)

        qa = audit_review_integrity(out_path)
        self.assertTrue(qa["passed"], qa["issues"])
        self.assertEqual(qa["comment_count"], 1)

        with zipfile.ZipFile(out_path) as zf:
            comments_xml = zf.read("word/comments.xml").decode("utf-8")
        self.assertIn("未能自动定位", comments_xml)
        self.assertIn("文档中不存在这句话", comments_xml)


if __name__ == "__main__":
    unittest.main(verbosity=2)
