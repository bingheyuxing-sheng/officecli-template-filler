# -*- coding: utf-8 -*-
"""CLI routing and exit-code contract for the template analyzers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import docx
import pytest

ROOT = Path(__file__).resolve().parents[1]
WORD_ANALYZER = ROOT / "scripts" / "analyze_template.py"
EXCEL_ANALYZER = ROOT / "scripts" / "analyze_excel_template.py"
GATE_CLI = ROOT / "scripts" / "template_gate.py"
INSPECT_CLI = ROOT / "scripts" / "inspect_document.py"


def _run(
    script: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _payload(run: subprocess.CompletedProcess) -> dict:
    return json.loads(run.stdout.strip())


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    book.active["A1"] = "{{project}}"
    path = tmp_path / "template.xlsx"
    book.save(path)
    return path


@pytest.fixture
def word_template(tmp_path: Path) -> Path:
    document = docx.Document()
    document.add_heading("Template", level=0)
    document.add_paragraph("Client: {{client}}")
    path = tmp_path / "template.docx"
    document.save(str(path))
    return path


def test_word_analyzer_rejects_excel_container(workbook, tmp_path):
    out = tmp_path / "analysis.json"
    run = _run(WORD_ANALYZER, str(workbook), "--out", str(out))

    assert run.returncode == 2
    assert not out.exists()
    body = _payload(run)
    assert body["error"] == "UNSUPPORTED_CONTAINER"
    assert body["input"] == str(workbook)
    assert ".docx" in body["supported"]
    assert "analyze_excel_template.py" in body["message"]


def test_word_analyzer_rejects_unknown_container(tmp_path):
    path = tmp_path / "template.pdf"
    path.write_bytes(b"%PDF-1.7")
    run = _run(WORD_ANALYZER, str(path))

    assert run.returncode == 2
    assert _payload(run)["error"] == "UNSUPPORTED_CONTAINER"


def test_word_analyzer_unreadable_docx_legacy(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip package")
    run = _run(WORD_ANALYZER, str(path))

    assert run.returncode == 2
    body = _payload(run)
    assert body["error"] == "PACKAGE_NOT_READABLE"
    assert body["input"] == str(path)
    assert body["next_action"] == "PROVIDE_VALID_DOCX_OR_DOCM"
    assert body["message"]


def test_word_analyzer_unreadable_docx_spec_v4(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip package")
    out = tmp_path / "spec.json"
    run = _run(WORD_ANALYZER, str(path), "--spec-version", "4", "--out", str(out))

    assert run.returncode == 2
    assert not out.exists()
    body = _payload(run)
    assert body["error"] == "PACKAGE_NOT_READABLE"
    assert body["next_action"] == "PROVIDE_VALID_DOCX_OR_DOCM"


def test_word_analyzer_valid_docx_exits_zero(word_template):
    run = _run(WORD_ANALYZER, str(word_template))

    assert run.returncode == 0
    body = _payload(run)
    assert body["candidate_hits_count"] >= 1


def test_word_analyzer_valid_docx_spec_v4_exits_zero(word_template):
    run = _run(WORD_ANALYZER, str(word_template), "--spec-version", "4")

    assert run.returncode == 0
    body = _payload(run)
    assert body["schema_version"] == "4.0"
    assert body["errors"] == []
    assert body["slots"]


def test_word_analyzer_json_survives_legacy_console_encoding(tmp_path):
    document = docx.Document()
    document.add_paragraph("zero\u200bwidth character")
    path = tmp_path / "zero-width.docx"
    document.save(str(path))
    env = {**os.environ, "PYTHONIOENCODING": "gbk"}

    run = _run(WORD_ANALYZER, str(path), "--spec-version", "4", env=env)

    assert run.returncode == 0
    body = _payload(run)
    assert body["schema_version"] == "4.0"


def test_inspect_document_json_survives_legacy_console_encoding(tmp_path):
    document = docx.Document()
    document.add_paragraph("zero\u200bwidth character")
    path = tmp_path / "zero-width.docx"
    document.save(str(path))
    env = {**os.environ, "PYTHONIOENCODING": "gbk"}

    run = _run(
        INSPECT_CLI,
        "--inputs",
        str(path),
        "--intent",
        "生成文档",
        env=env,
    )

    assert run.returncode == 0
    body = _payload(run)
    assert body["routing"]["task_mode"] == "GENERATE"
    assert body["specs"]


def test_excel_analyzer_accepts_workbook(workbook):
    run = _run(EXCEL_ANALYZER, str(workbook))

    assert run.returncode == 0
    body = _payload(run)
    assert body["file_path"].endswith("template.xlsx")


def test_excel_analyzer_rejects_word_container(word_template):
    run = _run(EXCEL_ANALYZER, str(word_template))

    assert run.returncode == 2
    body = _payload(run)
    assert body["error"] == "UNSUPPORTED_CONTAINER"
    assert "analyze_template.py" in body["message"]


def test_excel_analyzer_rejects_unreadable_workbook(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a zip package")
    run = _run(EXCEL_ANALYZER, str(path))

    assert run.returncode == 2
    body = _payload(run)
    assert body["error"] == "PACKAGE_NOT_READABLE"
    assert body["next_action"] == "PROVIDE_VALID_XLSX_OR_XLSM"


def test_excel_analyzer_rejects_zip_without_workbook_parts(tmp_path):
    path = tmp_path / "empty.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    run = _run(EXCEL_ANALYZER, str(path))

    assert run.returncode == 2
    body = _payload(run)
    assert body["error"] == "DOCUMENT_SPEC_BLOCKED"
    assert body["errors"][0]["code"] == "EXCEL_PARSE_FAILED"
    assert body["next_action"] == "PROVIDE_VALID_XLSX_OR_XLSM"


def test_template_gate_rejects_excel_container(workbook):
    run = _run(GATE_CLI, "analyze", "--template", str(workbook), "--task-type", "GENERATE")

    assert run.returncode == 2
    body = _payload(run)
    assert body["error"] == "UNSUPPORTED_CONTAINER"
    assert body["input"] == str(workbook)
    assert ".docx" in body["supported"]
    assert "analyze_excel_template.py" in body["message"]


def test_template_gate_rejects_mismatched_supplement(word_template, tmp_path):
    supplement = tmp_path / "supplement.json"
    supplement.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "kind": "TemplateSemanticSupplement",
                "supplement_id": "SUP_TEST_MISMATCH",
                "template_sha256": "0" * 64,
                "font_rules": [],
            }
        ),
        encoding="utf-8",
    )

    run = _run(
        GATE_CLI,
        "analyze",
        "--template",
        str(word_template),
        "--task-type",
        "GENERATE",
        "--supplement",
        str(supplement),
    )

    assert run.returncode == 2
    body = _payload(run)
    assert body["error"] == "SEMANTIC_SUPPLEMENT_INVALID"
    assert body["next_action"] == "FIX_SEMANTIC_SUPPLEMENT"
    assert "template_sha256 mismatch" in body["message"]


def test_word_analyzer_emits_one_json_document_when_spec_blocked(tmp_path):
    path = tmp_path / "empty.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/theme/theme1.xml", "<theme/>")
    run = _run(WORD_ANALYZER, str(path), "--spec-version", "4")

    assert run.returncode == 2
    body = _payload(run)
    assert body["error"] == "DOCUMENT_SPEC_BLOCKED"
    assert body["spec"]["errors"][0]["code"] == "DOCUMENT_UNREADABLE"
    assert body["next_action"] == "FIX_TEMPLATE_OR_PROVIDE_READABLE_DOCX"
