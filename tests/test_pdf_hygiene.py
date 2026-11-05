# -*- coding: utf-8 -*-
"""W3-1: convert_docx_to_pdf must never leave the `pdf-src-*` source copy behind.

All backends are mocked (E2): the assertions do not depend on whether the host
has WPS or LibreOffice installed.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

import engine.pdf_backend as pdf_backend


def _leftovers(out_dir: str):
    return [name for name in os.listdir(out_dir) if name.startswith("pdf-src-")]


class PdfTempCopyHygieneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.out_dir = tempfile.mkdtemp(prefix="w31-out-")
        self.docx = os.path.join(self.out_dir, "secret-name.docx")
        with open(self.docx, "wb") as handle:
            handle.write(b"docx-bytes")

    def tearDown(self) -> None:
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def _backend(self, name: str) -> dict:
        return {"name": name, "executable": "fake-executable"}

    def test_success_path_cleans_copy(self) -> None:
        seen = {}

        def fake_wps(executable, source, pdf_path):
            seen["source_exists"] = os.path.isfile(source)
            with open(pdf_path, "wb") as handle:
                handle.write(b"pdf")
            return pdf_path, None

        with mock.patch.object(pdf_backend, "_convert_with_wps", fake_wps):
            pdf, error, name = pdf_backend.convert_docx_to_pdf(
                self.docx, self.out_dir, backend=self._backend("wps")
            )
        self.assertIsNone(error)
        self.assertEqual(name, "wps")
        self.assertTrue(seen.get("source_exists"), "conversion must run on a private copy")
        self.assertTrue(os.path.isfile(pdf), "the produced PDF must remain")
        self.assertEqual(_leftovers(self.out_dir), [])

    def test_conversion_failure_cleans_copy(self) -> None:
        with mock.patch.object(
            pdf_backend, "_convert_with_libreoffice",
            lambda exe, src, out, pdf: (None, "exit=1: boom"),
        ):
            pdf, error, name = pdf_backend.convert_docx_to_pdf(
                self.docx, self.out_dir, backend=self._backend("libreoffice")
            )
        self.assertIsNone(pdf)
        self.assertIn("boom", error)
        self.assertEqual(_leftovers(self.out_dir), [])

    def test_unexpected_exception_cleans_copy(self) -> None:
        def raise_timeout(executable, source, pdf_path):
            raise RuntimeError("simulated stuck converter")

        with mock.patch.object(pdf_backend, "_convert_with_wps", raise_timeout):
            with self.assertRaises(RuntimeError):
                pdf_backend.convert_docx_to_pdf(
                    self.docx, self.out_dir, backend=self._backend("wps")
                )
        self.assertEqual(_leftovers(self.out_dir), [])

    def test_copy_failure_cleans_copy(self) -> None:
        with mock.patch.object(pdf_backend.shutil, "copy2", side_effect=OSError("denied")):
            pdf, error, name = pdf_backend.convert_docx_to_pdf(
                self.docx, self.out_dir, backend=self._backend("wps")
            )
        self.assertIsNone(pdf)
        self.assertTrue(error.startswith("SOURCE_COPY_FAILED"))
        self.assertEqual(_leftovers(self.out_dir), [])

    def test_unknown_backend_cleans_copy(self) -> None:
        pdf, error, name = pdf_backend.convert_docx_to_pdf(
            self.docx, self.out_dir, backend={"name": "word", "executable": "x"}
        )
        self.assertIsNone(pdf)
        self.assertIn("UNKNOWN_PDF_BACKEND", error)
        self.assertEqual(_leftovers(self.out_dir), [])

    def test_no_backend_writes_nothing(self) -> None:
        pdf, error, name = pdf_backend.convert_docx_to_pdf(
            self.docx, self.out_dir, backend={"name": "none", "executable": None}
        )
        self.assertIsNone(pdf)
        self.assertEqual(error, "NO_PDF_BACKEND")
        self.assertEqual(_leftovers(self.out_dir), [])


if __name__ == "__main__":
    unittest.main()
