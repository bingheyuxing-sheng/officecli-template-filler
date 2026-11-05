"""
Decimal-Based Single-Source-of-Truth (SSOT) Mathematical Solver (v3.0 — Fixes P0-2).

Replaces binary floating-point (`float` / `round(..., 4)`) with `decimal.Decimal`:
- Exact decimal arithmetic (`Decimal("0.1") + Decimal("0.2") == Decimal("0.3")`).
- Explicit precision, rounding mode (`ROUND_HALF_UP`, `ROUND_HALF_EVEN`, etc.), and unit conversion rules
  (`yuan`, `wan_yuan`, `percent`, `fraction`, `hours`, `credits`, `integer`).
- Explicit threshold unit representation (`{"value": "0.50", "unit": "fraction"}` or `{"value": "50", "unit": "percent"}`),
  eliminating heuristic guessing (`if min_r > 1.0: min_r /= 100.0`).
- Deterministic zero-denominator and missing-value policy (`raise`, `zero`, or `null`).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, List, Optional, Tuple, Union


class SSOTValidationError(ValueError):
    """
    Raised when supplied data violates a declared SSOT rule.

    This must never be an `assert`: `python -O` strips assertions, so a totals check written
    as `assert` silently accepts wrong numbers in optimized mode.

    The error carries structured evidence (`metric`, `locations`, `values`) so a caller can
    report which metric failed, where the conflicting entries live, and both values instead
    of only a prose message.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "SSOT_VALIDATION_FAILED",
        metric: Optional[str] = None,
        locations: Optional[List[str]] = None,
        values: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.metric = metric
        self.locations = list(locations or [])
        self.values = dict(values or {})

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "metric": self.metric,
            "locations": self.locations,
            "values": self.values,
        }


ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_UP": ROUND_UP,
}

# Standard unit conversion factors to base unit within dimension
UNIT_SCALE_TO_BASE: Dict[str, Tuple[str, Decimal]] = {
    "yuan": ("currency", Decimal("1")),
    "wan_yuan": ("currency", Decimal("10000")),
    "qian_yuan": ("currency", Decimal("1000")),
    "yi_yuan": ("currency", Decimal("100000000")),
    "fraction": ("ratio", Decimal("1")),
    "percent": ("ratio", Decimal("0.01")),
    "permille": ("ratio", Decimal("0.001")),
    "hours": ("time", Decimal("1")),
    "credits": ("credit", Decimal("1")),
    "integer": ("count", Decimal("1")),
}

DEFAULT_UNIT_DECIMALS: Dict[str, int] = {
    "yuan": 2,
    "wan_yuan": 4,
    "qian_yuan": 3,
    "yi_yuan": 6,
    "fraction": 4,
    "percent": 2,
    "permille": 3,
    "hours": 1,
    "credits": 1,
    "integer": 0,
}


