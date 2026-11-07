# -*- coding: utf-8 -*-
"""COMPAT-01: the documented Python floor must match the configured target.

The production code uses 3.10-only syntax (``zip(..., strict=)``).  Declaring
3.9 support makes those calls fail at runtime with ``TypeError``, so the floor
is pinned here and kept in sync with ``ruff.toml``.
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
RUFF = ROOT / "ruff.toml"


class PythonFloorTests(unittest.TestCase):
    def _readme_text(self) -> str:
        return README.read_text(encoding="utf-8")

    def test_readme_requires_python_310_or_newer(self) -> None:
        match = re.search(r"Python (\d+)\.(\d+) 或更高版本", self._readme_text())
        self.assertIsNotNone(match, "README must state the minimum Python version")
        floor = (int(match.group(1)), int(match.group(2)))
        self.assertGreaterEqual(floor, (3, 10), "zip(strict=) requires Python 3.10")

    def test_badge_matches_declared_floor(self) -> None:
        text = self._readme_text()
        self.assertIn("Python-3.10%2B", text)
        self.assertNotIn("Python-3.9%2B", text)

    def test_ruff_target_matches_declared_floor(self) -> None:
        text = RUFF.read_text(encoding="utf-8")
        match = re.search(r'target-version\s*=\s*"py(\d)(\d+)"', text)
        self.assertIsNotNone(match, "ruff.toml must declare target-version")
        self.assertEqual((int(match.group(1)), int(match.group(2))), (3, 10))


if __name__ == "__main__":
    unittest.main()
