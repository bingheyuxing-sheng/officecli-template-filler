#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the suite in explicit profiles.

The full suite mixes two kinds of tests: host-independent checks (python-docx,
OOXML, contracts) and checks that need a real external tool (WPS/LibreOffice for
pagination, the officecli binary for the optional writer).  Keeping them in one
undifferentiated run makes CI either impossible or permanently red on machines
without those tools.

Profiles:

    fast      host-independent tests + contract tests + W5 backend tests
    external  only the modules listed in tests/external.py
    all       everything (default, same set as unittest discover)

Usage:

    python scripts/run_tests.py --profile fast
    python scripts/run_tests.py --profile external
    python scripts/run_tests.py --profile all -v
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import unittest

# Tests spawn CLI scripts with subprocess.run(); on a Windows runner the default
# console encoding is cp1252, which cannot encode the Chinese output and turns a
# valid command into UnicodeEncodeError.  Child processes inherit this value.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
for _path in (str(ROOT), str(TESTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from external import EXTERNAL_MODULES  # noqa: E402


def _module_names() -> list:
    return sorted(path.stem for path in TESTS.glob("test_*.py"))


def _package_names(package: str) -> list:
    return sorted(
        "%s.%s" % (package, path.stem)
        for path in (TESTS / package).glob("test_*.py")
    )


def _select(profile: str) -> list:
    internal = [name for name in _module_names() if name not in EXTERNAL_MODULES]
    external = [name for name in _module_names() if name in EXTERNAL_MODULES]
    contracts = _package_names("contracts")
    w5 = _package_names("w5")
    if profile == "fast":
        return internal + contracts + w5
    if profile == "external":
        return external
    return internal + external + contracts + w5


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the officecli-template-filler test suite by profile.")
    parser.add_argument("--profile", choices=("fast", "external", "all"), default="all")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.profile == "fast":
        for name, reason in sorted(EXTERNAL_MODULES.items()):
            print("skip %s: %s" % (name, reason))
    elif args.profile == "external":
        for name, reason in sorted(EXTERNAL_MODULES.items()):
            print("include %s: %s" % (name, reason))

    names = _select(args.profile)
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for name in names:
        try:
            suite.addTests(loader.loadTestsFromName(name))
        except Exception as exc:  # a broken module must fail the run, not vanish
            print("ERROR loading %s: %s: %s" % (name, type(exc).__name__, exc), file=sys.stderr)
            return 2

    print("profile=%s modules=%d" % (args.profile, len(names)))
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