def to_decimal(
    val: Any,
    missing_policy: str = "zero",
    field_name: str = "",
) -> Optional[Decimal]:
    """
    Convert `val` (str, int, Decimal, float, or `{"value": ..., "unit": ...}`) to `Decimal`
    without binary float representation artifacts (converts `float` via `str(val)`).
    - `missing_policy`: `"zero"` -> `Decimal("0")`, `"null"` -> `None`, `"raise"` -> raises ValueError.
    """
    if isinstance(val, dict) and "value" in val:
        val = val["value"]
    if val is None or (isinstance(val, str) and val.strip() == ""):
        if missing_policy == "raise":
            raise ValueError(f"Missing required numeric value for field '{field_name}'")
        if missing_policy == "null":
            return None
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    if isinstance(val, bool):
        raise ValueError(f"Boolean is not a valid numeric value for field '{field_name}'")
    try:
        return Decimal(str(val).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Decimal value {val!r} for field '{field_name}'") from exc


def quantize_decimal(
    val: Decimal,
    decimals: int = 2,
    rounding: str = "ROUND_HALF_UP",
) -> Decimal:
    mode = ROUNDING_MODES.get(rounding, ROUND_HALF_UP)
    q_exp = Decimal("1") if decimals <= 0 else Decimal("1." + ("0" * decimals))
    return val.quantize(q_exp, rounding=mode)


def convert_unit(
    val: Union[Decimal, int, str, Dict[str, Any]],
    from_unit: Optional[str] = None,
    to_unit: str = "yuan",
    decimals: Optional[int] = None,
    rounding: str = "ROUND_HALF_UP",
) -> Decimal:
    """Convert a value between compatible units (e.g., `yuan` <-> `wan_yuan`, `percent` <-> `fraction`)."""
    if isinstance(val, dict) and "value" in val:
        from_unit = from_unit or val.get("unit")
        dec_val = to_decimal(val["value"], missing_policy="raise")
    else:
        dec_val = to_decimal(val, missing_policy="raise")

    if not from_unit or from_unit == to_unit:
        target_dec = DEFAULT_UNIT_DECIMALS.get(to_unit, 2) if decimals is None else decimals
        return quantize_decimal(dec_val, decimals=target_dec, rounding=rounding)

    if from_unit not in UNIT_SCALE_TO_BASE or to_unit not in UNIT_SCALE_TO_BASE:
        raise ValueError(f"Unsupported unit conversion: {from_unit!r} -> {to_unit!r}")
    dim_from, scale_from = UNIT_SCALE_TO_BASE[from_unit]
    dim_to, scale_to = UNIT_SCALE_TO_BASE[to_unit]
    if dim_from != dim_to:
        raise ValueError(f"Incompatible unit dimensions: {from_unit} ({dim_from}) vs {to_unit} ({dim_to})")

    base_val = dec_val * scale_from
    converted = base_val / scale_to
    target_dec = DEFAULT_UNIT_DECIMALS.get(to_unit, 2) if decimals is None else decimals
    return quantize_decimal(converted, decimals=target_dec, rounding=rounding)


def parse_ratio_bound(bound_spec: Any, rule_name: str = "") -> Decimal:
    """
    Parse a ratio threshold without guessing unit from magnitude (P0-2 fix):
    - Preferred structured format: `{"value": "0.50", "unit": "fraction"}` or `{"value": "50.0", "unit": "percent"}`.
    - String with `%` suffix: `"50%"` -> `Decimal("0.50")`.
    - Bare numeric / Decimal: treated strictly as a fraction in `[0, 1]` unless `unit` is explicitly specified.
      Raises `ValueError` if a bare number `> 1` is passed without an explicit `"unit": "percent"`.
    """
    if isinstance(bound_spec, dict):
        unit = bound_spec.get("unit", "fraction")
        raw = to_decimal(bound_spec.get("value"), missing_policy="raise", field_name=rule_name)
        if unit == "percent":
            return raw * Decimal("0.01")
        if unit == "permille":
            return raw * Decimal("0.001")
        if unit == "fraction":
            return raw
        raise ValueError(f"Unknown ratio bound unit {unit!r} in rule '{rule_name}'")

    if isinstance(bound_spec, str) and bound_spec.strip().endswith("%"):
        raw = to_decimal(bound_spec.strip()[:-1], missing_policy="raise", field_name=rule_name)
        return raw * Decimal("0.01")

    dec = to_decimal(bound_spec, missing_policy="raise", field_name=rule_name)
    if dec > Decimal("1"):
        raise ValueError(
            f"Ambiguous ratio bound {bound_spec!r} in rule '{rule_name}': bare numbers > 1 are forbidden. "
            f"Pass {{'value': '{bound_spec}', 'unit': 'percent'}} or '{bound_spec}%' explicitly."
        )
    return dec


def compute_exact_percentages(
    values: List[Any],
    decimals: int = 2,
    zero_total_policy: str = "zero",
) -> List[Decimal]:
    """
    Decimal-exact Largest-Remainder Method so rounded percentages are guaranteed
    to sum to exactly `Decimal('100.00')` (when total > 0).
    """
    dec_vals = [to_decimal(v, missing_policy="zero") for v in values]
    total = sum(dec_vals, Decimal("0"))
    q_exp = Decimal("1") if decimals <= 0 else Decimal("1." + ("0" * decimals))
    if total == Decimal("0"):
        if zero_total_policy == "raise":
            raise ZeroDivisionError("Cannot compute exact percentages when sum(values) == 0")
        return [Decimal("0").quantize(q_exp) for _ in dec_vals]

    scale = Decimal(10) ** decimals
    target_int = int(Decimal(100) * scale)
    exact_scaled = [(v * Decimal(target_int)) / total for v in dec_vals]
    floored = [int(x // Decimal("1")) for x in exact_scaled]
    remainders = [(exact_scaled[i] - Decimal(floored[i]), i) for i in range(len(dec_vals))]
    remainders.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    diff = target_int - sum(floored)
    for k in range(diff):
        floored[remainders[k][1]] += 1
    return [(Decimal(x) / scale).quantize(q_exp) for x in floored]


def format_decimal_value(val: Union[Decimal, int, float], decimals: Optional[int] = None) -> Union[int, Decimal]:
    """Return `int` when value is an exact integer and `decimals == 0`, else quantized `Decimal`."""
    d = to_decimal(val)
    if decimals is not None:
        d = quantize_decimal(d, decimals=decimals)
    if d == d.to_integral_value() and (decimals == 0 or (decimals is None and "." not in str(val))):
        return int(d)
    return d


def build_ssot_master_data(
    records: List[Dict[str, Any]],
    numeric_fields: List[str],
    part_sum_rules: Optional[List[Tuple[str, List[str]]]] = None,
    group_by_keys: Optional[List[str]] = None,
    char_Length_caps: Optional[Dict[str, int]] = None,
    min_total_Rules: Optional[Dict[str, Any]] = None,
    ratio_rules: Optional[List[Dict[str, Any]]] = None,
    active_filter_key: str = "counted_in_total",
    field_specs: Optional[Dict[str, Dict[str, Any]]] = None,
    missing_value_policy: str = "zero",
    zero_denominator_policy: str = "raise",
) -> Dict[str, Any]:
    """
    Decimal-based Single-Source-of-Truth (SSOT) mathematical solver (fixes P0-2).

    Parameters:
    - `field_specs`: optional dict `{field_name: {"unit": "yuan"|"wan_yuan"|"hours"|..., "decimals": 2, "rounding": "ROUND_HALF_UP"}}`
    - `missing_value_policy`: `"zero"` | `"raise"` | `"null"`
    - `zero_denominator_policy`: `"raise"` | `"zero"`
    - `ratio_rules`: list of dicts supporting explicit unit bounds:
      `{"name": str, "numerator_group": (g_key, g_val, field), "denominator_field": field,
        "min_ratio": {"value": "0.50", "unit": "fraction"}, "max_ratio": {"value": "70", "unit": "percent"},
        "zero_denominator_policy": "raise"|"zero"}`
    """
    field_specs = field_specs or {}
    active = [r for r in records if r.get(active_filter_key, True)]

    def _field_dec_places(nf: str, sample_vals: Optional[List[Any]] = None) -> int:
        if nf in field_specs and "decimals" in field_specs[nf]:
            return int(field_specs[nf]["decimals"])
        unit = field_specs.get(nf, {}).get("unit")
        if unit and unit in DEFAULT_UNIT_DECIMALS:
            return DEFAULT_UNIT_DECIMALS[unit]
        if sample_vals:
            for v in sample_vals:
                if isinstance(v, (float, Decimal)) and Decimal(str(v)) != Decimal(str(v)).to_integral_value():
                    return 2
                if isinstance(v, str) and "." in v:
                    return len(v.split(".")[1])
        return 0

    def _field_rounding(nf: str) -> str:
        return field_specs.get(nf, {}).get("rounding", "ROUND_HALF_UP")

    def _extract_field_decimal(rec: Dict[str, Any], nf: str) -> Decimal:
        raw = rec.get(nf)
        policy = field_specs.get(nf, {}).get("missing_policy", missing_value_policy)
        target_unit = field_specs.get(nf, {}).get("unit")
        if isinstance(raw, dict) and "value" in raw and target_unit:
            dec = convert_unit(raw, to_unit=target_unit, decimals=field_specs.get(nf, {}).get("decimals"), rounding=_field_rounding(nf))
            return dec
        dec = to_decimal(raw, missing_policy=policy, field_name=nf)
        if dec is None:
            return Decimal("0")
        if nf in field_specs and "decimals" in field_specs[nf]:
            dec = quantize_decimal(dec, decimals=int(field_specs[nf]["decimals"]), rounding=_field_rounding(nf))
        return dec

    # 1. Per-record part-sum & character length assertions using exact Decimal
    for idx, rec in enumerate(records):
        rec_label = rec.get("name") or rec.get("title") or rec.get("id") or f"record[{idx}]"
        for total_key, part_keys in (part_sum_rules or []):
            dec_places = max(
                [_field_dec_places(total_key, [rec.get(total_key)])]
                + [_field_dec_places(k, [rec.get(k)]) for k in part_keys]
            )
            rounding_mode = _field_rounding(total_key)
            expected = quantize_decimal(
                sum((_extract_field_decimal(rec, k) for k in part_keys), Decimal("0")),
                decimals=dec_places,
                rounding=rounding_mode,
            )
            actual = quantize_decimal(
                _extract_field_decimal(rec, total_key),
                decimals=dec_places,
                rounding=rounding_mode,
            )
            if actual != expected:
                part_values = {
                    key: str(_extract_field_decimal(rec, key)) for key in part_keys
                }
                locations: List[str] = []
                for key in list(part_keys) + [total_key]:
                    where = rec.get(f"{key}_location") or rec.get("location") or rec.get("location_id")
                    locations.append(f"{key}@{where}" if where else f"{key}@{rec_label}")
                raise SSOTValidationError(
                    f"Part-sum mismatch in {rec_label}: {total_key}={actual} != sum({part_keys})={expected}",
                    code="SSOT_PART_SUM_MISMATCH",
                    metric=total_key,
                    locations=locations,
                    values={
                        "actual": str(actual),
                        "expected": str(expected),
                        **part_values,
                    },
                )
        for field_name, max_chars in (char_Length_caps or {}).items():
            val_str = str(rec.get(field_name, "") or "")
            if val_str and len(val_str) > max_chars:
                where = rec.get(f"{field_name}_location") or rec.get("location") or rec.get("location_id")
                raise SSOTValidationError(
                    f"Field '{field_name}' too long ({len(val_str)} > {max_chars} chars) in {rec_label}",
                    code="SSOT_FIELD_TOO_LONG",
                    metric=field_name,
                    locations=[where or rec_label],
                    values={"length": len(val_str), "max_length": max_chars},
                )

    # 2. Aggregation with exact Decimal
    def _agg(sub_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        res: Dict[str, Any] = {"count": len(sub_list)}
        for nf in numeric_fields:
            raw_vals = [r.get(nf) for r in sub_list]
            dec_vals = [_extract_field_decimal(r, nf) for r in sub_list]
            dec_places = _field_dec_places(nf, raw_vals)
            total_dec = quantize_decimal(sum(dec_vals, Decimal("0")), decimals=dec_places, rounding=_field_rounding(nf))
            res[nf] = int(total_dec) if dec_places == 0 and total_dec == total_dec.to_integral_value() else total_dec
            res[f"{nf}_decimal"] = total_dec
        return res

    grand = _agg(active)
    grouped: Dict[str, Dict[Any, Dict[str, Any]]] = {}
    for gk in (group_by_keys or []):
        distinct_vals = list(dict.fromkeys(r.get(gk) for r in active if r.get(gk) is not None))
        grouped[gk] = {gv: _agg([r for r in active if r.get(gk) == gv]) for gv in distinct_vals}
        if numeric_fields and distinct_vals:
            primary_nf = numeric_fields[0]
            pcts = compute_exact_percentages(
                [grouped[gk][gv][f"{primary_nf}_decimal"] for gv in distinct_vals],
                decimals=2,
                zero_total_policy="zero",
            )
            for gv, pct in zip(distinct_vals, pcts, strict=True):
                grouped[gk][gv][f"{primary_nf}_pct"] = pct

    # 3. Minimum grand-total rules
    for nf, min_val in (min_total_Rules or {}).items():
        min_dec = to_decimal(min_val, missing_policy="raise", field_name=nf)
        actual_dec = to_decimal(grand.get(f"{nf}_decimal", grand.get(nf, 0)))
        if actual_dec < min_dec:
            raise SSOTValidationError(
                f"Grand total '{nf}' ({actual_dec}) < required minimum {min_dec}",
                code="SSOT_MIN_TOTAL_VIOLATION",
                metric=nf,
                locations=[f"grand.{nf}"],
                values={"actual": str(actual_dec), "minimum": str(min_dec)},
            )

    # 4. Ratio rules with explicit unit bounds and zero-denominator handling
    computed_ratios: Dict[str, Decimal] = {}
    computed_ratios_meta: Dict[str, Dict[str, Any]] = {}
    for rule in (ratio_rules or []):
        r_name = rule["name"]
        g_key, g_val, num_field = rule["numerator_group"]
        den_field = rule["denominator_field"]
        num_val = (
            grand.get(f"{num_field}_decimal", Decimal("0"))
            if g_key == "__grand__"
            else grouped.get(g_key, {}).get(g_val, {}).get(f"{num_field}_decimal", Decimal("0"))
        )
        den_val = grand.get(f"{den_field}_decimal", Decimal("0"))
        z_policy = rule.get("zero_denominator_policy", zero_denominator_policy)
        pct_decimals = int(rule.get("decimals", 2))

        if den_val == Decimal("0"):
            if z_policy == "raise":
                raise ZeroDivisionError(f"Zero denominator '{den_field}' in ratio rule '{r_name}'")
            ratio_fraction = Decimal("0")
        else:
            ratio_fraction = num_val / den_val

        ratio_pct = quantize_decimal(ratio_fraction * Decimal("100"), decimals=pct_decimals)
        computed_ratios[r_name] = ratio_pct
        computed_ratios_meta[r_name] = {
            "fraction": str(quantize_decimal(ratio_fraction, decimals=pct_decimals + 2)),
            "percent": str(ratio_pct),
            "unit": "percent",
        }

        if rule.get("min_ratio") is not None:
            min_r = parse_ratio_bound(rule["min_ratio"], rule_name=r_name)
            if ratio_fraction < min_r:
                raise SSOTValidationError(
                    f"Ratio '{r_name}' ({ratio_fraction:.4f}) < minimum {min_r:.4f}",
                    code="SSOT_RATIO_BELOW_MINIMUM",
                    metric=r_name,
                    locations=[f"ratio.{r_name}"],
                    values={"actual": str(ratio_fraction), "minimum": str(min_r)},
                )
        if rule.get("max_ratio") is not None:
            max_r = parse_ratio_bound(rule["max_ratio"], rule_name=r_name)
            if ratio_fraction > max_r:
                raise SSOTValidationError(
                    f"Ratio '{r_name}' ({ratio_fraction:.4f}) > maximum {max_r:.4f}",
                    code="SSOT_RATIO_ABOVE_MAXIMUM",
                    metric=r_name,
                    locations=[f"ratio.{r_name}"],
                    values={"actual": str(ratio_fraction), "maximum": str(max_r)},
                )

    return {
        "records_all": records,
        "records_active": active,
        "grouped": grouped,
        "grand": grand,
        "ratios_pct": computed_ratios,
        "ratios_meta": computed_ratios_meta,
    }
