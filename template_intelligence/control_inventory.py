# -*- coding: utf-8 -*-
"""Read-only inventory of fields and structured document tags.

The inventory is derived from OOXML and, when a template path and OfficeCLI
are available, cross-checked against OfficeCLI's addressable field paths.  No
document is mutated here.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from docx.oxml.ns import qn

from engine.ooxml_utils import iter_all_document_paragraphs_with_Wait_context


_FIELD_TYPE_RE = re.compile(r"^\s*([A-Za-z]+)")
_PART_RE = re.compile(
    r"^/?word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml$"
)


def _local_name(el: Any) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.split("}")[-1] if "}" in tag else tag


def _sha(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return prefix + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _officecli_part(partname: str) -> Optional[str]:
    match = _PART_RE.match(str(partname).replace("\\", "/"))
    if match is None:
        return None
    name = match.group(1)
    if name == "document":
        return "/document"
    if name == "footnotes":
        return "/footnotes"
    if name == "endnotes":
        return "/endnotes"
    number = re.search(r"(\d+)$", name)
    if number is None:
        return None
    stem = "header" if name.startswith("header") else "footer"
    return "/{0}[{1}]".format(stem, int(number.group(1)))


def _part_rank(partname: str) -> Tuple[int, str]:
    name = str(partname).replace("\\", "/")
    if name.endswith("/document.xml"):
        return (0, name)
    if "/header" in name:
        return (1, name)
    if "/footer" in name:
        return (2, name)
    if name.endswith("/footnotes.xml"):
        return (3, name)
    if name.endswith("/endnotes.xml"):
        return (4, name)
    return (9, name)


def _xml_parts(doc) -> List[Tuple[str, Any]]:
    package = getattr(doc.part, "package", None)
    if package is None or not hasattr(package, "iter_parts"):
        return []
    result: List[Tuple[str, Any]] = []
    for part in package.iter_parts():
        partname = str(getattr(part, "partname", ""))
        if not _officecli_part(partname):
            continue
        root = getattr(part, "element", None)
        if root is None:
            root = getattr(part, "_element", None)
        if root is None:
            blob = getattr(part, "blob", None)
            if blob:
                from docx.oxml import parse_xml

                root = parse_xml(blob)
        if root is not None and _officecli_part(partname):
            result.append((partname, root))
    return sorted(result, key=lambda item: _part_rank(item[0]))


def _element_xpath(el: Any, root: Any) -> str:
    """Build an absolute WordprocessingML XPath rooted at ``root``."""
    segments: List[str] = []
    node = el
    while node is not None:
        parent = node.getparent()
        if parent is None:
            name = _local_name(node)
            if name:
                segments.append("w:" + name)
            break
        name = _local_name(node)
        if name:
            siblings = [
                child
                for child in parent
                if _local_name(child) == name
            ]
            position = siblings.index(node) + 1
            segments.append("w:{0}[{1}]".format(name, position))
        node = parent
    return "/" + "/".join(reversed(segments))


def _paragraph_map(doc) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    for context in iter_all_document_paragraphs_with_Wait_context(doc):
        p_el = context.get("p_el")
        location = context.get("location_id")
        if p_el is not None and isinstance(location, str) and location:
            mapping.setdefault(id(p_el), location)
    return mapping


def _ancestor(el: Any, local_name: str) -> Any:
    node = el
    while node is not None:
        if _local_name(node) == local_name:
            return node
        node = node.getparent()
    return None


def _field_type(instruction: str) -> str:
    match = _FIELD_TYPE_RE.match(instruction or "")
    return match.group(1).upper() if match else "FIELD"


def _field_units(root: Any) -> List[Dict[str, Any]]:
    """Return complex fields that do not contain nested fields.

    A TOC field contains nested PAGEREF fields.  OfficeCLI addresses the inner
    PAGEREF/PAGE fields, not the TOC container, so nested-only filtering keeps
    the OOXML and OfficeCLI inventories comparable.
    """
    stack: List[Dict[str, Any]] = []
    fields: List[Dict[str, Any]] = []
    for el in root.iter():
        name = _local_name(el)
        if name == "fldChar":
            kind = el.get(qn("w:fldCharType")) or ""
            if kind == "begin":
                if stack:
                    stack[-1]["has_nested"] = True
                stack.append(
                    {
                        "begin": el,
                        "instr": [],
                        "instr_nodes": [],
                        "separate": None,
                        "end": None,
                        "result_texts": [],
                        "has_nested": False,
                    }
                )
            elif kind == "separate" and stack:
                stack[-1]["separate"] = el
            elif kind == "end" and stack:
                state = stack.pop()
                state["end"] = el
                fields.append(state)
            continue
        if not stack:
            continue
        state = stack[-1]
        if name == "instrText" and state["separate"] is None:
            text = el.text or ""
            if text:
                state["instr"].append(text)
                state["instr_nodes"].append(el)
        elif name == "t" and state["separate"] is not None:
            state["result_texts"].append(el)

    # fldSimple is a first-class field and has no begin/end markers.
    for simple in (
        node for node in root.iter() if _local_name(node) == "fldSimple"
    ):
        instruction = simple.get(qn("w:instr")) or ""
        texts = [node for node in simple.iter() if _local_name(node) == "t"]
        fields.append(
            {
                "begin": simple,
                "instr": [instruction] if instruction else [],
                "instr_nodes": [simple] if instruction else [],
                "separate": simple,
                "end": simple,
                "result_texts": texts,
                "has_nested": False,
                "simple": simple,
            }
        )
    return [item for item in fields if not item.get("has_nested")]


def _normalize_instruction(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _officecli_field_paths(file_path: str) -> Optional[List[Dict[str, Any]]]:
    if not file_path:
        return None
    try:
        from engine.officecli_runtime import OfficecliRuntime

        runtime = OfficecliRuntime(timeout=30)
        try:
            results = runtime.query(file_path, "field")
        finally:
            runtime.close(file_path)
        return [item for item in results if isinstance(item, dict)]
    except Exception:
        return None


def _assign_officecli_paths(
    fields: Sequence[Dict[str, Any]],
    query_results: Optional[Sequence[Dict[str, Any]]],
) -> None:
    for item in fields:
        item["officecli_path"] = None
        item["address_status"] = "UNRESOLVED"
        item["address_warning"] = None
    if not query_results:
        for item in fields:
            item["address_warning"] = "OfficeCLI field query returned no usable paths"
        return

    if len(query_results) == len(fields):
        for index, (field, result) in enumerate(
            zip(fields, query_results, strict=True)
        ):
            path = result.get("path")
            if not isinstance(path, str) or not path.startswith("/field["):
                field["address_warning"] = "OfficeCLI field result has no /field[N] path"
                continue
            fmt = result.get("format") if isinstance(result.get("format"), dict) else {}
            reported_type = str(fmt.get("fieldType") or "").strip().upper()
            reported_text = result.get("text")
            type_matches = reported_type in ("", "FIELD", field["field_type"])
            text_matches = not isinstance(reported_text, str) or (
                reported_text == field.get("cached_result")
            )
            if not type_matches or not text_matches:
                field["address_warning"] = (
                    "OfficeCLI result order could not be cross-checked at index {} "
                    "(type={!r}, text={!r})".format(index, reported_type, reported_text)
                )
                continue
            field["officecli_path"] = path
            field["address_status"] = "RESOLVED"
        return

    remaining = list(query_results)
    for field in fields:
        instruction = _normalize_instruction(field["instruction"])
        if not instruction:
            continue
        matches = [
            result
            for result in remaining
            if _normalize_instruction(
                str((result.get("format") or {}).get("instruction") or "")
            )
            == instruction
        ]
        if len(matches) == 1:
            result = matches[0]
            path = result.get("path")
            if isinstance(path, str) and path.startswith("/field["):
                field["officecli_path"] = path
                field["address_status"] = "RESOLVED"
                field["address_warning"] = None
                remaining.remove(result)
    for field in fields:
        if field["address_status"] == "UNRESOLVED" and not field["address_warning"]:
            field["address_warning"] = (
                "no unique OfficeCLI /field[N] path matches this field"
            )


def _field_lock(begin: Any) -> str:
    for node in [begin] + list(begin.iter()):
        if _local_name(node) == "fldChar":
            value = node.get(qn("w:fldLock"))
            if value and value.lower() in ("1", "true", "on"):
                return "LOCKED"
    return "UNLOCKED"


def collect_fields(doc, file_path: str = "") -> List[Dict[str, Any]]:
    paragraph_locations = _paragraph_map(doc)
    records: List[Dict[str, Any]] = []
    part_addresses: Dict[str, List[str]] = {}
    if file_path:
        try:
            from engine.officecli_runtime import build_part_address_map

            part_addresses = build_part_address_map(
                file_path,
                document=doc,
            )
        except Exception:
            part_addresses = {}
    for partname, root in _xml_parts(doc):
        normalized_partname = "/" + str(partname).lstrip("/")
        candidates = part_addresses.get(normalized_partname) or []
        part = candidates[0] if len(candidates) == 1 else _officecli_part(partname)
        if part is None:
            continue
        for root_order, state in enumerate(_field_units(root)):
            begin = state["begin"]
            p_el = _ancestor(begin, "p")
            location = paragraph_locations.get(id(p_el)) if p_el is not None else None
            if not location:
                continue
            instruction = "".join(state["instr"]).strip()
            result_texts = []
            seen: set[int] = set()
            for node in state["result_texts"]:
                if id(node) in seen:
                    continue
                seen.add(id(node))
                result_texts.append(node)
            cached_result = "".join(node.text or "" for node in result_texts)
            end = state["end"]
            insert_before = None
            if end is not None:
                end_run = _ancestor(end, "r")
                if end_run is not None:
                    insert_before = _element_xpath(end_run, root)
            field = {
                "field_id": _sha(
                    "FLD_",
                    location,
                    part,
                    instruction,
                    cached_result,
                    _element_xpath(begin, root),
                ),
                "location_id": location,
                "officecli_path": None,
                "instruction": instruction,
                "field_type": _field_type(instruction),
                "cached_result": cached_result,
                "lock_state": _field_lock(begin),
            "editable": False,
            "refresh_allowed": False,
                "parent_sdt_id": None,
                "address_status": "UNRESOLVED",
                "raw_locator": {
                    "part": part,
                    "begin_xpath": _element_xpath(begin, root),
                    "end_xpath": _element_xpath(end, root) if end is not None else None,
                    "result_text_xpaths": [
                        _element_xpath(node, root) for node in result_texts
                    ],
                    "result_insert_before_xpath": insert_before,
                    "instruction_xpaths": [
                        _element_xpath(node, root) for node in state["instr_nodes"]
                    ],
                },
                "_sdt_element_id": id(_ancestor(begin, "sdt"))
                if _ancestor(begin, "sdt") is not None
                else None,
                "_part_order": root_order,
                "_part_address": part,
                "_part_address_unique": len(candidates) == 1,
            }
            records.append(field)

    from engine.officecli_runtime import _address_rank

    records.sort(
        key=lambda item: (
            _address_rank(item.get("_part_address")),
            item.get("_part_order", 0),
        )
    )
    _assign_officecli_paths(records, _officecli_field_paths(file_path))
    for record in records:
        if not record.get("_part_address_unique", False):
            record["officecli_path"] = None
            record["address_status"] = "UNRESOLVED"
            record["address_warning"] = (
                "OfficeCLI part address is missing or ambiguous for this OOXML part"
            )
        record.pop("_part_order", None)
        record.pop("_part_address", None)
        record.pop("_part_address_unique", None)
        unlocked = record["lock_state"] != "LOCKED"
        record["editable"] = (
            record["address_status"] == "RESOLVED" and unlocked
        )
        record["refresh_allowed"] = (
            record["address_status"] == "RESOLVED" and unlocked
        )
    return records


def _sdt_id(sdt_el: Any) -> Optional[int]:
    pr = sdt_el.find(qn("w:sdtPr"))
    if pr is None:
        return None
    node = pr.find(qn("w:id"))
    if node is None:
        return None
    raw = node.get(qn("w:val")) or ""
    try:
        return int(raw)
    except ValueError:
        return None


def _sdt_lock(sdt_el: Any) -> str:
    pr = sdt_el.find(qn("w:sdtPr"))
    node = pr.find(qn("w:lock")) if pr is not None else None
    value = (node.get(qn("w:val")) or "unlocked") if node is not None else "unlocked"
    return {
        "contentLocked": "CONTENT_LOCKED",
        "sdtLocked": "SDT_LOCKED",
        "sdtContentLocked": "SDT_CONTENT_LOCKED",
    }.get(value, "UNLOCKED")


def _sdt_type(sdt_el: Any) -> str:
    pr = sdt_el.find(qn("w:sdtPr"))
    if pr is None:
        return "richtext"
    names = {_local_name(child) for child in pr}
    if "dropDownList" in names:
        return "dropdown"
    if "comboBox" in names:
        return "combobox"
    if "date" in names:
        return "date"
    if "picture" in names:
        return "picture"
    if "checkbox" in names:
        return "checkbox"
    if "text" in names:
        return "text"
    return "richtext"


def _sdt_text(sdt_el: Any) -> str:
    content = sdt_el.find(qn("w:sdtContent"))
    if content is None:
        return ""
    return "".join(node.text or "" for node in content.iter(qn("w:t")))


def _sdt_tag(sdt_el: Any, key: str) -> Optional[str]:
    pr = sdt_el.find(qn("w:sdtPr"))
    if pr is None:
        return None
    node = pr.find(qn("w:" + key))
    if node is None:
        return None
    value = node.get(qn("w:val"))
    return value


def collect_sdts(
    doc,
    file_path: str,
    containers: Sequence[Dict[str, Any]],
    fields: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    story_map: Dict[str, str] = {}
    if file_path:
        try:
            from engine.officecli_runtime import build_story_map

            story_map = build_story_map(file_path, document=doc)
        except Exception:
            story_map = {}

    from engine.officecli_runtime import OfficecliError, location_to_path

    records: List[Dict[str, Any]] = []
    by_element_id: Dict[int, str] = {}
    for container in containers:
        sdt_el = container.get("sdt_element")
        location = container.get("location")
        if sdt_el is None or not isinstance(location, str):
            continue
        ooxml_id = _sdt_id(sdt_el)
        record_id = _sha("SDT_", location, ooxml_id, _sdt_text(sdt_el))
        officecli_path = None
        try:
            officecli_path = location_to_path(location, story_map=story_map)
        except (OfficecliError, ValueError):
            officecli_path = None
        lock = _sdt_lock(sdt_el)
        editable = lock not in ("CONTENT_LOCKED", "SDT_CONTENT_LOCKED") and bool(
            officecli_path
        )
        field_ids = [
            field["field_id"]
            for field in fields
            if field.get("_sdt_element_id") == id(sdt_el)
        ]
        contains_fields = bool(field_ids)
        record = {
            "sdt_id": record_id,
            "ooxml_id": ooxml_id,
            "location_id": location,
            "officecli_path": officecli_path,
            "scope": str(container.get("scope") or ""),
            "type": _sdt_type(sdt_el),
            "tag": _sdt_tag(sdt_el, "tag"),
            "alias": _sdt_tag(sdt_el, "alias"),
            "text": _sdt_text(sdt_el),
            "lock": lock,
            "editable": editable,
            "contains_fields": contains_fields,
            "field_ids": field_ids,
            "requires_confirmation": contains_fields,
            "default_action": "REFRESH_FIELDS"
            if any(
                field.get("field_type") == "PAGE"
                for field in fields
                if field.get("field_id") in field_ids
            )
            else "PRESERVE",
        }
        records.append(record)
        by_element_id[id(sdt_el)] = record_id

    for field in fields:
        parent_id = field.get("_sdt_element_id")
        field["parent_sdt_id"] = by_element_id.get(parent_id) if parent_id else None
        field.pop("_sdt_element_id", None)
    return records


def build_control_inventory(
    doc,
    file_path: str,
    sdt_containers: Sequence[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    fields = collect_fields(doc, file_path=file_path)
    sdts = collect_sdts(doc, file_path, sdt_containers, fields)
    return {"fields": fields, "sdts": sdts}


__all__ = ["build_control_inventory", "collect_fields", "collect_sdts"]
