# -*- coding: utf-8 -*-
"""VER-01/VER-02: contract and software versions must agree across the repo.

The contract index, the individual contract headers and AGENTS.md had drifted
(4.3.0 / 4.2.0 / "frozen 4.2.0"), and ``engine.__version__`` could advance
without a matching CHANGELOG section.  These checks make both invariants
mechanical.
"""

from __future__ import annotations

import pathlib
import re
import unittest

import engine

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
INDEX = CONTRACTS / "README.md"
AGENTS = ROOT / "AGENTS.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def _tuple(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


class ContractVersionConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index_text = INDEX.read_text(encoding="utf-8")
        match = re.search(r"Contract set version:\s*\*\*(\d+\.\d+\.\d+)\*\*", cls.index_text)
        if match is None:
            raise AssertionError("contracts/README.md must declare 'Contract set version'")
        cls.set_version = match.group(1)

    def test_agents_md_names_the_same_set_version(self) -> None:
        text = AGENTS.read_text(encoding="utf-8")
        self.assertIn("`%s`" % self.set_version, text)

    def test_index_marks_contract_06_as_draft(self) -> None:
        self.assertIn("Contract 06", self.index_text)
        self.assertIn("DRAFT", self.index_text)

    def test_no_frozen_contract_exceeds_the_set_version(self) -> None:
        for path in sorted(CONTRACTS.glob("0*.md")):
            text = path.read_text(encoding="utf-8")
            status = re.search(r"Status:\s*\*\*(.+?)\*\*", text)
            self.assertIsNotNone(status, "%s has no Status line" % path.name)
            status_text = status.group(1)
            if "FROZEN" not in status_text:
                continue
            frozen = re.search(r"FROZEN \((\d+\.\d+\.\d+)", status_text)
            if frozen is None:
                # Legacy headers use "FROZEN (W0, ...)" without a set version;
                # there is no version claim to compare.
                continue
            self.assertLessEqual(
                _tuple(frozen.group(1)),
                _tuple(self.set_version),
                "%s is frozen at %s but the set is %s" % (path.name, frozen.group(1), self.set_version),
            )


class SoftwareVersionConsistencyTests(unittest.TestCase):
    def test_engine_version_has_a_changelog_section(self) -> None:
        version = engine.__version__
        text = CHANGELOG.read_text(encoding="utf-8")
        pattern = r"(?m)^## v?%s\b" % re.escape(version)
        self.assertRegex(text, pattern, "engine.__version__ %s has no CHANGELOG section" % version)


if __name__ == "__main__":
    unittest.main()
