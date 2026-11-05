# -*- coding: utf-8 -*-
"""Template Intelligence — DocumentSpec 4.0 producer (W1-A).

Public API only; the contract surface is deliberately small.
"""

from .fingerprint import compute_four_hashes
from .slot_id import (
    LOCATION_RE,
    SLOT_ID_RE,
    SLOT_KEY_RE,
    make_slot_id,
    make_slot_key,
    normalize_text,
    resolve_slot_id_collisions,
)
from .spec_builder import build_document_spec, build_document_spec_from_path

__all__ = [
    "LOCATION_RE",
    "SLOT_ID_RE",
    "SLOT_KEY_RE",
    "normalize_text",
    "make_slot_id",
    "make_slot_key",
    "resolve_slot_id_collisions",
    "compute_four_hashes",
    "build_document_spec",
    "build_document_spec_from_path",
]
