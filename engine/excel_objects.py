# -*- coding: utf-8 -*-
"""
v3.5 M5 — Excel object preflight.

`openpyxl` only round-trips a subset of workbook parts. ActiveX controls, Power Query
tables, pivot caches, slicers, external connections and form controls are silently
dropped on save, which turns a "filled template" into a damaged workbook. Drawing
parts are the same story for plain shapes (text boxes, arrows, grouped shapes):
openpyxl rebuilds a drawing only from its own image/chart objects, so a shape-only
drawing is lost on save. This module lists what the package contains and whether the
engine can promise to keep it.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
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


# Element local names inside a drawing part that openpyxl does not round-trip.
# Images (`xdr:pic`) and charts (`xdr:graphicFrame`) are rebuilt from openpyxl's
# own objects; shapes, groups and connectors are dropped on save.
_UNPRESERVED_DRAWING_ELEMENTS = frozenset({"sp", "grpSp", "cxnSp"})


def _drawing_has_unpreserved_shapes(archive: zipfile.ZipFile) -> bool:
    """True when any `xl/drawings/*.xml` part carries a shape openpyxl will lose."""
    for name in archive.namelist():
        if not name.startswith("xl/drawings/") or not name.endswith(".xml"):
            continue
        try:
            root = ET.fromstring(archive.read(name))
        except Exception:
            continue
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue  # comment / processing-instruction nodes
            if element.tag.rpartition("}")[2] in _UNPRESERVED_DRAWING_ELEMENTS:
                return True
    return False


def inspect_excel_objects(file_path: str) -> Dict[str, Any]:
    """List every part that carries structure openpyxl may not preserve."""
    with zipfile.ZipFile(file_path) as archive:
        part_names = archive.namelist()
        shapes_present = _drawing_has_unpreserved_shapes(archive)

    objects: List[Dict[str, Any]] = []
    for part_name in part_names:
        object_type, preserved = _classify(part_name)
        if object_type:
            if object_type == "drawing" and shapes_present:
                preserved = False
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
