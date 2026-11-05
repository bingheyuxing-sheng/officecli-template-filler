# -*- coding: utf-8 -*-
"""Contract 01 conformance: deterministic vectors, invalidation rules and collision handling."""

from __future__ import annotations

import unittest

from .helpers import (
    EXAMPLE_DIR,
    LOCATION_RE,
    SLOT_ID_RE,
    SLOT_KEY_RE,
    example,
    load_json,
    normalize_text,
    resolve_collisions,
    slot_id_ref,
    slot_key_ref,
    validate_slot_inputs,
)


class SlotIdVectorTests(unittest.TestCase):
    def test_valid_vectors(self) -> None:
        cases = load_json(EXAMPLE_DIR / "slot-id" / "cases.json")["cases"]
        for name, case in cases.items():
            if case["kind"] != "valid":
                continue
            with self.subTest(case=name):
                inputs = case["inputs"]
                computed = slot_id_ref(
                    inputs["template_sha256"],
                    inputs["location_id"],
                    inputs["matched_text"],
                    inputs["occurrence"],
                )
                computed_key = slot_key_ref(
                    inputs["location_id"], inputs["matched_text"], inputs["occurrence"]
                )
                self.assertEqual(computed, case["expected"]["slot_id"])
                self.assertEqual(computed_key, case["expected"]["slot_key"])
                self.assertRegex(computed, SLOT_ID_RE)
                self.assertRegex(computed_key, SLOT_KEY_RE)

    def test_whitespace_normalization_is_stable(self) -> None:
        basic = example("slot-id", "basic_valid")
        spaced = example("slot-id", "whitespace_stable")
        self.assertEqual(
            slot_id_ref(basic["inputs"]["template_sha256"], "body.p[0]", basic["inputs"]["matched_text"], 1),
            slot_id_ref(spaced["inputs"]["template_sha256"], "body.p[0]", spaced["inputs"]["matched_text"], 1),
        )
        self.assertEqual(normalize_text("  {{项目名称}}  "), "{{项目名称}}")

    def test_occurrence_and_upgrade(self) -> None:
        first = example("slot-id", "basic_valid")["inputs"]
        second = example("slot-id", "occurrence_separated")["inputs"]
        upgraded = example("slot-id", "template_upgrade")["inputs"]

        id_first = slot_id_ref(first["template_sha256"], first["location_id"], first["matched_text"], first["occurrence"])
        id_second = slot_id_ref(second["template_sha256"], second["location_id"], second["matched_text"], second["occurrence"])
        id_upgraded = slot_id_ref(upgraded["template_sha256"], upgraded["location_id"], upgraded["matched_text"], upgraded["occurrence"])

        self.assertNotEqual(id_first, id_second)
        self.assertNotEqual(id_first, id_upgraded)
        self.assertEqual(
            slot_key_ref(first["location_id"], first["matched_text"], first["occurrence"]),
            slot_key_ref(upgraded["location_id"], upgraded["matched_text"], upgraded["occurrence"]),
        )

    def test_table_cell_vector(self) -> None:
        case = example("slot-id", "table_cell")
        inputs = case["inputs"]
        self.assertEqual(
            slot_id_ref(inputs["template_sha256"], inputs["location_id"], inputs["matched_text"], inputs["occurrence"]),
            case["expected"]["slot_id"],
        )
        self.assertEqual(
            slot_key_ref(inputs["location_id"], inputs["matched_text"], inputs["occurrence"]),
            case["expected"]["slot_key"],
        )


class SlotInputValidationTests(unittest.TestCase):
    def test_invalid_occurrence(self) -> None:
        case = example("slot-id", "invalid_occurrence")
        self.assertEqual(
            validate_slot_inputs(**case["inputs"]), [case["expected_error"]]
        )

    def test_invalid_location(self) -> None:
        case = example("slot-id", "invalid_location")
        self.assertEqual(
            validate_slot_inputs(**case["inputs"]), [case["expected_error"]]
        )

    def test_invalid_sha_and_empty_text(self) -> None:
        sha = "0" * 64
        self.assertEqual(
            validate_slot_inputs("A" * 64, "body.p[0]", "{{x}}", 1),
            ["SLOT_TEMPLATE_SHA_INVALID"],
        )
        self.assertEqual(validate_slot_inputs(sha, "body.p[0]", "   ", 1), ["SLOT_TEXT_EMPTY_UNEVIDENCED"])

    def test_location_and_id_grammar(self) -> None:
        for value in (
            "body.p[0]",
            "body.tbl[1].r[2].c[1].p[0]",
            "sec[0].header.p[0]",
            "sec[1].first_page_header.p[0]",
            "sec[0].even_page_footer.tbl[0].r[1].c[0].p[0]",
            "footnotes.p[4]",
            # CP-W2-002: `sdt` is a location element in every addressable container.
            "body.sdt[0].p[0]",
            "body.sdt[0].sdt[1].p[0]",
            "body.tbl[0].r[0].c[0].sdt[0].p[0]",
            "sec[0].header.sdt[0].p[0]",
            "sec[0].even_page_footer.sdt[0].p[0]",
            "body.sdt[0].tbl[0].r[0].c[0].p[0]",
            "body.sdt[0]",
        ):
            self.assertRegex(value, LOCATION_RE)
        for value in (
            "body.p0", "body.p[-1]", "", "body", "sec[0].first_page_header",
            # bare container/paragraph forms without an index are still invalid
            "body.sdt", "body.sdt[0].p", "body.sdt[-1]", "body.sdt[0].p[0].sdt",
        ):
            self.assertNotRegex(value, LOCATION_RE)

        self.assertRegex("S_d6df35f1e6cd", SLOT_ID_RE)
        self.assertRegex("S_d6df35f1e6cd-c2", SLOT_ID_RE)
        self.assertNotRegex("S_D6DF35F1E6CD", SLOT_ID_RE)
        self.assertNotRegex("S_d6df35f1e6c", SLOT_ID_RE)
        self.assertNotRegex("S_d6df35f1e6cd-c1", SLOT_ID_RE)


class CollisionRuleTests(unittest.TestCase):
    def test_collision_suffix_is_deterministic(self) -> None:
        base = "S_abcdef123456"
        items = [("canonical-c", base), ("canonical-a", base), ("canonical-b", base)]
        first_run = resolve_collisions(items)
        second_run = resolve_collisions(list(reversed(items)))
        self.assertEqual(first_run, second_run)
        self.assertEqual(first_run, [base, f"{base}-c2", f"{base}-c3"])


if __name__ == "__main__":
    unittest.main()
