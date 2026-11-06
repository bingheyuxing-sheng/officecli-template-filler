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
    OFFICECLI_BACKEND_NAME,
    OFFICECLI_ENVELOPE_ALIASES,
    OpOutcome,
    ReasonCode,
    REASON_CODE_CATALOG,
    ValidationStatus,
    ValidationResult,
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


class EnvelopeAttributionTests(unittest.TestCase):
    """R1: generic Backend failures map to BACKEND_* codes; only the
    officecli path resolves the B0-era OFFICECLI_* spellings."""

    def setUp(self) -> None:
        self.registry = _registered_codes()

    def test_failure_reasons_map_to_generic_backend_codes(self) -> None:
        self.assertEqual(envelope_code_for(ReasonCode.BATCH_ROLLED_BACK), "BACKEND_BATCH_FAILED")
        self.assertEqual(envelope_code_for(ReasonCode.READBACK_MISMATCH), "BACKEND_READBACK_FAILED")
        self.assertEqual(envelope_code_for(ReasonCode.NORMALIZE_FAILED), "BACKEND_NORMALIZE_FAILED")
        self.assertEqual(envelope_code_for(ReasonCode.STAGE_CHECK_FAILED), "STAGE_CHECK_FAILED")
        self.assertEqual(envelope_code_for(ReasonCode.BACKEND_VALIDATE_FAILED),
                         "BACKEND_VALIDATE_FAILED")
        self.assertEqual(envelope_code_for(ReasonCode.BACKEND_SINGLE_WRITER_VIOLATION),
                         "BACKEND_SINGLE_WRITER_VIOLATION")

    def test_officecli_backend_resolves_backward_compatible_spellings(self) -> None:
        self.assertEqual(envelope_code_for(ReasonCode.BATCH_ROLLED_BACK, OFFICECLI_BACKEND_NAME),
                         "OFFICECLI_WRITE_FAILED")
        self.assertEqual(envelope_code_for(ReasonCode.READBACK_MISMATCH, OFFICECLI_BACKEND_NAME),
                         "OFFICECLI_READBACK_FAILED")
        self.assertEqual(envelope_code_for(ReasonCode.NORMALIZE_FAILED, OFFICECLI_BACKEND_NAME),
                         "OFFICECLI_NORMALIZE_FAILED")

    def test_python_backend_never_reports_officecli_codes(self) -> None:
        for reason, spec in REASON_CODE_CATALOG.items():
            if spec.is_failure:
                code = envelope_code_for(reason, "python-docx")
                self.assertFalse(
                    code.startswith("OFFICECLI_"),
                    "%s leaked an OfficeCLI spelling for a python-docx failure" % reason,
                )

    def test_same_failure_is_attributed_per_backend(self) -> None:
        # R1.6: the same failure type resolves to the right family both ways.
        for reason in (ReasonCode.BATCH_ROLLED_BACK, ReasonCode.READBACK_MISMATCH,
                       ReasonCode.NORMALIZE_FAILED):
            self.assertTrue(
                envelope_code_for(reason, OFFICECLI_BACKEND_NAME).startswith("OFFICECLI_")
            )
            self.assertTrue(envelope_code_for(reason, "python-docx").startswith("BACKEND_"))

    def test_generic_codes_and_aliases_are_registered(self) -> None:
        for generic, officecli in OFFICECLI_ENVELOPE_ALIASES.items():
            self.assertIn(generic, self.registry)
            self.assertIn(officecli, self.registry,
                          "the B0 executor still emits %s; it must stay registered" % officecli)

    def test_alias_table_covers_all_generic_failure_codes(self) -> None:
        generic_codes = {spec.envelope_code for spec in REASON_CODE_CATALOG.values()
                         if spec.is_failure}
        self.assertTrue(set(OFFICECLI_ENVELOPE_ALIASES) <= generic_codes)


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

    def test_per_op_is_read_only(self) -> None:
        # R3: the proxy must reject every mutation route.
        result = BackendResult.success(
            "officecli", per_op={"OP_001": OpOutcome(status="SUCCESS")}
        )
        with self.assertRaises(TypeError):
            result.per_op["OP_002"] = OpOutcome(status="SKIPPED")
        with self.assertRaises(TypeError):
            del result.per_op["OP_001"]
        # mappingproxy does not even expose the mutating helpers.
        self.assertFalse(hasattr(result.per_op, "clear"))
        self.assertFalse(hasattr(result.per_op, "update"))
        self.assertEqual(result.per_op["OP_001"].status, "SUCCESS")

    def test_result_serializes_through_to_dict(self) -> None:
        # R3.4: per_op is a proxy, so serialization must go through to_dict().
        result = BackendResult.failure(
            "python-docx", ReasonCode.READBACK_MISMATCH, detail="stale",
            per_op={"OP_001": OpOutcome(status="FAILED",
                                        reason_code=ReasonCode.READBACK_MISMATCH)},
        )
        payload = json.dumps(result.to_dict())
        restored = json.loads(payload)
        self.assertEqual(restored["backend"], "python-docx")
        self.assertFalse(restored["ok"])
        self.assertEqual(restored["reason_code"], "READBACK_MISMATCH")
        self.assertEqual(restored["per_op"]["OP_001"]["status"], "FAILED")
        self.assertEqual(restored["per_op"]["OP_001"]["reason_code"], "READBACK_MISMATCH")

    def test_op_outcome_to_dict_keeps_null_reason_for_success(self) -> None:
        payload = json.dumps(OpOutcome(status="SKIPPED").to_dict())
        self.assertIsNone(json.loads(payload)["reason_code"])


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


