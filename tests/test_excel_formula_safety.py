# -*- coding: utf-8 -*-
"""SEC-02: document-derived arithmetic must never reach ``eval``.

The Excel QA evaluator substitutes cell references into a Python expression.
A character whitelist alone is a fragile boundary, so the expression is now
walked as an AST that only accepts numeric literals, ``Decimal(<literal>)`` and
``+ - * /``.  These tests pin both the accepted language and the rejections.
"""

from __future__ import annotations

import ast
import pathlib
import unittest
from decimal import Decimal

import engine.excel_engine as excel_engine


class _Cell:
    def __init__(self, value):
        self.value = value


class _Sheet(dict):
    """Minimal ``ws[coord].value`` stand-in for the formula evaluator."""


class SafeDecimalEvalTests(unittest.TestCase):
    def test_arithmetic_and_decimal_literals_are_supported(self) -> None:
        self.assertEqual(
            excel_engine._safe_decimal_eval("Decimal('1.5') + Decimal('2.5')"), Decimal("4.0")
        )
        self.assertEqual(excel_engine._safe_decimal_eval("2 * 3 - 1"), Decimal("5"))
        self.assertEqual(excel_engine._safe_decimal_eval("-(4) + 1"), Decimal("-3"))

    def test_attribute_access_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            excel_engine._safe_decimal_eval("Decimal.__class__")

    def test_arbitrary_calls_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            excel_engine._safe_decimal_eval("__import__('os')")

    def test_boolean_constants_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            excel_engine._safe_decimal_eval("True")

    def test_power_operator_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            excel_engine._safe_decimal_eval("2 ** 8")

    def test_module_does_not_call_eval(self) -> None:
        source = pathlib.Path(excel_engine.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "eval"
        ]
        self.assertEqual(calls, [])


class FormulaEvaluatorRegressionTests(unittest.TestCase):
    def _sheet(self):
        return _Sheet(
            {
                "C5": _Cell(3),
                "D5": _Cell(2.5),
                "A1": _Cell(None),
            }
        )

    def test_arithmetic_over_cells(self) -> None:
        value, error = excel_engine._eval_simple_excel_formula(self._sheet(), "=C5*2")
        self.assertIsNone(error)
        self.assertEqual(value, Decimal("6"))

    def test_division_by_zero_is_reported(self) -> None:
        value, error = excel_engine._eval_simple_excel_formula(self._sheet(), "=C5/0")
        self.assertIsNone(value)
        self.assertEqual(error, "#DIV/0!")

    def test_text_operand_is_value_error(self) -> None:
        value, error = excel_engine._eval_simple_excel_formula(self._sheet(), "=C5*'e'")
        self.assertIsNone(value)
        self.assertEqual(error, "#VALUE!")


if __name__ == "__main__":
    unittest.main()
