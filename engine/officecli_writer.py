# -*- coding: utf-8 -*-
"""Compatibility facade over :mod:`engine.officecli_runtime`.

The runtime owns the process boundary, JSON envelopes, resident lifecycle and
DocumentSpec path translation. This module keeps the historical function names
used by the executors and adds the two post-write normalisers that undo
OfficeCLI's paragraph-identity and ``w:tblLook`` stamping.

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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .officecli_runtime import (
    DEFAULT_TIMEOUT,
    OfficecliError,
    OfficecliRuntime,
    OfficecliUnavailable,
    UnsupportedLocation,
    build_set_command,
    build_story_map,
    find_binary,
    get_runtime,
    location_to_path,
)


def find_officecli() -> Optional[str]:
    """Return the OfficeCLI executable path, or None when it is not installed."""
    return find_binary()


def is_available() -> bool:
    return find_binary() is not None


def version(timeout: int = 30) -> str:
    return OfficecliRuntime(timeout=timeout).version()


def preflight(timeout: int = 30) -> str:
    """Verify the binary runs and meets the capability floor."""
    return OfficecliRuntime(timeout=timeout).preflight()


def dump(file_path: str, path: str = "/", timeout: int = DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
    """Return a replayable batch command list for one subtree."""
    runtime = get_runtime(timeout=timeout)
    try:
        return runtime.dump(file_path, path)
    finally:
        runtime.close(file_path)


def run_batch(
    file_path: str,
    commands: List[Dict[str, Any]],
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Apply ``commands`` atomically; raise :class:`OfficecliError` on failure."""
    return get_runtime(timeout=timeout).batch(file_path, commands)


def get_text(file_path: str, path: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Read back the text of one node after a batch."""
    runtime = get_runtime(timeout=timeout)
    try:
        return str(runtime.get(file_path, path).get("text") or "")
    finally:
        runtime.close(file_path)


def close(file_path: str, timeout: int = 30) -> None:
    """Release the resident and flush the deferred disk write."""
    get_runtime().close(file_path, timeout=timeout)


def validate(file_path: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """OpenXML schema validation; returns the parsed payload (``success`` flag)."""
    runtime = get_runtime(timeout=timeout)
    try:
        return runtime.validate(file_path)
    finally:
        runtime.close(file_path)


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


__all__ = [
    "OfficecliError",
    "OfficecliUnavailable",
    "UnsupportedLocation",
    "build_set_command",
    "build_story_map",
    "close",
    "dump",
    "find_officecli",
    "get_text",
    "is_available",
    "location_to_path",
    "preflight",
    "restore_paragraph_identity",
    "restore_table_look",
    "run_batch",
    "validate",
    "version",
]
