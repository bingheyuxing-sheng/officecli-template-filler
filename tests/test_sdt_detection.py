# -*- coding: utf-8 -*-
"""W3-3: body-level w:sdt must be discovered, capped to L3 and disclosed.

Covers the audit P1-01 reproduction plus fail-closed behaviour: the spec must
never silently report L1/L2 when body-level SDT content exists or the scan
itself failed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from template_intelligence import build_document_spec_from_path  # noqa: E402
from template_intelligence import spec_builder  # noqa: E402
from template_intelligence.spec_validator import validate_document_spec  # noqa: E402


def _wrap_paragraph_in_body_sdt(doc, paragraph) -> None:
    """Move `paragraph` into a body-level w:sdt/w:sdtContent container."""
    body = doc.element.body
    sdt = OxmlElement("w:sdt")
    content = OxmlElement("w:sdtContent")
    paragraph._p.addprevious(sdt)
    body.remove(paragraph._p)
    content.append(paragraph._p)
    sdt.append(content)


def _append_empty_body_sdt(doc) -> None:
    body = doc.element.body
    sdt = OxmlElement("w:sdt")
    sdt.append(OxmlElement("w:sdtPr"))
    sdt.append(OxmlElement("w:sdtContent"))
    sect = body.find(qn("w:sectPr"))
    if sect is not None:
        sect.addprevious(sdt)
    else:
        body.append(sdt)


class SdtBodyDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.counter = 0

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp.name, ignore_errors=True)

    def _save(self, doc) -> str:
        self.counter += 1
        path = os.path.join(self._tmp.name, "t%d.docx" % self.counter)
        doc.save(path)
        return path

    def _assert_valid(self, spec) -> None:
        report = validate_document_spec(spec)
        self.assertTrue(report["passed"], report["errors"][:5])

    def test_audit_reproduction_is_disclosed_and_capped(self) -> None:
        doc = docx.Document()
        para = doc.add_paragraph("{{project_name}} 项目信息")
        _wrap_paragraph_in_body_sdt(doc, para)
        spec = build_document_spec_from_path(self._save(doc))
        self._assert_valid(spec)
        self.assertEqual(spec["template"]["compatibility"], "L3")
        codes = [item["code"] for item in spec["unsupported_features"]]
        self.assertIn("SDT_BODY_UNSUPPORTED", codes)
        detail = next(i["detail"] for i in spec["unsupported_features"] if i["code"] == "SDT_BODY_UNSUPPORTED")
        self.assertIn("child[", detail, "disclosure must name the concrete body position")
        self.assertIn("1 paragraph", detail)
        warnings = [w for w in spec["warnings"] if w["code"] == "SDT_BODY_ENUMERATION_GAP"]
        self.assertTrue(warnings)
        self.assertEqual(warnings[0]["severity"], "high")
        self.assertEqual(spec["slots"], [])  # undiscoverable until CP-W2-002, but now disclosed

    def test_sdt_wrapping_table_is_disclosed(self) -> None:
        doc = docx.Document()
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "标签"
        body = doc.element.body
        sdt = OxmlElement("w:sdt")
        content = OxmlElement("w:sdtContent")
        tbl_el = table._tbl
        tbl_el.addprevious(sdt)
        body.remove(tbl_el)
        content.append(tbl_el)
        sdt.append(content)
        spec = build_document_spec_from_path(self._save(doc))
        self._assert_valid(spec)
        self.assertEqual(spec["template"]["compatibility"], "L3")
        detail = " ".join(i["detail"] for i in spec["unsupported_features"] if i["code"] == "SDT_BODY_UNSUPPORTED")
        self.assertIn("1 table", detail)

    def test_nested_sdt_counted_once_as_one_body_container(self) -> None:
        doc = docx.Document()
        para = doc.add_paragraph("{{inner}}")
        _wrap_paragraph_in_body_sdt(doc, para)
        # wrap the outer sdt inside another body-level sdt
        body = doc.element.body
        outer = OxmlElement("w:sdt")
        outer_content = OxmlElement("w:sdtContent")
        target = body.find(qn("w:sdt"))
        target.addprevious(outer)
        body.remove(target)
        outer_content.append(target)
        outer.append(outer_content)
        spec = build_document_spec_from_path(self._save(doc))
        sdt_entries = [i for i in spec["unsupported_features"] if i["code"] == "SDT_BODY_UNSUPPORTED"]
        self.assertEqual(len(sdt_entries), 1, "only direct body children are containers")

    def test_inline_sdt_in_paragraph_is_not_body_level(self) -> None:
        doc = docx.Document()
        para = doc.add_paragraph()
        sdt = OxmlElement("w:sdt")
        content = OxmlElement("w:sdtContent")
        run = para.add_run("{{inline}}")
        run._r.addprevious(sdt)
        para._p.remove(run._r)
        content.append(run._r)
        sdt.append(content)
        spec = build_document_spec_from_path(self._save(doc))
        codes = [i["code"] for i in spec["unsupported_features"]]
        self.assertNotIn("SDT_BODY_UNSUPPORTED", codes)
        self.assertNotIn("SDT_BODY_ENUMERATION_GAP", [w["code"] for w in spec["warnings"]])

    def test_empty_body_sdt_only_low_warning(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("正文")
        _append_empty_body_sdt(doc)
        spec = build_document_spec_from_path(self._save(doc))
        self.assertEqual(spec["template"]["compatibility"], "L1")
        codes = [w["code"] for w in spec["warnings"]]
        self.assertIn("SDT_BODY_EMPTY", codes)
        self.assertNotIn("SDT_BODY_UNSUPPORTED", [i["code"] for i in spec["unsupported_features"]])

    def test_clean_template_has_no_sdt_disclosure(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{项目名称}}")
        spec = build_document_spec_from_path(self._save(doc))
        self._assert_valid(spec)
        all_codes = ([i["code"] for i in spec["unsupported_features"]]
                     + [w["code"] for w in spec["warnings"]])
        self.assertNotIn("SDT_BODY_UNSUPPORTED", all_codes)
        self.assertNotIn("SDT_BODY_ENUMERATION_GAP", all_codes)

    def test_scan_failure_is_fail_closed(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{项目名称}}")
        path = self._save(doc)
        broken = {"containers": [], "scan_error": "RuntimeError: simulated"}
        with mock.patch.object(spec_builder, "_scan_body_sdt", return_value=broken):
            spec = build_document_spec_from_path(path)
        self.assertEqual(spec["template"]["compatibility"], "L3")
        self.assertIn("SDT_BODY_SCAN_INCOMPLETE", [i["code"] for i in spec["unsupported_features"]])
        high = [w for w in spec["warnings"] if w["code"] == "SDT_BODY_ENUMERATION_GAP"]
        self.assertTrue(high)
        self.assertEqual(high[0]["severity"], "high")


if __name__ == "__main__":
    unittest.main()
