# -*- coding: utf-8 -*-
"""REVIEW/PROOFREAD execution on the OfficeCLI revision/comment substrate."""

from __future__ import annotations

import docx
import pytest

from engine.officecli_commands import (
    add_comment_command,
    paragraph_props,
    tracked_replace_command,
)
from engine.officecli_runtime import OfficecliError, OfficecliRuntime
from engine.review_engine import (
    ISO_DATE_PATTERN,
    _single_run_index,
    audit_review_integrity,
    build_proofread_plan,
    execute_review_plan,
    list_revisions,
    review_snapshot_path,
    restore_revision,
    accept_revision,
    write_review_snapshot,
)


def _require_officecli() -> None:
    try:
        OfficecliRuntime().preflight()
    except OfficecliError as exc:
        pytest.skip("officecli is not runnable here: {}".format(exc))


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-09T12:31:35Z",
        "2026-11-09T12:31:35.9573987Z",
        "2026-11-09T20:46:07+08:00",
        "2026-11-09T20:46:07.9573987+08:00",
        "2026-11-09T12:31:35",
    ],
)
def test_iso_date_pattern_accepts_officecli_timestamps(value):
    assert ISO_DATE_PATTERN.match(value)


def test_paragraph_props_map_to_officecli_keys():
    props = paragraph_props({
        "jc": "center",
        "spacing_before": "120",
        "spacing_after": "240",
        "spacing_line": "360",
        "spacing_lineRule": "auto",
        "first_line_chars": "200",
        "left_indent": "420",
    })
    assert props == {
        "align": "center",
        "spaceBefore": 120,
        "spaceAfter": 240,
        "lineSpacing": "1.5x",
        "firstLineChars": 200,
        "indent": 420,
    }


def test_single_run_index_refuses_a_run_with_two_matches():
    document = docx.Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("foo foo")
    paragraph.add_run("foo")
    assert _single_run_index(paragraph, "foo", 1) is None
    assert _single_run_index(paragraph, "foo", 3) == 2


def test_command_builders_keep_revision_and_comment_metadata():
    replace = tracked_replace_command(
        "/body/p[1]", "old", "new", author="Alice", date="2026-01-01T00:00:00Z"
    )
    assert replace["command"] == "set"
    assert replace["props"]["find"] == "old"
    assert replace["props"]["revision.author"] == "Alice"
    assert replace["props"]["revision.date"] == "2026-01-01T00:00:00Z"

    comment = add_comment_command(
        "/body/p[2]", "check", author="Bob", date="2026-01-01T00:00:00Z"
    )
    assert comment["type"] == "comment"
    assert comment["props"]["runStart"] == 0
    assert comment["props"]["author"] == "Bob"


def test_audit_accepts_the_schema_track_revisions_element(tmp_path):
    # The skill used to write a non-schema <w:trackChanges/>; Word actually stores
    # <w:trackRevisions/>. Both must satisfy the audit's "review mode is on" check.
    from engine.review_engine import enable_track_changes

    path = tmp_path / "track.docx"
    document = docx.Document()
    document.add_paragraph("Body")
    enable_track_changes(document, True)
    document.save(str(path))

    audit = audit_review_integrity(str(path))
    assert audit["track_changes_enabled"] is True
    assert "TRACK_CHANGES_DISABLED" not in audit["coverage_gaps"]


def test_live_proofread_tracked_revision_comment_and_accept(tmp_path):
    _require_officecli()
    target = tmp_path / "target.docx"
    reviewed = tmp_path / "reviewed.docx"
    accepted = tmp_path / "accepted.docx"

    document = docx.Document()
    document.add_paragraph("Hello world")
    document.add_paragraph("Second paragraph")
    document.save(str(target))

    plan = build_proofread_plan(
        str(target),
        text_revisions=[{"old_text": "world", "new_text": "earth"}],
        auto_check=False,
    )
    plan["actions"].append({
        "action_id": "manual_comment",
        "action_type": "ADD_REVIEW_COMMENT",
        "target": "body.p[1]",
        "location_id": "body.p[1]",
        "comment": "Please confirm this sentence.",
    })
    plan["summary"]["total_actions"] = len(plan["actions"])

    result = execute_review_plan(plan, str(reviewed), snapshot_path="")
    assert result["writer_backend"] == "officecli"
    assert result["tracked_text_revisions"] == 1
    assert result["comments_added"] == 1
    assert result["unresolved_actions"] == []

    revisions = list_revisions(str(reviewed), include_format=True)
    text_revisions = [item for item in revisions if item["kind"] == "text"]
    assert {item["type"] for item in text_revisions} == {"ins", "del"}
    audit = audit_review_integrity(str(reviewed))
    assert audit["passed"] is True, audit["issues"]
    assert audit["revision_count"] == 2
    assert audit["comment_count"] == 1

    # Accept one end of the pair through OfficeCLI's revision.action verb.
    revision_id = next(item["revision_id"] for item in text_revisions if item["type"] == "ins")
    accepted_result = accept_revision(str(reviewed), str(accepted), revision_id)
    assert accepted_result["status"] == "APPLIED", accepted_result
    assert revision_id not in {
        str(item["revision_id"]) for item in list_revisions(str(accepted), include_format=True)
    }


def test_live_snapshot_restore_rebuilds_a_decided_revision(tmp_path):
    _require_officecli()
    target = tmp_path / "target.docx"
    reviewed = tmp_path / "reviewed.docx"
    accepted = tmp_path / "accepted.docx"
    restored = tmp_path / "restored.docx"

    document = docx.Document()
    document.add_paragraph("Hello world")
    document.save(str(target))
    plan = build_proofread_plan(
        str(target),
        text_revisions=[{"old_text": "world", "new_text": "earth"}],
        auto_check=False,
    )
    execute_review_plan(plan, str(reviewed), snapshot_path="")
    snapshot = review_snapshot_path(str(reviewed))
    write_review_snapshot(str(reviewed), snapshot)
    revision_id = next(
        item["revision_id"]
        for item in list_revisions(str(reviewed), include_format=True)
        if item["kind"] == "text" and item["type"] == "ins"
    )
    accepted_result = accept_revision(str(reviewed), str(accepted), revision_id)
    assert accepted_result["status"] == "APPLIED"

    restored_result = restore_revision(
        str(accepted), str(restored), revision_id, snapshot_path=snapshot
    )
    assert restored_result["status"] == "RESTORED"
    assert revision_id in {
        str(item["revision_id"])
        for item in list_revisions(str(restored), include_format=True)
    }
