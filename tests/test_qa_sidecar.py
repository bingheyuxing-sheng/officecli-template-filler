# -*- coding: utf-8 -*-
"""QAReport sidecar writing and reuse validation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from document_engine.fill_executor import _write_qa_report_sidecar
from scripts.run_qa import _load_reuse_candidate


ROOT = Path(__file__).resolve().parents[1]


def _write_sidecar(path: Path, report: dict, output_sha256: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "output_sha256": output_sha256,
                "qa_report": report,
            }
        ),
        encoding="utf-8",
    )


def _reuse_args(**overrides):
    values = {
        "task_mode": "GENERATE",
        "reference": "",
        "profile": "auto",
        "review": False,
        "ocr": False,
        "no_content_qa": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_sidecar_rebases_staged_paths_and_records_output_hash(
    tmp_path: Path, qa_report, sha256_path
):
    staged = tmp_path / "staged.docx"
    final = tmp_path / "out.docx"
    staged.write_bytes(b"staged")
    final.write_bytes(b"final")
    sidecar = tmp_path / "qa.json"
    report = qa_report()
    report["checks"][0]["evidence"]["artifact_path"] = str(staged)

    _write_qa_report_sidecar(
        str(sidecar),
        report,
        str(staged),
        str(final),
        sha256_path(final),
        "TASK_TEST_0001",
        "STANDARD",
        "GENERATE",
    )

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["output_sha256"] == sha256_path(final)
    assert payload["qa_report"]["checks"][0]["evidence"]["artifact_path"] == str(final)
    assert not (tmp_path / "qa.json.tmp").exists()


def test_sidecar_refuses_to_overwrite_output_or_template(
    tmp_path: Path, qa_report, sha256_path
):
    staged = tmp_path / "staged.docx"
    final = tmp_path / "out.docx"
    template = tmp_path / "template.docx"
    staged.write_bytes(b"staged")
    final.write_bytes(b"final")
    template.write_bytes(b"template")

    with pytest.raises(ValueError, match="must not overwrite"):
        _write_qa_report_sidecar(
            str(final),
            qa_report(),
            str(staged),
            str(final),
            sha256_path(final),
            "TASK_TEST_0001",
            "STANDARD",
            "GENERATE",
        )

    with pytest.raises(ValueError, match="must not overwrite"):
        _write_qa_report_sidecar(
            str(template),
            qa_report(),
            str(staged),
            str(final),
            sha256_path(final),
            "TASK_TEST_0001",
            "STANDARD",
            "GENERATE",
            protected_paths=[str(template)],
        )


def test_reuse_candidate_accepts_matching_report(tmp_path: Path, qa_report, sha256_path):
    final = tmp_path / "out.docx"
    final.write_bytes(b"final")
    sidecar = tmp_path / "qa.json"
    _write_sidecar(sidecar, qa_report(), sha256_path(final))

    report, reason = _load_reuse_candidate(
        str(sidecar), str(final), _reuse_args()
    )

    assert report is not None
    assert reason == ""


def test_reuse_candidate_rejects_hash_mismatch(tmp_path: Path, qa_report):
    final = tmp_path / "out.docx"
    final.write_bytes(b"final")
    sidecar = tmp_path / "qa.json"
    _write_sidecar(sidecar, qa_report(), "0" * 64)

    report, reason = _load_reuse_candidate(
        str(sidecar), str(final), _reuse_args()
    )

    assert report is None
    assert "hash differs" in reason


def test_reuse_candidate_rejects_invalid_report(tmp_path: Path, qa_report, sha256_path):
    final = tmp_path / "out.docx"
    final.write_bytes(b"final")
    sidecar = tmp_path / "qa.json"
    invalid = qa_report(status="PASSED", coverage_gaps=["VISUAL_PAGE_COUNT"])
    _write_sidecar(sidecar, invalid, sha256_path(final))

    report, reason = _load_reuse_candidate(
        str(sidecar), str(final), _reuse_args()
    )

    assert report is None
    assert "stored QA report is invalid" in reason


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"reference": "template.docx"}, "explicit reference"),
        ({"profile": "replica"}, "explicit profile"),
        ({"review": True}, "extra or disabled checks"),
        ({"ocr": True}, "extra or disabled checks"),
        ({"no_content_qa": True}, "extra or disabled checks"),
        ({"task_mode": "REVIEW"}, "task mode differs"),
    ],
)
def test_reuse_candidate_falls_back_for_changed_request(
    tmp_path: Path, qa_report, sha256_path, overrides, expected
):
    final = tmp_path / "out.docx"
    final.write_bytes(b"final")
    sidecar = tmp_path / "qa.json"
    _write_sidecar(sidecar, qa_report(), sha256_path(final))

    report, reason = _load_reuse_candidate(
        str(sidecar), str(final), _reuse_args(**overrides)
    )

    assert report is None
    assert expected in reason


def test_legacy_data_path_rejects_qa_report(tmp_path: Path, make_template):
    template = make_template(tmp_path / "template.docx")
    data = tmp_path / "data.json"
    data.write_text('{"tokens": {}}', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_document.py"),
            "--template",
            str(template),
            "--data",
            str(data),
            "--out",
            str(tmp_path / "out.docx"),
            "--qa-report",
            str(tmp_path / "qa.json"),
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=str(ROOT),
    )

    assert result.returncode == 2
    assert "--qa-report requires --plan" in result.stderr
