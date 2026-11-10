# -*- coding: utf-8 -*-
"""Live field/SDT edits keep package structure and control identity intact."""

from __future__ import annotations

import docx
import pytest
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

from engine.officecli_runtime import OfficecliError, OfficecliRuntime


def _require_officecli() -> None:
    try:
        OfficecliRuntime().preflight()
    except OfficecliError as exc:
        pytest.skip("officecli is not runnable here: {}".format(exc))


def _field_paragraph() -> str:
    return (
        '<w:p %s><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        "<w:r><w:instrText xml:space=\"preserve\"> PAGE </w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>1</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>' % nsdecls("w")
    )


def _fresh_line_start_runs(paragraph) -> int:
    return sum(
        1
        for node in paragraph._p.findall(qn("w:r"))
        if node.find(qn("w:fldChar")) is not None
    )


def test_field_instruction_and_cached_result_round_trip(tmp_path):
    _require_officecli()
    path = tmp_path / "field.docx"
    document = docx.Document()
    body = document.element.body
    body.insert(len(body) - 1, parse_xml(_field_paragraph()))
    document.save(str(path))
    before = docx.Document(str(path))
    assert _fresh_line_start_runs(before.paragraphs[0]) == 3

    runtime = OfficecliRuntime()
    try:
        initial = runtime.get(str(path), "/field[1]")
        assert initial["format"]["fieldType"] == "page"
        runtime.set_props(
            str(path),
            "/field[1]",
            {"instruction": r"PAGE \* MERGEFORMAT", "text": "7"},
        )
        updated = runtime.get(str(path), "/field[1]")
        assert updated["format"]["instruction"] == r"PAGE \* MERGEFORMAT"
        assert updated["format"]["fieldType"] == "page"
        assert updated["text"] == "7"
        assert runtime.validate(str(path))["success"] is True
    finally:
        runtime.close(str(path))

    after = docx.Document(str(path))
    assert _fresh_line_start_runs(after.paragraphs[0]) == 3
    assert len(after.paragraphs) == 1
    assert after.paragraphs[0].text  # cached result is still a text run


def test_sdt_tag_edit_preserves_id_and_embedded_field(tmp_path):
    _require_officecli()
    path = tmp_path / "sdt.docx"
    document = docx.Document()
    document.add_paragraph("Body")
    footer = document.sections[0].footer
    footer._element.append(
        parse_xml(
            '<w:sdt %s><w:sdtPr><w:id w:val="4242"/></w:sdtPr>'
            "<w:sdtContent>%s</w:sdtContent></w:sdt>"
            % (nsdecls("w"), _field_paragraph())
        )
    )
    document.save(str(path))

    runtime = OfficecliRuntime()
    try:
        initial = runtime.get(str(path), "/footer[1]/sdt[1]")
        assert initial["format"]["id"] == 4242
        runtime.set_props(str(path), "/footer[1]/sdt[1]", {"tag": "audit_tag", "alias": "Audit"})
        updated = runtime.get(str(path), "/footer[1]/sdt[1]")
        assert updated["format"]["id"] == 4242
        assert updated["format"]["tag"] == "audit_tag"
        assert updated["format"]["alias"] == "Audit"
        fields = runtime.query(str(path), "field")
        assert len(fields) == 1
        assert runtime.validate(str(path))["success"] is True
    finally:
        runtime.close(str(path))

    after = docx.Document(str(path))
    sdts = list(after.sections[0].footer._element.iter(qn("w:sdt")))
    assert len(sdts) == 1
    assert sdts[0].find(qn("w:sdtPr")).find(qn("w:id")).get(qn("w:val")) == "4242"
    assert next(iter(after.sections[0].footer._element.iter(qn("w:instrText")))).text.strip() == "PAGE"
