# -*- coding: utf-8 -*-
"""W2 environment capability detection tests.

The contract under test: declarative expectations state ``required``; only live
probes decide ``status``; a missing optional capability stays local, while a
missing required capability can never yield a PASSED report.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa import environment as env_mod  # noqa: E402
from qa import pipeline as pipeline_mod  # noqa: E402
from qa.environment import (  # noqa: E402
    capability_matrix,
    detect_environment,
    load_environment_capabilities,
    missing_capabilities,
    required_capabilities_ok,
)
from qa.gate import validate_qa_report  # noqa: E402

OUT_DOCX = ROOT / "tests" / "fixtures" / "legacy" / "legacy_out.docx"
REF_DOCX = ROOT / "tests" / "fixtures" / "legacy" / "legacy_ref.docx"
JSON_CONFIG = ROOT / "config" / "environment_capabilities.json"
YAML_CONFIG = ROOT / "config" / "environment_capabilities.yaml"

REQUIRED_CAPABILITIES = ("docx_parse", "docx_write", "wps_pdf_render", "pdf_page_analysis")
OPTIONAL_CAPABILITIES = ("pixel_visual_diff", "ocr", "chart_render")


def _synthetic_matrix(required_status: str = "AVAILABLE", optional_status: str = "UNAVAILABLE") -> dict:
    """A complete matrix derived from the real config with explicit probe verdicts."""
    config = load_environment_capabilities()["capabilities"]
    matrix = {}
    for name, declaration in config.items():
        status = required_status if declaration.get("required") else optional_status
        matrix[name] = {
            "required": bool(declaration.get("required")),
            "available": status == "AVAILABLE",
            "status": status,
            "evidence": "test probe evidence for %s" % name,
        }
    return matrix


def _get_record(report: dict, check_id: str) -> dict:
    for record in report["checks"]:
        if record["check_id"] == check_id:
            return record
    raise AssertionError("no check record for %s" % check_id)


def _run_qa(report_matrix: dict, **qa_kwargs) -> dict:
    with mock.patch.object(pipeline_mod, "capability_matrix", return_value=report_matrix):
        return pipeline_mod.run_full_qa(
            str(OUT_DOCX),
            template_path=str(REF_DOCX),
            task_id="TASK_W2_ENV",
            task_mode="GENERATE",
            gate_mode="STRICT",
            **qa_kwargs,
        )


class EnvironmentConfigTests(unittest.TestCase):
    def test_config_declares_every_capability_with_requiredness(self) -> None:
        config = load_environment_capabilities()
        self.assertEqual(config["schema_version"], "4.0")
        self.assertIn(config["source"], ("yaml", "json", "built_in_defaults"))
        capabilities = config["capabilities"]
        for name in REQUIRED_CAPABILITIES:
            self.assertIn(name, capabilities)
            self.assertIs(capabilities[name]["required"], True, name)
        for name in OPTIONAL_CAPABILITIES:
            self.assertIn(name, capabilities)
            self.assertIs(capabilities[name]["required"], False, name)

    def test_json_mirror_is_the_machine_readable_source_of_the_yaml(self) -> None:
        self.assertTrue(JSON_CONFIG.is_file())
        with open(JSON_CONFIG, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["schema_version"], "4.0")
        self.assertEqual(
            set(payload["capabilities"]),
            set(load_environment_capabilities()["capabilities"]),
        )
        try:
            import yaml  # type: ignore
        except Exception:
            # PyYAML is optional: the loader must then use the JSON mirror.
            self.assertEqual(load_environment_capabilities()["source"], "json")
        else:
            with open(YAML_CONFIG, "r", encoding="utf-8") as handle:
                declared = yaml.safe_load(handle)
            self.assertEqual(declared["schema_version"], payload["schema_version"])
            self.assertEqual(set(declared["capabilities"]), set(payload["capabilities"]))
            for name, entry in payload["capabilities"].items():
                self.assertEqual(
                    bool(declared["capabilities"][name]["required"]),
                    bool(entry["required"]),
                    name,
                )


class EnvironmentDetectionTests(unittest.TestCase):
    def test_matrix_entries_are_well_formed_and_consistent(self) -> None:
        matrix = capability_matrix()
        self.assertTrue(set(REQUIRED_CAPABILITIES) <= set(matrix))
        for name, entry in matrix.items():
            self.assertEqual(set(entry), {"required", "available", "status", "evidence"}, name)
            self.assertIsInstance(entry["required"], bool, name)
            self.assertIsInstance(entry["available"], bool, name)
            self.assertIn(entry["status"], ("AVAILABLE", "UNAVAILABLE", "UNVERIFIED"), name)
            self.assertTrue(entry["evidence"], "evidence must never be empty: %s" % name)
            # An entry is available only when the probe said AVAILABLE.
            self.assertEqual(entry["available"], entry["status"] == "AVAILABLE", name)

    def test_missing_modules_are_never_reported_available(self) -> None:
        real_import = importlib.import_module

        def fake_import(name: str):
            if name in ("fitz", "docx"):
                raise ModuleNotFoundError("No module named %r" % name)
            return real_import(name)

        unavailable_backend = {"name": "none", "executable": None}
        with mock.patch.object(env_mod, "_try_import", side_effect=fake_import), mock.patch(
            "engine.pdf_backend.find_pdf_backend", return_value=unavailable_backend
        ), mock.patch(
            "engine.ocr_engine.detect_ocr_backend",
            return_value={"name": "none", "reader": None, "reason": "OCR_UNAVAILABLE"},
        ), mock.patch(
            "engine.chart_render.backend_status",
            return_value={
                "available": False,
                "reason": "RENDER_BACKEND_UNAVAILABLE",
                "detail": "No module named 'matplotlib'",
                "cjk_font": None,
            },
        ):
            detected = detect_environment()
            matrix = capability_matrix()
            self.assertEqual(set(detected), set(matrix))
            for name, entry in matrix.items():
                self.assertFalse(entry["available"], name)
                self.assertNotEqual(entry["status"], "AVAILABLE", name)
            self.assertFalse(required_capabilities_ok())
            self.assertEqual(sorted(missing_capabilities()), sorted(REQUIRED_CAPABILITIES))

    def test_optional_gap_does_not_fail_required_capabilities(self) -> None:
        real_import = importlib.import_module

        def fake_import(name: str):
            if name == "fitz":
                raise ModuleNotFoundError("No module named 'fitz'")
            return real_import(name)

        with mock.patch.object(env_mod, "_try_import", side_effect=fake_import), mock.patch(
            "engine.pdf_backend.find_pdf_backend",
            return_value={"name": "wps", "executable": sys.executable},
        ), mock.patch(
            "engine.ocr_engine.detect_ocr_backend",
            return_value={"name": "none", "reader": None, "reason": "OCR_UNAVAILABLE"},
        ), mock.patch(
            "engine.chart_render.backend_status",
            return_value={
                "available": False,
                "reason": "RENDER_BACKEND_UNAVAILABLE",
                "detail": "no matplotlib",
                "cjk_font": None,
            },
        ):
            matrix = capability_matrix()
            self.assertFalse(matrix["pixel_visual_diff"]["available"])
            self.assertFalse(matrix["ocr"]["available"])
            self.assertFalse(matrix["chart_render"]["available"])
            self.assertTrue(matrix["wps_pdf_render"]["available"])
            self.assertTrue(matrix["pdf_page_analysis"]["available"])
            self.assertTrue(required_capabilities_ok())
            self.assertEqual(missing_capabilities(), [])

    def test_required_gap_is_named_by_missing_capabilities(self) -> None:
        real_detect = env_mod.detect_environment
        detection = real_detect()
        detection["pdf_page_analysis"] = {
            "probe": "pymupdf_import_or_wps_pdfinfo",
            "available": False,
            "status": "UNAVAILABLE",
            "evidence": "NO_PDF_PAGE_COUNT_BACKEND",
        }
        with mock.patch.object(env_mod, "detect_environment", return_value=detection):
            matrix = capability_matrix()
            self.assertFalse(matrix["pdf_page_analysis"]["available"])
            self.assertFalse(required_capabilities_ok())
            self.assertIn("pdf_page_analysis", missing_capabilities())
            self.assertNotIn("ocr", missing_capabilities())

    def test_contradictory_detection_is_downgraded_not_trusted(self) -> None:
        config = {
            "schema_version": "4.0",
            "source": "test",
            "capabilities": {"docx_parse": {"required": True}},
        }
        detection = {
            "docx_parse": {
                "probe": "python_docx_import",
                "available": True,
                "status": "UNAVAILABLE",
                "evidence": "import raised",
            }
        }
        with mock.patch.object(env_mod, "load_environment_capabilities", return_value=config), mock.patch.object(
            env_mod, "detect_environment", return_value=detection
        ):
            matrix = capability_matrix()
        self.assertFalse(matrix["docx_parse"]["available"])
        self.assertNotEqual(matrix["docx_parse"]["status"], "AVAILABLE")

    def test_capability_without_a_probe_is_unverified(self) -> None:
        config = {
            "schema_version": "4.0",
            "source": "test",
            "capabilities": {"mystery_capability": {"required": True}},
        }
        with mock.patch.object(env_mod, "load_environment_capabilities", return_value=config), mock.patch.object(
            env_mod, "detect_environment", return_value={}
        ):
            matrix = capability_matrix()
            self.assertIn("mystery_capability", missing_capabilities())
        entry = matrix["mystery_capability"]
        self.assertTrue(entry["required"])
        self.assertFalse(entry["available"])
        self.assertEqual(entry["status"], "UNVERIFIED")

    def test_detect_environment_covers_every_configured_capability(self) -> None:
        detected = detect_environment()
        configured = set(load_environment_capabilities()["capabilities"])
        self.assertTrue(configured <= set(detected))


class PipelineCapabilityIntegrationTests(unittest.TestCase):
    def test_required_capability_gap_keeps_visual_check_unverified(self) -> None:
        matrix = _synthetic_matrix()
        matrix["wps_pdf_render"] = {
            "required": True,
            "available": False,
            "status": "UNAVAILABLE",
            "evidence": "NO_PDF_BACKEND",
        }
        matrix["pdf_page_analysis"] = {
            "required": True,
            "available": False,
            "status": "UNAVAILABLE",
            "evidence": "NO_PDF_PAGE_COUNT_BACKEND",
        }
        report = _run_qa(matrix)

        self.assertNotEqual(report["status"], "PASSED")
        self.assertTrue(validate_qa_report(report)["passed"], report.get("coverage_gaps"))
        record = _get_record(report, "VISUAL_PAGE_COUNT")
        self.assertEqual(record["status"], "UNVERIFIED")
        self.assertIn("wps_pdf_render", record["evidence"]["detail"])
        self.assertIn("pdf_page_analysis", record["evidence"]["detail"])

    def test_docx_parse_gap_marks_docx_dependent_checks_unverified(self) -> None:
        matrix = _synthetic_matrix()
        matrix["docx_parse"] = {
            "required": True,
            "available": False,
            "status": "UNAVAILABLE",
            "evidence": "python-docx import failed",
        }
        report = _run_qa(matrix)

        self.assertNotEqual(report["status"], "PASSED")
        self.assertTrue(validate_qa_report(report)["passed"])
        for check_id in ("PACKAGE", "FORMAT", "FIDELITY", "CONTENT", "VISUAL_PAGE_COUNT"):
            record = _get_record(report, check_id)
            self.assertEqual(record["status"], "UNVERIFIED", check_id)
            self.assertIn("docx_parse", record["evidence"]["detail"], check_id)

    def test_optional_gaps_do_not_demote_verified_page_counts(self) -> None:
        visual = {
            "passed": True,
            "issues": [],
            "structured_issues": [],
            "coverage_gaps": [
                "PDF_PAGE_DIFF_UNAVAILABLE",
                "FONT_AVAILABILITY_UNVERIFIED",
                "LAYOUT_FINGERPRINT_UNAVAILABLE",
            ],
            "pdf_rendered": True,
            "pdf_backend": "wps",
            "page_count_available": True,
        }
        matrix = _synthetic_matrix(required_status="AVAILABLE", optional_status="UNAVAILABLE")
        with mock.patch.object(pipeline_mod, "run_visual_layout_qa", return_value=visual), mock.patch.object(
            pipeline_mod, "capability_matrix", return_value=matrix
        ):
            report = pipeline_mod.run_full_qa(
                str(OUT_DOCX),
                template_path=str(REF_DOCX),
                task_id="TASK_W2_ENV_OPTIONAL",
                task_mode="GENERATE",
                gate_mode="STRICT",
            )

        record = _get_record(report, "VISUAL_PAGE_COUNT")
        self.assertEqual(record["status"], "PASSED")
        detail = record["evidence"]["detail"].lower()
        self.assertIn("backend", detail)
        self.assertIn("page count", detail)
        self.assertIn("optional unavailable: pixel_visual_diff, ocr", detail)
        self.assertNotIn("PDF_PAGE_DIFF_UNAVAILABLE", report["coverage_gaps"])
        self.assertNotIn("OCR_UNAVAILABLE", report["coverage_gaps"])
        self.assertTrue(validate_qa_report(report)["passed"])


if __name__ == "__main__":
    unittest.main()
