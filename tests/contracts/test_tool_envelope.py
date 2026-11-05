# -*- coding: utf-8 -*-
"""Contract 05 conformance: envelope/status/next_action consistency and registered codes."""

from __future__ import annotations

import unittest

from .helpers import (
    example_document,
    schema_errors,
    semantic_envelope,
)


class ToolEnvelopeTests(unittest.TestCase):
    def test_valid_cases(self) -> None:
        for case in ("minimal_valid", "full_valid"):
            with self.subTest(case=case):
                envelope = example_document("tool-envelope", case)
                self.assertEqual(schema_errors("tool_envelope", envelope), [])
                self.assertEqual(semantic_envelope(envelope), [])

    def test_missing_and_type_errors(self) -> None:
        self.assertTrue(schema_errors("tool_envelope", example_document("tool-envelope", "missing_required")))
        self.assertTrue(schema_errors("tool_envelope", example_document("tool-envelope", "type_error")))

    def test_commit_after_failure_is_rejected(self) -> None:
        envelope = example_document("tool-envelope", "boundary_conflict")
        self.assertEqual(schema_errors("tool_envelope", envelope), [])
        errors = semantic_envelope(envelope)
        self.assertTrue(any("COMMIT without SUCCESS" in item for item in errors), errors)

    def test_unregistered_code_is_rejected(self) -> None:
        envelope = example_document("tool-envelope", "minimal_valid")
        envelope["errors"] = [
            {
                "code": "NOT_REGISTERED",
                "message": "unknown",
                "severity": "high",
                "retryable": False,
                "rollback_required": False,
                "human_intervention": False,
            }
        ]
        errors = semantic_envelope(envelope)
        self.assertTrue(any("unregistered error code" in item for item in errors), errors)

    def test_staged_path_cannot_be_an_artifact(self) -> None:
        envelope = example_document("tool-envelope", "minimal_valid")
        envelope["artifacts"][0]["path"] = ".out.tmp-abc.docx"
        errors = semantic_envelope(envelope)
        self.assertTrue(any("staged path exposed" in item for item in errors), errors)

    def test_unverified_commit_requires_qa_eligible(self) -> None:
        envelope = example_document("tool-envelope", "minimal_valid")
        envelope["status"] = "UNVERIFIED"
        envelope["next_action"] = "COMMIT"
        errors = semantic_envelope(envelope)
        self.assertTrue(any("qa_eligible" in item for item in errors), errors)

        envelope["data"] = {"qa_eligible": True, "missing_checks": ["VISUAL_PAGE_COUNT"]}
        self.assertEqual(semantic_envelope(envelope), [])

    def test_retry_requires_retryable_error(self) -> None:
        envelope = example_document("tool-envelope", "full_valid")
        for item in envelope["errors"]:
            item["retryable"] = False
        errors = semantic_envelope(envelope)
        self.assertTrue(any("RETRY without a retryable error" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
