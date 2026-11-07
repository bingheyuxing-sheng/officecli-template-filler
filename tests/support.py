# -*- coding: utf-8 -*-
"""Shared test-only helpers: file digests and a passing QAReport stub.

Discovery runs with ``-s tests`` so ``tests/`` is the top-level directory and
this module imports as ``support`` from every test file, exactly like
``gate_helpers``. The file is intentionally not named ``test_*``: it holds no
cases and must never be collected.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict


def sha256_file(path) -> str:
    """Streaming SHA-256 of a file; accepts ``str`` or ``pathlib.Path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def passing_qa(_staged) -> Dict[str, Any]:
    """QA stub for tests that exercise the gate, not the QA body itself."""
    return {"status": "PASSED", "passed": True, "issues": [], "coverage_gaps": []}
