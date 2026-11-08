# -*- coding: utf-8 -*-
"""OfficeCLI write backend for FillPlan execution.

This module is the only place that shells out to ``officecli`` for *mutation*.
It is deliberately thin: the executor owns slot authorisation, capacity policy,
the transaction boundary and QA; officecli only applies already-authorised
``set`` commands and reports what it matched.

Verified against officecli 1.0.160:

    officecli batch <file> --input <json> --stop-on-error --json
        -> {"success": bool, "data": {"results": [...], "summary": {...}}}
        Batch is atomic: any failed item rolls the whole batch back
        (``summary.atomicRolledBack == true``) and the file stays untouched.

    officecli get <file> <path> --json
        -> {"data": {"results": [{"path": ..., "text": ...}]}}

    officecli close <file>
        -> releases the resident process; the disk write is deferred until it
        runs, so the executor must close before QA or python-docx reads the
        staged file.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_TIMEOUT = 120

_SEGMENT_RE = re.compile(r"^([a-z_]+)\[([0-9]+)\]$")


class OfficecliError(RuntimeError):
    """Raised when officecli is missing or reports a failed command."""


class OfficecliUnavailable(OfficecliError):
    """The binary is not installed or cannot report its version."""


class UnsupportedLocation(Exception):
    """The DocumentSpec location cannot be expressed as an officecli path."""


# ---------------------------------------------------------------------------
# binary discovery
# ---------------------------------------------------------------------------


def find_officecli() -> Optional[str]:
    """Return the officecli executable path, or None when it is not installed."""
    override = os.environ.get("OFFICECLI_BINARY")
    if override and os.path.isfile(override):
        return override
    for name in ("officecli", "officecli.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        os.path.expanduser(r"~\AppData\Local\OfficeCLI\officecli.exe"),
        "/usr/local/bin/officecli",
        os.path.expanduser("~/.local/bin/officecli"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def is_available() -> bool:
    return find_officecli() is not None


def version(timeout: int = 30) -> str:
    binary = find_officecli()
    if binary is None:
        raise OfficecliUnavailable("officecli is not installed")
    try:
        run = _run([binary, "--version"], timeout=timeout)
    except OSError as exc:
        raise OfficecliUnavailable("officecli could not be started: {}".format(exc)) from exc
    if run.returncode != 0:
        raise OfficecliUnavailable(
            "officecli --version failed with exit {}: {}".format(
                run.returncode, (run.stderr or "").strip()[:300]
            )
        )
    return (run.stdout or "").strip()


# ---------------------------------------------------------------------------
# location translation (DocumentSpec -> officecli DOM path)
# -------------------------------------------------------------------------

_SEGMENT_MAP = {
    "p": "p",
    "tbl": "tbl",
    "r": "tr",
    "c": "tc",
}


def location_to_path(location_id: str) -> str:
    """Translate ``body.tbl[0].r[1].c[0].p[0]`` into ``/body/tbl[1]/tr[2]/tc[1]/p[1]``.

    DocumentSpec locations are 0-based; officecli paths are 1-based. Only body
    and table stories are accepted. Textboxes, SDT containers, footnotes,
    endnotes, comments and every header/footer variant raise
    :class:`UnsupportedLocation`, because officecli also stamps
    ``w14:paraId``/``w14:textId`` into those parts and this writer only restores
    body paragraph identity.
    """
    if not isinstance(location_id, str) or not location_id:
        raise UnsupportedLocation("empty location id")

    parts = location_id.split(".")
    if parts[0] != "body":
        raise UnsupportedLocation(
            "story {!r} is not addressable by the officecli writer".format(parts[0])
        )

    path = "/body"
    rest = parts[1:]
    if not rest:
        raise UnsupportedLocation("location {!r} has no addressable segment".format(location_id))

    for segment in rest:
        match = _SEGMENT_RE.match(segment)
        if not match:
            raise UnsupportedLocation(
                "segment {!r} is not addressable (textbox/sdt/field containers)".format(segment)
            )
        name, index = match.group(1), int(match.group(2))
        mapped = _SEGMENT_MAP.get(name)
        if mapped is None:
            raise UnsupportedLocation(
                "segment {!r} has no officecli equivalent".format(segment)
            )
        path += "/{0}[{1}]".format(mapped, index + 1)

    return path


# ---------------------------------------------------------------------------
# command execution
# ---------------------------------------------------------------------------


def build_set_command(path: str, find: str, replace: str) -> Dict[str, Any]:
    """One atomic ``set`` item: literal find/replace scoped to ``path``."""
    return {
        "command": "set",
        "path": path,
        "props": {"find": find, "replace": replace},
    }


def dump(file_path: str, path: str = "/", timeout: int = DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
    """Return a replayable batch command list for one subtree.

    ``officecli dump --json`` wraps the command array in an envelope whose
    ``data`` is the array itself. The resident is closed afterwards so a read
    never leaves the file locked for the next batch or for python-docx.
    """
    binary = find_officecli()
    if binary is None:
        raise OfficecliUnavailable("officecli is not installed")
    try:
        run = _run([binary, "dump", file_path, path, "--json"], timeout=timeout)
    finally:
        close(file_path)
    payload = _parse_json(run.stdout)
    if run.returncode != 0 or not payload.get("success"):
        raise OfficecliError(
            "officecli dump {} {} failed: {}".format(
                file_path, path, _failure_message(payload, run)
            )
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise OfficecliError(
            "officecli dump {} {} returned no command list".format(file_path, path)
        )
    return [item for item in data if isinstance(item, dict)]


def run_batch(file_path: str, commands: List[Dict[str, Any]], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Apply ``commands`` atomically; raise :class:`OfficecliError` on failure.

    Returns the parsed JSON payload. A failed command makes officecli roll the
    whole batch back, so a raise here always means the staged file is unchanged.
    """
    binary = find_officecli()
    if binary is None:
        raise OfficecliUnavailable("officecli is not installed")

    handle, payload_path = tempfile.mkstemp(prefix="officecli-batch-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(commands, stream, ensure_ascii=False)
        run = _run(
            [binary, "batch", file_path, "--input", payload_path, "--json"],
            timeout=timeout,
        )
    finally:
        try:
            os.unlink(payload_path)
        except OSError:
            pass

    payload = _parse_json(run.stdout)
    if run.returncode != 0 or not payload.get("success"):
        raise OfficecliError(_failure_message(payload, run))
    return payload


def get_text(file_path: str, path: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Read back the text of one node after a batch.

    ``get`` auto-starts a resident, so this closes it again before returning:
    a read must never leave the file locked for QA or the commit.
    """
    binary = find_officecli()
    if binary is None:
        raise OfficecliUnavailable("officecli is not installed")
    try:
        run = _run([binary, "get", file_path, path, "--json"], timeout=timeout)
    finally:
        close(file_path)
    payload = _parse_json(run.stdout)
    if run.returncode != 0 or not payload.get("success"):
        raise OfficecliError(
            "officecli get {} failed: {}".format(path, _failure_message(payload, run))
        )
    results = (payload.get("data") or {}).get("results") or []
    if not results:
        raise OfficecliError("officecli get {} returned no node".format(path))
    return str(results[0].get("text") or "")


def close(file_path: str, timeout: int = 30) -> None:
    """Release the resident and flush the deferred disk write."""
    binary = find_officecli()
    if binary is None:
        return
    try:
        _run([binary, "close", file_path], timeout=timeout)
    except OSError:
        return


def validate(file_path: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """OpenXML schema validation; returns the parsed payload (``success`` flag)."""
    binary = find_officecli()
    if binary is None:
        raise OfficecliUnavailable("officecli is not installed")
    try:
        run = _run([binary, "validate", file_path, "--json"], timeout=timeout)
    finally:
        close(file_path)
    return _parse_json(run.stdout)


_W14_ATTRIBUTES = (
    "{http://schemas.microsoft.com/office/word/2010/wordml}paraId",
    "{http://schemas.microsoft.com/office/word/2010/wordml}textId",
)


def _xml_part_roots(document) -> Dict[str, Any]:
    """Map every XML part name to its root element (body, headers, notes...)."""
    roots: Dict[str, Any] = {}
    package = getattr(document.part, "package", None)
    if package is None or not hasattr(package, "iter_parts"):
        return roots
    for part in package.iter_parts():
        element = getattr(part, "element", None)
        if element is None:
            continue
        roots[str(part.partname)] = element
    return roots


def _strip_red_on_runs(document, targets: Sequence[Tuple[str, int]]) -> None:
    """Remove red placeholder colour from the runs the batch replaced.

    The v4 executor strips red placeholder colour on the anchor run of every
    authorised fill. officecli preserves the run's ``rPr`` verbatim, so the
    value would stay red and QA would (correctly) report ``RED_TEXT_RESIDUAL``.
    """
    from docx.oxml.ns import qn

    from engine.ooxml_utils import (  # noqa: PLC0415 - avoid an import cycle
        _is_red_rgb,
        iter_all_document_paragraphs_with_Wait_context,
    )

    paragraphs: Dict[str, Any] = {}
    for context in iter_all_document_paragraphs_with_Wait_context(document):
        paragraphs.setdefault(context["location_id"], context["paragraph"])
    for location_id, run_index in targets:
        paragraph = paragraphs.get(location_id)
        if paragraph is None or not isinstance(run_index, int):
            continue
        runs = paragraph._p.findall(qn("w:r"))
        if run_index < 1 or run_index > len(runs):
            continue
        r_pr = runs[run_index - 1].find(qn("w:rPr"))
        if r_pr is None:
            continue
        color = r_pr.find(qn("w:color"))
        if color is not None and _is_red_rgb(color.get(qn("w:val")) or ""):
            r_pr.remove(color)


def restore_paragraph_identity(
    template_path: str,
    staged_path: str,
    strip_red_runs: Optional[Sequence[Tuple[str, int]]] = None,
    allow_appended: bool = False,
) -> None:
    """Undo officecli's ``w14:paraId`` / ``w14:textId`` stamping in every part.

    officecli adds these Word-2010 identity attributes to every paragraph on
    save — body, headers/footers, footnotes and endnotes — even when the
    template has none. They carry no visual meaning but they are real attribute
    nodes, so the template fingerprint reads them as an unauthorised structural
    change. The writer restores the template's own values (or removes the ones
    the template never had) per part, so the only remaining delta is the
    authorised text fill. ``strip_red_runs`` additionally mirrors the executor's
    red-placeholder convention on the runs the batch replaced.
    """
    import docx
    from docx.oxml.ns import qn

    source = docx.Document(template_path)
    target = docx.Document(staged_path)
    source_roots = _xml_part_roots(source)
    target_roots = _xml_part_roots(target)

    for partname, source_root in source_roots.items():
        target_root = target_roots.get(partname)
        if target_root is None:
            raise OfficecliError(
                "officecli removed part {}; refusing to normalise".format(partname)
            )
        original = list(source_root.iter(qn("w:p")))
        staged = list(target_root.iter(qn("w:p")))
        if len(original) != len(staged):
            if not (allow_appended and len(staged) > len(original)):
                raise OfficecliError(
                    "officecli changed the paragraph count in {} ({} -> {}); "
                    "refusing to normalise".format(partname, len(original), len(staged))
                )
            # MERGE appends paragraphs. The base paragraphs keep their identity;
            # appended ones are new and legitimately carry officecli's fresh ids.
            staged = staged[:len(original)]
        for before, after in zip(original, staged, strict=False):
            for attribute in _W14_ATTRIBUTES:
                value = before.get(attribute)
                if value is None:
                    if attribute in after.attrib:
                        del after.attrib[attribute]
                else:
                    after.set(attribute, value)

    if strip_red_runs:
        _strip_red_on_runs(target, strip_red_runs)
    target.save(staged_path)


def restore_table_look(template_path: str, staged_path: str) -> None:
    """Restore the template's ``w:tblLook`` representation after a raw-set save.

    officecli collapses ``w:tblLook`` to its legacy ``w:val`` form when a batch
    contains ``raw-set``, which is a visible attribute delta even though the
    flags are equivalent. The template's exact attributes are restored on the
    first N tables (base tables precede appended ones).
    """
    import docx
    from docx.oxml.ns import qn

    source = docx.Document(template_path)
    target = docx.Document(staged_path)
    source_tables = list(source.element.body.iter(qn("w:tbl")))
    target_tables = list(target.element.body.iter(qn("w:tbl")))
    if len(target_tables) < len(source_tables):
        raise OfficecliError(
            "officecli removed tables ({} -> {}); refusing to restore tblLook".format(
                len(source_tables), len(target_tables)
            )
        )

    for before, after in zip(source_tables, target_tables):
        before_pr = before.find(qn("w:tblPr"))
        after_pr = after.find(qn("w:tblPr"))
        if after_pr is None:
            continue
        before_look = before_pr.find(qn("w:tblLook")) if before_pr is not None else None
        after_look = after_pr.find(qn("w:tblLook"))
        if before_look is None:
            if after_look is not None:
                after_pr.remove(after_look)
            continue
        if after_look is None:
            after_look = copy.deepcopy(before_look)
            insert_at = len(after_pr)
            for index, child in enumerate(list(after_pr)):
                if child.tag in (qn("w:tblCaption"), qn("w:tblDescription")):
                    insert_at = index
                    break
            after_pr.insert(insert_at, after_look)
        else:
            after_look.attrib.clear()
            after_look.attrib.update(before_look.attrib)

    target.save(staged_path)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _run(arguments: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _parse_json(stdout: Optional[str]) -> Dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _failure_message(payload: Dict[str, Any], run: subprocess.CompletedProcess) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    failures = [
        item for item in (data.get("results") or [])
        if isinstance(item, dict) and not item.get("success")
    ]
    if failures:
        first = failures[0]
        return "{} (code {})".format(
            str(first.get("error") or "batch item failed")[:300],
            first.get("code") or "unknown",
        )
    message = payload.get("message") or payload.get("error")
    if message:
        return str(message)[:300]
    return (run.stderr or "").strip()[:300] or "officecli batch failed"


__all__ = [
    "OfficecliError",
    "OfficecliUnavailable",
    "UnsupportedLocation",
    "build_set_command",
    "close",
    "dump",
    "find_officecli",
    "get_text",
    "is_available",
    "location_to_path",
    "restore_paragraph_identity",
    "restore_table_look",
    "run_batch",
    "validate",
    "version",
]
