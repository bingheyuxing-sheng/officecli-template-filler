# -*- coding: utf-8 -*-
"""W4-5 tests: Gate Record persistence, HMAC integrity and expiry."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from template_gate import build_analysis  # noqa: E402
from template_gate.report import build_report  # noqa: E402
from template_gate.store import GateStore  # noqa: E402


def _standard_template(directory: str) -> str:
    path = os.path.join(directory, "template.docx")
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    document.save(path)
    return path


class GateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.gate_home = os.path.join(self._tmp.name, "gates")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _confirmed(self, directory: str) -> tuple:
        template = _standard_template(directory)
        analysis = build_analysis(template, "GENERATE")
        report = build_report(analysis)
        store = GateStore(self.gate_home)
        record = store.confirm(
            analysis,
            report,
            user_statement="确认，按该模板生成",
            ttl_seconds=3600,
        )
        return store, record, analysis

    def test_confirm_persists_and_finds_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, record, analysis = self._confirmed(directory)
            self.assertTrue(os.path.isfile(store.secret_path))
            self.assertEqual(record["status"], "CONFIRMED")
            self.assertTrue(record["user_confirmed"])
            self.assertTrue(record["confirmation_token"])
            self.assertTrue(store.verify(record))
            loaded = store.load(record["gate_id"])
            self.assertIsNotNone(loaded)
            found = store.find(analysis["template_sha256"], "GENERATE")
            self.assertIsNotNone(found)
            self.assertEqual(found["gate_id"], record["gate_id"])
            self.assertFalse(os.path.isfile(store._record_path(record) + ".tmp"))

    def test_record_validates_against_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _store, record, _analysis = self._confirmed(directory)
        with open(ROOT / "schemas" / "template_gate_record-1.0.schema.json", "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        errors = sorted(Draft202012Validator(schema).iter_errors(record), key=lambda item: list(item.absolute_path))
        self.assertEqual(errors, [], [error.message for error in errors])

    def test_tampered_record_fails_hmac(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, record, _analysis = self._confirmed(directory)
        tampered = dict(record)
        tampered["user_statement"] = "已被篡改"
        self.assertFalse(store.verify(tampered))

    def test_expired_record_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, record, _analysis = self._confirmed(directory)
        expired = dict(record)
        expired["expires_at"] = "2000-01-01T00:00:00+00:00"
        self.assertTrue(store.is_expired(expired))
        self.assertFalse(store.is_expired(record))

    def test_corrupted_record_does_not_raise(self) -> None:
        os.makedirs(self.gate_home, exist_ok=True)
        bad_path = os.path.join(self.gate_home, "gate_deadbeef1234_GENERATE_gate_abcdef123456.json")
        with open(bad_path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        store = GateStore(self.gate_home)
        self.assertIsNone(store.load("gate_abcdef123456"))
        self.assertEqual(store.list(), [])

    def test_reject_record_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _standard_template(directory)
            analysis = build_analysis(template, "GENERATE")
            store = GateStore(self.gate_home)
            record = store.reject(analysis, user_statement="暂不生成")
        self.assertEqual(record["status"], "REJECTED")
        self.assertFalse(record["user_confirmed"])
        self.assertFalse(store.verify(record))

    def test_secret_bytes_round_trip_verbatim(self) -> None:
        """A random key may begin or end with whitespace; it must not be trimmed.

        ``_secret()`` used to ``.strip()`` the key file. Roughly 5% of 32-byte
        keys start or end with a whitespace byte, so signing and verification
        silently disagreed and gate records failed HMAC at random.
        """
        raw = b" " + b"A" * 30 + b"\t"
        os.makedirs(self.gate_home, exist_ok=True)
        store = GateStore(self.gate_home)
        with open(store.secret_path, "wb") as handle:
            handle.write(raw)
        self.assertEqual(store._secret(), raw)


if __name__ == "__main__":
    unittest.main()
