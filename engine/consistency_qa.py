# -*- coding: utf-8 -*-
"""Content-truth QA: numeric conflicts, table subtotals, term drift, fact sources.

Format QA proves the document *looks* right. This module checks whether the numbers and
names *agree with each other*, which is the failure mode a reviewer spends the most time
on: prose says 100 万 while the table says 105 万, a subtotal row does not add up, or the
same course/person is spelled two ways.

Design rules:
- Deterministic and evidence-first: every issue carries both locations and both values.
- Conservative severities: an explicit total label (总/合计/小计/共) that contradicts itself
  is `high` (not deliverable); an ordinary label that varies is `medium` (advisory) because
  it may legitimately describe different scopes.
- No inference of "truth": the module never decides which value is correct.
"""

from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import docx

_NUM = r"[-+]?\d[\d,]*(?:\.\d+)?"
_UNIT_PATTERN = r"(学分|学时|课时|万元|亿元|元|%|人|门|个|项|次|天|周)"

# `总学时：2504`, `总学分 126.5`, `实践教学占总学时比例达61.18%`
_LABEL_VALUE_RE = re.compile(
    rf"([\u4e00-\u9fa5]{{2,12}}?)\s*(?:为|达到|达|是|共|约)?\s*[：:]\s*({_NUM})\s*{_UNIT_PATTERN}?"
)
_LABEL_WITH_UNIT_RE = re.compile(
    rf"([\u4e00-\u9fa5]{{2,12}}?)\s*({_NUM})\s*{_UNIT_PATTERN}"
)
_TOTAL_LABEL_MARKERS = ("总", "合计", "小计", "共计", "累计", "总计")
_TOTAL_ROW_RE = re.compile(r"^\s*(合计|小计|总计|共计|总\s*计|合\s*计)\s*$")
_DATE_CN_RE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
_DATE_ISO_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")

_SEVERITY_HIGH = "high"
_SEVERITY_MEDIUM = "medium"
_SEVERITY_LOW = "low"