class ValidationResultTests(unittest.TestCase):
    """R2: the four-state validation model and its legal transitions."""

    def test_state_model_has_exactly_four_distinct_states(self) -> None:
        self.assertEqual(
            {status.value for status in ValidationStatus},
            {"PASSED", "FAILED", "UNAVAILABLE", "UNVERIFIED"},
        )

    def test_passed_means_validation_executed(self) -> None:
        result = ValidationResult.passed("officecli")
        self.assertEqual(result.status, ValidationStatus.PASSED)
        self.assertIsNone(result.reason_code)

    def test_passed_rejects_reason_code(self) -> None:
        with self.assertRaises(ValueError):
            ValidationResult("officecli", ValidationStatus.PASSED, ReasonCode.BACKEND_VALIDATE_FAILED)

    def test_failed_requires_validate_reason_and_detail(self) -> None:
        result = ValidationResult.failed("officecli", "schema violation at /body/p[2]")
        self.assertEqual(result.status, ValidationStatus.FAILED)
        self.assertEqual(result.reason_code, ReasonCode.BACKEND_VALIDATE_FAILED)
        self.assertTrue(result.detail)
        with self.assertRaises(ValueError):
            ValidationResult.failed("officecli", "")
        with self.assertRaises(ValueError):
            ValidationResult("officecli", ValidationStatus.FAILED,
                             ReasonCode.OFFICECLI_BINARY_MISSING, "wrong reason")

    def test_unavailable_keeps_traceability(self) -> None:
        result = ValidationResult.unavailable("python-docx", "no OpenXML validator in this backend")
        self.assertEqual(result.status, ValidationStatus.UNAVAILABLE)
        self.assertEqual(result.reason_code, ReasonCode.BACKEND_VALIDATE_UNAVAILABLE)
        self.assertTrue(result.detail)
        with self.assertRaises(ValueError):
            ValidationResult.unavailable("python-docx", "")

    def test_unverified_keeps_traceability(self) -> None:
        result = ValidationResult.unverified(
            "officecli", ReasonCode.OFFICECLI_BINARY_MISSING, "binary not installed"
        )
        self.assertEqual(result.status, ValidationStatus.UNVERIFIED)
        self.assertTrue(result.detail)
        with self.assertRaises(ValueError):
            ValidationResult.unverified("officecli", ReasonCode.OFFICECLI_BINARY_MISSING, "")

    def test_unverified_rejects_failure_reasons(self) -> None:
        # A validation that ran and found problems is FAILED, never UNVERIFIED.
        with self.assertRaises(ValueError):
            ValidationResult.unverified("officecli", ReasonCode.BATCH_ROLLED_BACK, "x")
        with self.assertRaises(ValueError):
            ValidationResult.unverified("officecli", ReasonCode.BACKEND_VALIDATE_FAILED, "x")

    def test_not_executed_states_never_collapse_into_passed(self) -> None:
        # R2.1/2: "no validator" and "not executed" are their own states.
        unavailable = ValidationResult.unavailable("python-docx", "no validator")
        unverified = ValidationResult.unverified(
            "officecli", ReasonCode.OFFICECLI_BINARY_MISSING, "binary missing"
        )
        for result in (unavailable, unverified):
            self.assertNotEqual(result.status, ValidationStatus.PASSED)

    def test_validation_result_is_frozen(self) -> None:
        result = ValidationResult.passed("officecli")
        with self.assertRaises(FrozenInstanceError):
            result.status = ValidationStatus.FAILED  # type: ignore[misc]

    def test_validation_result_serializes(self) -> None:
        payload = json.dumps(ValidationResult.unavailable("python-docx", "no validator").to_dict())
        restored = json.loads(payload)
        self.assertEqual(restored["status"], "UNAVAILABLE")
        self.assertEqual(restored["reason_code"], "BACKEND_VALIDATE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
