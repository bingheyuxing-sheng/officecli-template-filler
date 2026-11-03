# -*- coding: utf-8 -*-
"""
v3.5 M1 — Transactional document delivery.

Every entrypoint that writes a deliverable must follow:

    Preflight -> Execute (staged temp file) -> QA (on the staged file) -> Commit

The final path only appears after QA has run and has not failed. A failed or
unverified-QA run never leaves a half-written document behind that could be
mistaken for a finished deliverable.

Usage:

    tx = DocumentTransaction("template.docx", "out.docx", task_mode="GENERATE")
    with tx:                      # runs preflight, aborts on exception
        doc.save(tx.stage())      # write to the staged path
        tx.record_qa(qa_report)   # QA against tx.temp_path
        tx.commit()               # atomic replace into tx.output_path

`commit()` raises `TransactionAborted` when QA failed; the staged artifacts are
already removed at that point, and `tx.record()` explains why.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any, Dict, Iterable, Optional, Tuple

from .qa_policy import split_issues
from .process_guard import list_process_pids

QA_PASSED = "PASSED"
QA_PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
QA_UNVERIFIED = "UNVERIFIED"
QA_FAILED = "FAILED"

# Only REVIEW deliverables may keep template placeholders on purpose.
PENDING_HUMAN_REVIEW_CODES = ("TEMPLATE_TEXT_RESIDUAL",)

SUPPORTED_EXTENSIONS = frozenset({".docx", ".docm", ".xlsx", ".xlsm"})
# RENDER mode publishes a PDF, so the output may be a non-Office container.
SUPPORTED_OUTPUT_EXTENSIONS = SUPPORTED_EXTENSIONS | {".pdf"}
_EXTENSION_FAMILY = {".docx": "word", ".docm": "word", ".xlsx": "excel", ".xlsm": "excel"}


class TransactionPreflightError(RuntimeError):
    """Raised when the inputs cannot produce a safe transaction (bad path, format, ...)."""


class TransactionAborted(RuntimeError):
    """Raised by `commit()` when the transaction produced no deliverable."""

    def __init__(self, reason: str, record: Dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.record = record


def _check(name: str, ok: bool, detail: str, required: bool = True) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "required": required, "detail": detail}


def _sha256(path: str) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_issues(report: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for key in ("structured_issues", "issues"):
        for item in report.get(key) or []:
            if isinstance(item, dict) and item.get("code"):
                yield item


def resolve_qa_status(
    *reports: Optional[Dict[str, Any]],
    pending_codes: Tuple[str, ...] = (),
) -> str:
    """
    Fold one or more QA section reports into a single status.

    Rules (honest-reporting):
    - any hard issue, or a report that says `passed: False` without issues -> FAILED
    - issues that are explicitly allowed to wait for a human -> PENDING_HUMAN_REVIEW
    - coverage gaps / unverified checks -> UNVERIFIED (never PASSED)
    - otherwise PASSED
    """
    issues = []
    coverage_gaps = []
    unverified = 0
    explicit_status = []
    reported_failure = False

    for report in reports:
        if not isinstance(report, dict):
            continue
        issues.extend(_iter_issues(report))
        coverage_gaps.extend(report.get("coverage_gaps") or [])
        unverified += int(report.get("unverified_count") or 0)
        status = report.get("status")
        if status in (QA_PASSED, QA_PENDING_HUMAN_REVIEW, QA_UNVERIFIED, QA_FAILED):
            explicit_status.append(status)
        if report.get("passed") is False:
            reported_failure = True

    hard_issues, warnings, pending_issues = split_issues(issues, pending_codes)

    if QA_FAILED in explicit_status or hard_issues:
        return QA_FAILED
    if reported_failure and not pending_issues and not warnings:
        return QA_FAILED
    if QA_PENDING_HUMAN_REVIEW in explicit_status or pending_issues:
        return QA_PENDING_HUMAN_REVIEW
    if QA_UNVERIFIED in explicit_status or coverage_gaps or unverified:
        return QA_UNVERIFIED
    return QA_PASSED


class DocumentTransaction:
    """Stage a deliverable in a sibling temp file and publish it only after QA."""

    def __init__(
        self,
        source_path: Optional[str],
        output_path: Optional[str],
        *,
        task_mode: str = "",
    ) -> None:
        self.source_path = os.path.abspath(source_path) if source_path else None
        self.output_path = os.path.abspath(output_path) if output_path else None
        self.task_mode = task_mode
        self.transaction_id = uuid.uuid4().hex

        out_dir = (
            os.path.dirname(self.output_path)
            if self.output_path
            else os.path.dirname(self.source_path or os.getcwd())
        )
        base_name = os.path.basename(self.output_path or self.source_path or "output")
        stem, ext = os.path.splitext(base_name)
        self.temp_path = os.path.join(out_dir, f".{stem}.tmp-{self.transaction_id}{ext}")
        self.pending_path = os.path.join(out_dir, f".{stem}.pending-{self.transaction_id}{ext}")

        self.preflight_report: Dict[str, Any] = {"passed": False, "checks": []}
        self.qa_status: Optional[str] = None
        self.qa_report_path: Optional[str] = None
        self.input_sha256: Optional[str] = None
        self.output_sha256: Optional[str] = None
        self.committed = False
        self.abort_reason: Optional[str] = None
        self.commit_skipped_reason: Optional[str] = None
        self.lock_info: Optional[Dict[str, Any]] = None

        self._preflighted = False
        self._finished = False

    # ------------------------------------------------------------------ context

    def __enter__(self) -> "DocumentTransaction":
        report = self.preflight()
        if not report["passed"]:
            failed = [c["name"] for c in report["checks"] if c["required"] and not c["ok"]]
            raise TransactionPreflightError(
                "preflight failed: " + ", ".join(failed or ["unknown"])
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._finished:
            return False
        if exc_type is not None:
            self.abort(f"EXCEPTION: {exc_type.__name__}: {exc_val}")
        else:
            self.abort("NOT_COMMITTED")
        return False

    # ------------------------------------------------------------------ phases

    def preflight(self) -> Dict[str, Any]:
        """Validate inputs/outputs before anything is written."""
        if self._preflighted:
            return self.preflight_report

        checks = []
        source_ok = bool(self.source_path) and os.path.isfile(self.source_path)
        checks.append(_check("source_exists", source_ok, self.source_path or "missing source path"))
        if source_ok:
            self.input_sha256 = _sha256(self.source_path)
            source_ext = os.path.splitext(self.source_path)[1].lower()
            checks.append(_check(
                "source_extension",
                source_ext in SUPPORTED_EXTENSIONS,
                f"{source_ext or '(none)'} (supported: {sorted(SUPPORTED_EXTENSIONS)})",
            ))
        else:
            source_ext = ""

        if self.output_path is None:
            checks.append(_check(
                "output_configured",
                True,
                "no final path configured: QA artifacts will not be published",
                required=False,
            ))
        else:
            out_ext = os.path.splitext(self.output_path)[1].lower()
            checks.append(_check(
                "output_extension",
                out_ext in SUPPORTED_OUTPUT_EXTENSIONS,
                f"{out_ext or '(none)'} (supported: {sorted(SUPPORTED_OUTPUT_EXTENSIONS)})",
            ))
            if source_ext in _EXTENSION_FAMILY and out_ext in _EXTENSION_FAMILY:
                checks.append(_check(
                    "output_container_family",
                    _EXTENSION_FAMILY[source_ext] == _EXTENSION_FAMILY[out_ext],
                    f"{source_ext} -> {out_ext}",
                ))
            out_dir = os.path.dirname(self.output_path) or os.getcwd()
            try:
                os.makedirs(out_dir, exist_ok=True)
                writable = os.access(out_dir, os.W_OK)
                detail = out_dir
            except OSError as exc:
                writable = False
                detail = f"{out_dir} ({exc})"
            checks.append(_check("output_directory_writable", writable, detail))
            if self.source_path and os.path.normcase(self.source_path) == os.path.normcase(self.output_path):
                checks.append(_check(
                    "in_place_output",
                    True,
                    "source and output are the same file; it will be replaced atomically",
                    required=False,
                ))

        self.preflight_report = {
            "passed": all(c["ok"] for c in checks if c["required"]),
            "checks": checks,
        }
        self._preflighted = True
        return self.preflight_report

    def stage(self) -> str:
        """Return the staged file path that the writer must save to."""
        if not self._preflighted:
            self.preflight()
        os.makedirs(os.path.dirname(self.temp_path) or os.getcwd(), exist_ok=True)
        return self.temp_path

    def record_qa(
        self,
        *reports: Optional[Dict[str, Any]],
        pending_codes: Tuple[str, ...] = (),
        qa_report_path: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str:
        """Attach QA results produced against the staged file."""
        self.qa_status = status or resolve_qa_status(*reports, pending_codes=tuple(pending_codes))
        if qa_report_path:
            self.qa_report_path = qa_report_path
        return self.qa_status

    def commit(self) -> Dict[str, Any]:
        """Publish the staged file to the final path, or abort when QA did not pass."""
        if self._finished:
            return self.record()

        if not self.preflight_report.get("passed"):
            raise TransactionAborted("PREFLIGHT_FAILED", self.record())
        if self.qa_status is None:
            self.abort("QA_NOT_RUN")
            raise TransactionAborted("QA_NOT_RUN", self.record())
        if self.qa_status == QA_FAILED:
            self.abort("QA_FAILED")
            raise TransactionAborted("QA_FAILED", self.record())

        if self.output_path is None:
            self._remove_staged()
            self.commit_skipped_reason = "NO_FINAL_PATH"
            self._finished = True
            return self.record()

        if not os.path.isfile(self.temp_path):
            self.abort("STAGED_FILE_MISSING")
            raise TransactionAborted("STAGED_FILE_MISSING", self.record())

        self.output_sha256 = _sha256(self.temp_path)
        try:
            # Two renames on the same filesystem: temp -> pending -> final.
            # The final path is only ever complete content, never a partial write.
            os.replace(self.temp_path, self.pending_path)
            os.replace(self.pending_path, self.output_path)
        except PermissionError as exc:
            # A preview process (WPS editor_sdk.exe, Explorer preview, ...) can hold the
            # final path. Report the actionable facts instead of a bare traceback.
            self.lock_info = {
                "code": "OUTPUT_FILE_LOCKED",
                "output_path": self.output_path,
                "error": str(exc),
                "editor_sdk_pids": list_process_pids("editor_sdk.exe"),
                "hint": (
                    "Close the preview that holds the file, or run "
                    "`python scripts/cleanup_editor_sdk.py --list` and then "
                    "`--kill-pid <pid> --confirm` for the preview process you own."
                ),
            }
            self.abort("OUTPUT_FILE_LOCKED")
            raise TransactionAborted("OUTPUT_FILE_LOCKED", self.record())
        except OSError as exc:
            self.abort(f"COMMIT_FAILED: {exc}")
            raise TransactionAborted(f"COMMIT_FAILED: {exc}", self.record())

        self.committed = True
        self._finished = True
        return self.record()

    def abort(self, reason: str) -> Dict[str, Any]:
        """Discard staged artifacts. Idempotent; the first reason wins."""
        if self._finished and self.committed:
            return self.record()
        self._remove_staged()
        if self.abort_reason is None:
            self.abort_reason = reason
        self.committed = False
        self._finished = True
        return self.record()

    # ------------------------------------------------------------------ helpers

    def _remove_staged(self) -> None:
        for path in (self.temp_path, self.pending_path):
            try:
                if path and os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass

    def record(self) -> Dict[str, Any]:
        """Serializable transaction summary for the entrypoint's JSON output."""
        return {
            "transaction_id": self.transaction_id,
            "task_mode": self.task_mode,
            "source": self.source_path,
            "output": self.output_path,
            "preflight": self.preflight_report,
            "qa_status": self.qa_status,
            "committed": self.committed,
            "commit_skipped_reason": self.commit_skipped_reason,
            "abort_reason": self.abort_reason,
            "lock_info": self.lock_info,
            "staged_path": None if self._finished else self.temp_path,
            "qa_report_path": self.qa_report_path,
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
        }
