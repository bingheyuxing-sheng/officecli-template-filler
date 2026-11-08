# -*- coding: utf-8 -*-
"""MERGE mode: consolidate 2+ same-format Office files with OfficeCLI.

The first input is the base package; every later input is replayed into it as
an OfficeCLI ``dump`` batch. That keeps the base package's styles, numbering,
theme, headers and media intact while the replay carries paragraph/run
formatting, tables, pictures (as data URIs) and hyperlinks from the source.

DOCX gap handling is explicit: appended headers/footers, footnotes, endnotes
and comments are not merged, and the base document's page setup governs the
result. Those facts are reported as ``limitations`` instead of being hidden.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import zipfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

import docx
import openpyxl
from docx.oxml.ns import qn

from . import officecli_writer
from .excel_objects import inspect_excel_objects

DOCX_EXTENSIONS = (".docx", ".docm")
XLSX_EXTENSIONS = (".xlsx", ".xlsm")


class MergePlanningError(ValueError):
    """The inputs cannot be merged without guessing."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class MergeExecutionError(RuntimeError):
    """OfficeCLI rejected one replay batch or the verification failed."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _drop_meta(commands: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [copy.deepcopy(item) for item in commands if item.get("command") != "meta"]


def _dump(path: str, subtree: str) -> List[Dict[str, Any]]:
    return officecli_writer.dump(path, subtree)


def _props(command: Dict[str, Any]) -> Dict[str, Any]:
    return command.get("props") if isinstance(command.get("props"), dict) else {}


def _next_id(used: set) -> int:
    candidate = 1
    while candidate in used:
        candidate += 1
    used.add(candidate)
    return candidate


def normalize_inputs(paths: Sequence[str]) -> List[str]:
    normalized = []
    for path in paths:
        absolute = os.path.abspath(path)
        if not os.path.isfile(absolute):
            raise MergePlanningError(
                "MERGE_INPUT_MISSING",
                "input file does not exist: %s" % path,
                {"input": path},
            )
        normalized.append(absolute)
    if len(normalized) < 2:
        raise MergePlanningError(
            "MERGE_INPUTS_INSUFFICIENT",
            "MERGE needs at least two source files; got %d" % len(normalized),
            {"inputs": normalized},
        )
    extensions = {os.path.splitext(path)[1].lower() for path in normalized}
    if extensions <= set(DOCX_EXTENSIONS):
        return normalized
    if extensions <= set(XLSX_EXTENSIONS):
        return normalized
    raise MergePlanningError(
        "MERGE_FORMAT_MISMATCH",
        "all inputs must share one container family (DOCX/DOCM or XLSX/XLSM)",
        {"extensions": sorted(extensions)},
    )


def container_family(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    if extension in DOCX_EXTENSIONS:
        return "docx"
    if extension in XLSX_EXTENSIONS:
        return "xlsx"
    raise MergePlanningError(
        "MERGE_FORMAT_MISMATCH",
        "unsupported input extension: %s" % extension,
        {"input": path},
    )


# ---------------------------------------------------------------------------
# DOCX planning
# ---------------------------------------------------------------------------


def _style_groups(commands: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for command in commands:
        if command.get("command") != "add":
            continue
        parent = str(command.get("parent") or "")
        if parent == "/styles" and command.get("type") == "style":
            style_id = str(_props(command).get("id") or "")
            if style_id:
                groups[style_id] = [copy.deepcopy(command)]
            continue
        if parent.startswith("/styles/"):
            style_id = parent[len("/styles/"):].split("/", 1)[0]
            if style_id in groups:
                groups[style_id].append(copy.deepcopy(command))
    return groups


def _style_references(commands: Sequence[Dict[str, Any]]) -> List[str]:
    referenced = []
    for command in commands:
        if command.get("type") in ("w:basedOn", "w:link", "w:next", "w:numStyleLink", "w:styleLink"):
            value = str(_props(command).get("w:val") or "")
            if value:
                referenced.append(value)
    return referenced


def _missing_style_commands(
    source_groups: Dict[str, List[Dict[str, Any]]],
    target_ids: set,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Copy missing styles plus the closure of styles they reference."""
    missing = {style_id for style_id in source_groups if style_id not in target_ids}
    pending = list(missing)
    while pending:
        style_id = pending.pop()
        for reference in _style_references(source_groups.get(style_id, [])):
            if reference in source_groups and reference not in target_ids and reference not in missing:
                missing.add(reference)
                pending.append(reference)

    commands: List[Dict[str, Any]] = []
    for style_id in source_groups:
        if style_id in missing:
            commands.extend(source_groups[style_id])
    return commands, sorted(missing)


