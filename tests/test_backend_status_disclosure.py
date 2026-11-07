# -*- coding: utf-8 -*-
"""ARCH-01: the un-wired backend layer must say so, in code and in docs.

``document_backends`` carries a tested interface but is not imported by the
execution chain.  Leaving that ambiguous made readers assume the W5 adapter was
already authoritative.  The package now exposes a machine-readable status and
the README/CHANGELOG repeat it.
"""

from __future__ import annotations

import pathlib
import unittest

import document_backends

ROOT = pathlib.Path(__file__).resolve().parents[1]


class BackendStatusDisclosureTests(unittest.TestCase):
    def test_package_marks_itself_experimental(self) -> None:
        self.assertEqual(document_backends.PACKAGE_STATUS, "EXPERIMENTAL_NOT_WIRED")
        self.assertIn("EXPERIMENTAL", document_backends.__doc__ or "")
        self.assertIn("PACKAGE_STATUS", document_backends.__all__)

    def test_readme_discloses_not_wired(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("document_backends", text)
        self.assertIn("尚未接入执行链", text)
        self.assertIn("EXPERIMENTAL_NOT_WIRED", text)

    def test_changelog_discloses_not_wired(self) -> None:
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("document_backends", text)
        self.assertIn("EXPERIMENTAL_NOT_WIRED", text)


if __name__ == "__main__":
    unittest.main()
