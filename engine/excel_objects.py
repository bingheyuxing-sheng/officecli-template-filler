# -*- coding: utf-8 -*-
"""
v3.5 M5 — Excel object preflight.

`openpyxl` only round-trips a subset of workbook parts. ActiveX controls, Power Query
tables, pivot caches, slicers, external connections and form controls are silently
dropped on save, which turns a "filled template" into a damaged workbook. This module
lists what the package contains and whether the engine can promise to keep it.
"""

from __future__ import annotations

import os
import zipfile
from typing import Any, Dict, List

# (part prefix, object type, preserved by openpyxl when loading/saving)
_OBJECT_PARTS = (
    ("xl/vbaProject.bin", "vba_project", True),
    ("xl/activeX/", "activex", False),
    ("xl/queryTables/", "query_table", False),
    ("xl/pivotTables/", "pivot_table", False),
    ("xl/pivotCache/", "pivot_cache", False),
    ("xl/slicers/", "slicer", False),
    ("xl/connections.xml", "connections", False),
    ("xl/controlProps/", "form_control", False),
    ("xl/embeddings/", "ole_object", False),
    ("xl/charts/", "chart", False),
    ("xl/drawings/", "drawing", True),
    ("xl/media/", "image", True),
)


def _classify(part_name: str):
    for prefix, object_type, preserved in _OBJECT_PARTS:
        if part_name == prefix or part_name.startswith(prefix):
            return object_type, preserved
    return None, None


def inspect_excel_objects(file_path: str) -> Dict[str, Any]:
    """List every part that carries structure openpyxl may not preserve."""
    with zipfile.ZipFile(file_path) as archive:
        part_names = archive.namelist()

    objects: List[Dict[str, Any]] = []
    for part_name in part_names:
        object_type, preserved = _classify(part_name)
        if object_type:
            objects.append({
                "type": object_type,
                "part": part_name,
                "preserved_by_openpyxl": preserved,
            })

    loss_risk = [item for item in objects if not item["preserved_by_openpyxl"]]
    return {
        "file_path": os.path.abspath(file_path),
        "file_type": "xlsm" if file_path.lower().endswith(".xlsm") else "xlsx",
        "macro_enabled": any(item["type"] == "vba_project" for item in objects),
        "object_count": len(objects),
        "objects": objects,
        "loss_risk_objects": loss_risk,
        "object_loss_risk": bool(loss_risk),
    }
