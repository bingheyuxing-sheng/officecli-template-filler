# -*- coding: utf-8 -*-
"""W5-B1 unit tests: error-code registry governance closure.

The B0-committed officecli writer path already emitted code strings that
were not registered (contract 05 §9: "error code absent from registry" is
invalid). B1 closes that gap; these tests pin it so the codes can never
silently drop out of the registry again.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from document_backends.result import OFFICECLI_ENVELOPE_ALIASES, ReasonCode  # noqa: E402

REGISTRY_PATH = ROOT / "config" / "error-codes.json"
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")

#: Codes already emitted by the B0-committed executor but unregistered at
#: the time. B1 registers them (introduced_in "4.2.0").
PREVIOUSLY_UNREGISTERED = (
    "EXECUTION_FAILED",
    "OFFICECLI_WRITE_FAILED",
    "OFFICECLI_READBACK_FAILED",
    "OFFICECLI_NORMALIZE_FAILED",
)

ADDITION_VERSION = "4.2.0"

REQUIRED_FIELDS = (
    "code", "severity", "retryable", "rollback_required",
    "human_intervention", "owner", "message_template", "introduced_in",
)


def _entries() -> list:
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return json.load(handle)["codes"]


class RegistryClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = _entries()
        self.by_code = {entry["code"]: entry for entry in self.entries}
        self.added = [entry for entry in self.entries
                      if entry["introduced_in"] == ADDITION_VERSION]

    def test_codes_are_unique(self) -> None:
        codes = [entry["code"] for entry in self.entries]
        self.assertEqual(len(codes), len(set(codes)))

    def test_previously_unregistered_codes_are_now_registered(self) -> None:
        for code in PREVIOUSLY_UNREGISTERED:
            self.assertIn(code, self.by_code,
                          "%s is emitted by the executor and must be registered" % code)

    def test_b1_additions_are_all_present(self) -> None:
        added_codes = {entry["code"] for entry in self.added}
        expected = (set(PREVIOUSLY_UNREGISTERED)
                    | {reason.value for reason in ReasonCode}
                    | set(OFFICECLI_ENVELOPE_ALIASES))
        self.assertEqual(added_codes, expected,
                         "the B1 addition set must be exactly the gap codes plus the "
                         "reason vocabulary plus the generic envelope codes")

    def test_b1_additions_declare_full_semantics(self) -> None:
        self.assertTrue(self.added)
        for entry in self.added:
            with self.subTest(code=entry["code"]):
                self.assertTrue(set(REQUIRED_FIELDS) <= set(entry))
                self.assertTrue(CODE_PATTERN.match(entry["code"]))
                self.assertIn(entry["severity"], ("low", "medium", "high", "blocking"))
                self.assertIn(entry["owner"],
                              ("AGENT01", "AGENT02", "AGENT03", "AGENT04",
                               "AGENT05", "AGENT06", "AGENT07", "CORE"))
                self.assertTrue(entry["message_template"])

    def test_blocking_additions_are_not_retryable(self) -> None:
        for entry in self.added:
            if entry["severity"] == "blocking":
                self.assertFalse(entry["retryable"], entry["code"])

    def test_failure_reason_additions_require_rollback(self) -> None:
        rollback_codes = {
            "EXECUTION_FAILED", "OFFICECLI_WRITE_FAILED", "OFFICECLI_READBACK_FAILED",
            "OFFICECLI_NORMALIZE_FAILED", "BATCH_ROLLED_BACK", "READBACK_MISMATCH",
            "NORMALIZE_FAILED", "STAGE_CHECK_FAILED", "BACKEND_VALIDATE_FAILED",
            "BACKEND_SINGLE_WRITER_VIOLATION", "BACKEND_BATCH_FAILED",
            "BACKEND_READBACK_FAILED", "BACKEND_NORMALIZE_FAILED",
        }
        for entry in self.added:
            if entry["code"] in rollback_codes:
                self.assertTrue(entry["rollback_required"], entry["code"])

    def test_fallback_reason_additions_do_not_require_rollback(self) -> None:
        fallback_codes = {
            "OFFICECLI_BINARY_MISSING", "OFFICECLI_VERSION_UNSUPPORTED",
            "CAPABILITY_NOT_ROUTABLE", "OPERATION_TYPE_UNSUPPORTED",
            "LOCATION_UNSUPPORTED", "TOKEN_SPANS_RUNS", "TOKEN_NOT_UNIQUE",
            "CELL_MULTIPLE_PARAGRAPHS", "BACKEND_VALIDATE_UNAVAILABLE",
        }
        for entry in self.added:
            if entry["code"] in fallback_codes:
                self.assertFalse(entry["rollback_required"], entry["code"])


if __name__ == "__main__":
    unittest.main()
