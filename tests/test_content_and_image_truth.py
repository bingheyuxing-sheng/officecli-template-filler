# -*- coding: utf-8 -*-
"""P0 truth-integrity tests: SVG dual embeds, vector gaps, content consistency, fact sources."""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from PIL import Image

from engine import (
    audit_content_consistency,
    audit_fact_sources,
    count_image_part_references,
    find_numeric_occurrences,
    replace_inline_image_in_paragraph,
    verify_docx_images_integrity,
)

SVG_EXT_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
SVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"


def _png(path: str, size=(120, 60), color=(200, 30, 30)) -> str:
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def _docx_with_png(work_dir: str) -> str:
    image_path = _png(os.path.join(work_dir, "pic.png"))
    path = os.path.join(work_dir, "base.docx")
    document = docx.Document()
    document.add_paragraph("图前文字")
    document.add_picture(image_path)
    document.save(path)
    return path


def _add_svg_blip(docx_path: str, work_dir: str) -> str:
    """
    Rewrite the package so the picture carries a Word-style SVG dual embed:

        a:blip (PNG fallback) + asvg:svgBlip -> word/media/icon.svg
    """
    out_path = os.path.join(work_dir, "svg_icon.docx")
    svg_bytes = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">'
        b'<rect width="120" height="60" fill="#123456"/></svg>'
    )
    with zipfile.ZipFile(docx_path, "r") as src, zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                document = docx.Document(docx_path)
                blip = document.element.body.xpath(".//a:blip")[0]
                extension = parse_xml(
                    f'<a:extLst {nsdecls("a", "r")}>'
                    f'<a:ext uri="{SVG_EXT_URI}">'
                    f'<asvg:svgBlip xmlns:asvg="{SVG_NS}" r:embed="rIdSvg"/>'
                    f"</a:ext></a:extLst>"
                )
                blip.append(extension)
                # Serialize the modified document part only (the rest of the package is untouched).
                from lxml import etree

                data = etree.tostring(document.element, xml_declaration=True, encoding="UTF-8", standalone=True)
            elif item.filename == "word/_rels/document.xml.rels":
                data = data.replace(
                    b"</Relationships>",
                    b'<Relationship Id="rIdSvg" '
                    b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                    b'Target="media/icon.svg"/></Relationships>',
                )
            elif item.filename == "[Content_Types].xml":
                data = data.replace(
                    b"</Types>",
                    b'<Default Extension="svg" ContentType="image/svg+xml"/></Types>',
                )
            dst.writestr(item, data)
        dst.writestr("word/media/icon.svg", svg_bytes)
    return out_path


class TestImageTruthSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_img_truth_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_svg_blip_counts_as_shared_reference(self) -> None:
        base = _docx_with_png(self.work_dir)
        svg_doc = _add_svg_blip(base, self.work_dir)
        document = docx.Document(svg_doc)
        summary = count_image_part_references(document)
        kinds = {info["reference_kind"] for info in summary.values()}
        self.assertIn("blip", kinds)
        self.assertIn("svgBlip", kinds)

    def test_verification_reports_svg_and_vector_gap(self) -> None:
        base = _docx_with_png(self.work_dir)
        svg_doc = _add_svg_blip(base, self.work_dir)
        report = verify_docx_images_integrity(svg_doc)
        self.assertTrue(report["passed"], report["issues"])
        self.assertTrue(report["svg_dual_embeds"], "svgBlip must be reported, not ignored")
        self.assertTrue(
            any("VECTOR_IMAGE_UNVERIFIED" in gap for gap in report["coverage_gaps"]),
            report["coverage_gaps"],
        )
        self.assertGreaterEqual(report["unverified_count"], 1)

    def test_replacement_removes_stale_svg_blip(self) -> None:
        base = _docx_with_png(self.work_dir)
        svg_doc = _add_svg_blip(base, self.work_dir)
        document = docx.Document(svg_doc)
        paragraph = document.paragraphs[0] if document.paragraphs[0]._p.xpath(".//a:blip") else document.paragraphs[1]
        new_image = _png(os.path.join(self.work_dir, "new.png"), size=(200, 200), color=(10, 120, 200))
        result = replace_inline_image_in_paragraph(document, paragraph, new_image)
        self.assertIn("svg_fallback_removed", result["adjustments"])
        self.assertTrue(result["removed_svg_rids"])
        output = os.path.join(self.work_dir, "replaced.docx")
        document.save(output)
        with zipfile.ZipFile(output, "r") as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        self.assertNotIn("svgBlip", document_xml, "a stale svgBlip would keep rendering the old icon")

    def test_replacement_clears_crop_and_fits_extent(self) -> None:
        base = _docx_with_png(self.work_dir)
        document = docx.Document(base)
        paragraph = document.paragraphs[1]
        blip = paragraph._p.xpath(".//a:blip")[0]
        blip_fill = blip.getparent()
        blip_fill.append(parse_xml(f'<a:srcRect {nsdecls("a")} l="10000" t="5000"/>'))
        new_image = _png(os.path.join(self.work_dir, "wide.png"), size=(400, 100), color=(30, 30, 30))
        result = replace_inline_image_in_paragraph(
            document, paragraph, new_image, fit_mode="fit_image"
        )
        self.assertIn("crop_rect_cleared", result["adjustments"])
        self.assertIn("extent_fitted", result["adjustments"])
        self.assertIsNotNone(result["extent"])
        self.assertLess(result["extent"]["cy"], result["extent"]["previous_cy"])

    def test_vml_picture_is_replaced(self) -> None:
        """WPS header logos use w:pict/v:imagedata, which has no a:blip."""
        base = _docx_with_png(self.work_dir)
        document = docx.Document(base)
        paragraph = document.paragraphs[1]
        blip = paragraph._p.xpath(".//a:blip")[0]
        old_rId = blip.get(qn("r:embed"))
        run = blip.getparent().getparent().getparent()  # a:graphic -> w:drawing -> w:r
        while run is not None and run.tag != qn("w:r"):
            run = run.getparent()
        self.assertIsNotNone(run)
        for drawing in paragraph._p.xpath(".//w:drawing"):
            drawing.getparent().remove(drawing)
        run.append(parse_xml(
            f'<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            f'xmlns:v="urn:schemas-microsoft-com:vml" '
            f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<v:shape style="width:120pt;height:60pt">'
            f'<v:imagedata r:id="{old_rId}"/></v:shape></w:pict>'
        ))
        new_image = _png(os.path.join(self.work_dir, "logo.png"), size=(80, 80), color=(0, 100, 0))
        summary = count_image_part_references(document)
        self.assertTrue(any(info["reference_kind"] == "vml" for info in summary.values()))
        result = replace_inline_image_in_paragraph(document, paragraph, new_image)
        self.assertEqual(result["reference_kind"], "vml")
        self.assertTrue(result["effective"])
        output = os.path.join(self.work_dir, "vml_replaced.docx")
        document.save(output)
        with zipfile.ZipFile(output, "r") as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("imagedata", document_xml)
        self.assertIn(result["new_rId"], document_xml)


class TestContentTruthSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_content_truth_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _table(self, document, rows):
        table = document.add_table(rows=len(rows), cols=2)
        for row_index, (label, value) in enumerate(rows):
            table.cell(row_index, 0).text = label
            table.cell(row_index, 1).text = value
        return table

    def test_subtotal_mismatch_is_high_severity(self) -> None:
        document = docx.Document()
        document.add_paragraph("总学时为2504学时。")
        self._table(document, [("理论", "972"), ("实践", "1532"), ("合计", "2400")])
        report = audit_content_consistency(doc=document)
        issues = [item for item in report["issues"] if item["code"] == "CONTENT_SUBTOTAL_MISMATCH"]
        self.assertTrue(issues, report["issues"])
        self.assertEqual(issues[0]["severity"], "high")
        self.assertFalse(report["passed"])

    def test_consistent_subtotal_passes(self) -> None:
        document = docx.Document()
        document.add_paragraph("总学时为2504学时。")
        self._table(document, [("理论", "972"), ("实践", "1532"), ("合计", "2504")])
        report = audit_content_consistency(doc=document)
        self.assertEqual(
            [item for item in report["issues"] if item["code"] == "CONTENT_SUBTOTAL_MISMATCH"],
            [],
        )
        self.assertTrue(report["passed"])

    def test_prose_vs_table_total_conflict(self) -> None:
        document = docx.Document()
        document.add_paragraph("项目总投资：100万元。")
        self._table(document, [("建设内容", "平台"), ("总投资", "105万元")])
        report = audit_content_consistency(doc=document)
        conflicts = [item for item in report["issues"] if item["code"] == "CONTENT_VALUE_CONFLICT"]
        self.assertTrue(conflicts, report["issues"])
        self.assertIn("100", conflicts[0]["detail"])
        self.assertIn("105", conflicts[0]["detail"])

    def test_per_row_values_do_not_conflict(self) -> None:
        document = docx.Document()
        table = document.add_table(rows=3, cols=2)
        for index, value in enumerate(("16", "24", "32")):
            table.cell(index, 0).text = f"课程{index}"
            table.cell(index, 1).text = value
        report = audit_content_consistency(doc=document)
        self.assertFalse(
            [item for item in report["issues"] if item["code"].startswith("CONTENT_VALUE")]
        )

    def test_term_drift_detects_name_typo(self) -> None:
        document = docx.Document()
        table = document.add_table(rows=2, cols=1)
        table.cell(0, 0).text = "张伟"
        table.cell(1, 0).text = "张玮"
        for _ in range(4):
            document.add_paragraph("张伟负责本模块。")
        report = audit_content_consistency(doc=document)
        drift = [item for item in report["issues"] if item["code"] == "CONTENT_TERM_DRIFT"]
        self.assertTrue(drift, report["issues"])

    def test_numeric_occurrences_report_context(self) -> None:
        document = docx.Document()
        document.add_paragraph("总学时 2504，其中实践 1532。")
        occurrences = find_numeric_occurrences(document, ["2504"])
        self.assertEqual(len(occurrences), 1)
        self.assertIn("2504", occurrences[0]["context"])

    def test_fact_source_required(self) -> None:
        report = audit_fact_sources([
            {"label": "总学时", "value": 2504, "source": "https://example.edu/plan"},
            {"label": "就业率", "value": "98%"},
        ])
        self.assertFalse(report["passed"])
        self.assertEqual(report["issues"][0]["code"], "FACT_SOURCE_MISSING")
        self.assertEqual(report["issues"][0]["severity"], "high")
        self.assertEqual(audit_fact_sources([{"label": "x", "source": "UNVERIFIED"}])["unverified_count"], 1)


if __name__ == "__main__":
    unittest.main()
