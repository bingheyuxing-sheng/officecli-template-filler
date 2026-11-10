# -*- coding: utf-8 -*-
"""Template Analysis Report: JSON structure plus Markdown rendering."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .models import canonical_json, sha256_text

_REPORT_SCHEMA_VERSION = "1.0"
_COVERAGE_NOTE = "覆盖率只说明有多少属性有证据，不等于模板理解正确。"
_CONFIRMATION_PROMPT_READY = (
    "模板解析已经完成。\n\n"
    "当前没有影响本次任务正确性的阻断性问题。\n"
    "请检查以上模板结构和格式规则。\n"
    "确认后，我将按照该模板开始正式生成。"
)
_CONFIRMATION_PROMPT_BLOCKED = (
    "模板解析尚未通过。\n\n"
    "当前仍有 %d 个阻断性问题未解决，不能确认或开始生成。\n"
    "请先按第6节补充证据或明确处理方式，然后重新分析。"
)

_POSSIBLE_ERRORS = {
    "table.purpose": "表格可能被错误填充，或固定内容被误改。",
    "font_family": "填充后字体与模板不一致。",
    "font_size": "填充后字号与模板不一致。",
    "font_rule": "标签与占位符的混排字号规则未被确认，填充可能破坏模板版式。",
    "red_text.semantic": "红色说明文字可能被当作占位符删除或填错。",
    "field": "字段指令、结果或可编辑状态与模板不一致。",
    "sdt": "内容控件被误改，或含字段控件丢失字段。",
    "textbox.position": "文本框位置或版式发生漂移。",
    "paragraph.style": "段落样式对齐错误。",
    "paragraph.spacing": "段落间距/行距对齐错误。",
    "table.border": "表格边框或底纹丢失。",
    "table.shading": "表头底纹丢失。",
    "table.merge": "合并单元格拓扑被破坏。",
    "table.column_width": "表格列宽漂移。",
    "page.setup": "页面规格或页边距被改变。",
    "image.layout": "图片比例或位置发生漂移。",
}

_ACCEPTABLE_RESOLUTIONS = [
    "上传一份已填写完成的同类文档",
    "上传该位置的填写说明",
    "直接回答该属性的值",
    "明确要求保留原样（需通过安全性校验）",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [item for item in analysis.get("evidence") or [] if isinstance(item, dict)]


def _values(records: Iterable[Dict[str, Any]], prop: str) -> List[Any]:
    return [item.get("value") for item in records if item.get("property") == prop]


def _unique(values: Iterable[Any]) -> List[Any]:
    result: List[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _paragraph_values(records: List[Dict[str, Any]], prop: str) -> List[Any]:
    values: List[Any] = []
    for item in records:
        if item.get("property") != prop:
            continue
        value = item.get("value")
        if isinstance(value, dict):
            values.append(value)
    return values


def _blocking_items(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocking = sorted(
        [item for item in records if item.get("blocking")],
        key=lambda item: (str(item.get("property")), str(item.get("evidence_id"))),
    )
    items: List[Dict[str, Any]] = []
    for index, item in enumerate(blocking, start=1):
        prop = str(item.get("property") or "")
        items.append(
            {
                "item_id": "EVI-%03d" % index,
                "evidence_id": item.get("evidence_id"),
                "location": item.get("location"),
                "property": prop,
                "current_result": item.get("value"),
                "verification_status": item.get("verification_status"),
                "reason": item.get("detail") or "no deterministic evidence",
                "possible_error": _POSSIBLE_ERRORS.get(prop, "当前任务结果可能与模板不一致。"),
                "required_materials": list(item.get("required_materials") or []),
                "acceptable_resolutions": list(_ACCEPTABLE_RESOLUTIONS),
            }
        )
    return items


def _non_blocking_risks(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    risks: List[Dict[str, Any]] = []
    for item in records:
        if item.get("blocking"):
            continue
        if item.get("verification_status") == "VERIFIED":
            continue
        risks.append(
            {
                "location": item.get("location"),
                "property": item.get("property"),
                "verification_status": item.get("verification_status"),
                "detail": item.get("detail"),
            }
        )
    return risks


def _page_setup(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = _values(records, "page.setup")
    value = values[0] if values and isinstance(values[0], dict) else {}
    sections = value.get("sections") or []
    return {
        "page_size": value.get("page_size"),
        "orientation": value.get("orientation"),
        "sections": sections,
        "margins": [section.get("margins") for section in sections if isinstance(section, dict)],
    }


def _style_block(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    style_values = _paragraph_values(records, "paragraph.style")
    slot_styles = [
        item.get("value")
        for item in records
        if item.get("property") == "slot.style" and isinstance(item.get("value"), dict)
    ]
    fonts = _unique(
        [value.get("font_east_asia") for value in style_values + slot_styles if value.get("font_east_asia")]
    )
    sizes = _unique(
        [value.get("effective_sz_half_pt") for value in style_values + slot_styles if value.get("effective_sz_half_pt")]
    )
    style_names = _unique(
        [value.get("style_name") for value in style_values + slot_styles if value.get("style_name")]
    )
    return {
        "style_names": style_names,
        "fonts": fonts,
        "sizes_half_pt": sizes,
        "paragraph_spacing": _paragraph_values(records, "paragraph.spacing")[:20],
    }


def _structure_block(spec: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    protected = _values(records, "protected.region")
    slots = [
        item
        for item in records
        if item.get("property") == "slot.location" and item.get("task_relevant")
    ]
    tables = _values(records, "table.structure")
    fields = [
        item.get("value")
        for item in records
        if item.get("property") == "field" and isinstance(item.get("value"), dict)
    ]
    sdts = [
        item.get("value")
        for item in records
        if item.get("property") == "sdt" and isinstance(item.get("value"), dict)
    ]
    return {
        "fixed_content": [
            {"kind": item.get("kind"), "location_id": item.get("location_id")}
            for item in protected
            if isinstance(item, dict)
        ],
        "fillable_areas": [item.get("value") for item in slots],
        "protected_areas": [
            {"kind": item.get("kind"), "location_id": item.get("location_id")}
            for item in protected
            if isinstance(item, dict)
        ],
        "tables": tables,
        "controls": {
            "fields": fields,
            "sdts": sdts,
        },
    }


def build_report(
    analysis: Dict[str, Any],
    validation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the JSON Analysis Report from an analysis result."""
    records = _evidence(analysis)
    summary = dict(analysis.get("summary") or {})
    page = _page_setup(records)
    style = _style_block(records)
    blocking = _blocking_items(records)
    risks = _non_blocking_risks(records)
    resolved = [item for item in records if item.get("resolutions")]
    tables = _values(records, "table.structure")
    images = _values(records, "image.layout")
    special = _values(records, "object.preservable")

    report: Dict[str, Any] = {
        "schema_version": _REPORT_SCHEMA_VERSION,
        "analysis_id": analysis.get("analysis_id"),
        "template_name": analysis.get("template_name"),
        "template_sha256": analysis.get("template_sha256"),
        "task_type": analysis.get("task_type"),
        "generated_at": _now(),
        "basics": {
            "template_name": analysis.get("template_name"),
            "template_sha256": analysis.get("template_sha256"),
            "page_count": None,
            "page_count_verifiable": False,
            "section_count": len(page.get("sections") or []),
            "table_count": len(tables),
            "image_count": len(images),
            "special_object_count": len(special),
        },
        "page_and_styles": {
            "page_size": page.get("page_size"),
            "orientation": page.get("orientation"),
            "margins": page.get("margins"),
            "fonts": style.get("fonts"),
            "sizes_half_pt": style.get("sizes_half_pt"),
            "style_names": style.get("style_names"),
            "paragraph_spacing": style.get("paragraph_spacing"),
            "table_styles": {
                "border": _values(records, "table.border"),
                "shading": _values(records, "table.shading"),
                "merge": _values(records, "table.merge"),
                "column_width": _values(records, "table.column_width"),
            },
            "header_footer_rules": [
                item
                for item in _values(records, "protected.region")
                if isinstance(item, dict) and item.get("kind") in ("header", "footer", "repeated_header")
            ],
        },
        "structure": _structure_block({}, records),
        "quality": {
            "verified": int(summary.get("verified") or 0),
            "unverified": int(summary.get("unverified") or 0),
            "ambiguous": int(summary.get("ambiguous") or 0),
            "conflict": int(summary.get("conflict") or 0),
            "resolved": len(resolved),
            "unresolved_blocking": len(blocking),
            "coverage": float(summary.get("coverage") or 0.0),
            "coverage_note": _COVERAGE_NOTE,
        },
        "blocking_items": blocking,
        "non_blocking_risks": risks,
        "confirmation": {
            "prompt": (
                _CONFIRMATION_PROMPT_BLOCKED % len(blocking)
                if blocking
                else _CONFIRMATION_PROMPT_READY
            ),
            "required": True,
            "confirmed": False,
            "review_token": None,
        },
    }
    if isinstance(validation, dict):
        report["validation"] = dict(validation)
    report["report_digest"] = _report_digest(report)
    return report


