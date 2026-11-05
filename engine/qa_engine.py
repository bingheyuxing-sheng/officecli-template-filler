# -*- coding: utf-8 -*-
"""
Full DOCX Package QA & Visual QA Engine (v3.0 — Fix for P1-7).

Core improvements:
1. Full DOCX Package Inspection (`audit_docx_package_integrity`):
   - Inspects ALL XML parts in the `.docx` ZIP package:
     `word/document.xml`, `word/styles.xml`, `word/numbering.xml`, `word/settings.xml`,
     `word/header*.xml`, `word/footer*.xml`, `word/comments.xml`, `word/footnotes.xml`,
     `word/endnotes.xml`, `[Content_Types].xml`, and all `*.rels` files.
   - Verifies:
     * Well-formed XML across every package member.
     * Zero dangling internal relationships (`Target` in `.rels` must exist in the ZIP archive when `TargetMode != "External"`).
     * Zero unreferenced or broken `r:embed` / `r:id` references in XML parts.
     * Media integrity and MIME / `[Content_Types].xml` alignment (`verify_docx_images_integrity`).
     * Duplicate `w14:paraId` and `wp:docPr` IDs across the entire package.
2. Node-Level Format-Diff & Text-Residue QA (`audit_format_and_text_qa`):
   - Compares output against template baseline while incorporating full package QA.
3. Visual Layout & Rendering QA (`run_visual_layout_qa`):
   - Converts `.docx` -> `.pdf` (via LibreOffice / Word COM if available) and renders page images or inspects page counts, unexpected blank pages, table overflow, and image aspect-ratio distortion.
"""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
import tempfile
import zipfile
from typing import Any, Dict, List, Optional, Set, Tuple
from xml.etree import ElementTree as ET

import docx
from docx.oxml.ns import qn

from .ooxml_utils import TOKEN_PATTERN, is_red_run, iter_all_document_paragraphs_with_Wait_context
from .qa_policy import resolve_comparison_profile, split_issues
from .pdf_backend import find_pdf_backend, convert_docx_to_pdf, pdf_page_count
from .style_engine import resolve_run_effective_sz, resolve_run_effective_font
from .table_engine import table_style_signature, compare_table_style
from .image_engine import verify_docx_images_integrity
from .alignment import align_paragraphs, align_tables


class QAValidationError(ValueError):
    """
    Raised when a document fails a QA gate.

    Deliberately not an `assert`: `python -O` removes assertions, which would make red-text,
    size, font and table drift silently pass in optimized environments. Callers that prefer
    data over exceptions pass `raise_on_failure=False` and read `issues` from the report.
    """


def _issue(code: str, location: str, detail: Any, severity: str = "high") -> Dict[str, Any]:
    return {"code": code, "location": location, "detail": str(detail), "severity": severity}


def _red_issues(red_residuals) -> List[Dict[str, Any]]:
    return [_issue("RED_TEXT_RESIDUAL", str(item[0]), item[1]) for item in red_residuals]


def _size_issues(size_anomalies, comparison_profile: str = "REPLICA") -> List[Dict[str, Any]]:
    issues = []
    for anomaly in size_anomalies:
        kind = anomaly[0]
        location = f"{kind}[{anomaly[1]}]" if len(anomaly) > 1 else kind
        severity = "high"
        if comparison_profile == "STYLE_GUIDE" and kind in ("table_dominant_size", "table"):
            severity = "medium"
        issues.append(_issue("FONT_SIZE_ANOMALY", location, anomaly, severity=severity))
    return issues


def _font_issues(font_anomalies) -> List[Dict[str, Any]]:
    issues = []
    for anomaly in font_anomalies:
        kind = anomaly[0]
        location = f"{kind}[{anomaly[1]}]" if len(anomaly) > 1 else kind
        issues.append(_issue("FONT_FAMILY_ANOMALY", location, anomaly))
    return issues


def _table_issues(table_style_anomalies, comparison_profile: str = "REPLICA") -> List[Dict[str, Any]]:
    issues = []
    for anomaly in table_style_anomalies:
        kind = anomaly[0]
        location = f"{kind}[{anomaly[1]}]" if len(anomaly) > 1 else kind
        severity = "high"
        if kind == "table_row_count":
            severity = "low"
        elif kind in ("table_row_height", "table_header_height"):
            severity = "medium"
        elif kind == "table_cell_font_or_size" and comparison_profile == "STYLE_GUIDE":
            severity = "medium"
        elif kind == "table_cell_property" and comparison_profile == "STYLE_GUIDE":
            severity = "medium"
        issues.append(_issue("TABLE_STYLE_ANOMALY", location, anomaly, severity=severity))
    return issues


def _text_issues(text_residuals) -> List[Dict[str, Any]]:
    issues = []
    for residual in text_residuals:
        kind = residual[0]
        location = ".".join(str(part) for part in residual[:-1])
        issues.append(_issue("TEMPLATE_TEXT_RESIDUAL", f"{kind}:{location}", residual[-1]))
    return issues


_XML_SPACE_NS = "{http://www.w3.org/XML/1998/namespace}space"


def _count_missing_space_preserve(document) -> int:
    """Count body `w:t` values that carry spaces without `xml:space="preserve"`."""
    count = 0
    for t_el in document.element.body.xpath(".//w:t"):
        value = t_el.text or ""
        if (
            value.startswith(" ") or value.endswith(" ") or "  " in value
        ) and t_el.get(_XML_SPACE_NS) != "preserve":
            count += 1
    return count


