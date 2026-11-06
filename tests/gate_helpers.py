# -*- coding: utf-8 -*-
"""Test-only helper: create a real confirmed Gate Record for synthetic fixtures.

This is not a production bypass: records are produced through the same analyzer,
report and store APIs used by the CLI, and the execution entry still validates
them.  Tests use a temporary gate home so no user-level state is written.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict

_GATE_HOME = os.path.join(tempfile.mkdtemp(prefix="officecli-w4-gates-"), "gates")
os.environ.setdefault("OFFICECLI_GATE_HOME", _GATE_HOME)

from template_gate import GateStore, build_analysis  # noqa: E402
from template_gate.models import canonical_json  # noqa: E402
from template_gate.report import build_report  # noqa: E402
from template_gate.supplements import resolve_evidence  # noqa: E402


def gate_home() -> str:
    return _GATE_HOME


def ensure_gate(template_path: str, task_type: str = "GENERATE") -> Dict[str, Any]:
    """Return an existing confirmed record or create one for the fixture."""
    store = GateStore(_GATE_HOME)
    analysis = build_analysis(template_path, task_type)
    existing = store.find(str(analysis.get("template_sha256")), task_type)
    if existing is not None and store.verify(existing) and not store.is_expired(existing):
        return existing

    for _ in range(10):
        blocking = [item for item in analysis.get("evidence") or [] if item.get("blocking")]
        if not blocking:
            break
        for item in blocking:
            value = item.get("value")
            if isinstance(value, dict):
                value = canonical_json(value)
            elif isinstance(value, list):
                value = value[0] if value else "TEST_FIXTURE"
            elif value is None:
                value = "TEST_FIXTURE"
            analysis = resolve_evidence(
                analysis,
                str(item["evidence_id"]),
                resolution_type="PROVIDE_VALUE",
                value=value,
                user_statement="test fixture resolution",
            )
    report = build_report(analysis)
    if report.get("blocking_items"):
        raise AssertionError("synthetic fixture still has blocking items: %s" % report["blocking_items"])
    record = store.confirm(
        analysis,
        report,
        user_statement="test fixture: explicit confirmation",
        ttl_seconds=86400,
    )
    return record
