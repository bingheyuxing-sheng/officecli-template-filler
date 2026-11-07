# -*- coding: utf-8 -*-
"""Test-profile helpers: separate host-independent tests from external ones.

The full suite exercises two external dependencies that a clean CI runner does
not necessarily have: a WPS/LibreOffice PDF backend (real pagination and page
counts) and the officecli binary.  Modules that need them are listed here so
``scripts/run_tests.py --profile fast`` can skip them deterministically instead
of failing on a machine without the tool.
"""

from __future__ import annotations

import unittest

from engine.officecli_writer import is_available as _officecli_available
from engine.pdf_backend import find_pdf_backend

#: Modules that require a real external dependency.  Keep the reason next to the
#: name: the profile runner prints it when a module is skipped.
EXTERNAL_MODULES = {
    "test_fixture_matrix": "requires a WPS/LibreOffice PDF backend (visual_render capability)",
    "test_officecli_writer": "requires the external officecli binary",
}


def pdf_backend_available() -> bool:
    """True when a real DOCX-to-PDF backend is installed."""
    try:
        return str((find_pdf_backend() or {}).get("name") or "none") != "none"
    except Exception:
        return False


def officecli_available() -> bool:
    try:
        return bool(_officecli_available())
    except Exception:
        return False


requires_pdf_backend = unittest.skipUnless(
    pdf_backend_available(), "requires WPS or LibreOffice PDF backend"
)
requires_officecli = unittest.skipUnless(
    officecli_available(), "requires the officecli binary"
)


__all__ = [
    "EXTERNAL_MODULES",
    "pdf_backend_available",
    "officecli_available",
    "requires_pdf_backend",
    "requires_officecli",
]
