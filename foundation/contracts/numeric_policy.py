"""Versioned decimal policy shared by every declared computation."""

from decimal import ROUND_HALF_EVEN, Decimal

from .canonical import canonical_decimal

NUMERIC_POLICY = {
    "decimal_precision": 28,
    "output_scale": 6,
    "rounding": "ROUND_HALF_EVEN",
    "version": "mydjangocs.numeric-policy/1",
}


def render_result_decimal(value: Decimal) -> str:
    """Quantize and canonically render a result under numeric policy v1."""

    quantum = Decimal(1).scaleb(-NUMERIC_POLICY["output_scale"])
    return canonical_decimal(value.quantize(quantum, rounding=ROUND_HALF_EVEN))