def _numbering_groups(
    commands: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
    abstract: Dict[str, List[Dict[str, Any]]] = {}
    nums: Dict[str, Dict[str, Any]] = {}
    current_abstract: Optional[str] = None
    current_num: Optional[str] = None
    for command in commands:
        if command.get("command") == "add" and command.get("parent") == "/numbering":
            kind = command.get("type")
            if kind == "w:abstractNum":
                current_abstract = str(_props(command).get("w:abstractNumId") or "")
                current_num = None
                if current_abstract:
                    abstract[current_abstract] = [copy.deepcopy(command)]
                continue
            if kind == "w:num":
                current_num = str(_props(command).get("w:numId") or "")
                current_abstract = None
                if current_num:
                    nums[current_num] = {"commands": [copy.deepcopy(command)], "abstract": None}
                continue
        parent = str(command.get("parent") or "")
        if command.get("command") != "add":
            continue
        if current_abstract and parent.startswith("/numbering/abstractNum"):
            abstract[current_abstract].append(copy.deepcopy(command))
        elif current_num and parent.startswith("/numbering/num"):
            nums[current_num]["commands"].append(copy.deepcopy(command))
            if command.get("type") == "w:abstractNumId":
                nums[current_num]["abstract"] = str(_props(command).get("w:val") or "")
    return abstract, nums


def _referenced_num_ids(commands: Sequence[Dict[str, Any]]) -> List[str]:
    referenced: List[str] = []
    for command in commands:
        props = _props(command)
        value = props.get("numId")
        if value is None and command.get("type") == "w:numId":
            value = props.get("w:val")
        if value is not None and str(value) not in referenced:
            referenced.append(str(value))
    return referenced


def _copy_numbering(
    abstract_groups: Dict[str, List[Dict[str, Any]]],
    num_groups: Dict[str, Dict[str, Any]],
    referenced: Sequence[str],
    used_num_ids: set,
    used_abstract_ids: set,
) -> Tuple[List[Dict[str, Any]], Dict[str, str], List[str]]:
    """Copy referenced numbering definitions under fresh ids."""
    commands: List[Dict[str, Any]] = []
    num_map: Dict[str, str] = {}
    abstract_map: Dict[str, str] = {}
    warnings: List[str] = []

    for old_num_id in referenced:
        entry = num_groups.get(old_num_id)
        if entry is None:
            warnings.append("numbering id %s is not defined in the source" % old_num_id)
            continue
        old_abstract = entry.get("abstract")
        new_abstract = None
        if old_abstract:
            if old_abstract not in abstract_groups:
                warnings.append("abstractNum %s is not defined in the source" % old_abstract)
            else:
                if old_abstract not in abstract_map:
                    new_abstract = str(_next_id(used_abstract_ids))
                    abstract_map[old_abstract] = new_abstract
                    for command in abstract_groups[old_abstract]:
                        clone = copy.deepcopy(command)
                        if clone.get("type") == "w:abstractNum":
                            clone.setdefault("props", {})["w:abstractNumId"] = new_abstract
                        commands.append(clone)
                new_abstract = abstract_map[old_abstract]

        new_num_id = str(_next_id(used_num_ids))
        num_map[old_num_id] = new_num_id
        for command in entry["commands"]:
            clone = copy.deepcopy(command)
            props = clone.setdefault("props", {})
            if clone.get("type") == "w:num":
                props["w:numId"] = new_num_id
            elif clone.get("type") == "w:abstractNumId" and new_abstract is not None:
                props["w:val"] = new_abstract
            commands.append(clone)
    return commands, num_map, warnings


def _rewrite_num_references(commands: Sequence[Dict[str, Any]], mapping: Dict[str, str]) -> None:
    for command in commands:
        props = command.get("props")
        if not isinstance(props, dict):
            continue
        if "numId" in props and str(props["numId"]) in mapping:
            props["numId"] = mapping[str(props["numId"])]
        if command.get("type") == "w:numId" and "w:val" in props:
            value = str(props["w:val"])
            if value in mapping:
                props["w:val"] = mapping[value]


def _existing_style_ids(path: str) -> set:
    document = docx.Document(path)
    return {str(style.style_id) for style in document.styles if style.style_id}


def _existing_number_ids(path: str) -> Tuple[set, set]:
    document = docx.Document(path)
    try:
        numbering = document.part.numbering_part.element
    except Exception:
        return set(), set()
    num_ids = {
        int(node.get(qn("w:numId")))
        for node in numbering.findall(qn("w:num"))
        if node.get(qn("w:numId"))
    }
    abstract_ids = {
        int(node.get(qn("w:abstractNumId")))
        for node in numbering.findall(qn("w:abstractNum"))
        if node.get(qn("w:abstractNumId"))
    }
    return num_ids, abstract_ids


def _story_coverage_gaps(path: str) -> List[str]:
    gaps: List[str] = []
    document = docx.Document(path)
    for section in document.sections:
        for name in (
            "header",
            "footer",
            "first_page_header",
            "first_page_footer",
            "even_page_header",
            "even_page_footer",
        ):
            part = getattr(section, name, None)
            if part is None:
                continue
            try:
                if part.is_linked_to_previous:
                    continue
            except Exception:
                pass
            has_text = any((paragraph.text or "").strip() for paragraph in part.paragraphs)
            has_object = bool(part._element.xpath(".//w:drawing | .//w:pict"))
            if has_text or has_object:
                gaps.append("HEADERS_FOOTERS_NOT_MERGED")
                break
        if "HEADERS_FOOTERS_NOT_MERGED" in gaps:
            break

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            checks = (
                ("word/footnotes.xml", "FOOTNOTES_NOT_MERGED", "w:footnote"),
                ("word/endnotes.xml", "ENDNOTES_NOT_MERGED", "w:endnote"),
                ("word/comments.xml", "COMMENTS_NOT_MERGED", "w:comment"),
            )
            for part_name, gap, tag in checks:
                if part_name not in names:
                    continue
                text = archive.read(part_name).decode("utf-8", "ignore")
                ids = re.findall(r"<%s[^>]*w:id=\"(-?\d+)\"" % tag, text)
                if any(int(value) > 0 for value in ids):
                    gaps.append(gap)
    except (OSError, zipfile.BadZipFile):
        gaps.append("SOURCE_PACKAGE_UNREADABLE")
    return gaps


def _first_and_last_text(path: str) -> Tuple[str, str]:
    document = docx.Document(path)
    texts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    if not texts:
        return "", ""
    return texts[0], texts[-1]


def plan_docx_merge(
    inputs: Sequence[str],
    *,
    output_path: str = "",
    separator: str = "page",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    base = inputs[0]
    target_styles = _existing_style_ids(base)
    used_num_ids, used_abstract_ids = _existing_number_ids(base)

    documents: List[Dict[str, Any]] = [{
        "path": base,
        "role": "base",
        "style_ids_added": [],
        "numbering": [],
        "body_commands": 0,
    }]
    payload_documents: List[Dict[str, Any]] = [{"path": base, "role": "base"}]
    limitations: List[str] = []
    warnings: List[str] = []

    for source in inputs[1:]:
        style_commands, added_styles = _missing_style_commands(
            _style_groups(_dump(source, "/styles")), target_styles
        )
        target_styles.update(added_styles)

        body_commands = _drop_meta(_dump(source, "/body"))
        abstract_groups, num_groups = _numbering_groups(_dump(source, "/numbering"))
        referenced = _referenced_num_ids(body_commands) + _referenced_num_ids(style_commands)
        numbering_commands, num_map, numbering_warnings = _copy_numbering(
            abstract_groups,
            num_groups,
            list(dict.fromkeys(referenced)),
            used_num_ids,
            used_abstract_ids,
        )
        _rewrite_num_references(body_commands, num_map)
        _rewrite_num_references(style_commands, num_map)
        warnings.extend("%s: %s" % (os.path.basename(source), text) for text in numbering_warnings)

        documents.append({
            "path": source,
            "role": "append",
            "style_ids_added": added_styles,
            "numbering": [
                {"source_num_id": old, "new_num_id": new}
                for old, new in sorted(num_map.items(), key=lambda item: item[0])
            ],
            "body_commands": len(body_commands),
        })
        payload_documents.append({
            "path": source,
            "role": "append",
            "style_commands": style_commands,
            "numbering_commands": numbering_commands,
            "body_commands": body_commands,
        })

        for gap in _story_coverage_gaps(source):
            if gap not in limitations:
                limitations.append(gap)
        if source.lower().endswith(".docm") and "MACROS_NOT_MERGED" not in limitations:
            limitations.append("MACROS_NOT_MERGED")
        if "SOURCE_FINAL_PAGE_SETUP_NOT_APPLIED" not in limitations:
            limitations.append("SOURCE_FINAL_PAGE_SETUP_NOT_APPLIED")

    plan = {
        "schema_version": "1.0",
        "task_mode": "MERGE",
        "format": "docx",
        "inputs": list(inputs),
        "output": output_path,
        "separator": separator,
        "backend": "officecli",
        "documents": documents,
        "summary": {
            "input_count": len(inputs),
            "appended_count": len(inputs) - 1,
            "style_ids_added": sum(len(item["style_ids_added"]) for item in documents),
            "numbering_entries": sum(len(item["numbering"]) for item in documents),
        },
        "warnings": warnings,
        "limitations": limitations,
    }
    payload = {
        "format": "docx",
        "inputs": list(inputs),
        "separator": separator,
        "documents": payload_documents,
        "verification": [
            {"path": source, "first_text": _first_and_last_text(source)[0],
             "last_text": _first_and_last_text(source)[1]}
            for source in inputs[1:]
        ],
    }
    return plan, payload


# ---------------------------------------------------------------------------
# XLSX planning
# ---------------------------------------------------------------------------


def _sheet_names(path: str) -> List[str]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def _rewrite_sheet_reference(value: str, mapping: Dict[str, str]) -> str:
    rewritten = value
    for old, new in mapping.items():
        if old == new:
            continue
        quoted_old = "'" + old.replace("'", "''") + "'!"
        quoted_new = "'" + new.replace("'", "''") + "'!"
        rewritten = rewritten.replace(quoted_old, quoted_new)
        rewritten = rewritten.replace(old + "!", new + "!")
    return rewritten


def _rewrite_sheet_commands(commands: Sequence[Dict[str, Any]], mapping: Dict[str, str]) -> List[Dict[str, Any]]:
    rewritten: List[Dict[str, Any]] = []
    for original in commands:
        command = copy.deepcopy(original)
        if command.get("command") == "meta":
            continue
        if command.get("command") == "add" and command.get("parent") == "/" and command.get("type") == "sheet":
            props = command.setdefault("props", {})
            name = str(props.get("name") or "")
            if name in mapping:
                props["name"] = mapping[name]
            rewritten.append(command)
            continue

        for key in ("path", "parent"):
            value = command.get(key)
            if isinstance(value, str):
                for old, new in mapping.items():
                    if old == new:
                        continue
                    if value == "/" + old or value.startswith("/" + old + "/"):
                        command[key] = "/" + new + value[len(old) + 1:]
                        break

        text = command.get("text")
        if isinstance(text, str) and command.get("command") == "import":
            command["text"] = _rewrite_sheet_reference(text, mapping)

        props = command.get("props")
        if isinstance(props, dict):
            for prop_key, prop_value in list(props.items()):
                if isinstance(prop_value, str) and (
                    prop_value.startswith("=") or prop_key.lower() in ("formula", "text")
                ):
                    props[prop_key] = _rewrite_sheet_reference(prop_value, mapping)
        rewritten.append(command)
    return rewritten


def plan_xlsx_merge(
    inputs: Sequence[str],
    *,
    output_path: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    used_names: List[str] = []
    seen = set()
    for name in _sheet_names(inputs[0]):
        used_names.append(name)
        seen.add(name.casefold())

    documents: List[Dict[str, Any]] = [{
        "path": inputs[0],
        "role": "base",
        "sheets": [{"source": name, "merged": name} for name in _sheet_names(inputs[0])],
    }]
    payload_documents: List[Dict[str, Any]] = [
        {"path": inputs[0], "role": "base", "sheets": []}
    ]
    limitations: List[str] = []
    warnings: List[str] = []

    for source in inputs[1:]:
        source_sheets = _sheet_names(source)
        mapping: Dict[str, str] = {}
        for name in source_sheets:
            merged = name
            suffix = 2
            while merged.casefold() in seen:
                merged = "%s-%d" % (name, suffix)
                suffix += 1
            mapping[name] = merged
            seen.add(merged.casefold())
            used_names.append(merged)

        sheet_entries = []
        sheet_payloads = []
        for name in source_sheets:
            commands = _rewrite_sheet_commands(_dump(source, "/" + name), mapping)
            sheet_entries.append({"source": name, "merged": mapping[name]})
            sheet_payloads.append({"source": name, "name": mapping[name], "commands": commands})
        documents.append({"path": source, "role": "append", "sheets": sheet_entries})
        payload_documents.append({"path": source, "role": "append", "sheets": sheet_payloads})

        workbook = openpyxl.load_workbook(source, read_only=True)
        try:
            if getattr(workbook, "defined_names", None):
                if "NAMED_RANGES_NOT_MERGED" not in limitations:
                    limitations.append("NAMED_RANGES_NOT_MERGED")
        finally:
            workbook.close()
        objects = inspect_excel_objects(source)
        if objects.get("object_loss_risk"):
            if "WORKBOOK_OBJECTS_NOT_MERGED" not in limitations:
                limitations.append("WORKBOOK_OBJECTS_NOT_MERGED")
            warnings.append(
                "%s: %s" % (os.path.basename(source), ", ".join(objects.get("loss_risk_objects") or []))
            )
        if source.lower().endswith(".xlsm") and "VBA_NOT_MERGED" not in limitations:
            limitations.append("VBA_NOT_MERGED")

    plan = {
        "schema_version": "1.0",
        "task_mode": "MERGE",
        "format": "xlsx",
        "inputs": list(inputs),
        "output": output_path,
        "backend": "officecli",
        "documents": documents,
        "summary": {
            "input_count": len(inputs),
            "appended_count": len(inputs) - 1,
            "sheets": len(used_names),
            "renamed_sheets": sum(
                1
                for document in documents
                for sheet in document["sheets"]
                if sheet["source"] != sheet["merged"]
            ),
        },
        "warnings": warnings,
        "limitations": limitations,
    }
    payload = {
        "format": "xlsx",
        "inputs": list(inputs),
        "documents": payload_documents,
        "sheet_map": {
            os.path.basename(document["path"]): {
                sheet["source"]: sheet["merged"] for sheet in document["sheets"]
            }
            for document in documents
        },
    }
    return plan, payload


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------


def execute_merge(plan: Dict[str, Any], payload: Dict[str, Any], stage_path: str) -> Dict[str, Any]:
    """Replay every appended source into a staged copy of the base file."""
    inputs = payload["inputs"]
    shutil.copyfile(inputs[0], stage_path)
    batches = 0
    has_raw_set = False
    try:
        if payload["format"] == "docx":
            for document in payload["documents"][1:]:
                if any(command.get("command") == "raw-set"
                       for command in (document.get("body_commands") or [])):
                    has_raw_set = True
                for phase, key in (
                    ("styles", "style_commands"),
                    ("numbering", "numbering_commands"),
                ):
                    commands = document.get(key) or []
                    if commands:
                        try:
                            officecli_writer.run_batch(stage_path, commands)
                        except Exception as exc:
                            raise MergeExecutionError(
                                "MERGE_BATCH_FAILED",
                                "%s replay failed for %s: %s: %s"
                                % (phase, os.path.basename(document["path"]), type(exc).__name__, exc),
                                {"phase": phase, "source": document["path"]},
                            ) from exc
                        batches += 1
                if payload.get("separator") == "page":
                    try:
                        officecli_writer.run_batch(stage_path, [
                            {"command": "add", "parent": "/body", "type": "p"},
                            {"command": "add", "parent": "/body/p[last()]",
                             "type": "pagebreak", "props": {"type": "page"}},
                        ])
                    except Exception as exc:
                        raise MergeExecutionError(
                            "MERGE_BATCH_FAILED",
                            "page-break insertion failed before %s: %s: %s"
                            % (os.path.basename(document["path"]), type(exc).__name__, exc),
                            {"phase": "separator", "source": document["path"]},
                        ) from exc
                    batches += 1
                body = document.get("body_commands") or []
                if body:
                    try:
                        officecli_writer.run_batch(stage_path, body)
                    except Exception as exc:
                        raise MergeExecutionError(
                            "MERGE_BATCH_FAILED",
                            "body replay failed for %s: %s: %s"
                            % (os.path.basename(document["path"]), type(exc).__name__, exc),
                            {"phase": "body", "source": document["path"]},
                        ) from exc
                    batches += 1

            officecli_writer.close(stage_path)
            try:
                officecli_writer.restore_paragraph_identity(
                    inputs[0], stage_path, allow_appended=True
                )
                if has_raw_set:
                    officecli_writer.restore_table_look(inputs[0], stage_path)
            except Exception as exc:
                raise MergeExecutionError(
                    "MERGE_NORMALIZE_FAILED",
                    "officecli output could not be normalised: %s: %s"
                    % (type(exc).__name__, exc),
                ) from exc
        else:
            for document in payload["documents"][1:]:
                for sheet in document["sheets"]:
                    commands = sheet.get("commands") or []
                    if not commands:
                        continue
                    try:
                        officecli_writer.run_batch(stage_path, commands)
                    except Exception as exc:
                        raise MergeExecutionError(
                            "MERGE_BATCH_FAILED",
                            "sheet %r replay failed for %s: %s: %s"
                            % (sheet["name"], os.path.basename(document["path"]),
                               type(exc).__name__, exc),
                            {"phase": "sheet", "source": document["path"], "sheet": sheet["name"]},
                        ) from exc
                    batches += 1
            officecli_writer.close(stage_path)
    finally:
        officecli_writer.close(stage_path)

    return {"backend": "officecli", "batches": batches}


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


def verify_merge(plan: Dict[str, Any], payload: Dict[str, Any], staged_path: str) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    limitations = list(plan.get("limitations") or [])

    if payload["format"] == "docx":
        document = docx.Document(staged_path)
        text = "\n".join(
            paragraph.text
            for paragraph in document.paragraphs
        )
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    text += "\n" + "\n".join(paragraph.text for paragraph in cell.paragraphs)
        for entry in payload.get("verification") or []:
            for key in ("first_text", "last_text"):
                expected = entry.get(key) or ""
                if expected and expected not in text:
                    issues.append({
                        "code": "MERGE_CONTENT_MISSING",
                        "severity": "high",
                        "location": os.path.basename(entry["path"]),
                        "detail": "%s text was not found in the merged document: %.60r"
                                  % (key, expected),
                    })
        return {
            "passed": not issues,
            "issues": issues,
            "coverage_gaps": [],
            "limitations": limitations,
            "unverified_count": 0,
        }

    output = openpyxl.load_workbook(staged_path, data_only=False)
    try:
        output_sheets = set(output.sheetnames)
        for document in payload["documents"][1:]:
            source = openpyxl.load_workbook(document["path"], data_only=False)
            try:
                for sheet in document["sheets"]:
                    merged_name = sheet["name"]
                    source_name = sheet["source"]
                    if merged_name not in output_sheets:
                        issues.append({
                            "code": "MERGE_SHEET_MISSING",
                            "severity": "high",
                            "location": os.path.basename(document["path"]),
                            "detail": "sheet %r (merged as %r) is missing"
                                      % (source_name, merged_name),
                        })
                        continue
                    source_ws = source[source_name]
                    output_ws = output[merged_name]
                    source_formulas = sum(
                        1
                        for row in source_ws.iter_rows()
                        for cell in row
                        if isinstance(cell.value, str) and cell.value.startswith("=")
                    )
                    output_formulas = sum(
                        1
                        for row in output_ws.iter_rows()
                        for cell in row
                        if isinstance(cell.value, str) and cell.value.startswith("=")
                    )
                    if output_formulas < source_formulas:
                        issues.append({
                            "code": "MERGE_FORMULA_LOSS",
                            "severity": "high",
                            "location": "%s!%s" % (merged_name, os.path.basename(document["path"])),
                            "detail": "formulas %d -> %d" % (source_formulas, output_formulas),
                        })
                    if len(output_ws.merged_cells.ranges) < len(source_ws.merged_cells.ranges):
                        issues.append({
                            "code": "MERGE_MERGE_LOSS",
                            "severity": "high",
                            "location": merged_name,
                            "detail": "merged ranges %d -> %d"
                                      % (len(source_ws.merged_cells.ranges),
                                         len(output_ws.merged_cells.ranges)),
                        })
                    for row in output_ws.iter_rows():
                        for cell in row:
                            if isinstance(cell.value, str) and "#REF!" in cell.value:
                                issues.append({
                                    "code": "MERGE_BROKEN_REFERENCE",
                                    "severity": "high",
                                    "location": "%s!%s" % (merged_name, cell.coordinate),
                                    "detail": cell.value[:120],
                                })
            finally:
                source.close()
    finally:
        output.close()

    return {
        "passed": not issues,
        "issues": issues,
        "coverage_gaps": [],
        "limitations": limitations,
        "unverified_count": 0,
    }


__all__ = [
    "MergeExecutionError",
    "MergePlanningError",
    "container_family",
    "execute_merge",
    "normalize_inputs",
    "plan_docx_merge",
    "plan_xlsx_merge",
    "verify_merge",
]
