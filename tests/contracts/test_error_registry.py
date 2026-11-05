# -*- coding: utf-8 -*-
"""Contract 05 registry data: uniqueness, required semantics and backward-compatible codes."""

from __future__ import annotations

import unittest

from .helpers import CONFIG_DIR, example_document, load_json, schema_errors


class ErrorRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = load_json(CONFIG_DIR / "error-codes.json")
        self.codes = [entry["code"] for entry in self.data["codes"]]

    def test_registry_matches_schema(self) -> None:
        self.assertEqual(schema_errors("error_registry", self.data), [])

    def test_codes_are_unique(self) -> None:
        self.assertEqual(len(self.codes), len(set(self.codes)))

    def test_existing_codes_are_grandfathered(self) -> None:
        for code in ("OUTPUT_FILE_LOCKED", "SSOT_VALIDATION_FAILED", "TEMPLATE_TEXT_RESIDUAL", "PACKAGE_DANGLING_REL"):
            self.assertIn(code, self.codes, f"{code} must stay registered under its v3.5.9 spelling")

    def test_every_entry_declares_semantics(self) -> None:
        required = {"severity", "retryable", "rollback_required", "human_intervention", "owner"}
        for entry in self.data["codes"]:
            with self.subTest(code=entry["code"]):
                self.assertTrue(required <= set(entry))
                self.assertIn(entry["severity"], ("low", "medium", "high", "blocking"))
                for key in ("retryable", "rollback_required", "human_intervention"):
                    self.assertIsInstance(entry[key], bool)

    def test_examples_only_use_registered_codes(self) -> None:
        envelope = example_document("tool-envelope", "full_valid")
        referenced = {item["code"] for item in envelope["warnings"] + envelope["errors"]}
        self.assertEqual(referenced - set(self.codes), set())

    def test_blocking_codes_are_not_silently_retryable(self) -> None:
        for entry in self.data["codes"]:
            if entry["severity"] == "blocking":
                with self.subTest(code=entry["code"]):
                    self.assertFalse(entry["retryable"], "blocking errors must not be auto-retried")


if __name__ == "__main__":
    unittest.main()
