# -*- coding: utf-8 -*-
"""Full QA runner for QAReport 4.0 (Contract 04).

``run_full_qa`` inspects the staged artifact re-read from disk; it never trusts
an in-memory generator object and never writes to the staged path.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List, Optional

import docx
from docx.oxml.ns import qn

from engine import (
    audit_content_consistency,
    audit_docx_package_integrity,
    audit_fact_sources,
    audit_format_and_text_qa,
    audit_review_integrity,
    iter_all_document_paragraphs_with_Wait_context,
    run_visual_layout_qa,
)
from engine.ooxml_utils import TOKEN_PATTERN, is_red_run

from .environment import capability_matrix
from .gate import resolve_required_checks
from .report_builder import build_qa_report, check_record

_SEVERITIES = frozenset({"high", "medium", "low"})

# Required capabilities a check cannot produce a verdict without.  Optional
# capabilities (pixel diff, OCR, chart rendering) are deliberately absent: their
# gaps stay local to the check evidence and never demote a required verdict.
_CHECK_CAPABILITY_DEPENDENCIES = {
    "PACKAGE": ("docx_parse",),
    "FORMAT": ("docx_parse",),
    "FIDELITY": ("docx_parse",),
    "CONTENT": ("docx_parse",),
    "REVIEW_INTEGRITY": ("docx_parse",),
    "VISUAL_PAGE_COUNT": ("docx_parse", "wps_pdf_render", "pdf_page_analysis"),
}

# Optional capabilities that only add secondary visual evidence.
_VISUAL_OPTIONAL_CAPABILITIES = ("pixel_visual_diff", "ocr")


def _severity(value: Any) -> str:
    severity = str(value or "high").strip().lower()
    return severity if severity in _SEVERITIES else "high"


def _section_issues(section: Any) -> List[Any]:
    if not isinstance(section, dict):
        return []
    structured = section.get("structured_issues")
    if isinstance(structured, list):
        return structured
    plain = section.get("issues")
    return plain if isinstance(plain, list) else []


def _to_contract_issue(item: Any, check_id: str) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    code = str(item.get("code") or "").strip()
    if not code:
        return None
    severity = _severity(item.get("severity"))
    return {
        "code": code,
        "severity": severity,
        "location": str(item.get("location") or check_id),
        "detail": str(item.get("detail") or code),
        "blocking": severity == "high",
        "check_id": check_id,
    }


def _absorb(
    section: Any,
    check_id: str,
    issues: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    coverage_gaps: List[str],
) -> None:
    """Map a section report: high findings block, medium/low become warnings."""
    for item in _section_issues(section):
        record = _to_contract_issue(item, check_id)
        if record is None:
            continue
        if record["severity"] == "high":
            issues.append(record)
        else:
            warnings.append(
                {
                    "code": record["code"],
                    "severity": record["severity"],
                    "detail": record["detail"],
                }
            )
    for gap in _section_gaps(section):
        text = str(gap).strip()
        if text:
            coverage_gaps.append(text)


def _section_gaps(section: Any) -> List[Any]:
    if not isinstance(section, dict):
        return []
    gaps = section.get("coverage_gaps")
    return gaps if isinstance(gaps, list) else []


def _ensure_failure_issue(
    check_id: str,
    status: str,
    issues: List[Dict[str, Any]],
    detail: str,
) -> None:
    """A FAILED check must carry a blocking issue; otherwise the report is invalid."""
    if status != "FAILED":
        return
    if any(item.get("check_id") == check_id and item.get("severity") == "high" for item in issues):
        return
    issues.append(
        {
            "code": "%s_CHECK_FAILED" % check_id,
            "severity": "high",
            "location": check_id,
            "detail": detail or "%s reported failure" % check_id,
            "blocking": True,
            "check_id": check_id,
        }
    )


def _spec_protected_texts(doc, spec: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """Header/footer texts that belong to explicit protected regions.

    A header paragraph that carries a fillable slot is not a protected region, so
    its text must not enter the protected fingerprint; otherwise filling the slot
    would be reported as an unauthorized template change.
    """
    if not isinstance(spec, dict):
        return None
    locations = {
        region["location_id"]
        for region in spec.get("protected_regions", [])
        if isinstance(region, dict)
        and region.get("kind") in ("header", "footer", "logo", "stamp")
        and isinstance(region.get("location_id"), str)
    }
    if not locations:
        return []
    texts: List[str] = []
    for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
        if ctx["location_id"] in locations:
            text = (ctx["paragraph"].text or "").strip()
            if text:
                texts.append(text)
    return texts


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


_OPTIONAL_VISUAL_GAPS = frozenset(
    {
        "PDF_PAGE_DIFF_UNAVAILABLE",
        "PDF_PAGE_DIFF_PARTIAL",
        "FONT_AVAILABILITY_UNVERIFIED",
        "LAYOUT_FINGERPRINT_UNAVAILABLE",
    }
)


def _has_image_ops(fill_plan: Any) -> bool:
    """True when the execution plan authorizes an image replacement."""
    if not isinstance(fill_plan, dict):
        return False
    operations = fill_plan.get("operations")
    if not isinstance(operations, list):
        return False
    return any(
        isinstance(operation, dict) and operation.get("type") == "replace_image"
        for operation in operations
    )


def _attempted_body_paragraphs(fill_plan: Any) -> set:
    indexes = set()
    if not isinstance(fill_plan, dict):
        return indexes
    for operation in fill_plan.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        location = (operation.get("target") or {}).get("location_id")
        if not isinstance(location, str):
            continue
        match = re.fullmatch(r"body\.p\[(\d+)\]", location)
        if match:
            indexes.add(int(match.group(1)))
    return indexes


def _attempted_locations(fill_plan: Any) -> set:
    """Every location_id a FillPlan operation targeted, verbatim."""
    locations = set()
    if not isinstance(fill_plan, dict):
        return locations
    for operation in fill_plan.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        location = (operation.get("target") or {}).get("location_id")
        if isinstance(location, str) and location:
            locations.add(location)
    return locations


def _template_red_texts(template: Optional[str]) -> set:
    """Truncated red-run texts the template already contained.

    Mirrors the residual scanner's extraction (text[:40]) so comparison against
    a RED_TEXT_RESIDUAL detail is exact.  Scan failures return an empty set:
    without positive evidence of inheritance nothing is ever downgraded.
    """
    if not template:
        return set()
    try:
        document = docx.Document(template)
    except Exception:
        return set()
    texts = set()
    for ctx in iter_all_document_paragraphs_with_Wait_context(document):
        p_el = ctx["p_el"]
        for r_el in p_el.iter(qn("w:r")):
            text = "".join((node.text or "") for node in r_el.iter(qn("w:t"))).strip()
            if text and is_red_run(r_el, ctx["paragraph"]):
                texts.add(text[:40])
    return texts


def _template_tokens(template: Optional[str]) -> set:
    if not template:
        return set()
    try:
        document = docx.Document(template)
    except Exception:
        return set()
    tokens = set()
    for paragraph in document.paragraphs:
        tokens.update(TOKEN_PATTERN.findall(paragraph.text))
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                tokens.update(TOKEN_PATTERN.findall(cell.text))
    return tokens


def _slot_matched_texts(spec: Any) -> set:
    """``matched_text`` of every fillable (non-PROTECTED) slot in the spec.

    A template token that was never registered as a slot — e.g. an exam paper's
    underscore blanks ``___________`` that are legitimate content, not
    placeholders — must not block a commit. Only a token the plan actually
    undertook to clear (a registered slot whose paragraph was targeted) stays
    blocking when it survives the fill.
    """
    if not isinstance(spec, dict):
        return set()
    texts = set()
    for slot in spec.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        if slot.get("protection_status") == "PROTECTED":
            continue
        matched = slot.get("matched_text")
        if isinstance(matched, str) and matched:
            texts.add(matched)
    return texts


def _adjust_inherited_residuals(
    formatting: Any, template: Optional[str], fill_plan: Any, spec: Any = None
) -> tuple:
    """Separate untouched template content from what this fill failed to clear.

    A slot the FillPlan targeted and left unfilled stays blocking. A blank or a
    red run that the template already had and no operation targeted is a
    disclosed warning: leaving an unbound conditional field — or the template's
    own red-emphasis content — untouched is the contract-correct behaviour, not
    a fill defect. A template token that is not the ``matched_text`` of any
    fillable slot is inherited content even when its paragraph was attempted.
    """
    if not isinstance(formatting, dict):
        return formatting, []
    tokens = _template_tokens(template)
    red_texts = _template_red_texts(template)
    attempted = _attempted_body_paragraphs(fill_plan)
    attempted_locations = _attempted_locations(fill_plan)
    slot_texts = _slot_matched_texts(spec)
    kept: List[Any] = []
    inherited: List[Dict[str, Any]] = []
    for issue in _section_issues(formatting):
        if (
            isinstance(issue, dict)
            and issue.get("code") == "TEMPLATE_TEXT_RESIDUAL"
            and str(issue.get("detail") or "") in tokens
        ):
            match = re.search(r"body_p_token\.(\d+)", str(issue.get("location") or ""))
            targeted_unfilled = (
                bool(match)
                and int(match.group(1)) in attempted
                and str(issue.get("detail") or "") in slot_texts
            )
            if not targeted_unfilled:
                inherited.append(
                    {
                        "code": "TEMPLATE_TEXT_RESIDUAL",
                        "severity": "medium",
                        "detail": "unfilled template placeholder left as-is: %s" % issue.get("detail"),
                    }
                )
                continue
        if (
            isinstance(issue, dict)
            and issue.get("code") == "RED_TEXT_RESIDUAL"
            and str(issue.get("detail") or "") in red_texts
            and str(issue.get("location") or "") not in attempted_locations
        ):
            inherited.append(
                {
                    "code": "RED_TEXT_RESIDUAL",
                    "severity": "medium",
                    "detail": "red text inherited from the template, no operation targeted it: %s"
                              % issue.get("detail"),
                }
            )
            continue
        kept.append(issue)
    if not inherited:
        return formatting, []
    adjusted = dict(formatting)
    adjusted["structured_issues"] = kept
    adjusted["issues"] = kept
    adjusted["passed"] = bool(formatting.get("passed")) or not any(
        isinstance(item, dict) and _severity(item.get("severity")) == "high"
        for item in kept
    )
    return adjusted, inherited


def _required_capability_blockers(
    check_id: str, capabilities: Dict[str, Dict[str, Any]]
) -> List[str]:
    """Required capabilities this check depends on that are not AVAILABLE."""
    blockers: List[str] = []
    for name in _CHECK_CAPABILITY_DEPENDENCIES.get(check_id, ()):
        entry = capabilities.get(name)
        if not isinstance(entry, dict) or not bool(entry.get("required")):
            continue
        if entry.get("status") != "AVAILABLE":
            blockers.append(name)
    return blockers


def _capability_detail(
    blockers: List[str], capabilities: Dict[str, Dict[str, Any]]
) -> str:
    """Evidence detail for an environment-blocked check; always names the capability."""
    descriptions: List[str] = []
    for name in blockers:
        entry = capabilities.get(name) if isinstance(capabilities, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        status = str(entry.get("status") or "UNVERIFIED")
        evidence = str(entry.get("evidence") or "").strip()
        text = "%s=%s" % (name, status)
        if evidence:
            text += " (%s)" % evidence
        descriptions.append(text)
    return "CAPABILITY_UNAVAILABLE[%s]" % "; ".join(descriptions)


def _optional_visual_notes(capabilities: Dict[str, Dict[str, Any]]) -> str:
    """Optional-capability gaps that qualify (but never demote) the page-count verdict."""
    notes = [
        name
        for name in _VISUAL_OPTIONAL_CAPABILITIES
        if isinstance(capabilities.get(name), dict)
        and capabilities[name].get("status") != "AVAILABLE"
    ]
    return "; optional unavailable: %s" % ", ".join(notes) if notes else ""


def run_full_qa(
    staged_path: str,
    *,
    template_path: Optional[str],
    task_id: str,
    task_mode: str = "GENERATE",
    gate_mode: str = "STRICT",
    content_plan: Optional[Dict[str, Any]] = None,
    facts: Optional[List[Dict[str, Any]]] = None,
    fill_plan: Optional[Dict[str, Any]] = None,
    spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run every required check for the policy and return a validated QAReport."""
    staged = os.path.abspath(os.fspath(staged_path))
    if not os.path.isfile(staged):
        raise ValueError("staged document does not exist: %s" % staged)

    template: Optional[str] = None
    if template_path:
        template = os.path.abspath(os.fspath(template_path))
        if not os.path.isfile(template):
            raise ValueError("template document does not exist: %s" % template)

    task_mode = str(task_mode or "").strip().upper()
    gate_mode = str(gate_mode or "").strip().upper()
    policy = resolve_required_checks(task_mode, gate_mode)
    # Environment truth is measured once per run; a required capability that is
    # unavailable blocks the checks that depend on it instead of guessing.
    capabilities = capability_matrix()

    try:
        docx.Document(staged)
    except Exception as exc:
        raise ValueError("staged document cannot be read: %s" % exc) from exc

    comparison_profile = "STYLE_GUIDE" if task_mode == "GENERATE" else "REPLICA"
    checks: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    coverage_gaps: List[str] = []

    for check_id in policy["required"]:
        blockers = _required_capability_blockers(check_id, capabilities)
        if blockers:
            detail = _capability_detail(blockers, capabilities)
            checks.append(
                check_record(
                    check_id,
                    "UNVERIFIED",
                    "environment_capability_probe",
                    artifact_path=staged,
                    detail=detail,
                )
            )
            continue

        if check_id == "PACKAGE":
            package = audit_docx_package_integrity(staged, baseline_path=template)
            status = "PASSED" if package.get("passed") else "FAILED"
            detail = "%d package parts inspected" % int(package.get("inspected_parts_count") or 0)
            checks.append(
                check_record(
                    "PACKAGE",
                    status,
                    "audit_docx_package_integrity",
                    artifact_path=staged,
                    detail=detail,
                )
            )
            _absorb(package, "PACKAGE", issues, warnings, coverage_gaps)
            _ensure_failure_issue("PACKAGE", status, issues, detail)

        elif check_id == "FORMAT":
            try:
                formatting = audit_format_and_text_qa(
                    docx.Document(staged),
                    docx_path=staged,
                    reference_docx_path=template,
                    raise_on_failure=False,
                    comparison_profile=comparison_profile,
                )
            except Exception as exc:
                checks.append(
                    check_record(
                        "FORMAT",
                        "UNVERIFIED",
                        "audit_format_and_text_qa",
                        artifact_path=staged,
                        detail="FORMAT_QA_UNAVAILABLE: %s: %s" % (type(exc).__name__, exc),
                    )
                )
            else:
                formatting, inherited_residuals = _adjust_inherited_residuals(
                    formatting, template, fill_plan, spec
                )
                status = "PASSED" if formatting.get("passed") else "FAILED"
                detail = "%s profile; %d finding(s)" % (
                    comparison_profile,
                    len(_section_issues(formatting)),
                )
                checks.append(
                    check_record(
                        "FORMAT",
                        status,
                        "audit_format_and_text_qa",
                        artifact_path=staged,
                        detail=detail,
                    )
                )
                _absorb(formatting, "FORMAT", issues, warnings, coverage_gaps)
                warnings.extend(inherited_residuals)
                _ensure_failure_issue("FORMAT", status, issues, detail)

        elif check_id == "FIDELITY":
            if template is None:
                checks.append(
                    check_record(
                        "FIDELITY",
                        "UNVERIFIED",
                        "template_intelligence.fingerprint.compute_four_hashes",
                        artifact_path=staged,
                        detail="FIDELITY_TEMPLATE_UNAVAILABLE",
                    )
                )
                continue
            try:
                from template_intelligence.fingerprint import compute_four_hashes

                template_doc = docx.Document(template)
                output_doc = docx.Document(staged)
                template_texts = _spec_protected_texts(template_doc, spec)
                output_texts = _spec_protected_texts(output_doc, spec)
                template_hashes = compute_four_hashes(
                    template_doc, protected_texts=template_texts
                )
                # QA checks may mutate a parsed document in memory; the output
                # fingerprint is therefore taken from a fresh disk read.
                output_hashes = compute_four_hashes(
                    output_doc, protected_texts=output_texts
                )
            except Exception as exc:
                checks.append(
                    check_record(
                        "FIDELITY",
                        "UNVERIFIED",
                        "template_intelligence.fingerprint.compute_four_hashes",
                        artifact_path=staged,
                        detail="FIDELITY_UNAVAILABLE: %s: %s" % (type(exc).__name__, exc),
                    )
                )
                continue

            protected_diffs = [
                key
                for key in ("structural_hash", "style_hash", "protected_hash")
                if template_hashes.get(key) != output_hashes.get(key)
            ]
            layout_diff = template_hashes.get("layout_hash") != output_hashes.get("layout_hash")

            status = "PASSED"
            for key in protected_diffs:
                status = "FAILED"
                issues.append(
                    {
                        "code": "UNAUTHORIZED_TEMPLATE_CHANGE",
                        "severity": "high",
                        "location": "fidelity.%s" % key,
                        "detail": "%s differs from the template fingerprint" % key,
                        "blocking": True,
                        "check_id": "FIDELITY",
                    }
                )
            if layout_diff:
                if _has_image_ops(fill_plan):
                    warnings.append(
                        {
                            "code": "LAYOUT_IMAGE_FRAME_CHANGE",
                            "severity": "medium",
                            "detail": "layout fingerprint changed by an authorized replace_image operation",
                        }
                    )
                else:
                    status = "FAILED"
                    issues.append(
                        {
                            "code": "UNAUTHORIZED_TEMPLATE_CHANGE",
                            "severity": "high",
                            "location": "fidelity.layout_hash",
                            "detail": "layout fingerprint differs from the template and no image operation authorizes it",
                            "blocking": True,
                            "check_id": "FIDELITY",
                        }
                    )

            detail = "structural/style/protected diffs=%d; layout=%s" % (
                len(protected_diffs),
                "diff" if layout_diff else "match",
            )
            record = check_record(
                "FIDELITY",
                status,
                "template_intelligence.fingerprint.compute_four_hashes",
                artifact_path=staged,
                detail=detail,
            )
            try:
                record["evidence"]["input_sha256"] = _sha256_file(template)
                record["evidence"]["output_sha256"] = _sha256_file(staged)
            except OSError:
                # Optional evidence: an unreadable file must not fabricate a hash.
                pass
            checks.append(record)

        elif check_id == "CONTENT":
            try:
                content = audit_content_consistency(doc=docx.Document(staged))
            except Exception as exc:
                checks.append(
                    check_record(
                        "CONTENT",
                        "UNVERIFIED",
                        "audit_content_consistency",
                        detail="CONTENT_QA_UNAVAILABLE: %s: %s" % (type(exc).__name__, exc),
                    )
                )
            else:
                status = "PASSED" if content.get("passed") else "FAILED"
                detail = "%d label/value pairs" % int(content.get("checked_labels") or 0)
                checks.append(
                    check_record("CONTENT", status, "audit_content_consistency", detail=detail)
                )
                _absorb(content, "CONTENT", issues, warnings, coverage_gaps)
                _ensure_failure_issue("CONTENT", status, issues, detail)

        elif check_id == "DATA":
            data_facts = facts
            if data_facts is None and isinstance(content_plan, dict):
                data_facts = content_plan.get("facts")
            if not data_facts:
                checks.append(
                    check_record(
                        "DATA",
                        "UNVERIFIED",
                        "audit_fact_sources",
                        detail="DATA_FACTS_NOT_PROVIDED",
                    )
                )
                continue
            try:
                data = audit_fact_sources(data_facts)
            except Exception as exc:
                checks.append(
                    check_record(
                        "DATA",
                        "UNVERIFIED",
                        "audit_fact_sources",
                        detail="DATA_QA_UNAVAILABLE: %s: %s" % (type(exc).__name__, exc),
                    )
                )
                continue
            if not data.get("passed"):
                status = "FAILED"
            elif data.get("unverified_count"):
                status = "UNVERIFIED"
            else:
                status = "PASSED"
            detail = "%d fact(s) checked; %d conflict(s)" % (
                int(data.get("checked_count") or 0),
                len(_section_issues(data)),
            )
            if status == "UNVERIFIED":
                detail = "DATA_FACTS_UNVERIFIED; " + detail
            checks.append(check_record("DATA", status, "audit_fact_sources", detail=detail))
            _absorb(data, "DATA", issues, warnings, coverage_gaps)
            _ensure_failure_issue("DATA", status, issues, detail)

        elif check_id == "VISUAL_PAGE_COUNT":
            try:
                visual = run_visual_layout_qa(
                    staged,
                    reference_docx_path=template,
                    comparison_profile=comparison_profile,
                )
            except Exception as exc:
                checks.append(
                    check_record(
                        "VISUAL_PAGE_COUNT",
                        "UNVERIFIED",
                        "run_visual_layout_qa",
                        artifact_path=staged,
                        detail="VISUAL_QA_UNAVAILABLE: %s: %s" % (type(exc).__name__, exc),
                    )
                )
                continue
            high_findings = any(
                _severity(item.get("severity")) == "high"
                for item in _section_issues(visual)
                if isinstance(item, dict)
            )
            backend = str(visual.get("pdf_backend") or "none")
            if high_findings or not visual.get("passed"):
                status = "FAILED"
                detail = "%s backend; blocking layout finding(s)" % backend
            elif visual.get("pdf_rendered") and visual.get("page_count_available"):
                status = "PASSED"
                detail = "%s backend; page counts verified%s" % (
                    backend,
                    _optional_visual_notes(capabilities),
                )
            elif not visual.get("pdf_rendered"):
                status = "UNVERIFIED"
                detail = "PDF_BACKEND_UNAVAILABLE"
            else:
                status = "UNVERIFIED"
                detail = "PDF_PAGE_COUNT_UNVERIFIED"
            checks.append(
                check_record(
                    "VISUAL_PAGE_COUNT",
                    status,
                    "run_visual_layout_qa",
                    artifact_path=staged,
                    detail=detail,
                )
            )
            _absorb(visual, "VISUAL_PAGE_COUNT", issues, warnings, coverage_gaps)
            # Optional pixel-diff / font-availability gaps belong to optional checks.
            # They must be visible in the visual check evidence, but they do not make
            # a required VISUAL_PAGE_COUNT verdict unverified.
            for gap in list(coverage_gaps):
                if gap in _OPTIONAL_VISUAL_GAPS:
                    coverage_gaps.remove(gap)
            _ensure_failure_issue("VISUAL_PAGE_COUNT", status, issues, detail)

        elif check_id == "REVIEW_INTEGRITY":
            if task_mode != "REVIEW":
                checks.append(
                    check_record(
                        "REVIEW_INTEGRITY",
                        "UNVERIFIED",
                        "audit_review_integrity",
                        artifact_path=staged,
                        detail="REVIEW_INTEGRITY_NOT_APPLICABLE",
                    )
                )
                continue
            try:
                review = audit_review_integrity(staged)
            except Exception as exc:
                checks.append(
                    check_record(
                        "REVIEW_INTEGRITY",
                        "UNVERIFIED",
                        "audit_review_integrity",
                        artifact_path=staged,
                        detail="REVIEW_INTEGRITY_UNAVAILABLE: %s: %s" % (type(exc).__name__, exc),
                    )
                )
                continue
            review_gaps = [str(item) for item in (review.get("coverage_gaps") or []) if str(item).strip()]
            if not review.get("passed"):
                status = "FAILED"
            elif review_gaps:
                status = "UNVERIFIED"
            else:
                status = "PASSED"
            detail = "%d revision(s), %d comment(s)" % (
                int(review.get("revision_count") or 0),
                int(review.get("comment_count") or 0),
            )
            if status == "UNVERIFIED":
                detail = review_gaps[0]
            checks.append(
                check_record(
                    "REVIEW_INTEGRITY",
                    status,
                    "audit_review_integrity",
                    artifact_path=staged,
                    detail=detail,
                )
            )
            _absorb(review, "REVIEW_INTEGRITY", issues, warnings, coverage_gaps)
            _ensure_failure_issue("REVIEW_INTEGRITY", status, issues, detail)

        else:
            checks.append(
                check_record(
                    check_id,
                    "UNVERIFIED",
                    "not_implemented",
                    detail="CHECK_IMPLEMENTATION_UNAVAILABLE",
                )
            )

    # Stable de-duplication: the same finding is often reported by two sections.
    unique_issues: List[Dict[str, Any]] = []
    seen_issues = set()
    for item in issues:
        key = (item.get("code"), item.get("location"), item.get("detail"), item.get("check_id"))
        if key in seen_issues:
            continue
        seen_issues.add(key)
        unique_issues.append(item)

    unique_warnings: List[Dict[str, Any]] = []
    seen_warnings = set()
    for item in warnings:
        key = (item.get("code"), item.get("severity"), item.get("detail"))
        if key in seen_warnings:
            continue
        seen_warnings.add(key)
        unique_warnings.append(item)

    unique_gaps = list(dict.fromkeys(gap for gap in coverage_gaps if gap))

    return build_qa_report(
        task_id=task_id,
        task_mode=task_mode,
        gate_mode=gate_mode,
        checks=checks,
        issues=unique_issues,
        warnings=unique_warnings,
        coverage_gaps=unique_gaps,
    )