def _report_digest(report: Dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("generated_at", None)
    payload.pop("report_digest", None)
    return sha256_text(canonical_json(payload))


def report_digest(report: Dict[str, Any]) -> str:
    return _report_digest(report)


def _format_value(value: Any) -> str:
    if value is None:
        return "（无）"
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    return str(value)


def render_markdown(report: Dict[str, Any]) -> str:
    """Render the user-facing Markdown report."""
    basics = report.get("basics") or {}
    styles = report.get("page_and_styles") or {}
    structure = report.get("structure") or {}
    quality = report.get("quality") or {}
    blocking = report.get("blocking_items") or []
    risks = report.get("non_blocking_risks") or []
    controls = structure.get("controls") or {}
    fields = controls.get("fields") or []
    sdts = controls.get("sdts") or []
    confirmation = report.get("confirmation") or {}

    lines: List[str] = [
        "# 模板分析报告",
        "",
        "- 模板：`%s`" % basics.get("template_name"),
        "- SHA-256：`%s`" % basics.get("template_sha256"),
        "- 任务类型：`%s`" % report.get("task_type"),
        "",
        "## 1. 模板基本信息",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 文件名称 | %s |" % basics.get("template_name"),
        "| SHA-256 | `%s` |" % basics.get("template_sha256"),
        "| 页面数量 | %s |" % ("可验证" if basics.get("page_count_verifiable") else "本次未验证"),
        "| 分节数量 | %s |" % basics.get("section_count"),
        "| 表格数量 | %s |" % basics.get("table_count"),
        "| 图片数量 | %s |" % basics.get("image_count"),
        "| 特殊对象数量 | %s |" % basics.get("special_object_count"),
        "",
        "## 2. 页面和样式规则",
        "",
        "- 页面规格：%s" % _format_value(styles.get("page_size")),
        "- 方向：%s" % _format_value(styles.get("orientation")),
        "- 页边距：%s" % _format_value(styles.get("margins")),
        "- 字体：%s" % _format_value(styles.get("fonts")),
        "- 字号（半磅）：%s" % _format_value(styles.get("sizes_half_pt")),
        "- 样式名：%s" % _format_value(styles.get("style_names")),
        "- 表格样式：%s" % _format_value(styles.get("table_styles")),
        "- 页眉页脚规则：%s" % _format_value(styles.get("header_footer_rules")),
        "",
        "## 3. 文档结构",
        "",
        "- 固定内容：%s" % _format_value(structure.get("fixed_content")),
        "- 可填写区域：%s" % _format_value(structure.get("fillable_areas")),
        "- 保护区：%s" % _format_value(structure.get("protected_areas")),
        "- 表格结构：%s" % _format_value(structure.get("tables")),
        "",
        "## 4. 字段与内容控件",
        "",
        "| 类型 | 位置 | 可编辑 | 说明 |",
        "|---|---|---|---|",
    ]
    for field in fields:
        lines.append(
            "| 字段 %s | `%s` | %s | `%s`；缓存结果 `%s`；锁 `%s` |"
            % (
                field.get("field_type"),
                field.get("officecli_path"),
                "是" if field.get("editable") else "否",
                field.get("instruction"),
                field.get("cached_result"),
                field.get("lock_state"),
            )
        )
    for sdt in sdts:
        lines.append(
            "| SDT %s | `%s` | %s | 含字段 `%s`；默认动作 `%s`；锁 `%s` |"
            % (
                sdt.get("type"),
                sdt.get("officecli_path"),
                "是" if sdt.get("editable") else "否",
                "是" if sdt.get("contains_fields") else "否",
                sdt.get("default_action"),
                sdt.get("lock"),
            )
        )
    if not fields and not sdts:
        lines.append("| （无） |  |  |  |")
    lines.extend(
        [
            "",
            "> 字段与未锁定 SDT 是可控编辑项，不再一律视为保护区；"
            "含字段 SDT 改文本必须显式确认字段丢失风险。",
            "",
            "## 5. 解析质量",
            "",
            "| 状态 | 数量 |",
            "|---|---|",
            "| VERIFIED | %s |" % quality.get("verified"),
            "| UNVERIFIED | %s |" % quality.get("unverified"),
            "| AMBIGUOUS | %s |" % quality.get("ambiguous"),
            "| CONFLICT | %s |" % quality.get("conflict"),
            "| 已解决 | %s |" % quality.get("resolved"),
            "| 未解决阻断项 | %s |" % quality.get("unresolved_blocking"),
            "| 覆盖率 | %s |" % quality.get("coverage"),
            "",
            "> %s" % quality.get("coverage_note"),
            "",
            "## 6. 阻断性问题",
            "",
        ]
    )
    if blocking:
        for item in blocking:
            lines.extend(
                [
                    "### %s — %s" % (item.get("item_id"), item.get("property")),
                    "",
                    "1. 问题编号：%s" % item.get("item_id"),
                    "2. 文档位置：`%s`" % item.get("location"),
                    "3. 当前解析结果：%s" % _format_value(item.get("current_result")),
                    "4. 不确定原因：%s" % item.get("reason"),
                    "5. 可能产生的错误：%s" % item.get("possible_error"),
                    "6. 需要补充的材料：%s" % "、".join(item.get("required_materials") or []),
                    "7. 可接受的解决方式：%s" % "；".join(item.get("acceptable_resolutions") or []),
                    "",
                ]
            )
    else:
        lines.extend(["当前没有阻断性问题。", ""])

    if risks:
        lines.extend(["## 7. 非阻断性风险", ""])
        for risk in risks:
            lines.append(
                "- `%s` %s（%s）：%s"
                % (
                    risk.get("property"),
                    risk.get("location"),
                    risk.get("verification_status"),
                    risk.get("detail"),
                )
            )
        lines.append("")

    lines.extend(
        [
            "## 8. 用户确认",
            "",
            str(confirmation.get("prompt") or "").strip(),
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


__all__ = ["build_report", "render_markdown", "report_digest"]
