# -*- coding: utf-8 -*-
"""Spec/analysis cache correctness and invalidation tests."""

from __future__ import annotations

import json
from pathlib import Path

from engine import analysis_cache
from template_gate import analyzer as analyzer_module
from template_gate.analyzer import build_analysis
from template_intelligence import spec_builder
from template_intelligence.spec_builder import build_document_spec_from_path


def test_cache_key_is_stable_for_dict_order_and_changes_with_versions():
    first = analysis_cache.key_from_parts("spec", "sha", {"a": 1, "b": 2})
    second = analysis_cache.key_from_parts("spec", "sha", {"b": 2, "a": 1})
    changed = analysis_cache.key_from_parts("spec", "sha", {"a": 1, "b": 3})

    assert first == second
    assert first != changed


def test_cache_enabled_respects_disable_environment(monkeypatch):
    monkeypatch.setenv("OFFICECLI_DISABLE_CACHE", "1")
    assert analysis_cache.cache_enabled() is False
    monkeypatch.setenv("OFFICECLI_DISABLE_CACHE", "yes")
    assert analysis_cache.cache_enabled() is False
    monkeypatch.setenv("OFFICECLI_DISABLE_CACHE", "0")
    assert analysis_cache.cache_enabled() is True


def test_read_json_ignores_invalid_payloads(tmp_path):
    key = "deadbeef"
    path = Path(analysis_cache.cache_path("spec", key, ".json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    assert analysis_cache.read_json("spec", key) is None

    path.write_text("[]", encoding="utf-8")
    assert analysis_cache.read_json("spec", key) is None


def test_write_json_leaves_no_partial_files(tmp_path):
    analysis_cache.write_json("spec", "abc", {"ok": True})

    path = Path(analysis_cache.cache_path("spec", "abc", ".json"))
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}
    assert list(path.parent.glob(".tmp-*")) == []


def test_spec_cache_hit_avoids_a_second_parse(tmp_path, monkeypatch, make_template):
    template = make_template(tmp_path / "template.docx")
    first = build_document_spec_from_path(str(template))
    assert first["errors"] == []
    cache_files = list((tmp_path / "cache" / "spec").glob("*.json"))
    assert cache_files

    monkeypatch.setattr(
        spec_builder.docx,
        "Document",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("spec cache miss")
        ),
    )
    second = build_document_spec_from_path(str(template))

    assert second["template"]["template_sha256"] == first["template"]["template_sha256"]


def test_spec_cache_invalidates_when_template_changes(
    tmp_path, make_template
):
    template = make_template(tmp_path / "template.docx", text="First Proposal")
    first = build_document_spec_from_path(str(template))
    make_template(template, text="Second Proposal")
    second = build_document_spec_from_path(str(template))

    assert first["template"]["template_sha256"] != second["template"]["template_sha256"]


def test_disabled_cache_parses_every_time(tmp_path, monkeypatch, make_template):
    monkeypatch.setenv("OFFICECLI_DISABLE_CACHE", "1")
    template = make_template(tmp_path / "template.docx")
    calls = {"count": 0}
    original = spec_builder.docx.Document

    def counting_document(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(spec_builder.docx, "Document", counting_document)
    build_document_spec_from_path(str(template))
    build_document_spec_from_path(str(template))

    assert calls["count"] == 2
    assert list((tmp_path / "cache" / "spec").glob("*.json")) == []


def test_analysis_cache_hit_avoids_a_second_parse(tmp_path, monkeypatch, make_template):
    template = make_template(tmp_path / "template.docx")
    spec = build_document_spec_from_path(str(template))
    first = build_analysis(str(template), "GENERATE", spec=spec)
    assert list((tmp_path / "cache" / "analysis").glob("*.json"))

    monkeypatch.setattr(
        analyzer_module.docx,
        "Document",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("analysis cache miss")
        ),
    )
    second = build_analysis(str(template), "GENERATE", spec=spec)

    assert second["analysis_id"] == first["analysis_id"]
    assert second["evidence_digest"] == first["evidence_digest"]


def test_policy_change_creates_a_new_analysis_cache_key(
    tmp_path, monkeypatch, make_template
):
    template = make_template(tmp_path / "template.docx")
    spec = build_document_spec_from_path(str(template))
    calls = {"count": 0}
    original = analyzer_module.docx.Document
    original_policy = analyzer_module.load_policy()

    def counting_document(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(analyzer_module.docx, "Document", counting_document)
    build_analysis(str(template), "GENERATE", spec=spec)
    assert calls["count"] == 1

    changed_policy = dict(original_policy)
    changed_policy["version"] = "9.9"
    monkeypatch.setattr(analyzer_module, "load_policy", lambda: changed_policy)
    build_analysis(str(template), "GENERATE", spec=spec)

    assert calls["count"] == 2
