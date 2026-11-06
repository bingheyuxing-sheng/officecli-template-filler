# -*- coding: utf-8 -*-
"""W5-B1 unit tests: reason-code vocabulary and BackendResult invariants.

The catalog is the single source of truth for backend reason codes, so the
tests pin it to the live registry in ``config/error-codes.json``: every
reason code must be registered (contract 05 §9), every failure reason
must map onto a registered envelope code, and no fallback reason may pose
as an envelope error.
"""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from document_backends.result import (  # noqa: E402
    DETAIL_MAX_CHARS,
    OP_STATUSES,
    BackendError,
    BackendResult,
    ErrorCategory,
    OpOutcome,
    ReasonCode,
    REASON_CODE_CATALOG,
    envelope_code_for,
    reason_category,
)

REGISTRY_PATH = ROOT / "config" / "error-codes.json"


def _registered_codes() -> set:
    with open(REGISTRY_PATH, encoding="utf-8") as handle:
        return {entry["code"] for entry in json.load(handle)["codes"]}


class ReasonCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = _registered_codes()

    def test_catalog_covers_every_reason_code(self) -> None:
        self.assertEqual(set(REASON_CODE_CATALOG), set(ReasonCode),
                         "every ReasonCode member needs a catalog entry")

    def test_catalog_has_no_orphan_entries(self) -> None:
        for reason in REASON_CODE_CATALOG:
            self.assertIsInstance(reason, ReasonCode)

    def test_backend_reason_categories_are_used(self) -> None:
        """Backend reasons cover DOCUMENT/BACKEND/INFRASTRUCTURE.

        BUSINESS stays empty on purpose: business refusals (authorization,
        capacity, protection) belong to the executor's existing codes and
        the backend layer never redefines them.
        """
        used = {spec.category for spec in REASON_CODE_CATALOG.values()}
        self.assertTrue({ErrorCategory.DOCUMENT, ErrorCategory.BACKEND,
                         ErrorCategory.INFRASTRUCTURE} <= used)
        self.assertNotIn(ErrorCategory.BUSINESS, used)

    def test_every_reason_code_is_registered(self) -> None:
        missing = {reason.value for reason in ReasonCode} - self.registry
        self.assertEqual(missing, set(),
                         "reason codes absent from the registry are contract violations")

    def test_failure_reasons_map_to_registered_envelope_codes(self) -> None:
        for reason, spec in REASON_CODE_CATALOG.items():
            if spec.is_failure:
                self.assertIsNotNone(spec.envelope_code, reason)
                self.assertIn(spec.envelope_code, self.registry,
                              "%s maps to unregistered envelope code" % reason)
                self.assertEqual(envelope_code_for(reason), spec.envelope_code)

    def test_fallback_reasons_are_never_envelope_errors(self) -> None:
        for reason, spec in REASON_CODE_CATALOG.items():
            if not spec.is_failure:
                self.assertIsNone(spec.envelope_code,
                                  "%s is a disclosed fallback, not an envelope error" % reason)

    def test_category_lookup_matches_catalog(self) -> None:
        for reason, spec in REASON_CODE_CATALOG.items():
            self.assertEqual(reason_category(reason), spec.category)
            self.assertTrue(spec.description)

    def test_offline_fallback_reasons_cannot_be_failures(self) -> None:
        for reason in (ReasonCode.OFFICECLI_BINARY_MISSING,
                       ReasonCode.OFFICECLI_VERSION_UNSUPPORTED,
                       ReasonCode.CAPABILITY_NOT_ROUTABLE):
            spec = REASON_CODE_CATALOG[reason]
            self.assertFalse(spec.is_failure)
            self.assertIsNone(spec.envelope_code)

    def test_document_structure_reasons_are_document_category(self) -> None:
        for reason in (ReasonCode.TOKEN_SPANS_RUNS, ReasonCode.TOKEN_NOT_UNIQUE,
                       ReasonCode.LOCATION_UNSUPPORTED, ReasonCode.CELL_MULTIPLE_PARAGRAPHS,
                       ReasonCode.OPERATION_TYPE_UNSUPPORTED):
            self.assertEqual(reason_category(reason), ErrorCategory.DOCUMENT)

    def test_write_path_reasons_are_backend_failures(self) -> None:
        for reason in (ReasonCode.BATCH_ROLLED_BACK, ReasonCode.READBACK_MISMATCH,
                       ReasonCode.NORMALIZE_FAILED, ReasonCode.STAGE_CHECK_FAILED,
                       ReasonCode.BACKEND_VALIDATE_FAILED,
                       ReasonCode.BACKEND_SINGLE_WRITER_VIOLATION):
            spec = REASON_CODE_CATALOG[reason]
            self.assertTrue(spec.is_failure)
            self.assertIsNotNone(spec.envelope_code)


