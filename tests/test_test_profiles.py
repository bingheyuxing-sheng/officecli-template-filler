# -*- coding: utf-8 -*-
"""TEST-01/CI-01: the profile runner must keep fast and external suites disjoint.

CI depends on ``--profile fast`` being runnable without WPS/LibreOffice or the
officecli binary.  These tests pin the selection logic rather than the runtime
of the selected modules.
"""

from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _load_runner():
    path = ROOT / "scripts" / "run_tests.py"
    spec = importlib.util.spec_from_file_location("profile_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProfileSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _load_runner()

    def test_external_modules_exist(self) -> None:
        for name in self.runner.EXTERNAL_MODULES:
            self.assertTrue((TESTS / ("%s.py" % name)).is_file(), name)

    def test_fast_excludes_every_external_module(self) -> None:
        selected = set(self.runner._select("fast"))
        for name in self.runner.EXTERNAL_MODULES:
            self.assertNotIn(name, selected)

    def test_fast_includes_contracts_and_w5(self) -> None:
        selected = self.runner._select("fast")
        self.assertIn("contracts.test_schemas", selected)
        self.assertIn("w5.test_b1_result", selected)

    def test_external_profile_contains_only_external_modules(self) -> None:
        self.assertEqual(
            set(self.runner._select("external")),
            set(self.runner.EXTERNAL_MODULES),
        )

    def test_all_is_the_union(self) -> None:
        self.assertEqual(
            set(self.runner._select("all")),
            set(self.runner._select("fast")) | set(self.runner._select("external")),
        )


if __name__ == "__main__":
    unittest.main()
