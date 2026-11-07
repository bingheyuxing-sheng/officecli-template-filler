# -*- coding: utf-8 -*-
"""Regression: paragraph-mark rPr must be created without CT_PPr.get_or_add_rPr.

python-docx 1.2 exposes neither ``CT_PPr.rPr`` nor ``get_or_add_rPr``.  The
review engine used that private API and crashed on real WPS documents whose
paragraph mark had no explicit run properties.  These tests pin the schema-order
creation path used by the tracked-format writer.
"""

from __future__ import annotations

import unittest

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from engine.review_engine import _paragraph_mark_rpr


class ParagraphMarkRprTests(unittest.TestCase):
    def test_creates_rpr_before_ppr_change(self) -> None:
        paragraph = Document().add_paragraph("x")._p
        p_pr = paragraph.get_or_add_pPr()
        change = OxmlElement("w:pPrChange")
        p_pr.append(change)

        r_pr = _paragraph_mark_rpr(paragraph, create=True)

        self.assertIsNotNone(r_pr)
        self.assertIs(p_pr.find(qn("w:rPr")), r_pr)
        children = list(p_pr)
        self.assertLess(children.index(r_pr), children.index(change))

    def test_creates_ppr_when_absent(self) -> None:
        paragraph = Document().add_paragraph("x")._p
        self.assertIsNone(paragraph.pPr)

        r_pr = _paragraph_mark_rpr(paragraph, create=True)

        self.assertIsNotNone(r_pr)
        self.assertIs(paragraph[0], paragraph.pPr)
        self.assertIs(paragraph.pPr.find(qn("w:rPr")), r_pr)

    def test_read_only_lookup_does_not_create(self) -> None:
        paragraph = Document().add_paragraph("x")._p

        self.assertIsNone(_paragraph_mark_rpr(paragraph))
        self.assertIsNone(paragraph.pPr)


if __name__ == "__main__":
    unittest.main()
