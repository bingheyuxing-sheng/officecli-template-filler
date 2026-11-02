# -*- coding: utf-8 -*-
"""
v3.5 M2 — Table signature tests (T5).

The signature must describe the table well enough to explain template drift:
row count, per-row `trHeight` including `hRule`, and the `tblLook` / band-size
switches that drive Word's banded formatting.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from engine import compare_table_style, restore_table_style_from_reference, table_style_signature


class TestTableSignatureSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_table_sig_")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _table(self, rows: int = 2, cols: int = 2):
        document = docx.Document()
        table = document.add_table(rows=rows, cols=cols)
        for row in table.rows:
            for cell in row.cells:
                cell.paragraphs[0].add_run("内容")
        return table

    @staticmethod
    def _set_row_height(row, value: str, rule: str = "atLeast") -> None:
        trPr = row._tr.get_or_add_trPr()
        height = OxmlElement("w:trHeight")
        height.set(qn("w:val"), value)
        height.set(qn("w:hRule"), rule)
        trPr.append(height)

    @staticmethod
    def _set_tbl_look(table, attributes) -> None:
        tblPr = table._tbl.tblPr
        for existing in tblPr.findall(qn("w:tblLook")):
            tblPr.remove(existing)
        look = OxmlElement("w:tblLook")
        for key, value in attributes.items():
            look.set(qn(f"w:{key}"), value)
        tblPr.append(look)

    @staticmethod
    def _set_band_sizes(table, row_band: str, col_band: str) -> None:
        tblPr = table._tbl.tblPr
        for tag, value in (("w:tblStyleRowBandSize", row_band), ("w:tblStyleColBandSize", col_band)):
            for existing in tblPr.findall(qn(tag)):
                tblPr.remove(existing)
            node = OxmlElement(tag)
            node.set(qn("w:val"), value)
            tblPr.append(node)

    def test_v35_table_signature_records_row_count(self) -> None:
        """Row count must be part of the signature, not inferred from the height list."""
        self.assertEqual(table_style_signature(self._table(rows=3))["row_count"], 3)
        self.assertEqual(table_style_signature(self._table(rows=1))["row_count"], 1)

    def test_v35_table_signature_records_trheight_hrule(self) -> None:
        """Row heights keep value AND rule; `atLeast` is not `exact`."""
        table = self._table(rows=2)
        self._set_row_height(table.rows[0], "400", "atLeast")
        self._set_row_height(table.rows[1], "400", "exact")

        heights = table_style_signature(table)["row_heights"]
        self.assertEqual(heights[0], {"val": 400, "hRule": "atLeast"})
        self.assertEqual(heights[1], {"val": 400, "hRule": "exact"})

        table_no_height = self._table(rows=1)
        self.assertEqual(table_style_signature(table_no_height)["row_heights"][0], {"val": None, "hRule": None})

    def test_v35_table_signature_records_tbl_look_and_band_sizes(self) -> None:
        """`tblLook` and the band-size switches decide how Word renders table bands."""
        table = self._table()
        tblPr = table._tbl.tblPr
        for existing in tblPr.findall(qn("w:tblLook")):
            tblPr.remove(existing)
        look = OxmlElement("w:tblLook")
        look.set(qn("w:val"), "04A0")
        look.set(qn("w:firstRow"), "1")
        look.set(qn("w:noHBand"), "0")
        tblPr.append(look)
        row_band = OxmlElement("w:tblStyleRowBandSize")
        row_band.set(qn("w:val"), "1")
        tblPr.append(row_band)
        col_band = OxmlElement("w:tblStyleColBandSize")
        col_band.set(qn("w:val"), "2")
        tblPr.append(col_band)

        signature = table_style_signature(table)
        self.assertEqual(signature["tbl_look"], {"val": "04A0", "firstRow": "1", "noHBand": "0"})
        self.assertEqual(signature["row_band_size"], "1")
        self.assertEqual(signature["col_band_size"], "2")

    def test_v35_compare_accepts_legacy_row_height_strings(self) -> None:
        """Profiles saved before v3.5 stored raw height strings; comparison must still read them."""
        table = self._table(rows=2)
        self._set_row_height(table.rows[0], "380", "atLeast")
        signature = table_style_signature(table)
        legacy_reference = dict(signature)
        legacy_reference["row_heights"] = ["380", None]

        issues = compare_table_style(signature, legacy_reference, 0)
        self.assertFalse([item for item in issues if item[0] == "table_row_height"])

    def test_v35_table_row_height_drift_threshold(self) -> None:
        """Within 15% is tolerated; beyond it (or a different hRule) must report and be repairable."""
        reference = self._table(rows=2)
        self._set_row_height(reference.rows[0], "400", "atLeast")
        self._set_row_height(reference.rows[1], "300", "atLeast")

        within = self._table(rows=2)
        self._set_row_height(within.rows[0], "440", "atLeast")  # 10% drift
        self._set_row_height(within.rows[1], "300", "atLeast")
        issues = compare_table_style(table_style_signature(within), table_style_signature(reference), 0)
        self.assertFalse([item for item in issues if item[0] == "table_row_height"])

        drifted = self._table(rows=2)
        self._set_row_height(drifted.rows[0], "500", "atLeast")  # 25% drift
        self._set_row_height(drifted.rows[1], "300", "exact")    # rule drift
        issues = compare_table_style(table_style_signature(drifted), table_style_signature(reference), 0)
        self.assertTrue(any(item[0] == "table_row_height" and item[2] == 0 for item in issues))
        self.assertTrue(any(item[0] == "table_row_height_rule" and item[2] == 1 for item in issues))

        self.assertTrue(restore_table_style_from_reference(drifted, reference))
        after = compare_table_style(table_style_signature(drifted), table_style_signature(reference), 0)
        self.assertFalse([
            item for item in after if item[0] in ("table_row_height", "table_row_height_rule")
        ])
        self.assertEqual(
            table_style_signature(drifted)["row_heights"][1],
            {"val": 300, "hRule": "atLeast"},
        )

    def test_v35_table_look_drift_detected_and_restored(self) -> None:
        """`tblLook` and band sizes drive Word banding; drift must be reported and repaired."""
        reference = self._table()
        self._set_tbl_look(reference, {"val": "04A0", "firstRow": "1", "noHBand": "0"})
        self._set_band_sizes(reference, "2", "1")

        target = self._table()
        self._set_tbl_look(target, {"val": "04A0", "firstRow": "1", "noHBand": "1"})
        self._set_band_sizes(target, "1", "1")

        issues = compare_table_style(table_style_signature(target), table_style_signature(reference), 0)
        self.assertTrue(any(item[0] == "table_tbl_look" for item in issues))
        self.assertTrue(any(item[0] == "table_band_size" for item in issues))

        self.assertTrue(restore_table_style_from_reference(target, reference))
        after = compare_table_style(table_style_signature(target), table_style_signature(reference), 0)
        self.assertFalse([
            item for item in after if item[0] in ("table_tbl_look", "table_band_size")
        ])

    def test_v35_table_row_count_reported_only(self) -> None:
        """Row-count drift is reported but never repaired: it would change business content."""
        reference = self._table(rows=3)
        target = self._table(rows=2)

        issues = compare_table_style(table_style_signature(target), table_style_signature(reference), 0)
        self.assertTrue(any(item[0] == "table_row_count" for item in issues))

        restore_table_style_from_reference(target, reference)
        self.assertEqual(len(target.rows), 2)
        after = compare_table_style(table_style_signature(target), table_style_signature(reference), 0)
        self.assertTrue(any(item[0] == "table_row_count" for item in after))


    def test_v35_merge_restore_requires_identical_topology(self) -> None:
        """Merges are written only when safe; conflicting text stays manual_required."""
        reference_doc = docx.Document()
        reference_table = reference_doc.add_table(rows=2, cols=2)
        merged = reference_table.cell(0, 0).merge(reference_table.cell(0, 1))
        merged.paragraphs[0].add_run("标题")
        reference_table.cell(1, 0).paragraphs[0].add_run("A")
        reference_table.cell(1, 1).paragraphs[0].add_run("B")

        safe_doc = docx.Document()
        safe_table = safe_doc.add_table(rows=2, cols=2)
        safe_table.cell(0, 0).paragraphs[0].add_run("标题")
        safe_table.cell(1, 0).paragraphs[0].add_run("A")
        safe_table.cell(1, 1).paragraphs[0].add_run("B")

        result = restore_table_style_from_reference(safe_table, reference_table)
        self.assertTrue(any("gridSpan" in item for item in result["restored"]))
        grid_span = safe_table.cell(0, 0)._tc.tcPr.find(qn("w:gridSpan"))
        self.assertIsNotNone(grid_span)
        self.assertEqual(grid_span.get(qn("w:val")), "2")

        unsafe_doc = docx.Document()
        unsafe_table = unsafe_doc.add_table(rows=2, cols=2)
        unsafe_table.cell(0, 0).paragraphs[0].add_run("标题")
        unsafe_table.cell(0, 1).paragraphs[0].add_run("副标题")
        unsafe_table.cell(1, 0).paragraphs[0].add_run("A")
        unsafe_table.cell(1, 1).paragraphs[0].add_run("B")

        unsafe_result = restore_table_style_from_reference(unsafe_table, reference_table)
        reasons = {item.get("reason") for item in unsafe_result["manual_required"]}
        self.assertIn("merged_cells_have_different_text", reasons)
        self.assertIsNone(unsafe_table.cell(0, 0)._tc.tcPr.find(qn("w:gridSpan")))

        short_doc = docx.Document()
        short_table = short_doc.add_table(rows=1, cols=2)
        short_result = restore_table_style_from_reference(short_table, reference_table)
        self.assertIn(
            "row_count_mismatch",
            {item.get("reason") for item in short_result["manual_required"]},
        )


if __name__ == "__main__":
    unittest.main()
