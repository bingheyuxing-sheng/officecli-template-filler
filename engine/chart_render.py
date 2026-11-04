# -*- coding: utf-8 -*-
"""Render data-driven pictures (tables, bar charts, pie charts) to PNG.

This closes the "NEEDS_REDRAW → actual redraw" gap: a placeholder figure can be rendered
from the SSOT payload and then inserted through the standard image-replacement channel
(`replace_inline_image_in_paragraph`), so shared-reference and MIME rules still apply.

matplotlib is optional. When it is missing, or when no CJK font is installed and the
labels contain Chinese, the function returns an explicit status instead of writing a
garbled image.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence

_CJK_RE = re.compile(r"[\u4e00-\u9fa5]")

_CJK_FONT_CANDIDATES = (
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
)


def _load_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt, None
    except Exception as exc:  # ImportError or a broken backend
        return None, f"{type(exc).__name__}: {exc}"


def _cjk_font() -> Optional[str]:
    try:
        from matplotlib import font_manager

        available = {font.name for font in font_manager.fontManager.ttflist}
    except Exception:
        return None
    for candidate in _CJK_FONT_CANDIDATES:
        if candidate in available:
            return candidate
    return None


def backend_status() -> Dict[str, Any]:
    """Report whether rendering can run here, and why not when it cannot."""
    plt, error = _load_matplotlib()
    if plt is None:
        return {"available": False, "reason": "RENDER_BACKEND_UNAVAILABLE", "detail": error, "cjk_font": None}
    font = _cjk_font()
    return {"available": True, "reason": None, "detail": None, "cjk_font": font}


def _has_cjk(texts: Sequence[str]) -> bool:
    return any(_CJK_RE.search(str(text or "")) for text in texts)


def _validate(spec: Dict[str, Any]) -> Optional[str]:
    kind = spec.get("kind")
    if kind == "table":
        rows = spec.get("rows")
        if not isinstance(rows, list) or not rows or not all(isinstance(row, (list, tuple)) for row in rows):
            return "table spec requires a non-empty 'rows' list of lists"
        width = max(len(row) for row in rows)
        if width == 0:
            return "table rows are empty"
        if not all(len(row) == width for row in rows):
            return "table rows must all have the same number of cells"
        return None
    if kind == "bar":
        categories = spec.get("categories")
        series = spec.get("series")
        if not isinstance(categories, list) or not categories:
            return "bar spec requires a non-empty 'categories' list"
        if not isinstance(series, dict) or not series:
            return "bar spec requires a 'series' mapping of name -> values"
        for name, values in series.items():
            if not isinstance(values, list) or len(values) != len(categories):
                return f"series '{name}' must have one value per category"
        return None
    if kind == "pie":
        categories = spec.get("categories")
        values = spec.get("values")
        if not isinstance(categories, list) or not categories:
            return "pie spec requires a non-empty 'categories' list"
        if not isinstance(values, list) or len(values) != len(categories):
            return "pie spec requires 'values' with one number per category"
        return None
    return f"unsupported chart kind: {kind!r} (expected 'table' | 'bar' | 'pie')"


def _finish(plt, figure, out_path: str, backend: Dict[str, Any]) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    figure.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    size = figure.get_size_inches()
    plt.close(figure)
    return {
        "status": "RENDERED",
        "path": os.path.abspath(out_path),
        "backend": backend.get("cjk_font") or "default",
        "width_px": int(round(size[0] * 200)),
        "height_px": int(round(size[1] * 200)),
        "warnings": [],
        "needs_redraw": False,
    }


def render_chart_image(spec: Dict[str, Any], out_path: str) -> Dict[str, Any]:
    """
    Render `spec` to a PNG. `spec["kind"]` selects the renderer:

    ```python
    {"kind": "table", "rows": [["课程", "学分"], ["Python", 4]], "title": "课程设置"}
    {"kind": "bar", "categories": ["2024", "2025"], "series": {"招生": [120, 150]}}
    {"kind": "pie", "categories": ["必修", "选修"], "values": [70, 30]}
    ```

    Returns `status` = `RENDERED` / `INVALID_SPEC` / `RENDER_BACKEND_UNAVAILABLE` /
    `CJK_FONT_UNAVAILABLE`. Only `RENDERED` means an image exists.
    """
    problem = _validate(spec or {})
    if problem:
        return {"status": "INVALID_SPEC", "detail": problem, "path": None, "warnings": [], "needs_redraw": True}

    backend = backend_status()
    if not backend["available"]:
        return {
            "status": "RENDER_BACKEND_UNAVAILABLE",
            "detail": backend["detail"],
            "path": None,
            "warnings": ["matplotlib is not installed; install it or mark the figure as SKIPPED_WITH_COVERAGE"],
            "needs_redraw": True,
        }

    texts: List[str] = [str(spec.get("title") or "")]
    kind = spec["kind"]
    if kind == "table":
        texts.extend(str(cell) for row in spec["rows"] for cell in row)
    else:
        texts.extend(str(item) for item in spec["categories"])
        if kind == "bar":
            texts.extend(str(name) for name in spec["series"])

    if _has_cjk(texts) and not backend["cjk_font"]:
        return {
            "status": "CJK_FONT_UNAVAILABLE",
            "detail": "labels contain Chinese but no CJK font is installed for matplotlib",
            "path": None,
            "warnings": ["install a CJK font (e.g. Microsoft YaHei / Noto Sans CJK) or render Latin-only labels"],
            "needs_redraw": True,
        }

    plt, error = _load_matplotlib()
    if plt is None:
        return {
            "status": "RENDER_BACKEND_UNAVAILABLE",
            "detail": error,
            "path": None,
            "warnings": [],
            "needs_redraw": True,
        }

    if backend["cjk_font"]:
        plt.rcParams["font.sans-serif"] = [backend["cjk_font"]]
        plt.rcParams["axes.unicode_minus"] = False

    if kind == "table":
        rows = spec["rows"]
        figure, axis = plt.subplots(figsize=(max(4.0, len(rows[0]) * 1.6), max(1.5, len(rows) * 0.45)))
        axis.axis("off")
        table = axis.table(cellText=[[str(cell) for cell in row] for row in rows], loc="center", cellLoc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(float(spec.get("font_size") or 9))
        table.scale(1, 1.4)
        if spec.get("title"):
            axis.set_title(str(spec["title"]), fontsize=11)
        return _finish(plt, figure, out_path, backend)

    if kind == "bar":
        categories = spec["categories"]
        series = spec["series"]
        figure, axis = plt.subplots(figsize=(max(4.5, len(categories) * 1.1), 3.2))
        width = 0.8 / max(len(series), 1)
        for index, (name, values) in enumerate(series.items()):
            offsets = [position + index * width for position in range(len(categories))]
            axis.bar(offsets, [float(value) for value in values], width=width, label=str(name))
        axis.set_xticks(range(len(categories)))
        axis.set_xticklabels([str(item) for item in categories])
        if spec.get("title"):
            axis.set_title(str(spec["title"]), fontsize=11)
        axis.legend()
        axis.grid(axis="y", linestyle="--", alpha=0.4)
        return _finish(plt, figure, out_path, backend)

    categories = spec["categories"]
    values = [float(value) for value in spec["values"]]
    figure, axis = plt.subplots(figsize=(4.5, 3.6))
    axis.pie(values, labels=[str(item) for item in categories], autopct="%1.1f%%", startangle=90)
    if spec.get("title"):
        axis.set_title(str(spec["title"]), fontsize=11)
    return _finish(plt, figure, out_path, backend)