class BackendResultTests(unittest.TestCase):
    def test_success_factory(self) -> None:
        result = BackendResult.success("officecli")
        self.assertTrue(result.ok)
        self.assertIsNone(result.reason_code)
        self.assertEqual(result.per_op, {})

    def test_failure_factory(self) -> None:
        result = BackendResult.failure("officecli", ReasonCode.BATCH_ROLLED_BACK,
                                       "boom")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason_code, ReasonCode.BATCH_ROLLED_BACK)
        self.assertEqual(result.detail, "boom")

    def test_success_with_reason_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BackendResult(backend="officecli", ok=True,
                          reason_code=ReasonCode.BATCH_ROLLED_BACK)

    def test_failure_without_reason_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BackendResult(backend="officecli", ok=False)

    def test_empty_backend_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BackendResult(backend="", ok=True)
        with self.assertRaises(ValueError):
            BackendResult.success("")

    def test_detail_is_truncated(self) -> None:
        result = BackendResult.success("officecli", detail="x" * (DETAIL_MAX_CHARS + 50))
        self.assertEqual(len(result.detail), DETAIL_MAX_CHARS)

    def test_result_is_frozen(self) -> None:
        result = BackendResult.success("officecli")
        with self.assertRaises(FrozenInstanceError):
            result.ok = False  # type: ignore[misc]

    def test_per_op_is_copied_into_a_plain_dict(self) -> None:
        outcome = OpOutcome(status="SUCCESS")
        source = {"OP_001": outcome}
        result = BackendResult.success("python-docx", per_op=source)
        source.clear()
        self.assertEqual(result.per_op, {"OP_001": outcome})


class OpOutcomeTests(unittest.TestCase):
    def test_valid_outcomes(self) -> None:
        for status in OP_STATUSES:
            if status == "FAILED":
                outcome = OpOutcome(status="FAILED", reason_code=ReasonCode.READBACK_MISMATCH)
            else:
                outcome = OpOutcome(status=status)
            self.assertEqual(outcome.status, status)

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OpOutcome(status="PASSED")

    def test_failed_requires_reason_code(self) -> None:
        with self.assertRaises(ValueError):
            OpOutcome(status="FAILED")

    def test_success_rejects_reason_code(self) -> None:
        with self.assertRaises(ValueError):
            OpOutcome(status="SUCCESS", reason_code=ReasonCode.BATCH_ROLLED_BACK)

    def test_sha256_fields_accept_valid_hex_or_none(self) -> None:
        sha = "a" * 64
        outcome = OpOutcome(status="SUCCESS", before_sha256=sha, after_sha256=sha.upper())
        self.assertEqual(outcome.after_sha256, sha)

    def test_sha256_fields_reject_short_values(self) -> None:
        with self.assertRaises(ValueError):
            OpOutcome(status="SUCCESS", before_sha256="abcd")

    def test_sha256_fields_reject_non_hex(self) -> None:
        with self.assertRaises(ValueError):
            OpOutcome(status="SUCCESS", after_sha256="z" * 64)


class BackendErrorTests(unittest.TestCase):
    def test_error_carries_reason_and_detail(self) -> None:
        error = BackendError(ReasonCode.OFFICECLI_BINARY_MISSING, "OFFICECLI_BINARY=... unset")
        self.assertEqual(error.reason_code, ReasonCode.OFFICECLI_BINARY_MISSING)
        self.assertIn("OFFICECLI_BINARY=... unset", error.detail)
        self.assertIn("OFFICECLI_BINARY_MISSING", str(error))

    def test_error_detail_is_truncated(self) -> None:
        error = BackendError(ReasonCode.BATCH_ROLLED_BACK, "y" * 1000)
        self.assertEqual(len(error.detail), DETAIL_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
