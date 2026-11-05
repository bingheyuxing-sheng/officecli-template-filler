# -*- coding: utf-8 -*-
"""v3.5.9 compatibility gate: public API, legacy producers and untouched old schemas."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import docx

from .helpers import ROOT, SCHEMA_DIR, load_json, schema_errors

TEMPLATE = ROOT / "tests" / "fixtures" / "legacy" / "legacy_ref.docx"


class LegacyPublicApiTests(unittest.TestCase):
    def test_engine_version_and_exports(self) -> None:
        import engine

        self.assertEqual(engine.__version__, "4.0.1")
        missing = [name for name in engine.__all__ if not hasattr(engine, name)]
        self.assertEqual(missing, [], f"removed public symbols: {missing}")

    def test_old_schemas_are_untouched(self) -> None:
        legacy = load_json(SCHEMA_DIR / "document_spec.schema.json")
        self.assertEqual(legacy["properties"]["schema_version"]["const"], "3.0")
        qa_schema = load_json(SCHEMA_DIR / "qa_report.schema.json")
        self.assertEqual(
            set(qa_schema["properties"]["status"]["enum"]),
            {"PASSED", "FAILED", "PENDING_HUMAN_REVIEW", "UNVERIFIED"},
        )


class LegacyProducerTests(unittest.TestCase):
    def test_library_output_validates_against_legacy_schema(self) -> None:
        from engine import extract_document_spec

        spec = extract_document_spec(docx.Document(str(TEMPLATE)), file_path=str(TEMPLATE))
        self.assertEqual(schema_errors("document_spec_legacy", spec), [])

    def test_cli_output_validates_against_legacy_cli_schema(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "analyze_template.py"), "--input", str(TEMPLATE)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(schema_errors("document_spec_legacy_cli", payload), [])

    def test_legacy_output_is_not_accepted_as_document_spec_4(self) -> None:
        from engine import extract_document_spec

        spec = extract_document_spec(docx.Document(str(TEMPLATE)), file_path=str(TEMPLATE))
        self.assertNotEqual(schema_errors("document_spec", spec), [], "3.0 output must not validate as 4.0")


if __name__ == "__main__":
    unittest.main()
