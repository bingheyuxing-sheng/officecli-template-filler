# -*- coding: utf-8 -*-
"""Read-only extraction of ContentPlan facts from approved source files.

The helpers never invent a missing value. PDF files that expose no extractable
text fail with ``PDF_TEXT_UNAVAILABLE``; workbook totals must reconcile before
the caller can treat the course facts as verified.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import openpyxl


PDF_TEXT_UNAVAILABLE = "PDF_TEXT_UNAVAILABLE"

_SUBTOTAL_LABELS = (
    "全校通识课学分小计",
    "专业通识课学分小计",
    "公共选修课学分小计",
    "公共基础课程学分小计",
    "专业基础课学分小计",
    "专业核心课学分小计",
    "专业拓展课限定选修学分小计",
    "专业课程学分小计",
    "基础技能实践学分小计",
    "核心技能实践学分小计",
    "综合技能实践学分小计",
    "创新实践与课外体育实践学分小计",
    "实践课程学分小计",
    "总学分",
)

_DETAIL_CHECKS = (
    (
        "公共基础课程学分小计",
        (
            "全校通识课学分小计",
            "专业通识课学分小计",
            "公共选修课学分小计",
        ),
    ),
    (
        "专业课程学分小计",
        (
            "专业基础课学分小计",
            "专业核心课学分小计",
            "专业拓展课限定选修学分小计",
        ),
    ),
    (
        "实践课程学分小计",
        (
            "基础技能实践学分小计",
            "核心技能实践学分小计",
            "综合技能实践学分小计",
            "创新实践与课外体育实践学分小计",
        ),
    ),
)


class SourceExtractionError(RuntimeError):
    """Raised when a source cannot be converted into reviewable facts."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if text and text.replace(".", "", 1).isdigit():
            return Decimal(text)
    return None


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def extract_pdf_pages(path: str) -> Dict[str, Any]:
    """Return per-page PDF text or raise ``PDF_TEXT_UNAVAILABLE``.

    Extraction failure is deliberately fatal for ContentPlan construction: the
    principle constraints must come from the source document, never from a
    model's recollection of the policy.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise SourceExtractionError(
            PDF_TEXT_UNAVAILABLE,
            "pypdf is not installed",
            details={"path": str(path)},
        ) from exc

    try:
        reader = PdfReader(str(path))
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page": page_number, "text": text})
    except Exception as exc:
        raise SourceExtractionError(
            PDF_TEXT_UNAVAILABLE,
            "{}: {}".format(type(exc).__name__, exc),
            details={"path": str(path)},
        ) from exc

    if not any(page["text"].strip() for page in pages):
        raise SourceExtractionError(
            PDF_TEXT_UNAVAILABLE,
            "no extractable text in {} page(s)".format(len(pages)),
            details={"path": str(path)},
        )
    return {
        "path": str(Path(path)),
        "page_count": len(pages),
        "pages": pages,
    }


def _expanded_rows(sheet) -> List[List[Any]]:
    rows = [
        [sheet.cell(row, column).value for column in range(1, sheet.max_column + 1)]
        for row in range(1, sheet.max_row + 1)
    ]
    for merged in sheet.merged_cells.ranges:
        top = rows[merged.min_row - 1][merged.min_col - 1]
        for row in range(merged.min_row, merged.max_row + 1):
            for column in range(merged.min_col, merged.max_col + 1):
                rows[row - 1][column - 1] = top
    return rows


def _find_header(rows: Iterable[List[Any]]) -> tuple[int, Dict[str, int]]:
    required = ("课程名称", "课程代码", "学分", "总学时", "理论", "实践")
    for row_index, values in enumerate(rows):
        texts = [str(value or "").strip() for value in values]
        if all(name in texts for name in required):
            header = {name: texts.index(name) for name in required}
            for name in ("考核方式", "备注"):
                if name in texts:
                    header[name] = texts.index(name)
            return row_index, header
    raise SourceExtractionError(
        "TEACHING_TABLE_HEADER_MISSING",
        "teaching plan header does not contain the required course columns",
    )


def _subtotal(rows: List[List[Any]], label: str) -> Optional[Dict[str, Any]]:
    for row_index, values in enumerate(rows):
        texts = [str(value or "").strip() for value in values]
        if any(label in text for text in texts):
            numbers = [_decimal(value) for value in values]
            return {
                "row": row_index + 1,
                "label": label,
                "credits": numbers[6],
                "total_hours": numbers[7],
                "theory_hours": numbers[8],
                "practice_hours": numbers[9],
            }
    return None


def _sum_course_metrics(
    courses: Iterable[Dict[str, Any]],
    *,
    subcategory: str,
) -> Dict[str, Any]:
    selected = [
        course
        for course in courses
        if course.get("subcategory") == subcategory
    ]
    if not selected:
        return {
            "status": "NOT_SEPARATELY_SCHEDULED",
            "credits": None,
            "total_hours": None,
            "theory_hours": None,
            "practice_hours": None,
            "course_count": 0,
        }
    totals = {
        field: sum(
            (Decimal(str(course[field])) for course in selected),
            Decimal("0"),
        )
        for field in ("credits", "total_hours", "theory_hours", "practice_hours")
    }
    return {
        "status": "DERIVED_FROM_COURSE_ROWS",
        "credits": _decimal_text(totals["credits"]),
        "total_hours": _decimal_text(totals["total_hours"]),
        "theory_hours": _decimal_text(totals["theory_hours"]),
        "practice_hours": _decimal_text(totals["practice_hours"]),
        "course_count": len(selected),
    }


def _extension_directions(courses: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    directions: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for course in courses:
        if course.get("subcategory") != "专业拓展课":
            continue
        note = str(course.get("note") or "")
        match = re.search(r"拓展方向[一二三四五六七八九十0-9]+", note)
        if match and (
            current is None
            or current.get("direction") != match.group(0)
        ):
            current = {
                "direction": match.group(0),
                "courses": [],
            }
            directions.append(current)
        if current is None:
            current = {
                "direction": None,
                "courses": [],
            }
            directions.append(current)
        current["courses"].append(
            {
                "name": course["name"],
                "code": course["code"],
                "credits": course["credits"],
                "total_hours": course["total_hours"],
                "theory_hours": course["theory_hours"],
                "practice_hours": course["practice_hours"],
                "semesters": course["semesters"],
                "row": course["row"],
            }
        )

    for direction in directions:
        metrics = _sum_course_metrics(
            (
                {
                    **course,
                    "subcategory": "专业拓展课",
                }
                for course in direction["courses"]
            ),
            subcategory="专业拓展课",
        )
        direction.update(
            {
                "credits": metrics["credits"],
                "total_hours": metrics["total_hours"],
                "theory_hours": metrics["theory_hours"],
                "practice_hours": metrics["practice_hours"],
                "course_count": metrics["course_count"],
            }
        )
    return directions


def _label_value(rows: Iterable[List[Any]], label: str) -> str:
    for values in rows:
        texts = [str(value or "").strip() for value in values]
        if label not in texts:
            continue
        index = texts.index(label)
        for value in values[index + 1 :]:
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _ratio(numerator: Optional[Decimal], denominator: Optional[Decimal]) -> Optional[str]:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return _decimal_text((numerator / denominator * Decimal("100")).quantize(Decimal("0.01")))


def extract_teaching_plan(path: str) -> Dict[str, Any]:
    """Extract course facts and Decimal-reconciled category totals."""
    try:
        workbook = openpyxl.load_workbook(str(path), data_only=True)
    except Exception as exc:
        raise SourceExtractionError(
            "TEACHING_TABLE_UNAVAILABLE",
            "{}: {}".format(type(exc).__name__, exc),
            details={"path": str(path)},
        ) from exc

    if "教学进程表" not in workbook.sheetnames:
        raise SourceExtractionError(
            "TEACHING_TABLE_UNAVAILABLE",
            "workbook is missing the 教学进程表 sheet",
            details={"sheets": workbook.sheetnames},
        )
    sheet = workbook["教学进程表"]
    rows = _expanded_rows(sheet)
    header_index, header = _find_header(rows)
    semester_columns = {
        str(value).strip(): index
        for index, value in enumerate(rows[header_index])
        if str(value or "").strip()
        and (
            str(value).strip().startswith(("一(", "二(", "三(", "四(", "五(", "六("))
        )
    }

    courses: List[Dict[str, Any]] = []
    for row_index in range(header_index + 1, len(rows)):
        values = rows[row_index]
        name = str(values[header["课程名称"]] or "").strip()
        code = str(values[header["课程代码"]] or "").strip()
        credits = _decimal(values[header["学分"]])
        if not name or not code or credits is None:
            continue
        semesters = []
        for header_text, column in semester_columns.items():
            value = values[column]
            if value is None:
                continue
            semesters.append(
                {
                    "header": header_text,
                    "value": str(value),
                }
            )
        courses.append(
            {
                "row": row_index + 1,
                "category": str(values[0] or "").strip(),
                "subcategory": str(values[1] or "").strip(),
                "nature": str(values[2] or "").strip(),
                "sequence": str(values[3] or "").strip(),
                "name": name,
                "code": code,
                "credits": _decimal_text(credits),
                "total_hours": _decimal_text(
                    _decimal(values[header["总学时"]]) or Decimal("0")
                ),
                "theory_hours": _decimal_text(
                    _decimal(values[header["理论"]]) or Decimal("0")
                ),
                "practice_hours": _decimal_text(
                    _decimal(values[header["实践"]]) or Decimal("0")
                ),
                "assessment": (
                    str(values[header["考核方式"]] or "").strip()
                    if "考核方式" in header
                    else ""
                ),
                "note": (
                    str(values[header["备注"]] or "").strip()
                    if "备注" in header
                    else ""
                ),
                "semesters": semesters,
            }
        )

    subtotals = {label: _subtotal(rows, label) for label in _SUBTOTAL_LABELS}
    category_totals = {
        label: subtotals[label]
        for label in (
            "公共基础课程学分小计",
            "专业课程学分小计",
            "实践课程学分小计",
        )
    }
    practice_component_sources = {
        "基础技能实践": ("基础技能实践学分小计", "基础技能实践"),
        "核心技能实践": ("核心技能实践学分小计", "核心技能实践"),
        "综合技能实践": ("综合技能实践学分小计", "综合技能实践"),
        "创新实践与课外体育实践": (
            "创新实践与课外体育实践学分小计",
            "创新实践与体育拓展",
        ),
    }
    practice_components: Dict[str, Dict[str, Any]] = {}
    for component_name, (label, subcategory) in practice_component_sources.items():
        if subtotals[label] is not None:
            practice_components[component_name] = {
                **subtotals[label],
                "status": "DECLARED_SUBTOTAL",
            }
        else:
            practice_components[component_name] = _sum_course_metrics(
                courses,
                subcategory=subcategory,
            )

    total = _subtotal(rows, "总学分")
    closed = True
    discrepancies: List[Dict[str, Any]] = []
    for field in ("credits", "total_hours", "theory_hours", "practice_hours"):
        subtotal_sum = sum(
            (item[field] for item in category_totals.values() if item and item[field] is not None),
            Decimal("0"),
        )
        declared = total.get(field) if total else None
        if declared is None or subtotal_sum != declared:
            closed = False
            discrepancies.append(
                {
                    "field": field,
                    "subtotal_sum": _decimal_text(subtotal_sum),
                    "declared_total": _decimal_text(declared) if declared is not None else None,
                }
            )

    detail_discrepancies: List[Dict[str, Any]] = []
    for parent_label, child_labels in _DETAIL_CHECKS:
        parent = subtotals[parent_label]
        if parent is None:
            continue
        for field in ("credits", "total_hours", "theory_hours", "practice_hours"):
            children = [
                subtotals[label]
                for label in child_labels
                if subtotals[label] is not None
            ]
            if not children:
                continue
            child_sum = sum(
                (item[field] for item in children if item.get(field) is not None),
                Decimal("0"),
            )
            declared = parent.get(field)
            if declared is None or child_sum != declared:
                detail_discrepancies.append(
                    {
                        "parent": parent_label,
                        "children": list(child_labels),
                        "field": field,
                        "child_sum": _decimal_text(child_sum),
                        "declared": (
                            _decimal_text(declared)
                            if declared is not None
                            else None
                        ),
                    }
                )
    closed = closed and not detail_discrepancies

    practice_total = subtotals["实践课程学分小计"]
    if practice_total is not None:
        for field in ("credits", "total_hours", "theory_hours", "practice_hours"):
            component_values = [
                Decimal(str(component[field]))
                for component in practice_components.values()
                if component.get(field) is not None
            ]
            component_sum = sum(component_values, Decimal("0"))
            declared = practice_total.get(field)
            if declared is None or component_sum != declared:
                detail_discrepancies.append(
                    {
                        "parent": "实践课程学分小计",
                        "children": list(practice_component_sources),
                        "field": field,
                        "child_sum": _decimal_text(component_sum),
                        "declared": (
                            _decimal_text(declared)
                            if declared is not None
                            else None
                        ),
                    }
                )
    closed = closed and not detail_discrepancies

    public_electives = subtotals["公共选修课学分小计"]
    professional_electives = subtotals["专业拓展课限定选修学分小计"]
    total_credits = total.get("credits") if total else None
    required_credits = total_credits
    if required_credits is not None:
        for block in (public_electives, professional_electives):
            if block and block.get("credits") is not None:
                required_credits -= block["credits"]

    return {
        "path": str(Path(path)),
        "title": str(rows[0][0] or "").strip() if rows else "",
        "major": _label_value(rows, "专业名称"),
        "college": _label_value(rows, "所属学院"),
        "duration": _label_value(rows, "学制"),
        "courses": courses,
        "extension_directions": _extension_directions(courses),
        "category_totals": category_totals,
        "subtotals": subtotals,
        "practice_components": practice_components,
        "total": total,
        "public_electives": public_electives,
        "professional_electives": professional_electives,
        "required_credits": (
            _decimal_text(required_credits) if required_credits is not None else None
        ),
        "ratios": {
            "practice_percent": _ratio(
                total.get("practice_hours") if total else None,
                total.get("total_hours") if total else None,
            ),
            "public_hours_percent": _ratio(
                category_totals["公共基础课程学分小计"].get("total_hours")
                if category_totals["公共基础课程学分小计"] else None,
                total.get("total_hours") if total else None,
            ),
            "elective_credits_percent": _ratio(
                (public_electives.get("credits") if public_electives else Decimal("0"))
                + (
                    professional_electives.get("credits")
                    if professional_electives
                    else Decimal("0")
                ),
                total_credits,
            ),
        },
        "ledger": {
            "closed": closed,
            "discrepancies": discrepancies,
            "detail_discrepancies": detail_discrepancies,
        },
    }


__all__ = [
    "PDF_TEXT_UNAVAILABLE",
    "SourceExtractionError",
    "extract_pdf_pages",
    "extract_teaching_plan",
]
