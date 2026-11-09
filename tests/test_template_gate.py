# -*- coding: utf-8 -*-
"""Template gate HMAC record and fast-path invariants."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from template_gate import GateStore, validate_gate
from template_gate import validator as validator_module


def _confirmed_record(tmp_path: Path, make_template, make_spec, make_analysis):
    template = make_template(tmp_path / "template.docx")
    spec = make_spec(_sha256(template))
    analysis = make_analysis(template, spec)
    gate_home = tmp_path / "gates"
    store = GateStore(str(gate_home))
    record = store.confirm(
        analysis,
        {"quality": {"unresolved_blocking": 0}, "report_digest": "f" * 64},
        user_statement="confirmed",
    )
    return template, spec, record, store, gate_home


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_fast_path_skips_evidence_and_fingerprint_rebuild(
    tmp_path, monkeypatch, make_template, make_spec, make_analysis
):
    template, spec, record, _store, gate_home = _confirmed_record(
        tmp_path, make_template, make_spec, make_analysis
    )
    monkeypatch.setattr(
        validator_module,
        "build_document_spec_from_path",
        lambda path: spec,
    )
    monkeypatch.setattr(
        validator_module,
        "build_analysis",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("fast path must not rebuild analysis")
        ),
    )

    result = validate_gate(
        str(template),
        "GENERATE",
        gate_record=record,
        gate_home=str(gate_home),
    )

    assert result["passed"] is True
    assert any(item["name"] == "execution_fast_path" for item in result["checks"])


def test_tampered_record_fails_signature_verification(
    tmp_path, make_template, make_spec, make_analysis
):
    template, spec, record, _store, gate_home = _confirmed_record(
        tmp_path, make_template, make_spec, make_analysis
    )
    record_path = next(Path(gate_home).glob("gate_*.json"))
    tampered = dict(record)
    tampered["spec_digest"] = "0" * 64
    record_path.write_text(json.dumps(tampered), encoding="utf-8")

    result = validate_gate(
        str(template),
        "GENERATE",
        gate_record=record["gate_id"],
        spec=spec,
        gate_home=str(gate_home),
    )

    assert result["passed"] is False
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "confirmation_token" in failed


def test_template_change_stales_the_confirmed_record(
    tmp_path, make_template, make_spec, make_analysis
):
    template, spec, record, _store, gate_home = _confirmed_record(
        tmp_path, make_template, make_spec, make_analysis
    )
    make_template(template, text="Replacement Proposal")

    result = validate_gate(
        str(template),
        "GENERATE",
        gate_record=record,
        spec=spec,
        gate_home=str(gate_home),
    )

    assert result["passed"] is False
    assert result["code"] == "TEMPLATE_GATE_STALE"
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "template_sha256" in failed
    assert "spec_template_sha256" in failed


def test_expired_record_is_rejected(tmp_path, make_template, make_spec, make_analysis):
    template, spec, record, store, gate_home = _confirmed_record(
        tmp_path, make_template, make_spec, make_analysis
    )
    record["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat()
    store.save(record)
    record = store.load(record["gate_id"]) or record

    result = validate_gate(
        str(template),
        "GENERATE",
        gate_record=record,
        spec=spec,
        gate_home=str(gate_home),
    )

    assert result["passed"] is False
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "not_expired" in failed


def test_policy_version_change_invalidates_the_record(
    tmp_path, monkeypatch, make_template, make_spec, make_analysis
):
    template, spec, record, _store, gate_home = _confirmed_record(
        tmp_path, make_template, make_spec, make_analysis
    )
    monkeypatch.setattr(
        validator_module,
        "load_policy",
        lambda: {"version": "9.9", "task_types": {}},
    )

    result = validate_gate(
        str(template),
        "GENERATE",
        gate_record=record,
        spec=spec,
        gate_home=str(gate_home),
    )

    assert result["passed"] is False
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "policy_version" in failed


def test_spec_digest_change_is_rejected(
    tmp_path, make_template, make_spec, make_analysis
):
    template, spec, record, _store, gate_home = _confirmed_record(
        tmp_path, make_template, make_spec, make_analysis
    )
    changed_spec = dict(spec)
    changed_spec["schema_version"] = "3.0"

    result = validate_gate(
        str(template),
        "GENERATE",
        gate_record=record,
        spec=changed_spec,
        gate_home=str(gate_home),
    )

    assert result["passed"] is False
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "spec_digest" in failed
    assert "spec_schema_version" in failed


def test_missing_record_is_reported_as_required(tmp_path, make_template):
    template = make_template(tmp_path / "template.docx")

    result = validate_gate(
        str(template),
        "GENERATE",
        gate_home=str(tmp_path / "empty-gates"),
    )

    assert result["passed"] is False
    assert result["code"] == "TEMPLATE_GATE_REQUIRED"
