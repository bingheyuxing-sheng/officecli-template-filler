# -*- coding: utf-8 -*-
"""Contract 01 — Slot ID implementation.

Deterministic slot identity for fillable template positions:

    canonical_slot_id := "v1|" + template_sha256 + "|" + location_id + "|" + normalized_text + "|" + occurrence
    slot_id           := "S_" + sha256_utf8(canonical_slot_id)[0:12]
    canonical_slot_key := "v1|" + location_id + "|" + normalized_text + "|" + occurrence
    slot_key          := sha256_utf8(canonical_slot_key)[0:16]

Only `hashlib.sha256` is used. Python's `hash()`, `uuid`, clocks and `random` are never touched,
so the same template analysis yields the same ids on any machine.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Dict, Iterable, List, Sequence

SLOT_ID_RE = re.compile(r"^S_[0-9a-f]{12}(-c[2-9][0-9]*)?$")
SLOT_KEY_RE = re.compile(r"^[0-9a-f]{16}$")
LOCATION_RE = re.compile(
    r"^(body|footnotes|endnotes|comments|sec\[[0-9]+\]\."
    r"(header|footer|first_page_header|first_page_footer|even_page_header|even_page_footer))"
    r"(\.[a-z_]+\[[0-9]+\])+$"
)
_TEMPLATE_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize matched text exactly as Contract 01 §4 requires.

    NFKC -> CRLF/CR to LF -> collapse whitespace to one space U+0020 -> strip.
    Case folding and punctuation rewriting are deliberately NOT applied.
    """
    value = unicodedata.normalize("NFKC", "" if text is None else str(text))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _WS_RE.sub(" ", value)
    return value.strip()


def _validate(
    template_sha256: str,
    location_id: str,
    matched_text: str,
    occurrence: int,
    *,
    allow_empty: bool = False,
) -> str:
    if not _TEMPLATE_SHA_RE.match(template_sha256 or ""):
        raise ValueError("SLOT_TEMPLATE_SHA_INVALID")
    if not LOCATION_RE.match(location_id or ""):
        raise ValueError("SLOT_LOCATION_INVALID")
    if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 1:
        raise ValueError("SLOT_OCCURRENCE_INVALID")
    normalized = normalize_text(matched_text)
    if not normalized:
        if allow_empty:
            # Empty-table anchors have no literal text. The U+2205 empty-set
            # character gives them a stable, visible canonical identity while
            # the public slot.matched_text remains "".
            return "\u2205"
        raise ValueError("SLOT_TEXT_EMPTY_UNEVIDENCED")
    return normalized


def make_slot_id(
    template_sha256: str,
    location_id: str,
    matched_text: str,
    occurrence: int,
    *,
    allow_empty: bool = False,
) -> str:
    """Return the stable `S_` slot id for one template position."""
    normalized = _validate(
        template_sha256,
        location_id,
        matched_text,
        occurrence,
        allow_empty=allow_empty,
    )
    canonical = (
        f"v1|{template_sha256}|{location_id}|{normalized}|{int(occurrence)}"
    )
    return "S_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def make_slot_key(
    location_id: str,
    matched_text: str,
    occurrence: int,
    *,
    allow_empty: bool = False,
) -> str:
    """Return the version-independent 16 hex slot key (template upgrade lineage only)."""
    if not LOCATION_RE.match(location_id or ""):
        raise ValueError("SLOT_LOCATION_INVALID")
    if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 1:
        raise ValueError("SLOT_OCCURRENCE_INVALID")
    normalized = normalize_text(matched_text)
    if not normalized:
        if allow_empty:
            normalized = "\u2205"
        else:
            raise ValueError("SLOT_TEXT_EMPTY_UNEVIDENCED")
    canonical = f"v1|{location_id}|{normalized}|{int(occurrence)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def resolve_slot_id_collisions(items: Iterable[Sequence[str]]) -> List[str]:
    """Deterministically suffix colliding 12-hex ids.

    `items` is an iterable of `(canonical_string, base_id)` pairs. Only ids that actually
    collide are suffixed: within each colliding base-id group the canonical strings are
    sorted lexicographically, the first keeps the bare id and the rest get `-c2`, `-c3`, ...
    The result is returned in canonical-string order, so dict iteration order never matters.
    """
    ordered = sorted((tuple(item) for item in items), key=lambda item: item[0])
    totals: Dict[str, int] = {}
    for _canonical, base_id in ordered:
        totals[base_id] = totals.get(base_id, 0) + 1

    seen: Dict[str, int] = {}
    result: List[str] = []
    for _canonical, base_id in ordered:
        if totals[base_id] <= 1:
            result.append(base_id)
            continue
        seen[base_id] = seen.get(base_id, 0) + 1
        rank = seen[base_id]
        result.append(base_id if rank == 1 else f"{base_id}-c{rank}")
    return result
