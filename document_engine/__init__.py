# -*- coding: utf-8 -*-
"""Public API of the v4.0 document engine (W1-D).

``execute_fill_plan`` is the deterministic FillPlan executor; ``generate_document_v4``
is the thin entry point used by the ``--plan`` CLI path; ``FillLedger`` is the
per-operation audit trail it writes.
"""

from __future__ import annotations

from .fill_executor import execute_fill_plan
from .fill_ledger import FillLedger
from .pipeline import generate_document_v4

__all__ = [
    "FillLedger",
    "execute_fill_plan",
    "generate_document_v4",
]
