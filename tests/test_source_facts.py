# -*- coding: utf-8 -*-
"""Source fact extraction and Decimal reconciliation tests."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from content_intelligence.source_facts import (
    PDF_TEXT_UNAVAILABLE,
    SourceExtractionError,
    extract_pdf_pages,
    extract_teaching_plan,
)


def _course(
    category: str,
    subcategory: str,
    code: str,
    name: str,
    credits: float | int,
    total_hours: int,
    theory_hours: int,
    practice_hours: int,
    note: str = "",
) -> list[object]:
    return [
        category,
        subcategory,
        "必修",
        None,
        name,
        code,
        credits,
        total_hours,
        theory_hours,
        practice_hours,
        "考试",
        None,
        None,
        None,
        None,
        None,
        None,
        note,
    ]


def _subtotal(
    label: str,
    credits: float | int,
    total_hours: int,
    theory_hours: int,
    practice_hours: int,
) -> list[object]:
    return [
        None,
        None,
        None,
        None,
        label,
        None,
        credits,
        total_hours,
        theory_hours,
        practice_hours,
    ]


def _write_workbook(path: Path, *, total_credits: float = 124.5) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "教学进程表"
    rows = [
        ["测试专业教学总体安排表"],
        [
            "专业名称",
            "信息安全技术应用",
            None,
            None,
            "所属学院",
            "软件工程学院",
            None,
            None,
            None,
            None,
            "学制",
            "三年",
        ],
        [],
        [
            "课程类别",
            "课程子类",
            "课程性质",
            "序号",
            "课程名称",
            "课程代码",
            "学分",
            "总学时",
            "理论",
            "实践",
            "考核方式",
            "一(16)",
            "二(16)",
            "三(16)",
            "四(16)",
            "五(16)",
            "六(20)",
            "备注",
        ],
        _course("公共基础课程", "全校通识课", "P001", "通识课", 27, 480, 318, 162),
        _course("公共基础课程", "专业通识课", "P002", "专业通识课", 6, 96, 48, 48),
        _course("公共基础课程", "公共选修课", "P003", "公共选修课", 8, 128, 128, 0),
        _subtotal("全校通识课学分小计", 27, 480, 318, 162),
        _subtotal("专业通识课学分小计", 6, 96, 48, 48),
        _subtotal("公共选修课学分小计", 8, 128, 128, 0),
        _subtotal("公共基础课程学分小计", 41, 704, 494, 210),
        _course("专业课程", "专业基础课", "Z001", "专业基础课", 14, 224, 112, 112),
        _subtotal("专业基础课学分小计", 14, 224, 112, 112),
        _course("专业课程", "专业核心课", "Z002", "专业核心课", 25, 400, 200, 200),
        _subtotal("专业核心课学分小计", 25, 400, 200, 200),
        _course(
            "专业课程",
            "专业拓展课",
            "Z101",
            "方向一课程一",
            4,
            64,
            32,
            32,
            "（微专业）拓展方向一",
        ),
        _course("专业课程", "专业拓展课", "Z102", "方向一课程二", 4, 64, 32, 32),
        _course("专业课程", "专业拓展课", "Z103", "方向一课程三", 4, 64, 32, 32),
        _course(
            "专业课程",
            "专业拓展课",
            "Z201",
            "方向二课程一",
            4,
            64,
            32,
            32,
            "（微专业）拓展方向二",
        ),
        _course("专业课程", "专业拓展课", "Z202", "方向二课程二", 4, 64, 32, 32),
        _course("专业课程", "专业拓展课", "Z203", "方向二课程三", 4, 64, 32, 32),
        _subtotal("专业拓展课限定选修学分小计", 12, 192, 96, 96),
        _subtotal("专业课程学分小计", 51, 816, 408, 408),
        _course("实践课程", "基础技能实践", "S001", "入学教育", 1, 24, 0, 24),
        _course("实践课程", "基础技能实践", "S002", "军事技能训练", 2, 112, 0, 112),
        _course("实践课程", "综合技能实践", "S101", "综合实训一", 20, 600, 0, 600),
        _course("实践课程", "综合技能实践", "S102", "综合实训二", 6, 144, 0, 144),
        _course(
            "实践课程",
            "创新实践与体育拓展",
            "S201",
            "素质拓展",
            2,
            32,
            0,
            32,
        ),
        _course(
            "实践课程",
            "创新实践与体育拓展",
            "S202",
            "课外体育",
            1.5,
            24,
            0,
            24,
        ),
        _subtotal("实践课程学分小计", 32.5, 936, 0, 936),
        _subtotal("总学分", total_credits, 2456, 902, 1554),
    ]
    for row in rows:
        sheet.append(row)
    workbook.save(str(path))


def test_teaching_plan_preserves_notes_and_reconciles_detail_totals(tmp_path):
    path = tmp_path / "teaching.xlsx"
    _write_workbook(path)

    facts = extract_teaching_plan(str(path))

    assert facts["major"] == "信息安全技术应用"
    assert facts["college"] == "软件工程学院"
    assert facts["duration"] == "三年"
    assert facts["ledger"] == {
        "closed": True,
        "discrepancies": [],
        "detail_discrepancies": [],
    }
    assert facts["subtotals"]["专业通识课学分小计"]["credits"] == 6
    assert facts["subtotals"]["总学分"]["credits"] == 124.5
    assert facts["practice_components"]["核心技能实践"] == {
        "status": "NOT_SEPARATELY_SCHEDULED",
        "credits": None,
        "total_hours": None,
        "theory_hours": None,
        "practice_hours": None,
        "course_count": 0,
    }
    assert facts["practice_components"]["创新实践与课外体育实践"]["credits"] == "3.5"
    assert [
        (direction["direction"], direction["credits"])
        for direction in facts["extension_directions"]
    ] == [("拓展方向一", "12"), ("拓展方向二", "12")]
    expanded_course = next(
        course for course in facts["courses"] if course["name"] == "方向一课程一"
    )
    assert expanded_course["note"] == "（微专业）拓展方向一"
    assert expanded_course["assessment"] == "考试"


def test_teaching_plan_surfaces_decimal_total_mismatch(tmp_path):
    path = tmp_path / "bad-total.xlsx"
    _write_workbook(path, total_credits=125)

    facts = extract_teaching_plan(str(path))

    assert facts["ledger"]["closed"] is False
    assert any(
        item["field"] == "credits"
        for item in facts["ledger"]["discrepancies"]
    )


def test_pdf_without_extractable_text_fails_explicitly(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as handle:
        writer.write(handle)

    with pytest.raises(SourceExtractionError) as error:
        extract_pdf_pages(str(path))

    assert error.value.code == PDF_TEXT_UNAVAILABLE