def audit_docx_package_integrity(docx_path: str, baseline_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Perform a comprehensive OOXML package-level audit on `docx_path` covering:
    - All XML parts (`document.xml`, `styles.xml`, `numbering.xml`, `settings.xml`,
      `header*.xml`, `footer*.xml`, `comments.xml`, `footnotes.xml`, `endnotes.xml`, `[Content_Types].xml`)
    - All `.rels` relationship files (checking for dangling internal targets)
    - All `r:embed` and `r:id` attributes inside `word/*.xml` against their corresponding `word/_rels/*.xml.rels`
    - All `word/media/*` image binaries and MIME content types
    - Duplicate `w14:paraId` and `wp:docPr` IDs across all story parts
    """
    xml_parse_errors: List[str] = []
    dangling_rels: List[str] = []
    unresolved_rids: List[str] = []
    duplicate_para_ids: List[str] = []
    duplicate_docpr_ids: List[str] = []
    missing_space_preserve: int = 0
    proof_err_unbalanced: List[str] = []
    inspected_xml_parts: List[str] = []

    W14_PARA_ID = "{http://schemas.microsoft.com/office/word/2010/wordml}paraId"
    R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    W_T = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
    W_PROOF_ERR = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}proofErr"
    W_TYPE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type"
    WP_DOCPR = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
    XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

    with zipfile.ZipFile(docx_path, "r") as zf:
        all_names: Set[str] = set(zf.namelist())
        rels_map_by_part: Dict[str, Dict[str, Tuple[str, str]]] = {}

        # 1. Parse all .rels files and verify internal targets exist
        for name in sorted(all_names):
            if name.endswith(".rels"):
                try:
                    root = ET.fromstring(zf.read(name))
                    inspected_xml_parts.append(name)
                except Exception as exc:
                    xml_parse_errors.append(f"{name}: {exc}")
                    continue

                # Determine owner part path from `word/_rels/document.xml.rels` -> `word/document.xml`
                rels_dir, rels_file = posixpath.split(name)
                owner_dir = posixpath.dirname(rels_dir) if rels_dir.endswith("_rels") else rels_dir
                owner_file = rels_file[:-5]  # strip `.rels`
                owner_part = posixpath.normpath(posixpath.join(owner_dir, owner_file)) if owner_file else ""
                part_rels: Dict[str, Tuple[str, str]] = {}

                for rel in root:
                    if not rel.tag.endswith("Relationship"):
                        continue
                    r_id = rel.get("Id") or ""
                    target = rel.get("Target") or ""
                    target_mode = (rel.get("TargetMode") or "").strip()
                    part_rels[r_id] = (target, target_mode)

                    if target_mode.lower() != "external" and target:
                        if target.startswith("/"):
                            resolved = target.lstrip("/")
                        else:
                            resolved = posixpath.normpath(posixpath.join(owner_dir, target))
                        if resolved not in all_names:
                            dangling_rels.append(f"{name} -> {r_id} -> missing '{resolved}'")

                rels_map_by_part[owner_part] = part_rels

        # 2. Parse all XML parts and check r:embed / r:id, paraId, docPr id, xml:space
        seen_para_ids: Set[str] = set()
        seen_docpr_ids: Set[str] = set()

        for name in sorted(all_names):
            if not name.endswith(".xml"):
                continue
            try:
                root = ET.fromstring(zf.read(name))
                inspected_xml_parts.append(name)
            except Exception as exc:
                xml_parse_errors.append(f"{name}: {exc}")
                continue

            part_rels = rels_map_by_part.get(name, {})

            # Spell/grammar markers must be balanced: an orphan spellEnd (or an unclosed
            # spellStart) is the kind of OOXML hygiene damage that only shows up as odd
            # behaviour in Word, so it is checked here instead of being silently carried.
            proof_err_balance: Dict[str, int] = {}
            for marker in root.iter(W_PROOF_ERR):
                marker_type = str(marker.get(W_TYPE) or "").lower()
                if marker_type.endswith("start"):
                    prefix = marker_type[:-5]
                    proof_err_balance[prefix] = proof_err_balance.get(prefix, 0) + 1
                elif marker_type.endswith("end"):
                    prefix = marker_type[:-3]
                    proof_err_balance[prefix] = proof_err_balance.get(prefix, 0) - 1
                    if proof_err_balance[prefix] < 0:
                        proof_err_unbalanced.append(f"{name}: orphan {marker_type}")
            for prefix, balance in sorted(proof_err_balance.items()):
                if balance > 0:
                    proof_err_unbalanced.append(f"{name}: {balance} unclosed {prefix}Start")

            for elem in root.iter():
                # Check paraId uniqueness across story parts
                pid = elem.get(W14_PARA_ID)
                if pid:
                    if pid in seen_para_ids:
                        duplicate_para_ids.append(f"{name}:{pid}")
                    seen_para_ids.add(pid)

                # Check wp:docPr id uniqueness
                if elem.tag == WP_DOCPR:
                    did = elem.get("id")
                    if did:
                        if did in seen_docpr_ids:
                            duplicate_docpr_ids.append(f"{name}:{did}")
                        seen_docpr_ids.add(did)

                # Check w:t xml:space="preserve"
                if elem.tag == W_T and elem.text:
                    txt = elem.text
                    if (txt.startswith(" ") or txt.endswith(" ") or "  " in txt):
                        if elem.get(XML_SPACE) != "preserve":
                            missing_space_preserve += 1

                # Check r:embed / r:id references in word/*.xml parts
                if name.startswith("word/"):
                    for attr_qname in (R_EMBED, R_ID):
                        ref_val = elem.get(attr_qname)
                        if ref_val and part_rels and ref_val not in part_rels:
                            unresolved_rids.append(f"{name}: unresolved {ref_val}")

    # 3. Verify image binaries & MIME types
    image_qa = verify_docx_images_integrity(docx_path)

    # A `w:t` without `xml:space` loses leading/trailing spaces in some consumers.
    # WPS itself emits such runs, and a template-filler cannot repair its read-only
    # template, so findings that the template baseline already carries are disclosed
    # instead of blocking. Any run beyond the baseline count is still blocking.
    inherited_space_preserve = 0
    baseline_space_preserve = None
    effective_space_preserve = missing_space_preserve
    if baseline_path and os.path.isfile(baseline_path) and missing_space_preserve:
        try:
            baseline_report = audit_docx_package_integrity(baseline_path)
            baseline_space_preserve = int(baseline_report.get("missing_space_preserve") or 0)
        except Exception:
            baseline_space_preserve = None
        if (
            baseline_space_preserve is not None
            and baseline_space_preserve > 0
            and missing_space_preserve <= baseline_space_preserve
        ):
            inherited_space_preserve = missing_space_preserve
            effective_space_preserve = 0

    passed = (
        len(xml_parse_errors) == 0
        and len(dangling_rels) == 0
        and len(unresolved_rids) == 0
        and len(duplicate_para_ids) == 0
        and len(duplicate_docpr_ids) == 0
        and effective_space_preserve == 0
        and image_qa["passed"]
    )

    structured_issues: List[Dict[str, Any]] = []
    structured_issues.extend(_issue("PACKAGE_XML_PARSE", "document_package", item) for item in xml_parse_errors)
    structured_issues.extend(_issue("PACKAGE_DANGLING_REL", "document_package", item) for item in dangling_rels)
    structured_issues.extend(_issue("PACKAGE_UNRESOLVED_RID", "document_package", item) for item in unresolved_rids)
    structured_issues.extend(_issue("PACKAGE_DUPLICATE_PARA_ID", "w14:paraId", item) for item in duplicate_para_ids)
    structured_issues.extend(_issue("PACKAGE_DUPLICATE_DOCPR_ID", "wp:docPr", item) for item in duplicate_docpr_ids)
    if effective_space_preserve:
        structured_issues.append(
            _issue("PACKAGE_SPACE_PRESERVE_MISSING", "w:t", f"{effective_space_preserve} runs lack xml:space")
        )
    elif inherited_space_preserve:
        structured_issues.append(
            _issue(
                "PACKAGE_SPACE_PRESERVE_MISSING",
                "w:t",
                "%d run(s) lack xml:space but the template baseline already carries %d"
                % (inherited_space_preserve, baseline_space_preserve),
                severity="medium",
            )
        )
    structured_issues.extend(
        _issue("PACKAGE_IMAGE_INTEGRITY", "media", item) for item in image_qa.get("issues", [])
    )
    structured_issues.extend(
        _issue("PACKAGE_PROOFERR_UNBALANCED", "w:proofErr", item, "medium")
        for item in proof_err_unbalanced
    )

    # Vector images and externally linked images cannot be byte-verified: surface them as
    # coverage gaps so the overall report becomes UNVERIFIED instead of a silent pass.
    image_gaps = list(image_qa.get("coverage_gaps") or [])
    package_gaps = list(dict.fromkeys(image_gaps))

    return {
        "passed": passed,
        "issues": structured_issues,
        "structured_issues": structured_issues,
        "coverage_gaps": package_gaps,
        "unverified_count": len(package_gaps),
        "inspected_parts_count": len(inspected_xml_parts),
        "xml_parse_errors": xml_parse_errors,
        "dangling_relationships": dangling_rels,
        "unresolved_rids": unresolved_rids,
        "duplicate_para_ids": duplicate_para_ids,
        "duplicate_docpr_ids": duplicate_docpr_ids,
        "missing_space_preserve": missing_space_preserve,
        "effective_space_preserve": effective_space_preserve,
        "inherited_space_preserve": inherited_space_preserve,
        "baseline_space_preserve": baseline_space_preserve,
        "proof_err_unbalanced": proof_err_unbalanced,
        "image_integrity": image_qa,
    }


# Paragraphs whose style legitimately uses a size other than the body baseline.
_SIZE_EXEMPT_STYLE_MARKERS = ("heading", "title", "caption", "toc", "标题", "题注", "目录")


# Styles that represent ordinary body copy, where the body baseline is authoritative.
_PLAIN_BODY_STYLE_MARKERS = ("normal", "body text", "bodytext", "正文", "默认")


def _normalize_sz(value) -> Optional[str]:
    """Normalize a half-point size value (`"24"`, `" 024"`, `24`) for comparison."""
    if value is None:
        return None
    try:
        return str(int(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _is_plain_body_style(paragraph) -> bool:
    """True for ordinary body copy (Normal / 正文 / Body Text), where the body baseline applies."""
    name = (getattr(getattr(paragraph, "style", None), "name", "") or "").strip().lower()
    if not name:
        return True
    return any(marker in name for marker in _PLAIN_BODY_STYLE_MARKERS)


def _is_heading_like(paragraph) -> bool:
    """
    True when `paragraph` is a heading/title/caption/TOC entry.

    These legitimately use sizes outside the body baseline, so comparing them to the body size
    would produce false positives. Heading-ness is decided by style name and `w:outlineLvl`,
    never by paragraph index or leading characters.
    """
    style = getattr(paragraph, "style", None)
    name = (getattr(style, "name", "") or "").strip().lower()
    if name and any(marker in name for marker in _SIZE_EXEMPT_STYLE_MARKERS):
        return True

    pPr = paragraph._p.pPr
    if pPr is not None and pPr.find(qn("w:outlineLvl")) is not None:
        return True

    visited = set()
    while style is not None and id(style) not in visited:
        visited.add(id(style))
        el = getattr(style, "element", None)
        if el is not None:
            style_pPr = el.find(qn("w:pPr"))
            if style_pPr is not None and style_pPr.find(qn("w:outlineLvl")) is not None:
                return True
        style = getattr(style, "base_style", None)
    return False


def _iter_unique_table_cells(doc):
    """Yield each physical table cell once (merged cells are reported repeatedly by python-docx)."""
    seen = set()
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                key = id(cell._tc)
                if key in seen:
                    continue
                seen.add(key)
                yield cell


def _body_run_pairs(doc):
    for p in doc.paragraphs:
        for r in p.runs:
            yield p, r


def _table_run_pairs(doc):
    for cell in _iter_unique_table_cells(doc):
        for p in cell.paragraphs:
            for r in p.runs:
                yield p, r


def _size_text_weights(pairs) -> Dict[str, int]:
    """Text-weighted size histogram, so one stray character cannot outvote a whole paragraph."""
    weights: Dict[str, int] = {}
    for p, r in pairs:
        text = (r.text or "").strip()
        if not text:
            continue
        size = _normalize_sz(resolve_run_effective_sz(r, p))
        if size is None:
            continue
        weights[size] = weights.get(size, 0) + len(text)
    return weights


def _dominant_size(weights: Dict[str, int]) -> Optional[str]:
    if not weights:
        return None
    return max(sorted(weights.items()), key=lambda kv: kv[1])[0]


def _document_body_baseline(doc) -> Optional[str]:
    """Dominant size of non-heading body text; falls back to all body text when every paragraph is a heading."""
    weights = _size_text_weights([(p, r) for p, r in _body_run_pairs(doc) if not _is_heading_like(p)])
    if not weights:
        weights = _size_text_weights(list(_body_run_pairs(doc)))
    return _dominant_size(weights)


def _document_size_inventory(doc) -> Set[str]:
    """Every size used anywhere in body paragraphs or table cells."""
    inventory = set(_size_text_weights(list(_body_run_pairs(doc))))
    inventory |= set(_size_text_weights(list(_table_run_pairs(doc))))
    return inventory


def _font_text_weights(pairs) -> Dict[Tuple[str, str], int]:
    """Text-weighted `(ascii, eastAsia)` font histogram."""
    weights: Dict[Tuple[str, str], int] = {}
    for p, r in pairs:
        text = (r.text or "").strip()
        if not text:
            continue
        ascii_font, east_asia = resolve_run_effective_font(r, p)
        key = ((ascii_font or "").strip(), (east_asia or "").strip())
        if not key[0] and not key[1]:
            continue
        weights[key] = weights.get(key, 0) + len(text)
    return weights


def _dominant_font(weights: Dict[Tuple[str, str], int]) -> Optional[Tuple[str, str]]:
    if not weights:
        return None
    return max(sorted(weights.items()), key=lambda kv: kv[1])[0]


def _table_pairs(tbl):
    for row in tbl.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for r in p.runs:
                    yield p, r


def _table_dominant_size(tbl) -> Optional[str]:
    return _dominant_size(_size_text_weights(list(_table_pairs(tbl))))


def _table_dominant_font(tbl) -> Optional[Tuple[str, str]]:
    return _dominant_font(_font_text_weights(list(_table_pairs(tbl))))


def _paragraph_size_set(paragraph) -> Set[str]:
    return set(_size_text_weights([(paragraph, run) for run in paragraph.runs]))


def _paragraph_dominant_size(paragraph) -> Optional[str]:
    return _dominant_size(_size_text_weights([(paragraph, run) for run in paragraph.runs]))


def _paragraph_font_keys(paragraph) -> Set[str]:
    keys = set()
    for (_ascii, east_asia), _weight in _font_text_weights([(paragraph, run) for run in paragraph.runs]).items():
        key = (east_asia or _ascii or "").strip()
        if key:
            keys.add(key)
    return keys


def _paragraph_dominant_font_key(paragraph) -> Optional[str]:
    weights = _font_text_weights([(paragraph, run) for run in paragraph.runs])
    for (ascii_font, east_asia), _weight in sorted(weights.items(), key=lambda item: item[1], reverse=True):
        key = (east_asia or ascii_font or "").strip()
        if key:
            return key
    return None


def _table_pagination_issues(tbl, ref_tbl, table_index: int) -> List[Dict[str, Any]]:
    """
    Compare row-level pagination attributes that tracked changes cannot express.

    Only reports drift the template actually proves: it never demands `w:cantSplit` or
    `w:tblHeader` on tables whose template does not use them.
    """
    issues: List[Dict[str, Any]] = []
    reference_rows = ref_tbl.rows
    if not reference_rows:
        return issues

    def _trpr_flag(row, tag: str) -> bool:
        trPr = row._tr.find(qn("w:trPr"))
        return trPr is not None and trPr.find(qn(tag)) is not None

    reference_all_cant_split = all(_trpr_flag(row, "w:cantSplit") for row in reference_rows)
    if reference_all_cant_split:
        missing = sum(1 for row in tbl.rows if not _trpr_flag(row, "w:cantSplit"))
        if missing:
            issues.append(_issue(
                "TABLE_PAGINATION_ANOMALY",
                f"missing_cant_split[{table_index}]",
                f"{missing}/{len(tbl.rows)} rows lack w:cantSplit while the template sets it on all rows",
            ))

    if _trpr_flag(reference_rows[0], "w:tblHeader"):
        if not tbl.rows or not _trpr_flag(tbl.rows[0], "w:tblHeader"):
            issues.append(_issue(
                "TABLE_PAGINATION_ANOMALY",
                f"missing_tbl_header[{table_index}]",
                "row 0 lacks w:tblHeader but the template marks it as a repeating header",
            ))

    return issues


def audit_format_and_text_qa(
    doc,
    forbidden_substrings: Optional[List[str]] = None,
    expected_body_sz: Optional[str] = None,
    docx_path: Optional[str] = None,
    reference_docx_path: Optional[str] = None,
    raise_on_failure: bool = True,
    comparison_profile: str = "REPLICA",
) -> Dict[str, Any]:
    """
    Verify:
    1. Zero residual red runs across paragraphs and tables.
    2. Every non-empty run in body paragraphs and table cells resolves to an effective size
       (explicit `w:sz` -> character style -> paragraph style chain -> `w:docDefaults`) that matches
       the baseline.
    3. Zero unreplaced template tokens (`{{...}}`, `【...】`, `***`) or `forbidden_substrings`.
    4. Zero missing `xml:space="preserve"` on runs with leading/trailing spaces and zero duplicate `w14:paraId` / `wp:docPr` IDs.
    5. If `docx_path` is provided, also runs `audit_docx_package_integrity(docx_path)` across all package parts.

    Size baseline priority: `expected_body_sz` -> `reference_docx_path` template body size ->
    this document's own dominant body size. Always pass the template as `reference_docx_path`:
    a document that drifted uniformly has no internal inconsistency to detect, so a self-baseline
    cannot prove anything and is reported as such via `size_baseline_source`.

    Failures raise `QAValidationError` (a `ValueError`) when `raise_on_failure=True`, otherwise
    the report returns `passed: False` plus a structured `issues` list.
    """
    forbidden_substrings = forbidden_substrings or []
    red_Wait_residuals = []
    size_anomalies = []
    font_anomalies = []
    table_style_anomalies = []
    pagination_anomalies: List[Dict[str, Any]] = []
    text_residuals = []
    missing_space_preserve = []
    duplicate_ids = []

    reference_inventory: Set[str] = set()
    reference_baseline = None
    reference_font_inventory: Set[Tuple[str, str]] = set()
    reference_tables: List[Any] = []
    profile = resolve_comparison_profile(
        comparison_profile, reference_provided=bool(reference_docx_path)
    )
    paragraph_matches: Dict[int, int] = {}
    new_paragraphs: List[int] = []
    removed_paragraphs: List[int] = []
    new_tables: List[int] = []
    removed_tables: List[int] = []
    matched_reference_tables: Dict[int, Any] = {}
    ref_doc = None
    if reference_docx_path and os.path.isfile(reference_docx_path):
        ref_doc = docx.Document(reference_docx_path)
        reference_inventory = _document_size_inventory(ref_doc)
        reference_baseline = _document_body_baseline(ref_doc)
        reference_font_inventory = set(_font_text_weights(list(_body_run_pairs(ref_doc))))
        reference_font_inventory |= set(_font_text_weights(list(_table_run_pairs(ref_doc))))
        reference_tables = list(ref_doc.tables)
        paragraph_alignment = align_paragraphs(doc.paragraphs, ref_doc.paragraphs)
        paragraph_matches = dict(paragraph_alignment["matches"])
        new_paragraphs = list(paragraph_alignment["unmatched_output"])
        removed_paragraphs = list(paragraph_alignment["unmatched_reference"])
        table_alignment = align_tables(doc.tables, ref_doc.tables)
        matched_reference_tables = {
            out_index: reference_tables[ref_index]
            for out_index, ref_index in table_alignment["matches"].items()
        }
        new_tables = list(table_alignment["unmatched_output"])
        removed_tables = list(table_alignment["unmatched_reference"])

    if expected_body_sz is not None:
        baseline_sz = _normalize_sz(expected_body_sz) or str(expected_body_sz).strip()
        baseline_source = "explicit_expected_body_sz"
    elif reference_baseline:
        baseline_sz = reference_baseline
        baseline_source = "reference_template"
    else:
        baseline_sz = _document_body_baseline(doc)
        baseline_source = "output_dominant_body_size"

    table_baseline = _dominant_size(_size_text_weights(list(_table_run_pairs(doc))))

    for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
        p = ctx["paragraph"]
        p_el = ctx["p_el"]
        location = ctx["location_id"]
        for r_el in p_el.iter(qn("w:r")):
            text = "".join((node.text or "") for node in r_el.iter(qn("w:t"))).strip()
            if text and is_red_run(r_el, p):
                red_Wait_residuals.append((location, text[:40]))

    for i, p in enumerate(doc.paragraphs):
        txt = p.text.strip()
        if not txt:
            continue
        for sub in forbidden_substrings:
            if sub in txt:
                text_residuals.append(("body_p", i, sub))
        for tok in TOKEN_PATTERN.findall(txt):
            text_residuals.append(("body_p_token", i, tok))

        heading_like = _is_heading_like(p)
        plain_body = _is_plain_body_style(p)
        if profile == "STYLE_GUIDE" and ref_doc is not None:
            ref_index = paragraph_matches.get(i)
            if ref_index is None:
                # New content has no template paragraph to compare against; its style is
                # validated by the style guide role, not by an unrelated neighbour.
                continue
            ref_paragraph = ref_doc.paragraphs[ref_index]
            out_dominant = _paragraph_dominant_size(p)
            ref_dominant = _paragraph_dominant_size(ref_paragraph)
            if out_dominant and ref_dominant and out_dominant != ref_dominant:
                size_anomalies.append(("body_p", i, out_dominant, ref_dominant, txt[:30]))
            out_font = _paragraph_dominant_font_key(p)
            ref_fonts = _paragraph_font_keys(ref_paragraph)
            if out_font and ref_fonts and out_font not in ref_fonts and not heading_like:
                font_anomalies.append(("body_p", i, out_font, sorted(ref_fonts), txt[:30]))
            continue

        for r in p.runs:
            run_text = (r.text or "").strip()
            if not run_text:
                continue
            run_sz = _normalize_sz(resolve_run_effective_sz(r, p))
            if run_sz is None:
                continue
            if reference_inventory and run_sz not in reference_inventory:
                size_anomalies.append(("body_p_not_in_template", i, run_sz, run_text[:30]))
            elif not heading_like and plain_body and baseline_sz and run_sz != baseline_sz:
                size_anomalies.append(("body_p", i, run_sz, baseline_sz, run_text[:30]))

            if reference_font_inventory and not heading_like:
                font = resolve_run_effective_font(r, p)
                east_asia = (font[1] or "").strip()
                known_east_asia = {ea for (_ascii, ea) in reference_font_inventory if ea}
                if east_asia and known_east_asia and east_asia not in known_east_asia:
                    font_anomalies.append(("body_p", i, east_asia, sorted(known_east_asia), run_text[:30]))

    for t_i, tbl in enumerate(doc.tables):
        ref_tbl = matched_reference_tables.get(t_i)
        for r_i, row in enumerate(tbl.rows):
            for c_i, cell in enumerate(row.cells):
                txt = cell.text.strip()
                for sub in forbidden_substrings:
                    if sub in txt:
                        text_residuals.append(("table", t_i, r_i, c_i, sub))
                for tok in TOKEN_PATTERN.findall(txt):
                    text_residuals.append(("table_token", t_i, r_i, c_i, tok))
                if profile == "REPLICA" or not reference_docx_path:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            run_text = (r.text or "").strip()
                            if not run_text:
                                continue
                            run_sz = _normalize_sz(resolve_run_effective_sz(r, p))
                            if run_sz is None:
                                continue
                            if reference_inventory:
                                if run_sz not in reference_inventory:
                                    size_anomalies.append(("table_not_in_template", t_i, r_i, c_i, run_sz, run_text[:30]))
                            elif table_baseline and run_sz != table_baseline and not _is_heading_like(p):
                                size_anomalies.append(("table", t_i, r_i, c_i, run_sz, table_baseline, run_text[:30]))

        if ref_tbl is not None:
            # Compare against the same table instead of a document-wide allowlist: a table
            # regenerated at a larger size still uses a size the template used somewhere else.
            out_size = _table_dominant_size(tbl)
            ref_size = _table_dominant_size(ref_tbl)
            if out_size and ref_size and out_size != ref_size:
                size_anomalies.append(("table_dominant_size", t_i, out_size, ref_size))

            out_font = _table_dominant_font(tbl)
            ref_font = _table_dominant_font(ref_tbl)
            if out_font and ref_font and out_font[1] and ref_font[1] and out_font[1] != ref_font[1]:
                font_anomalies.append(("table_dominant_font", t_i, out_font[1], ref_font[1]))

            table_style_anomalies.extend(
                compare_table_style(table_style_signature(tbl), table_style_signature(ref_tbl), t_i)
            )
            pagination_anomalies.extend(_table_pagination_issues(tbl, ref_tbl, t_i))

    if profile == "REPLICA" and reference_tables and len(doc.tables) < len(reference_tables):
        table_style_anomalies.append(("table_count", len(doc.tables), len(reference_tables)))

    for idx, t_el in enumerate(doc.element.body.xpath(".//w:t")):
        t_val = t_el.text or ""
        if (t_val.startswith(" ") or t_val.endswith(" ") or "  " in t_val) and t_el.get("{http://www.w3.org/XML/1998/namespace}space") != "preserve":
            missing_space_preserve.append(("w:t", idx, repr(t_val[:20])))

    # Findings the read-only template already carries cannot be fixed by a fill and
    # must not block it; report them as a disclosed warning instead.
    inherited_space_preserve = 0
    baseline_space_preserve = None
    if ref_doc is not None and missing_space_preserve:
        baseline_space_preserve = _count_missing_space_preserve(ref_doc)
        if baseline_space_preserve > 0 and len(missing_space_preserve) <= baseline_space_preserve:
            inherited_space_preserve = len(missing_space_preserve)
            missing_space_preserve = []

    seen_para_ids = set()
    w14_para_id_attr = "{http://schemas.microsoft.com/office/word/2010/wordml}paraId"
    for p_el in doc.element.body.xpath(".//w:p"):
        pid = p_el.get(w14_para_id_attr)
        if pid:
            if pid in seen_para_ids:
                duplicate_ids.append(("w14:paraId", pid))
            seen_para_ids.add(pid)

    seen_docpr_ids = set()
    for docPr in doc.element.body.xpath(".//wp:docPr"):
        did = docPr.get("id")
        if did:
            if did in seen_docpr_ids:
                duplicate_ids.append(("wp:docPr", did))
            seen_docpr_ids.add(did)

    package_report = None
    package_issues: List[Dict[str, Any]] = []
    if docx_path and os.path.isfile(docx_path):
        package_report = audit_docx_package_integrity(
            docx_path, baseline_path=reference_docx_path
        )
        if not package_report["passed"]:
            package_issues = list(package_report.get("structured_issues") or [])
            if raise_on_failure:
                raise QAValidationError(f"DOCX Package Integrity QA failed: {package_report}")

    issues: List[Dict[str, Any]] = []
    issues.extend(_red_issues(red_Wait_residuals))
    issues.extend(_size_issues(size_anomalies, profile))
    issues.extend(_font_issues(font_anomalies))
    issues.extend(_table_issues(table_style_anomalies, profile))
    issues.extend(pagination_anomalies)
    issues.extend(_text_issues(text_residuals))
    issues.extend(package_issues)
    issues.extend(_issue("XML_SPACE_MISSING", "w:t", item) for item in missing_space_preserve)
    if inherited_space_preserve:
        issues.append(
            _issue(
                "XML_SPACE_MISSING",
                "w:t",
                "%d run(s) lack xml:space but the template baseline already carries %d"
                % (inherited_space_preserve, baseline_space_preserve),
                severity="medium",
            )
        )
    issues.extend(_issue("DUPLICATE_OOXML_ID", item[0], item[1]) for item in duplicate_ids)

    blocking, warnings, _pending = split_issues(issues)

    if blocking and raise_on_failure:
        raise QAValidationError(
            "Format QA failed with %d blocking issue(s) (%d total):\n" % (len(blocking), len(issues))
            + "\n".join(
                f"{item['code']} at {item['location']}: {item['detail']}" for item in issues[:10]
            )
        )

    return {
        "passed": not blocking,
        "issues": issues,
        "structured_issues": issues,
        "warnings": warnings,
        "warning_count": len(warnings),
        "blocking_issue_count": len(blocking),
        "comparison_profile": profile,
        "alignment": {
            "matched_paragraphs": len(paragraph_matches),
            "new_paragraphs": new_paragraphs,
            "removed_paragraphs": removed_paragraphs,
            "new_tables": new_tables,
            "removed_tables": removed_tables,
        },
        "red_residuals": red_Wait_residuals,
        "size_anomalies": size_anomalies,
        "font_anomalies": font_anomalies,
        "table_style_anomalies": table_style_anomalies,
        "pagination_anomalies": pagination_anomalies,
        "size_baseline": baseline_sz,
        "size_baseline_source": baseline_source,
        "table_size_baseline": table_baseline,
        "template_sizes": sorted(reference_inventory, key=lambda v: int(v)) if reference_inventory else [],
        "template_fonts": sorted({ea for (_ascii, ea) in reference_font_inventory if ea}),
        "text_residuals": text_residuals,
        "missing_space_preserve": missing_space_preserve,
        "inherited_space_preserve": inherited_space_preserve,
        "baseline_space_preserve": baseline_space_preserve,
        "duplicate_ids": duplicate_ids,
        "package_integrity": package_report,
        "coverage_gaps": [],
        "unverified_count": 0,
    }


def _collect_declared_font_names(doc) -> Set[str]:
    """Font family names explicitly declared in body, styles defaults, headers and footers."""
    fonts: Set[str] = set()
    containers = [doc.element.body]
    try:
        containers.append(doc.styles.element)
    except Exception:
        pass
    for section in doc.sections:
        for hf in (
            getattr(section, "header", None),
            getattr(section, "footer", None),
            getattr(section, "first_page_header", None),
            getattr(section, "first_page_footer", None),
            getattr(section, "even_page_header", None),
            getattr(section, "even_page_footer", None),
        ):
            try:
                # ``hf._element`` lazily materializes a phantom part for linked
                # headers/footers; skip them before any content access.
                if hf is not None and not hf.is_linked_to_previous:
                    containers.append(hf._element)
            except Exception:
                continue
    for container in containers:
        for el in container.iter(qn("w:rFonts")):
            for attr in ("w:ascii", "w:eastAsia", "w:hAnsi", "w:cs"):
                value = el.get(qn(attr))
                if value and not value.lower().endswith("theme"):
                    fonts.add(value)
    return fonts


_FONT_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")

# Windows registers many CJK families under their English name (SimHei, FangSong,
# SimSun) while documents declare the Chinese family name. Without an alias table,
# `黑体` is reported missing even though SimHei is installed.
_FONT_ALIASES = {
    "simhei": "黑体",
    "黑体": "黑体",
    "simsun": "宋体",
    "宋体": "宋体",
    "songtisc": "宋体",
    "stsong": "宋体",
    "fangsong": "仿宋",
    "仿宋": "仿宋",
    "fangsong_gb2312": "仿宋_gb2312",
    "仿宋_gb2312": "仿宋_gb2312",
    "kaiti": "楷体",
    "楷体": "楷体",
    "microsoftyahei": "微软雅黑",
    "微软雅黑": "微软雅黑",
    "stzhongsong": "华文中宋",
    "华文中宋": "华文中宋",
    "stfangsong": "华文仿宋",
    "华文仿宋": "华文仿宋",
    # Legacy Word family names that Windows exposes under their modern alias.
    "courier": "couriernew",
    "couriernew": "couriernew",
}


def _canonical_font_name(name: str) -> str:
    value = str(name or "").strip().lower()
    value = _FONT_SUFFIX_RE.sub("", value)
    parts = [part.strip() for part in re.split(r"[&,，]", value) if part.strip()]
    for part in parts or [value]:
        compact = re.sub(r"\s+", "", part)
        if compact in _FONT_ALIASES:
            return _FONT_ALIASES[compact]
        # Keep the first family for multi-name entries (`SimHei & SimHei UI`).
        return compact
    return ""


def _installed_font_names() -> Tuple[Set[str], str]:
    if os.name == "nt":
        try:
            import winreg

            names: Set[str] = set()
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
                except OSError:
                    continue
                with key:
                    index = 0
                    while True:
                        try:
                            display_name, _value, _type = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        names.add(str(display_name).lower())
            if names:
                return names, "windows_registry"
        except Exception:
            pass
        return set(), "none"
    try:
        proc = subprocess.run(
            ["fc-list", ":", "family"], capture_output=True, text=True, timeout=10, check=False
        )
        if proc.returncode == 0:
            names = set()
            for line in proc.stdout.splitlines():
                for family in line.split(","):
                    family = family.strip().lower()
                    if family:
                        names.add(family)
            if names:
                return names, "fontconfig"
    except Exception:
        pass
    return set(), "none"


def check_font_availability(font_names) -> Dict[str, Any]:
    """
    Check whether the fonts a document declares exist on this machine.

    Renderers silently substitute missing fonts, which is a frequent cause of
    "output looks different from the template" reports. Environments where fonts
    cannot be verified are reported via `checked: False` instead of being
    silently treated as installed.
    """
    requested = sorted({str(name) for name in font_names if name})
    installed, source = _installed_font_names()
    if source == "none":
        return {
            "checked": False,
            "source": source,
            "installed_count": 0,
            "missing": [],
            "requested": requested,
        }

    installed_canonical = {_canonical_font_name(name) for name in installed}
    missing = [font for font in requested if _canonical_font_name(font) not in installed_canonical]
    return {
        "checked": True,
        "source": source,
        "installed_count": len(installed),
        "missing": missing,
        "requested": requested,
    }


def _convert_docx_to_pdf(soffice_bin: str, docx_path: str, out_dir: str) -> Tuple[Optional[str], Optional[str]]:
    os.makedirs(out_dir, exist_ok=True)
    try:
        proc = subprocess.run(
            [soffice_bin, "--headless", "--convert-to", "pdf", "--outdir", out_dir, docx_path],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        candidate = os.path.join(out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
        if proc.returncode == 0 and os.path.isfile(candidate):
            return candidate, None
        detail = (proc.stderr or proc.stdout or "PDF output file was not created").strip()
        return None, f"exit={proc.returncode}: {detail}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def run_visual_layout_qa(
    docx_path: str,
    reference_docx_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    comparison_profile: str = "REPLICA",
) -> Dict[str, Any]:
    """
    Visual Layout QA Module (v3.0):
    1. Checks structural layout metrics directly from the OOXML package (image aspect ratio distortion,
       table width vs printable page width overflow, pagination protection coverage).
    2. Optionally converts `docx_path` to PDF using LibreOffice (`soffice --headless --convert-to pdf`)
       if installed in PATH, verifying page count and rendering health.
    """
    doc = docx.Document(docx_path)
    layout_warnings: List[str] = []

    # 1. Check printable page width vs explicit table cell widths
    printable_width_twips = 9026  # Default A4 portrait printable width (~15.92 cm)
    if doc.sections:
        sec0 = doc.sections[0]
        if sec0.page_width and sec0.left_margin and sec0.right_margin:
            printable_width_twips = int(sec0.page_width.twips - sec0.left_margin.twips - sec0.right_margin.twips)

    ref_table_widths: Dict[int, int] = {}
    output_to_reference_table: Dict[int, int] = {}
    if reference_docx_path and os.path.isfile(reference_docx_path):
        try:
            ref_doc = docx.Document(reference_docx_path)
            for rt_idx, rtbl in enumerate(ref_doc.tables):
                ref_table_widths[rt_idx] = sum(
                    int(gc.get(qn("w:w")))
                    for gc in rtbl._tbl.xpath("./w:tblGrid/w:gridCol")
                    if (gc.get(qn("w:w")) or "").isdigit()
                )
            output_to_reference_table = align_tables(doc.tables, ref_doc.tables)["matches"]
        except Exception:
            pass

    for t_idx, tbl in enumerate(doc.tables):
        grid_cols = tbl._tbl.xpath("./w:tblGrid/w:gridCol")
        total_grid_twips = 0
        for gc in grid_cols:
            w_val = gc.get(qn("w:w"))
            if w_val and w_val.isdigit():
                total_grid_twips += int(w_val)
        # Skip false-positive overflow if table width matches the template table this
        # output table was actually aligned to (not merely the same list index).
        ref_index = output_to_reference_table.get(t_idx)
        if ref_index is not None and ref_table_widths.get(ref_index) == total_grid_twips:
            continue
        if total_grid_twips > printable_width_twips * 1.08:
            layout_warnings.append(
                f"Table[{t_idx}] grid width ({total_grid_twips} twips) exceeds printable width ({printable_width_twips} twips) by >8%"
            )

    # 2. Check inline image aspect ratio vs actual image pixel aspect ratio
    from PIL import Image
    import io

    for p_idx, p in enumerate(doc.paragraphs):
        blips = p._p.xpath(".//a:blip")
        extents = p._p.xpath(".//wp:extent")
        if blips and extents:
            rId = blips[0].get(qn("r:embed"))
            cx = int(extents[0].get("cx") or 0)
            cy = int(extents[0].get("cy") or 0)
            if rId and cx > 0 and cy > 0 and rId in doc.part.related_parts:
                part = doc.part.related_parts[rId]
                try:
                    with Image.open(io.BytesIO(part._blob)) as im:
                        px_w, px_h = im.size
                    if px_w > 0 and px_h > 0:
                        box_ratio = cx / float(cy)
                        img_ratio = px_w / float(px_h)
                        rel_diff = abs(box_ratio - img_ratio) / max(box_ratio, img_ratio)
                        if rel_diff > 0.20:
                            layout_warnings.append(
                                f"Paragraph[{p_idx}] image {rId} aspect ratio mismatch: frame={box_ratio:.2f}, bitmap={img_ratio:.2f}"
                            )
                except Exception:
                    pass

    # 3. PDF conversion (WPS word2pdf preferred on Windows, LibreOffice otherwise)
    profile = resolve_comparison_profile(
        comparison_profile, reference_provided=bool(reference_docx_path)
    )
    backend = find_pdf_backend()
    pdf_backend_name = backend.get("name") or "none"
    work_dir = output_dir or tempfile.mkdtemp(prefix="visual_qa_")
    output_pdf_dir = os.path.join(work_dir, "output_pdf")
    reference_pdf_dir = os.path.join(work_dir, "reference_pdf")
    pdf_generated = False
    pdf_path = None
    ref_pdf_path = None
    pdf_conversion_errors: Dict[str, str] = {}
    page_diff_available = False
    page_count_available = False
    page_count_source: Optional[str] = None
    page_count_error: Optional[str] = None
    page_count_mismatch: Optional[Tuple[int, int]] = None
    page_diffs: List[Tuple[int, float]] = []
    page_diff_error: Optional[str] = None
    pages_compared = 0
    pages_total = 0
    page_diff_partial = False
    if pdf_backend_name != "none":
        if pdf_backend_name == "libreoffice":
            pdf_path, conversion_error = _convert_docx_to_pdf(
                backend.get("executable"), docx_path, output_pdf_dir
            )
            used_backend = "libreoffice"
        else:
            pdf_path, conversion_error, used_backend = convert_docx_to_pdf(
                docx_path, output_pdf_dir, backend
            )
        pdf_backend_name = used_backend or pdf_backend_name
        if conversion_error:
            pdf_conversion_errors["output"] = conversion_error
        pdf_generated = pdf_path is not None
        if reference_docx_path and os.path.isfile(reference_docx_path) and pdf_generated:
            if pdf_backend_name == "libreoffice":
                ref_pdf_path, conversion_error = _convert_docx_to_pdf(
                    backend.get("executable"), reference_docx_path, reference_pdf_dir
                )
                used_backend = "libreoffice"
            else:
                ref_pdf_path, conversion_error, used_backend = convert_docx_to_pdf(
                    reference_docx_path, reference_pdf_dir, backend
                )
            pdf_backend_name = used_backend or pdf_backend_name
            if conversion_error:
                pdf_conversion_errors["reference"] = conversion_error
            if ref_pdf_path is not None:
                try:
                    import fitz  # PyMuPDF, optional rendering dependency
                except ImportError as exc:
                    fitz = None
                    page_diff_error = f"PyMuPDF unavailable: {exc}"
                if fitz is not None:
                    out_pdf = None
                    ref_pdf = None
                    try:
                        out_pdf = fitz.open(pdf_path)
                        ref_pdf = fitz.open(ref_pdf_path)
                        page_count_available = True
                        page_count_source = "pymupdf"
                        if out_pdf.page_count != ref_pdf.page_count:
                            page_count_mismatch = (ref_pdf.page_count, out_pdf.page_count)
                        pages_total = min(out_pdf.page_count, ref_pdf.page_count)
                        pages_compared = min(pages_total, 10)
                        page_diff_partial = pages_total > pages_compared
                        for page_index in range(pages_compared):
                            out_pix = out_pdf[page_index].get_pixmap(matrix=fitz.Matrix(1, 1), colorspace=fitz.csGRAY)
                            ref_pix = ref_pdf[page_index].get_pixmap(matrix=fitz.Matrix(1, 1), colorspace=fitz.csGRAY)
                            if (out_pix.width, out_pix.height) != (ref_pix.width, ref_pix.height):
                                page_diffs.append((page_index, 1.0))
                                continue
                            diff_count = sum(1 for a, b in zip(out_pix.samples, ref_pix.samples, strict=False) if abs(a - b) > 24)
                            ratio = diff_count / max(len(out_pix.samples), 1)
                            if ratio > 0.02:
                                page_diffs.append((page_index, round(ratio, 4)))
                        page_diff_available = True
                    except Exception as exc:
                        page_diff_error = f"{type(exc).__name__}: {exc}"
                    finally:
                        if out_pdf is not None:
                            out_pdf.close()
                        if ref_pdf is not None:
                            ref_pdf.close()

    # Page count does not need PyMuPDF: WPS pdfinfo returns the real pagination.
    if pdf_generated and ref_pdf_path and page_count_mismatch is None:
        out_count, out_source, out_error = pdf_page_count(pdf_path, backend)
        ref_count, ref_source, ref_error = pdf_page_count(ref_pdf_path, backend)
        page_count_source = out_source or ref_source
        if out_count is not None and ref_count is not None:
            page_count_available = True
            if out_count != ref_count:
                page_count_mismatch = (ref_count, out_count)
        else:
            page_count_error = out_error or ref_error or "PDF page count unavailable"

    # 4. Font availability: missing fonts make renderers substitute silently
    font_report = check_font_availability(_collect_declared_font_names(doc))

    # 5. Layout fingerprint comparison (content-independent): this is the primary
    #    layout signal; pixel diff below is only a secondary renderer check.
    layout_report = None
    if reference_docx_path and os.path.isfile(reference_docx_path):
        try:
            from .layout_qa import compare_layout_fingerprints
            layout_report = compare_layout_fingerprints(
                docx_path, reference_docx_path, comparison_profile=comparison_profile
            )
        except Exception:
            layout_report = {
                "passed": False,
                "issues": [],
                "coverage_gaps": ["LAYOUT_FINGERPRINT_UNAVAILABLE"],
            }

    structured_issues = [_issue("VISUAL_LAYOUT_WARNING", "layout", item, severity="medium") for item in layout_warnings]
    if layout_report:
        structured_issues.extend(layout_report.get("issues") or [])
    if page_count_mismatch is not None:
        structured_issues.append(_issue(
            "RENDER_PAGE_COUNT_MISMATCH",
            "pdf",
            f"reference pages={page_count_mismatch[0]}, output pages={page_count_mismatch[1]}",
            severity="high" if profile == "REPLICA" else "medium",
        ))
    for page_index, ratio in page_diffs:
        structured_issues.append(_issue("RENDER_PAGE_PIXEL_DIFF", f"pdf.page[{page_index}]", f"pixel difference ratio={ratio:.4f}", severity="medium"))
    if page_diff_partial:
        structured_issues.append(_issue("PDF_PAGE_DIFF_PARTIAL", "pdf", f"compared {pages_compared} of {pages_total} overlapping pages", severity="medium"))
    if font_report["checked"]:
        for font in font_report["missing"]:
            structured_issues.append(_issue("FONT_NOT_INSTALLED", f"font:{font}", "font is declared in the document but not installed; renderers will substitute it", severity="medium"))

    coverage_gaps: List[str] = list((layout_report or {}).get("coverage_gaps") or [])
    if reference_docx_path is None:
        coverage_gaps.append("REFERENCE_LAYOUT_NOT_PROVIDED")
    elif not os.path.isfile(reference_docx_path):
        coverage_gaps.append("REFERENCE_DOCX_NOT_FOUND")
    if not pdf_generated:
        coverage_gaps.append("RENDER_PDF_NOT_PRODUCED")
    if reference_docx_path and os.path.isfile(reference_docx_path):
        if pdf_generated and ref_pdf_path is None:
            coverage_gaps.append("REFERENCE_PDF_NOT_PRODUCED")
        elif pdf_generated and ref_pdf_path and not page_diff_available:
            coverage_gaps.append("PDF_PAGE_DIFF_UNAVAILABLE")
        if pdf_generated and ref_pdf_path and not page_count_available:
            coverage_gaps.append("PDF_PAGE_COUNT_UNVERIFIED")
    if not font_report["checked"]:
        coverage_gaps.append("FONT_AVAILABILITY_UNVERIFIED")
    coverage_gaps = list(dict.fromkeys(coverage_gaps))
    blocking, warnings, _pending = split_issues(structured_issues)

    return {
        "passed": not blocking,
        "issues": structured_issues,
        "structured_issues": structured_issues,
        "warnings": warnings,
        "warning_count": len(warnings),
        "blocking_issue_count": len(blocking),
        "comparison_profile": profile,
        "printable_width_twips": printable_width_twips,
        "layout_warnings": layout_warnings,
        "pdf_rendered": pdf_generated,
        "pdf_backend": pdf_backend_name,
        "pdf_path": pdf_path,
        "reference_pdf_path": ref_pdf_path,
        "pdf_conversion_errors": pdf_conversion_errors,
        "page_diff_available": page_diff_available,
        "page_diff_error": page_diff_error,
        "page_count_available": page_count_available,
        "page_count_source": page_count_source,
        "page_count_error": page_count_error,
        "page_diff_coverage": {"pages_compared": pages_compared, "pages_total": pages_total, "partial": page_diff_partial},
        "page_count_mismatch": page_count_mismatch,
        "page_diffs": page_diffs,
        "font_availability": font_report,
        "layout_fingerprint": layout_report,
        "coverage_gaps": coverage_gaps,
        "unverified_count": len(coverage_gaps),
    }
