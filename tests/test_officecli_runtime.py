# -*- coding: utf-8 -*-
"""OfficeCLI runtime contract: path translation, envelopes and a live probe."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import docx
import pytest

from engine.officecli_runtime import (
    OfficecliError,
    OfficecliRuntime,
    OfficecliUnavailable,
    UnsupportedLocation,
    build_story_map,
    location_to_path,
)


# ---------------------------------------------------------------------------
# path translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("body.p[0]", "/body/p[1]"),
        ("body.tbl[0]", "/body/tbl[1]"),
        ("body.tbl[1].r[2].c[3].p[0]", "/body/tbl[2]/tr[3]/tc[4]/p[1]"),
        ("/body/p[4]/r[2]", "/body/p[4]/r[2]"),
    ],
)
def test_body_locations_translate_to_officecli_paths(location, expected):
    assert location_to_path(location) == expected


def test_section_header_locations_use_the_section_crosswalk():
    story_map = {
        "sec[0].header": "/header[1]",
        "sec[0].first_page_footer": "/footer[2]",
    }
    assert location_to_path("sec[0].header.p[2]", story_map) == "/header[1]/p[3]"
    assert (
        location_to_path("sec[0].first_page_footer.tbl[0].r[1].c[0].p[0]", story_map)
        == "/footer[2]/tbl[1]/tr[2]/tc[1]/p[1]"
    )


def test_linked_section_story_without_a_part_is_refused():
    with pytest.raises(UnsupportedLocation) as excinfo:
        location_to_path("sec[1].header.p[0]", {"sec[0].header": "/header[1]"})
    assert excinfo.value.code == "WRITER_LOCATION_UNSUPPORTED"


def test_sdt_locations_translate_to_officecli_paths():
    assert location_to_path("body.sdt[0].p[0]") == "/body/sdt[1]/p[1]"
    assert (
        location_to_path("body.sdt[0].tbl[1].r[0].c[2].p[0]")
        == "/body/sdt[1]/tbl[2]/tr[1]/tc[3]/p[1]"
    )


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("footnotes.footnote[0].p[0]", "/footnotes/footnote[1]/p[1]"),
        ("endnotes.endnote[2].p[1]", "/endnotes/endnote[3]/p[2]"),
        ("comments.comment[0]", "/comments/comment[1]"),
        ("comments.p[3]", "/comments/comment[4]"),
    ],
)
def test_note_and_comment_locations(location, expected):
    assert location_to_path(location) == expected


@pytest.mark.parametrize(
    "location",
    [
        "",
        "textbox.p[0]",
        "footnotes.p[0]",
        "comments.comment[0].p[0]",
    ],
)
def test_unaddressable_locations_are_refused(location):
    with pytest.raises(UnsupportedLocation):
        location_to_path(location)


def test_build_story_map_matches_logical_parts(monkeypatch):
    class _FakeRuntime:
        def close(self, file_path):
            return None

    def _hf(partname):
        return SimpleNamespace(part=SimpleNamespace(partname=partname))

    section = SimpleNamespace(
        header=_hf("/word/header1.xml"),
        first_page_header=None,
        even_page_header=None,
        footer=_hf("/word/footer2.xml"),
        first_page_footer=None,
        even_page_footer=None,
    )
    monkeypatch.setattr(
        docx, "Document", lambda _path: SimpleNamespace(sections=[section])
    )
    import engine.officecli_runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_part_address_map",
        lambda *args, **kwargs: {
            "/word/header1.xml": ["/header[2]"],
            "/word/footer2.xml": ["/footer[1]"],
        },
    )
    mapping = build_story_map("ignored.docx", runtime=_FakeRuntime())
    assert mapping == {
        "sec[0].header": "/header[2]",
        "sec[0].footer": "/footer[1]",
    }


# ---------------------------------------------------------------------------
# envelope handling
# ---------------------------------------------------------------------------


def _completed(payload, returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=["officecli"],
        returncode=returncode,
        stdout=json.dumps(payload) if not isinstance(payload, str) else payload,
        stderr=stderr,
    )


def test_get_returns_the_first_result(monkeypatch):
    runtime = OfficecliRuntime(binary="officecli")
    monkeypatch.setattr(
        runtime,
        "_invoke",
        lambda arguments, timeout=None: _completed(
            {"success": True, "data": {"results": [{"path": "/body/p[1]", "text": "Hi"}]}}
        ),
    )
    assert runtime.get("doc.docx", "/body/p[1]")["text"] == "Hi"


def test_failed_envelope_raises_with_the_officecli_code(monkeypatch):
    runtime = OfficecliRuntime(binary="officecli")
    monkeypatch.setattr(
        runtime,
        "_invoke",
        lambda arguments, timeout=None: _completed(
            {
                "success": False,
                "data": {
                    "results": [
                        {"success": False, "code": "path_not_found", "error": "missing"}
                    ]
                },
            },
            returncode=1,
        ),
    )
    with pytest.raises(OfficecliError) as excinfo:
        runtime.batch("doc.docx", [{"command": "set", "path": "/body/p[9]"}])
    assert excinfo.value.code == "path_not_found"
    assert "missing" in str(excinfo.value)


def test_caveat_exit_code_with_success_is_accepted(monkeypatch):
    runtime = OfficecliRuntime(binary="officecli")
    monkeypatch.setattr(
        runtime,
        "_invoke",
        lambda arguments, timeout=None: _completed(
            {"success": True, "warnings": ["one prop ignored"], "data": {"results": []}},
            returncode=2,
        ),
    )
    payload = runtime.batch("doc.docx", [])
    assert payload["success"] is True
    assert payload["warnings"] == ["one prop ignored"]


def test_missing_binary_override_is_not_silently_ignored(monkeypatch):
    monkeypatch.setenv("OFFICECLI_BINARY", str(Path("missing") / "officecli.exe"))
    runtime = OfficecliRuntime()
    with pytest.raises(OfficecliUnavailable):
        runtime.ensure()


def test_close_is_safe_when_the_binary_override_is_invalid(monkeypatch):
    monkeypatch.setenv("OFFICECLI_BINARY", str(Path("missing") / "officecli.exe"))
    OfficecliRuntime().close("doc.docx")


def test_live_failed_batch_leaves_the_file_byte_identical(tmp_path):
    runtime = OfficecliRuntime()
    try:
        runtime.preflight()
    except OfficecliError as exc:
        pytest.skip("officecli is not runnable here: {}".format(exc))

    path = tmp_path / "atomic.docx"
    document = docx.Document()
    document.add_paragraph("Hello")
    document.save(str(path))
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(OfficecliError):
        runtime.batch(
            str(path),
            [
                {"command": "set", "path": "/body/p[1]", "props": {"find": "Hello", "replace": "Changed"}},
                {"command": "set", "path": "/body/p[99]", "props": {"text": "x"}},
            ],
        )
    runtime.close(str(path))

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_validate_returns_a_schema_failure_as_a_verdict(monkeypatch):
    runtime = OfficecliRuntime(binary="officecli")
    monkeypatch.setattr(
        runtime,
        "_invoke",
        lambda arguments, timeout=None: _completed(
            {
                "success": False,
                "message": "",
                "warnings": [{"message": "[Package] a required part is missing"}],
            },
            returncode=1,
        ),
    )
    payload = runtime.validate("doc.docx")
    assert payload["success"] is False


def test_validation_report_distinguishes_failed_from_unverified(monkeypatch):
    from engine import officecli_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "is_available", lambda: True)

    class _FakeRuntime:
        def validate(self, file_path):
            return {
                "success": False,
                "message": "",
                "warnings": [{"message": "[Package] a required part is missing"}],
            }

        def close(self, file_path):
            return None

    failed = runtime_module.validation_report("doc.docx", runtime=_FakeRuntime())
    assert failed["status"] == "FAILED"
    assert failed["issues"][0]["code"] == "PACKAGE_SCHEMA_INVALID"

    monkeypatch.setattr(runtime_module, "is_available", lambda: False)
    unverified = runtime_module.validation_report("doc.docx")
    assert unverified["status"] == "UNVERIFIED"
    assert unverified["coverage_gaps"] == ["OFFICECLI_VALIDATION_UNAVAILABLE"]


# ---------------------------------------------------------------------------
# live integration (skipped when the binary cannot run in this sandbox)
# ---------------------------------------------------------------------------


def test_live_officecli_round_trip(tmp_path):
    import docx

    runtime = OfficecliRuntime()
    try:
        runtime.preflight()
    except (OfficecliUnavailable, OfficecliError) as exc:
        pytest.skip("officecli is not runnable here: {}".format(exc))

    template = tmp_path / "probe.docx"
    document = docx.Document()
    document.add_paragraph("Body {{name}}")
    document.sections[0].header.paragraphs[0].text = "Header {{h}}"
    document.save(str(template))

    try:
        paragraphs = runtime.paragraphs(str(template))
        header = next(item for item in paragraphs if item["path"] == "/header[1]/p[1]")
        assert header["text"] == "Header {{h}}"

        runtime.batch(
            str(template),
            [
                {
                    "command": "set",
                    "path": "/header[1]/p[1]",
                    "props": {"find": "{{h}}", "replace": "Quarterly"},
                }
            ],
        )
        runtime.close(str(template))
        assert runtime.get(str(template), "/header[1]/p[1]")["text"] == "Header Quarterly"
        report = runtime.validate(str(template))
        assert report.get("success") is True
    finally:
        runtime.close(str(template))