def _to_decimal(raw: str) -> Optional[Decimal]:
    text = (raw or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _issue(code: str, location: str, detail: str, severity: str = _SEVERITY_MEDIUM) -> Dict[str, Any]:
    return {"code": code, "location": location, "detail": detail, "severity": severity}


def _story_paragraphs(document) -> Iterable[Tuple[str, Any]]:
    """Body paragraphs plus header/footer paragraphs, each with a stable location id."""
    for index, paragraph in enumerate(document.paragraphs):
        yield f"body.p[{index}]", paragraph
    for section_index, section in enumerate(document.sections):
        for name in (
            "header", "first_page_header", "even_page_header",
            "footer", "first_page_footer", "even_page_footer",
        ):
            hf = getattr(section, name, None)
            if hf is None:
                continue
            try:
                # Reading ``.paragraphs`` on a linked header/footer makes python-docx
                # create a phantom part and a reference in ``w:sectPr``; skip first.
                if hf.is_linked_to_previous:
                    continue
                paragraphs = list(hf.paragraphs)
            except Exception:
                continue
            for index, paragraph in enumerate(paragraphs):
                yield f"sec[{section_index}].{name}.p[{index}]", paragraph


_PLAIN_NUMBER_RE = re.compile(rf"^({_NUM})\s*{_UNIT_PATTERN}?$")
_LABEL_ONLY_RE = re.compile(r"^[\u4e00-\u9fa5]{2,12}$")


def _row_pairs(row) -> Iterable[Tuple[str, str]]:
    """Pair a label-only cell with the following numeric cell (`总投资` | `105万元`)."""
    cells = [(cell.text or "").strip() for cell in row.cells]
    for index, text in enumerate(cells[:-1]):
        if not _LABEL_ONLY_RE.match(text) or _is_total_row_text(text):
            continue
        match = _PLAIN_NUMBER_RE.match(cells[index + 1])
        if not match:
            continue
        yield text, cells[index + 1]


def _is_total_row_text(text: str) -> bool:
    return bool(_TOTAL_ROW_RE.match(text))


def extract_labeled_values(document) -> List[Dict[str, Any]]:
    """Extract `{label, value, unit, location, source}` pairs from prose and table cells."""
    findings: List[Dict[str, Any]] = []

    for location, paragraph in _story_paragraphs(document):
        text = paragraph.text or ""
        if not text.strip():
            continue
        for pattern in (_LABEL_VALUE_RE, _LABEL_WITH_UNIT_RE):
            for match in pattern.finditer(text):
                label = (match.group(1) or "").strip("，。、；：()（）")
                value = _to_decimal(match.group(2))
                unit = (match.group(3) or "").strip()
                if value is None or not label:
                    continue
                findings.append({
                    "label": _normalize_label(label),
                    "value": value,
                    "unit": unit,
                    "location": location,
                    "source": "text",
                    "table_index": None,
                })

    for table_index, table in enumerate(document.tables):
        for row_index, row in enumerate(table.rows):
            for cell_index, cell in enumerate(row.cells):
                text = (cell.text or "").strip()
                if not text or len(text) > 120:
                    continue
                location = f"body.tbl[{table_index}].r[{row_index}].c[{cell_index}]"
                for pattern in (_LABEL_VALUE_RE, _LABEL_WITH_UNIT_RE):
                    for match in pattern.finditer(text):
                        label = (match.group(1) or "").strip("，。、；：()（）")
                        value = _to_decimal(match.group(2))
                        unit = (match.group(3) or "").strip()
                        if value is None or not label:
                            continue
                        findings.append({
                            "label": _normalize_label(label),
                            "value": value,
                            "unit": unit,
                            "location": location,
                            "source": "table",
                            "table_index": table_index,
                        })
            # `总投资 | 105万元` split across two cells is the common table layout.
            for label, raw_value in _row_pairs(row):
                match = _PLAIN_NUMBER_RE.match(raw_value)
                value = _to_decimal(match.group(1)) if match else None
                if value is None:
                    continue
                findings.append({
                    "label": _normalize_label(label),
                    "value": value,
                    "unit": (match.group(2) or "").strip() if match else "",
                    "location": f"body.tbl[{table_index}].r[{row_index}].c[0]",
                    "source": "table",
                    "table_index": table_index,
                })
    return findings


_LABEL_PREFIXES = ("项目", "本", "该", "其中", "全校", "全院", "全专业", "本专业")


def _normalize_label(label: str) -> str:
    """Drop scope prefixes so `项目总投资` and `总投资` compare as the same metric."""
    value = (label or "").strip()
    changed = True
    while changed:
        changed = False
        for prefix in _LABEL_PREFIXES:
            if value.startswith(prefix) and len(value) - len(prefix) >= 2:
                value = value[len(prefix):]
                changed = True
    return value


def _is_total_label(label: str) -> bool:
    return any(marker in label for marker in _TOTAL_LABEL_MARKERS)


def check_value_conflicts(findings: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Report labels that carry different values in different places.

    Table-internal variation is normal (each row legitimately has its own 理论学时), so a
    conflict is only reported when:
    - the label is an explicit total (总/合计/小计/共) — any disagreement is a real error, or
    - prose and a table disagree — the classic "正文说 100 万、表格写 105 万" case.

    Values inside tables for the same non-total label are treated as data rows and skipped.
    """
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in findings:
        grouped[(item["label"], item["unit"])].append(item)

    issues: List[Dict[str, Any]] = []
    for (label, unit), items in grouped.items():
        distinct = {item["value"] for item in items}
        if len(distinct) < 2:
            continue
        sources = {item["source"] for item in items}
        tables = {item.get("table_index") for item in items if item.get("table_index") is not None}
        is_total = _is_total_label(label)
        if not is_total and sources == {"table"} and len(tables) <= 1:
            # Per-row data inside one table: each row legitimately has its own value.
            continue
        if not is_total and len(distinct) > 3:
            # Many distinct values under one generic label is an enumeration
            # (per-semester totals, per-course hours), not a contradiction.
            continue
        locations = [item["location"] for item in items][:6]
        values = ", ".join(str(value) for value in sorted(distinct))
        severity = _SEVERITY_HIGH if is_total else _SEVERITY_MEDIUM
        code = "CONTENT_VALUE_CONFLICT" if is_total else "CONTENT_LABEL_VALUE_VARIANCE"
        issues.append(_issue(
            code,
            locations[0],
            f"'{label}{unit}' appears with different values ({values}) at {locations}",
            severity,
        ))
    return issues


def check_table_subtotals(document) -> List[Dict[str, Any]]:
    """
    Verify that a trailing 合计/小计 row equals the sum of the rows above it.

    Only the last row of a table is treated as a total row, and only when every cell from
    the second column onward is a plain number. Anything else is left alone rather than
    guessed at.
    """
    issues: List[Dict[str, Any]] = []
    for table_index, table in enumerate(document.tables):
        if len(table.rows) < 3:
            continue
        total_row = table.rows[-1]
        first_cell = (total_row.cells[0].text or "").strip() if total_row.cells else ""
        if not _TOTAL_ROW_RE.match(first_cell):
            continue

        data_rows = table.rows[:-1]
        column_count = len(total_row.cells)
        for column_index in range(1, column_count):
            total_text = (total_row.cells[column_index].text or "").replace(",", "").strip()
            if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", total_text):
                continue
            total_value = _to_decimal(total_text)
            if total_value is None:
                continue
            parts: List[Decimal] = []
            for row_index, row in enumerate(data_rows):
                cell_text = (row.cells[column_index].text or "").replace(",", "").strip() if column_index < len(row.cells) else ""
                if not cell_text:
                    continue
                if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cell_text):
                    if row_index == 0:
                        # Ordinary tables carry a header row (指标 | 数值); it is a label
                        # row, not a broken data row, so skip it instead of giving up.
                        continue
                    parts = []
                    break
                value = _to_decimal(cell_text)
                if value is None:
                    if row_index == 0:
                        continue
                    parts = []
                    break
                parts.append(value)
            if len(parts) < 2:
                continue
            computed = sum(parts, Decimal("0"))
            if computed != total_value:
                total_row_index = len(table.rows) - 1
                issues.append(_issue(
                    "CONTENT_SUBTOTAL_MISMATCH",
                    f"body.tbl[{table_index}].r[{total_row_index}].c[{column_index}]",
                    f"total row says {total_value} but column sum is {computed} "
                    f"(tbl[{table_index}] col[{column_index}] over {len(parts)} rows)",
                    _SEVERITY_HIGH,
                ))
    return issues


def _edit_distance_one(left: str, right: str) -> bool:
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(1 for a, b in zip(left, right) if a != b) == 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    for index in range(len(longer)):
        if longer[:index] + longer[index + 1:] == shorter:
            return True
    return False


_NAME_MARKER_RE = re.compile(
    r"(?:姓名|名称|专业|学院|课程|负责人|主讲|教师|单位|部门|教研室)\s*[：:]?\s*([\u4e00-\u9fa5]{2,12})"
)

# Tokens that are metric or section words, not proper nouns. Without this filter
# 必修课学分 / 选修课学分 and 素质目标 / 素养目标 look like one-character typos.
_NON_NAME_WORDS = (
    "学分", "学时", "课时", "目标", "要求", "比例", "合计", "小计", "总数",
    "名称", "类别", "模块", "课程", "专业", "学院", "毕业", "培养", "教学",
)


def _looks_like_name(token: str) -> bool:
    return not any(word in token for word in _NON_NAME_WORDS)


def _name_columns(table) -> List[int]:
    """
    Columns whose cells are mostly distinct short Chinese values — i.e. name columns.

    A category column (必修/限选/考试) repeats a handful of values, so it is excluded;
    including it would make 教室/教师 or 考核/考试 look like spelling drift.
    """
    columns: List[int] = []
    try:
        column_count = len(table.columns)
    except Exception:
        return columns

    for column_index in range(column_count):
        values: List[str] = []
        for row in table.rows:
            if column_index >= len(row.cells):
                continue
            text = (row.cells[column_index].text or "").strip()
            if text:
                values.append(text)
        if len(values) < 2:
            continue
        if not all(2 <= len(value) <= 12 and re.fullmatch(r"[\u4e00-\u9fa5]+", value) for value in values):
            continue
        distinct = len(set(values))
        if distinct < 2 or distinct < 0.6 * len(values):
            continue
        columns.append(column_index)
    return columns


def _name_like_tokens(document) -> set:
    """
    Tokens that occupy a name position anywhere in the document.

    Restricting candidates to these positions is what separates a real spelling drift
    (张伟 / 张玮 in a name column) from ordinary vocabulary that differs by one character
    (必修课学分 / 选修课学分, 素质目标 / 素养目标, 考核 / 考试).
    """
    tokens: set = set()

    for _location, paragraph in _story_paragraphs(document):
        for match in _NAME_MARKER_RE.finditer(paragraph.text or ""):
            token = match.group(1)
            # 2-character captures after 专业/学院 are usually ordinary words, not names.
            if len(token) >= 3 and _looks_like_name(token):
                tokens.add(token)

    for table in document.tables:
        for column_index in _name_columns(table):
            for row in table.rows:
                if column_index >= len(row.cells):
                    continue
                text = (row.cells[column_index].text or "").strip()
                if _looks_like_name(text):
                    tokens.add(text)
    return tokens


def _count_occurrences(document, targets: set) -> Counter:
    """Total occurrences of the candidate names anywhere in the document."""
    counter: Counter = Counter()

    def _scan(text: str) -> None:
        for token in targets:
            count = (text or "").count(token)
            if count:
                counter[token] += count

    for _location, paragraph in _story_paragraphs(document):
        _scan(paragraph.text)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                _scan(cell.text)
    return counter


def _term_locations(document, target: str) -> str:
    for location, paragraph in _story_paragraphs(document):
        if target in (paragraph.text or ""):
            return location
    for table_index, table in enumerate(document.tables):
        for row_index, row in enumerate(table.rows):
            for cell_index, cell in enumerate(row.cells):
                if target in (cell.text or ""):
                    return f"body.tbl[{table_index}].r[{row_index}].c[{cell_index}]"
    return "body"


def check_term_drift(document, min_occurrences: int = 2, rarity_ratio: int = 3) -> List[Dict[str, Any]]:
    """
    Report one-character *substitutions* of the same proper noun (张伟 / 张玮).

    Tight rules, because a noisy term check is worse than none:
    - only tokens occupying a name position (a name column cell, or after 姓名/专业/课程…);
    - same length, exactly one substituted character — an inserted 「一」/「二」 or a longer
      prefix like 「专业拓展」 vs 「专业拓展课」 is a normal variant, not drift;
    - neither token is a substring of the other;
    - the rare spelling may appear once, but the common one must appear at least
      `min_occurrences` times and at least `rarity_ratio` times as often — that is the
      shape of a typo, not of two different names.
    """
    counter = _count_occurrences(document, _name_like_tokens(document))
    # The rare spelling may appear only once (a typo), but the common one must dominate.
    candidates = [token for token, count in counter.items() if count >= 1]

    issues: List[Dict[str, Any]] = []
    seen = set()
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            key = tuple(sorted((left, right)))
            if key in seen:
                continue
            if len(left) != len(right):
                continue
            if left in right or right in left:
                continue
            if not _edit_distance_one(left, right):
                continue
            common, rare = (left, right) if counter[left] >= counter[right] else (right, left)
            if counter[common] < max(min_occurrences, counter[rare] * rarity_ratio):
                continue
            seen.add(key)
            issues.append(_issue(
                "CONTENT_TERM_DRIFT",
                _term_locations(document, rare),
                f"'{rare}' ({counter[rare]}x) vs '{common}' ({counter[common]}x) differ by one character; "
                "confirm which spelling is correct",
                _SEVERITY_MEDIUM,
            ))
    return issues


def check_date_and_unit_style(document) -> List[Dict[str, Any]]:
    """Flag mixed Chinese/ISO date formats and 万/万元 unit style in the same document."""
    cn_dates = 0
    iso_dates = 0
    unit_wan = 0
    unit_wanyuan = 0
    first_cn = ""
    first_iso = ""
    first_wan = ""
    first_wanyuan = ""

    for location, paragraph in _story_paragraphs(document):
        text = paragraph.text or ""
        if not text:
            continue
        for _match in _DATE_CN_RE.finditer(text):
            cn_dates += 1
            first_cn = first_cn or location
        for _match in _DATE_ISO_RE.finditer(text):
            iso_dates += 1
            first_iso = first_iso or location
        if re.search(r"\d\s*万元", text):
            unit_wanyuan += 1
            first_wanyuan = first_wanyuan or location
        elif re.search(r"\d\s*万(?!元)", text):
            unit_wan += 1
            first_wan = first_wan or location

    issues: List[Dict[str, Any]] = []
    if cn_dates and iso_dates:
        issues.append(_issue(
            "CONTENT_DATE_FORMAT_MIXED",
            first_iso or first_cn,
            f"both '2026年11月4日' ({cn_dates}x, e.g. {first_cn}) and '2026-11-04' ({iso_dates}x, e.g. {first_iso}) are used",
            _SEVERITY_LOW,
        ))
    if unit_wan and unit_wanyuan:
        issues.append(_issue(
            "CONTENT_UNIT_STYLE_MIXED",
            first_wan or first_wanyuan,
            f"both '万' ({unit_wan}x, e.g. {first_wan}) and '万元' ({unit_wanyuan}x, e.g. {first_wanyuan}) are used",
            _SEVERITY_LOW,
        ))
    return issues


def audit_fact_sources(facts: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Verify that every fact in an SSOT payload declares where it came from.

    `source` must be a URL, a named internal reference, or the explicit marker
    `UNVERIFIED`/`MODEL_GENERATED` so an auditor can tell the three apart.
    """
    issues: List[Dict[str, Any]] = []
    items = list(facts or [])
    for index, fact in enumerate(items):
        if not isinstance(fact, dict):
            issues.append(_issue(
                "FACT_ENTRY_INVALID", f"facts[{index}]", "fact entry is not an object", _SEVERITY_HIGH,
            ))
            continue
        source = str(fact.get("source") or "").strip()
        label = fact.get("label") or fact.get("key") or fact.get("name") or f"facts[{index}]"
        if not source:
            issues.append(_issue(
                "FACT_SOURCE_MISSING", f"facts[{index}]",
                f"'{label}' has no source; add a URL, an internal reference name, or 'UNVERIFIED'",
                _SEVERITY_HIGH,
            ))
    return {
        "passed": not issues,
        "issues": issues,
        "checked_count": len(items),
        "unverified_count": sum(
            1 for fact in items
            if isinstance(fact, dict) and str(fact.get("source") or "").strip().upper() in ("UNVERIFIED", "MODEL_GENERATED")
        ),
    }


def find_numeric_occurrences(document, numbers: Sequence[Any]) -> List[Dict[str, Any]]:
    """Locate every occurrence of the given numbers (PROOFREAD evidence, not a decision)."""
    targets = []
    for value in numbers:
        dec = _to_decimal(str(value))
        if dec is not None:
            targets.append(dec)
    if not targets:
        return []

    results: List[Dict[str, Any]] = []

    def _scan(location: str, text: str) -> None:
        for match in re.finditer(_NUM, text or ""):
            dec = _to_decimal(match.group(0))
            if dec is None or dec not in targets:
                continue
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 20)
            results.append({
                "number": str(dec),
                "location": location,
                "context": text[start:end].strip(),
            })

    for location, paragraph in _story_paragraphs(document):
        _scan(location, paragraph.text)
    for table_index, table in enumerate(document.tables):
        for row_index, row in enumerate(table.rows):
            for cell_index, cell in enumerate(row.cells):
                _scan(f"body.tbl[{table_index}].r[{row_index}].c[{cell_index}]", cell.text)
    return results


def audit_content_consistency(
    docx_path: Optional[str] = None,
    doc: Optional[Any] = None,
    check_terms: bool = True,
) -> Dict[str, Any]:
    """Run every content-truth check and return one structured report section."""
    if doc is None:
        if not docx_path or not os.path.isfile(docx_path):
            return {
                "passed": False,
                "issues": [_issue("CONTENT_QA_INPUT_MISSING", "document", "no readable .docx supplied", _SEVERITY_HIGH)],
                "coverage_gaps": ["CONTENT_QA_NOT_RUN"],
                "unverified_count": 1,
                "checked_labels": 0,
            }
        doc = docx.Document(docx_path)

    findings = extract_labeled_values(doc)
    issues: List[Dict[str, Any]] = []
    issues.extend(check_value_conflicts(findings))
    issues.extend(check_table_subtotals(doc))
    if check_terms:
        issues.extend(check_term_drift(doc))
    issues.extend(check_date_and_unit_style(doc))

    return {
        "passed": not any(item["severity"] == _SEVERITY_HIGH for item in issues),
        "issues": issues,
        "structured_issues": issues,
        "checked_labels": len(findings),
        "labels_found": len(findings),
        "label_values": [
            {
                "label": item["label"],
                "value": str(item["value"]),
                "unit": item["unit"],
                "location": item["location"],
            }
            for item in findings
        ],
        # No numeric labels means there was nothing to cross-check, which is not a
        # verification gap: an empty document cannot contain a numeric contradiction.
        "coverage_gaps": [],
        "unverified_count": 0,
    }
