# -*- coding: utf-8 -*-
"""Console I/O helpers for CLI entrypoints."""

from __future__ import annotations

import sys


def configure_stdio() -> None:
    """Use UTF-8 for CLI output even when Windows defaults to a legacy code page."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass
