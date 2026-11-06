# -*- coding: utf-8 -*-
"""Contract test: TemplateEvidence 1.0 schema validates real analyzer output."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from template_gate import build_analysis  # noqa: E402


def _schema() -> dict:
    with open(ROOT / "schemas" / "template_evidence-1.0.schema.json", "r", encoding="utf-8") as handle:
        return json.load(handle)


class TemplateEvidenceSchemaTests(unittest.TestCase):
    def test_analyzer_output_validates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "template.docx")
            document = docx.Document()
            document.add_paragraph("{{标题}}")
            document.save(path)
            analysis = build_analysis(path, "GENERATE")

        errors = sorted(Draft202012Validator(_schema()).iter_errors(analysis), key=lambda item: list(item.absolute_path))
        self.assertEqual(errors, [], [error.message for error in errors])

    def test_schema_rejects_unknown_evidence_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "template.docx")
            document = docx.Document()
            document.add_paragraph("{{标题}}")
            document.save(path)
            analysis = build_analysis(path, "GENERATE")
        analysis["evidence"][0]["verification_status"] = "MAYBE"
        errors = list(Draft202012Validator(_schema()).iter_errors(analysis))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
