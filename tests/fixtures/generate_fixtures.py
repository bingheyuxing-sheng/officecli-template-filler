# -*- coding: utf-8 -*-
"""One-shot generator for the six W2 real-template fixture classes.

The committed fixtures (``template.docx``, ``content_plan.json``, ``fill_plan.json``,
``expected/expected.json``) are self-contained: ``tests/test_fixture_matrix.py``
never calls this module. Regenerating is optional and deterministic: every DOCX
is rewritten with fixed ZIP timestamps so the template SHA-256 (and therefore the
slot-id namespace) stays stable.

Run from the repository root::

    py -3.15 tests/fixtures/generate_fixtures.py
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import docx  # noqa: E402
from docx.oxml import OxmlElement, parse_xml  # noqa: E402
from docx.oxml.ns import nsdecls, qn  # noqa: E402
from docx.shared import Cm, RGBColor  # noqa: E402
from PIL import Image  # noqa: E402

from content_intelligence import build_content_plan, build_fill_plan, validate_fill_plan  # noqa: E402
from content_intelligence.plan_builder import DENY_OPERATIONS  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402
from template_intelligence.spec_validator import validate_document_spec  # noqa: E402

FIXTURES = Path(__file__).resolve().parent
SCHEMA_VERSION = "4.0"
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


# ---------------------------------------------------------------------------
# deterministic writers
# ---------------------------------------------------------------------------


def save_docx(doc, path: Path) -> Path:
    """Save a DOCX and rewrite the ZIP with fixed timestamps (stable SHA-256)."""
    raw = path.with_suffix(".raw.docx")
    doc.save(str(raw))
    with zipfile.ZipFile(raw, "r") as source, zipfile.ZipFile(path, "w") as target:
        for info in source.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=ZIP_DATE)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = info.external_attr
            entry.create_system = 0
            target.writestr(entry, source.read(info.filename))
    raw.unlink()
    return path


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_bytes(size: Tuple[int, int], color: Tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# expectation helpers
# ---------------------------------------------------------------------------

_SLOT_FIELDS = (
    "slot_id",
    "slot_key",
    "location_id",
    "matched_text",
    "occurrence",
    "candidate_type",
    "protection_status",
    "confirmation_tier",
    "scope",
)


def _slot_expectation(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {field: slot.get(field) for field in _SLOT_FIELDS}
        for slot in spec["slots"]
    ]


def _region_expectation(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    regions = [
        {
            "kind": region.get("kind"),
            "location_id": region.get("location_id"),
            "severity": region.get("severity"),
            "evidence": region.get("evidence"),
        }
        for region in spec["protected_regions"]
    ]
    return sorted(regions, key=lambda item: (item["kind"], item["location_id"], item["severity"]))


def _unsupported_expectation(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = [
        {"code": item.get("code"), "location_id": item.get("location_id")}
        for item in spec["unsupported_features"]
    ]
    return sorted(items, key=lambda item: (item["code"], item["location_id"] or ""))


def _slot_by_text(spec: Dict[str, Any], text: str) -> Dict[str, Any]:
    for slot in spec["slots"]:
        if slot.get("matched_text") == text:
            return slot
    raise AssertionError("slot not produced for %r: %r" % (text, [s.get("matched_text") for s in spec["slots"]]))


def _base_expectation(name: str, spec: Dict[str, Any], template: Path) -> Dict[str, Any]:
    return {
        "class_key": name,
        "schema_version": SCHEMA_VERSION,
        "template_sha256": sha256_file(template),
        "compatibility": spec["template"]["compatibility"],
        "capabilities": spec["template"]["capabilities"],
        "slots": _slot_expectation(spec),
        "protected_regions": _region_expectation(spec),
        "unsupported_features": _unsupported_expectation(spec),
        "scenarios": [],
    }


def _scenario(name: str, plan: str, statuses: List[str], committed: bool, **extra: Any) -> Dict[str, Any]:
    payload = {
        "name": name,
        "plan": plan,
        "content_plan": extra.pop("content_plan", "content_plan.json"),
        "allowed_status": statuses,
        "committed": committed,
    }
    payload.update(extra)
    return payload


def _write_plan_bundle(class_dir: Path, content: Dict[str, Any], plan: Dict[str, Any],
                       filename: str = "fill_plan.json") -> None:
    write_json(class_dir / "content_plan.json", content)
    write_json(class_dir / filename, plan)


# ---------------------------------------------------------------------------
# class 01 — basic report: body tokens + simple table
# ---------------------------------------------------------------------------


def build_class_01(class_dir: Path) -> Dict[str, Any]:
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    document.add_paragraph("{{项目背景}}")
    document.add_paragraph("本报告仅用于内部评审。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "【合计金额】"
    table.cell(1, 1).text = ""
    template = save_docx(document, class_dir / "template.docx")

    spec = build_document_spec_from_path(str(template))
    assert validate_document_spec(spec)["passed"], validate_document_spec(spec)["errors"]
    name_slot = _slot_by_text(spec, "{{项目名称}}")
    background_slot = _slot_by_text(spec, "{{项目背景}}")
    total_slot = _slot_by_text(spec, "【合计金额】")

    facts = [
        {"fact_id": "F_001", "label": "项目名称", "value": "示例项目", "unit": "none",
         "source": "USER_INPUT", "verification_status": "VERIFIED", "used_by_slots": [name_slot["slot_id"]]},
        {"fact_id": "F_002", "label": "项目背景", "value": "本项目面向区域产业升级需求。", "unit": "none",
         "source": "USER_INPUT", "verification_status": "VERIFIED", "used_by_slots": [background_slot["slot_id"]]},
        {"fact_id": "F_003", "label": "合计金额", "value": "120000", "unit": "yuan",
         "source": "budget.xlsx!Sheet1!B2", "verification_status": "VERIFIED",
         "used_by_slots": [total_slot["slot_id"]]},
    ]
    content = build_content_plan(
        spec, plan_id="CP_FIXTURE_01",
        sections=[
            {"section_id": "SEC_001", "purpose": "项目信息",
             "target_slots": [name_slot["slot_id"], background_slot["slot_id"]],
             "fact_refs": ["F_001", "F_002"]},
            {"section_id": "SEC_002", "purpose": "预算", "target_slots": [total_slot["slot_id"]],
             "fact_refs": ["F_003"]},
        ],
        facts=facts,
        required_slots=[name_slot["slot_id"], background_slot["slot_id"], total_slot["slot_id"]],
    )
    plan = build_fill_plan(spec, content, task_id="TASK_FIXTURE_01", mode="STANDARD")
    assert validate_fill_plan(plan, spec, content)["passed"], validate_fill_plan(plan, spec, content)["errors"]
    _write_plan_bundle(class_dir, content, plan)

    expected = _base_expectation("class_01_basic_report", spec, template)
    expected["scenarios"] = [
        _scenario("primary", "fill_plan.json", ["SUCCESS", "UNVERIFIED"], True,
                  expect_text=[
                      {"location_id": "body.p[0]", "text": "示例项目"},
                      {"location_id": "body.p[1]", "text": "本项目面向区域产业升级需求。"},
                      {"location_id": "body.tbl[0].r[1].c[0].p[0]", "text": "120000"},
                  ],
                  expect_unchanged_text=[
                      {"location_id": "body.p[2]", "text": "本报告仅用于内部评审。"},
                      {"location_id": "body.tbl[0].r[0].c[0].p[0]", "text": "项目"},
                  ]),
        _scenario("qa_failure", "fill_plan.json", ["FAILED"], False, build="qa_failure",
                  expect_qa_status=["FAILED"]),
    ]
    write_json(class_dir / "expected" / "expected.json", expected)
    return expected


# ---------------------------------------------------------------------------
# class 02 — merged cells, repeated header row, token in a cell
# ---------------------------------------------------------------------------


def build_class_02(class_dir: Path) -> Dict[str, Any]:
    document = docx.Document()
    document.add_paragraph("项目预算表")
    table = document.add_table(rows=4, cols=3)
    table.cell(0, 0).text = "阶段"
    table.cell(0, 1).text = "预算"
    table.cell(0, 2).text = "备注"
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))

    table.cell(1, 0).text = "{{阶段说明}}"
    table.cell(1, 1).text = "合并单元格（固定）"
    table.cell(1, 1).merge(table.cell(1, 2))

    table.cell(2, 0).text = "{{项目阶段}}"
    table.cell(2, 0).merge(table.cell(3, 0))
    table.cell(2, 1).text = "120000"
    table.cell(2, 2).text = "含税"
    table.cell(3, 1).text = "60000"
    table.cell(3, 2).text = "不含税"
    template = save_docx(document, class_dir / "template.docx")

    spec = build_document_spec_from_path(str(template))
    assert validate_document_spec(spec)["passed"], validate_document_spec(spec)["errors"]
    stage_slot = _slot_by_text(spec, "{{阶段说明}}")
    phase_slot = _slot_by_text(spec, "{{项目阶段}}")

    facts = [
        {"fact_id": "F_101", "label": "阶段说明", "value": "准备阶段", "unit": "none",
         "source": "USER_INPUT", "verification_status": "VERIFIED", "used_by_slots": [stage_slot["slot_id"]]},
        {"fact_id": "F_102", "label": "项目阶段", "value": "实施阶段", "unit": "none",
         "source": "USER_INPUT", "verification_status": "VERIFIED", "used_by_slots": [phase_slot["slot_id"]]},
    ]
    content = build_content_plan(
        spec, plan_id="CP_FIXTURE_02",
        sections=[{"section_id": "SEC_101", "purpose": "阶段预算",
                   "target_slots": [stage_slot["slot_id"], phase_slot["slot_id"]],
                   "fact_refs": ["F_101", "F_102"]}],
        facts=facts,
        required_slots=[stage_slot["slot_id"], phase_slot["slot_id"]],
    )
    plan = build_fill_plan(spec, content, task_id="TASK_FIXTURE_02", mode="STANDARD")
    assert validate_fill_plan(plan, spec, content)["passed"], validate_fill_plan(plan, spec, content)["errors"]
    _write_plan_bundle(class_dir, content, plan)

    expected = _base_expectation("class_02_complex_table", spec, template)
    expected["table_structure"] = {"table_id": "body.tbl[0]", "min_grid_span": 1,
                                   "min_v_merge": 2, "min_tbl_header": 1}
    expected["scenarios"] = [
        _scenario("primary", "fill_plan.json", ["SUCCESS", "UNVERIFIED"], True,
                  expect_text=[
                      {"location_id": "body.tbl[0].r[1].c[0].p[0]", "text": "准备阶段"},
                      {"location_id": "body.tbl[0].r[2].c[0].p[0]", "text": "实施阶段"},
                  ],
                  expect_unchanged_text=[
                      {"location_id": "body.p[0]", "text": "项目预算表"},
                      {"location_id": "body.tbl[0].r[1].c[1].p[0]", "text": "合并单元格（固定）"},
                      {"location_id": "body.tbl[0].r[2].c[1].p[0]", "text": "120000"},
                  ],
                  expect_region_warning=True),
    ]
    write_json(class_dir / "expected" / "expected.json", expected)
    return expected


# ---------------------------------------------------------------------------
# class 03 — different-first-page header + even-page footer
# ---------------------------------------------------------------------------


def build_class_03(class_dir: Path) -> Dict[str, Any]:
    document = docx.Document()
    document.add_paragraph("正文：年度项目说明。")
    section = document.sections[0]
    section.different_first_page_header_footer = True
    document.settings.odd_and_even_pages_header_footer = True

    header = section.first_page_header
    header.is_linked_to_previous = False
    header.paragraphs[0].text = "{{封面标题}}"
    header.add_paragraph("内部资料（固定）")

    footer = section.even_page_footer
    footer.is_linked_to_previous = False
    footer.paragraphs[0].text = "{{偶数页脚注}}"
    footer.add_paragraph("机密 · 请勿外传")
    template = save_docx(document, class_dir / "template.docx")

    spec = build_document_spec_from_path(str(template))
    assert validate_document_spec(spec)["passed"], validate_document_spec(spec)["errors"]
    header_slot = _slot_by_text(spec, "{{封面标题}}")
    footer_slot = _slot_by_text(spec, "{{偶数页脚注}}")
    assert header_slot["location_id"] == "sec[0].first_page_header.p[0]"
    assert footer_slot["location_id"] == "sec[0].even_page_footer.p[0]"

    facts = [
        {"fact_id": "F_201", "label": "封面标题", "value": "2025年度报告", "unit": "none",
         "source": "USER_INPUT", "verification_status": "VERIFIED", "used_by_slots": [header_slot["slot_id"]]},
        {"fact_id": "F_202", "label": "偶数页脚注", "value": "内部资料 第2页", "unit": "none",
         "source": "USER_INPUT", "verification_status": "VERIFIED", "used_by_slots": [footer_slot["slot_id"]]},
    ]
    content = build_content_plan(
        spec, plan_id="CP_FIXTURE_03",
        sections=[{"section_id": "SEC_201", "purpose": "页眉页脚",
                   "target_slots": [header_slot["slot_id"], footer_slot["slot_id"]],
                   "fact_refs": ["F_201", "F_202"]}],
        facts=facts,
        required_slots=[header_slot["slot_id"], footer_slot["slot_id"]],
    )
    plan = build_fill_plan(spec, content, task_id="TASK_FIXTURE_03", mode="STANDARD")
    assert validate_fill_plan(plan, spec, content)["passed"], validate_fill_plan(plan, spec, content)["errors"]
    _write_plan_bundle(class_dir, content, plan)

    expected = _base_expectation("class_03_header_footer", spec, template)
    expected["header_footer"] = {
        "first_page_header": ["2025年度报告", "内部资料（固定）"],
        "even_page_footer": ["内部资料 第2页", "机密 · 请勿外传"],
        "different_first_page_header_footer": True,
        "odd_and_even_pages_header_footer": True,
    }
    expected["scenarios"] = [
        _scenario("primary", "fill_plan.json", ["SUCCESS", "UNVERIFIED"], True,
                  expect_text=[
                      {"location_id": "sec[0].first_page_header.p[0]", "text": "2025年度报告"},
                      {"location_id": "sec[0].even_page_footer.p[0]", "text": "内部资料 第2页"},
                  ],
                  expect_unchanged_text=[
                      {"location_id": "body.p[0]", "text": "正文：年度项目说明。"},
                      {"location_id": "sec[0].first_page_header.p[1]", "text": "内部资料（固定）"},
                      {"location_id": "sec[0].even_page_footer.p[1]", "text": "机密 · 请勿外传"},
                  ]),
    ]
    write_json(class_dir / "expected" / "expected.json", expected)
    return expected


# ---------------------------------------------------------------------------
# class 04 — inline PNG placeholder + authorized replace_image
# ---------------------------------------------------------------------------


def build_class_04(class_dir: Path) -> Dict[str, Any]:
    old_png = png_bytes((420, 300), (30, 120, 200))
    replacement = class_dir / "replacement.png"
    replacement.write_bytes(png_bytes((420, 300), (200, 60, 30)))

    document = docx.Document()
    document.add_paragraph("项目示意图如下。")
    paragraph = document.add_paragraph()
    paragraph.add_run("{{图1}}").add_picture(io.BytesIO(old_png), width=Cm(6))
    document.add_paragraph("图后说明。")
    template = save_docx(document, class_dir / "template.docx")

    spec = build_document_spec_from_path(str(template))
    assert validate_document_spec(spec)["passed"], validate_document_spec(spec)["errors"]
    image_slot = _slot_by_text(spec, "{{图1}}")
    image_entries = [image for image in spec["structure"]["images"]
                     if image["location_id"] == image_slot["location_id"]]
    assert image_entries, "inline picture must share the slot paragraph"

    fact = {"fact_id": "F_IMG", "label": "图注", "value": "图1：项目示意", "unit": "none",
            "source": "USER_INPUT", "verification_status": "VERIFIED",
            "used_by_slots": [image_slot["slot_id"]]}
    content = build_content_plan(
        spec, plan_id="CP_FIXTURE_04",
        sections=[{"section_id": "SEC_301", "purpose": "配图",
                   "target_slots": [image_slot["slot_id"]], "fact_refs": ["F_IMG"]}],
        facts=[fact],
        required_slots=[image_slot["slot_id"]],
    )
    plan = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "TASK_FIXTURE_04",
        "template_id": spec["template"]["template_id"],
        "mode": "STANDARD",
        "baseline": {
            "template_sha256": spec["template"]["template_sha256"],
            "spec_schema_version": SCHEMA_VERSION,
            "fingerprint_id": spec["fingerprint_ref"]["fingerprint_id"],
            "allowed_slot_ids": [image_slot["slot_id"]],
        },
        "operations": [
            {
                "op_id": "OP_001", "sequence": 1, "type": "replace_image",
                "slot_id": image_slot["slot_id"],
                "target": {"location_id": image_slot["location_id"], "image_role": "illustration"},
                "source_ref": "IMAGE_INPUT", "value": "replacement.png", "policy": "STRICT",
                "preconditions": ["slot_exists", "not_protected", "template_sha_match"],
                "overflow": {"measured_chars": 0, "limit_source": "none",
                             "limit_value": None, "strategy": "REJECT"},
            },
            {
                "op_id": "OP_002", "sequence": 2, "type": "replace_text",
                "slot_id": image_slot["slot_id"],
                "target": {"location_id": image_slot["location_id"]},
                "source_ref": "F_IMG", "value": fact["value"], "value_ref": "F_IMG",
                "policy": "STRICT",
                "preconditions": ["slot_exists", "not_protected", "template_sha_match"],
                "overflow": {"measured_chars": len(fact["value"]), "limit_source": "none",
                             "limit_value": None, "strategy": "REJECT"},
            },
        ],
        "global_policy": {"allow_structure_change": False,
                          "deny_operations": list(DENY_OPERATIONS),
                          "styles": "DENY", "page_setup": "DENY"},
    }
    assert validate_fill_plan(plan, spec, content)["passed"], validate_fill_plan(plan, spec, content)["errors"]
    _write_plan_bundle(class_dir, content, plan)

    template_document = docx.Document(str(template))
    extent = template_document.element.body.xpath(".//wp:extent")[0]
    expected = _base_expectation("class_04_images", spec, template)
    expected["image"] = {
        "replacement_file": "replacement.png",
        "replacement_sha256": sha256_file(replacement),
        "extent_cx": int(extent.get("cx")),
        "extent_cy": int(extent.get("cy")),
        "slot_location": image_slot["location_id"],
        # The committed FillPlan stores a fixture-relative path so the repository
        # stays portable; test_fixture_matrix resolves it to an absolute path.
        "plan_value_is_relative": True,
    }
    expected["scenarios"] = [
        _scenario("primary", "fill_plan.json", ["SUCCESS", "UNVERIFIED"], True,
                  expect_text=[{"location_id": "body.p[1]", "text": "图1：项目示意"}],
                  expect_unchanged_text=[
                      {"location_id": "body.p[0]", "text": "项目示意图如下。"},
                      {"location_id": "body.p[2]", "text": "图后说明。"},
                  ],
                  image="replacement.png"),
    ]
    write_json(class_dir / "expected" / "expected.json", expected)
    return expected


# ---------------------------------------------------------------------------
# class 05 — nested table; slot inside a nested cell
# ---------------------------------------------------------------------------


def build_class_05(class_dir: Path) -> Dict[str, Any]:
    document = docx.Document()
    document.add_paragraph("嵌套结构模板")
    outer = document.add_table(rows=2, cols=2)
    outer.cell(0, 0).text = "阶段"
    outer.cell(0, 1).text = "金额"
    outer.cell(1, 0).text = "明细"
    inner = outer.cell(1, 1).add_table(rows=1, cols=2)
    inner.cell(0, 0).text = "{{子项名称}}"
    inner.cell(0, 1).text = "{{子项金额}}"
    template = save_docx(document, class_dir / "template.docx")

    spec = build_document_spec_from_path(str(template))
    assert validate_document_spec(spec)["passed"], validate_document_spec(spec)["errors"]
    assert spec["template"]["capabilities"]["nested_table"] is True
    name_slot = _slot_by_text(spec, "{{子项名称}}")
    amount_slot = _slot_by_text(spec, "{{子项金额}}")
    assert ".tbl[0].r[0].c[0]" in name_slot["location_id"], name_slot["location_id"]

    facts = [
        {"fact_id": "F_401", "label": "子项名称", "value": "设备采购", "unit": "none",
         "source": "USER_INPUT", "verification_status": "VERIFIED", "used_by_slots": [name_slot["slot_id"]]},
        {"fact_id": "F_402", "label": "子项金额", "value": "5000", "unit": "yuan",
         "source": "USER_INPUT", "verification_status": "VERIFIED", "used_by_slots": [amount_slot["slot_id"]]},
    ]
    content = build_content_plan(
        spec, plan_id="CP_FIXTURE_05",
        sections=[{"section_id": "SEC_401", "purpose": "子项明细",
                   "target_slots": [name_slot["slot_id"], amount_slot["slot_id"]],
                   "fact_refs": ["F_401", "F_402"]}],
        facts=facts,
        required_slots=[name_slot["slot_id"], amount_slot["slot_id"]],
    )
    plan = build_fill_plan(spec, content, task_id="TASK_FIXTURE_05", mode="STANDARD")
    assert validate_fill_plan(plan, spec, content)["passed"], validate_fill_plan(plan, spec, content)["errors"]

    # Paragraph-level alternative: the same authorized slots filled with `replace_text`
    # on the nested paragraph location.  The builder emits a `fill_cell` target for
    # the nested table itself; this second plan keeps the paragraph-level path covered.
    paragraph_plan = copy.deepcopy(plan)
    for operation, slot in zip(paragraph_plan["operations"], [name_slot, amount_slot]):
        operation["type"] = "replace_text"
        operation["target"] = {"location_id": slot["location_id"]}
    assert validate_fill_plan(paragraph_plan, spec, content)["passed"], \
        validate_fill_plan(paragraph_plan, spec, content)["errors"]

    _write_plan_bundle(class_dir, content, plan)
    write_json(class_dir / "fill_plan_paragraph_level.json", paragraph_plan)

    expected = _base_expectation("class_05_nested_structure", spec, template)
    expected["nested"] = {
        "outer_table": "body.tbl[0]",
        "inner_table": "body.tbl[0].r[1].c[1].tbl[0]",
        "outer_cell_text": "明细",
    }
    expected["known_production_gaps"] = [
        "Nested-table fill_cell targeting is fixed: the plan resolves "
        "body.tbl[0].r[1].c[1].tbl[0] directly. Legacy plans that still declare "
        "table_id=body.tbl[0] for a nested slot are now rejected as "
        "TARGET_FIELD_MISMATCH instead of silently addressing the outer cell."
    ]
    expected["scenarios"] = [
        _scenario("primary_builder_plan", "fill_plan.json", ["SUCCESS", "UNVERIFIED"], True,
                  expect_text=[
                      {"location_id": name_slot["location_id"], "text": "设备采购"},
                      {"location_id": amount_slot["location_id"], "text": "5000"},
                  ],
                  expect_unchanged_text=[
                      {"location_id": "body.p[0]", "text": "嵌套结构模板"},
                      {"location_id": "body.tbl[0].r[1].c[0].p[0]", "text": "明细"},
                  ]),
        _scenario("paragraph_level_plan", "fill_plan_paragraph_level.json", ["SUCCESS", "UNVERIFIED"], True,
                  expect_text=[
                      {"location_id": name_slot["location_id"], "text": "设备采购"},
                      {"location_id": amount_slot["location_id"], "text": "5000"},
                  ],
                  expect_unchanged_text=[
                      {"location_id": "body.p[0]", "text": "嵌套结构模板"},
                      {"location_id": "body.tbl[0].r[1].c[0].p[0]", "text": "明细"},
                  ]),
    ]
    write_json(class_dir / "expected" / "expected.json", expected)
    return expected


# ---------------------------------------------------------------------------
# class 06 — SDT, field code and a fixed title must stay untouched
# ---------------------------------------------------------------------------


def build_class_06(class_dir: Path) -> Dict[str, Any]:
    document = docx.Document()
    document.add_paragraph("年度报告（固定标题）")
    document.add_paragraph("{{报表名称}}")
    control_paragraph = document.add_paragraph()
    control_paragraph.add_run("受控字段：")
    control_paragraph._p.append(parse_xml(
        f"<w:sdt {nsdecls('w')}><w:sdtPr/><w:sdtContent>"
        "<w:r><w:t>项目编号</w:t></w:r></w:sdtContent></w:sdt>"
    ))
    field_paragraph = document.add_paragraph()
    field_paragraph.add_run("页码：")
    field_paragraph._p.append(parse_xml(
        f"<w:fldSimple {nsdecls('w')} w:instr=\"PAGE\"><w:r><w:t>1</w:t></w:r></w:fldSimple>"
    ))
    template = save_docx(document, class_dir / "template.docx")

    spec = build_document_spec_from_path(str(template))
    assert validate_document_spec(spec)["passed"], validate_document_spec(spec)["errors"]
    assert spec["template"]["compatibility"] == "L3"
    normal_slot = _slot_by_text(spec, "{{报表名称}}")
    protected_slots = [slot for slot in spec["slots"] if slot["protection_status"] == "PROTECTED"]
    assert len(protected_slots) == 2, protected_slots
    codes = {item["code"] for item in spec["unsupported_features"]}
    assert {"SDT_EDIT_UNSUPPORTED", "FIELD_UPDATE_UNSUPPORTED"} <= codes, codes

    fact = {"fact_id": "F_501", "label": "报表名称", "value": "2025年度报告", "unit": "none",
            "source": "USER_INPUT", "verification_status": "VERIFIED",
            "used_by_slots": [normal_slot["slot_id"]]}
    content = build_content_plan(
        spec, plan_id="CP_FIXTURE_06",
        sections=[{"section_id": "SEC_501", "purpose": "报表名称",
                   "target_slots": [normal_slot["slot_id"]], "fact_refs": ["F_501"]}],
        facts=[fact],
        required_slots=[normal_slot["slot_id"]],
    )
    plan = build_fill_plan(spec, content, task_id="TASK_FIXTURE_06", mode="STANDARD")
    assert validate_fill_plan(plan, spec, content)["passed"], validate_fill_plan(plan, spec, content)["errors"]
    _write_plan_bundle(class_dir, content, plan)

    expected = _base_expectation("class_06_complex_document", spec, template)
    expected["controls"] = {
        "sdt_count": 1,
        "field_count": 1,
        "sdt_texts": ["项目编号"],
        "field_texts": ["1"],
        "fixed_texts": ["年度报告（固定标题）"],
        "protected_slot_texts": [slot["matched_text"] for slot in protected_slots],
    }
    expected["scenarios"] = [
        _scenario("primary", "fill_plan.json", ["SUCCESS", "UNVERIFIED"], True,
                  expect_text=[
                      {"location_id": "body.p[0]", "text": "年度报告（固定标题）"},
                      {"location_id": "body.p[1]", "text": "2025年度报告"},
                      {"location_id": "body.p[2]", "text": "受控字段：项目编号"},
                      {"location_id": "body.p[3]", "text": "页码：1"},
                  ]),
        _scenario("protected_target_refused", None, ["BLOCKED"], False,
                  build="protected_target",
                  expect_validation_errors=["PROTECTED_SLOT_VIOLATION"]),
    ]
    write_json(class_dir / "expected" / "expected.json", expected)
    return expected


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

BUILDERS = (
    ("class_01_basic_report", build_class_01),
    ("class_02_complex_table", build_class_02),
    ("class_03_header_footer", build_class_03),
    ("class_04_images", build_class_04),
    ("class_05_nested_structure", build_class_05),
    ("class_06_complex_document", build_class_06),
)


def main() -> int:
    for name, builder in BUILDERS:
        class_dir = FIXTURES / name
        class_dir.mkdir(parents=True, exist_ok=True)
        (class_dir / "expected").mkdir(parents=True, exist_ok=True)
        expected = builder(class_dir)
        print("%-32s sha=%s slots=%d regions=%d unsupported=%d" % (
            name,
            expected["template_sha256"][:12],
            len(expected["slots"]),
            len(expected["protected_regions"]),
            len(expected["unsupported_features"]),
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
