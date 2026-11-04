# -*- coding: utf-8 -*-
"""Research planning and provenance validation.

The engine does not browse the web. This module makes the research step auditable:

- `research_policy()` states whether external lookup is allowed for a task mode;
- `build_research_plan()` turns public, searchable template slots into deterministic
  queries (internal facts and protected controls are excluded);
- `validate_research_facts()` requires every collected fact to declare a source and
  reports which facts remain `UNVERIFIED` / `MODEL_GENERATED`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .consistency_qa import audit_fact_sources

RESEARCH_POLICY_ON_DEMAND = "ON_DEMAND_PUBLIC_STANDARDS_ONLY"
RESEARCH_POLICY_DISABLED = "DISABLED_BY_DEFAULT"
RESEARCH_ENABLED_MODES = ("GENERATE", "EXCEL_GENERATE")
PROTECTED_TIERS = ("MUST_ASK_USER", "PROTECTED_DO_NOT_TOUCH")


def research_policy(task_mode: str) -> Dict[str, Any]:
    """Mirror the router's web-search policy as a standalone decision object."""
    mode = str(task_mode or "").strip().upper()
    enabled = mode in RESEARCH_ENABLED_MODES
    return {
        "task_mode": mode,
        "enabled": enabled,
        "policy": RESEARCH_POLICY_ON_DEMAND if enabled else RESEARCH_POLICY_DISABLED,
        "reason": (
            "public standards may be looked up on demand"
            if enabled
            else "audit targets stay offline unless the user explicitly asks to verify facts"
        ),
    }


def build_research_plan(
    topic: str,
    slots: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    task_mode: str = "GENERATE",
    max_queries: int = 20,
) -> Dict[str, Any]:
    """Build deterministic lookup queries for public, searchable slots."""
    policy = research_policy(task_mode)
    queries: List[Dict[str, Any]] = []
    if policy["enabled"]:
        seen = set()
        for slot in slots or []:
            tier = str(slot.get("confirmation_tier") or "")
            if tier in PROTECTED_TIERS:
                continue
            label = str(slot.get("matched_text") or "").strip()
            if not label:
                continue
            query = " ".join(part for part in (str(topic or "").strip(), label, "官方 标准") if part)
            key = query.lower()
            if key in seen:
                continue
            seen.add(key)
            queries.append({
                "slot_id": slot.get("location_id"),
                "label": label,
                "query": query,
                "priority": "high" if tier == "AUTO_DERIVE_OR_BIND" else "normal",
            })
            if len(queries) >= max(1, int(max_queries)):
                break
    return {
        "task_mode": policy["task_mode"],
        "enabled": policy["enabled"],
        "policy": policy["policy"],
        "topic": str(topic or "").strip(),
        "queries": queries,
    }


def validate_research_facts(facts: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """Require a source on every fact and list the ones still unverified."""
    report = audit_fact_sources(facts)
    items = list(facts or [])
    unverified = []
    for index, fact in enumerate(items):
        if not isinstance(fact, dict):
            continue
        source = str(fact.get("source") or "").strip().upper()
        if source in ("UNVERIFIED", "MODEL_GENERATED"):
            unverified.append({
                "index": index,
                "label": fact.get("label") or fact.get("key") or fact.get("name") or f"facts[{index}]",
                "source": source,
            })
    return {
        "passed": bool(report.get("passed")),
        "issues": list(report.get("issues") or []),
        "checked_count": int(report.get("checked_count") or len(items)),
        "unverified_count": len(unverified),
        "unverified_facts": unverified,
    }
