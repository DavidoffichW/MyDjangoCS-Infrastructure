"""Restricted canonical JSON and scientific scalar policies.

The profile follows the useful constraints of RFC 8785 while deliberately
excluding binary floating-point values. Scientific decimals and timestamps are
schema-defined strings before canonicalization.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import CanonicalizationError

SCHEMA_VERSION = "mydjangocs.canonical-json/1"
MIN_INTEGER = -(2**63)
MAX_INTEGER = 2**63 - 1


def _validate_string(value: str) -> None:
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError("Strings must not contain unpaired surrogates.") from exc


def _utf16_sort_key(value: str) -> bytes:
    _validate_string(value)
    return value.encode("utf-16-be")


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not MIN_INTEGER <= value <= MAX_INTEGER:
            raise CanonicalizationError("Integers must fit the signed 64-bit contract.")
        return value
    if isinstance(value, float | Decimal):
        raise CanonicalizationError(
            "Binary floats and Decimal objects are not canonical JSON values; "
            "encode schema-defined decimals as canonical strings."
        )
    if isinstance(value, str):
        _validate_string(value)
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalizationError("Canonical object keys must be strings.")
        return {
            key: _normalize(value[key])
            for key in sorted(value, key=_utf16_sort_key)
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | memoryview):
        return [_normalize(item) for item in value]
    raise CanonicalizationError(f"Unsupported canonical value type: {type(value).__name__}.")


def canonical_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON for the restricted canonical profile."""
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _reject_float(raw: str) -> None:
    raise CanonicalizationError(f"JSON floating-point value {raw!r} is not permitted.")


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalizationError(f"Duplicate JSON key {key!r} is not permitted.")
        result[key] = value
    return result


def parse_json_strict(raw: str | bytes) -> Any:
    """Parse JSON while rejecting duplicate keys, floats and invalid Unicode."""
    try:
        text = raw.decode("utf-8", "strict") if isinstance(raw, bytes) else raw
        value = json.loads(
            text,
            object_pairs_hook=_pairs_without_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalizationError("Input is not valid restricted UTF-8 JSON.") from exc
    _normalize(value)
    return value


def canonical_decimal(
    value: Decimal | str,
    *,
    max_abs: Decimal = Decimal("1000000000000"),
    max_places: int = 12,
) -> str:
    """Normalize a finite bounded decimal; negative zero is canonicalized to zero."""
    try:
        number = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalizationError("Value is not a valid decimal.") from exc
    if not number.is_finite():
        raise CanonicalizationError("NaN and infinite decimals are not permitted.")
    if abs(number) > max_abs:
        raise CanonicalizationError(f"Decimal magnitude exceeds {max_abs}.")
    places = max(0, -number.as_tuple().exponent)
    if places > max_places:
        raise CanonicalizationError(f"Decimal exceeds {max_places} fractional places.")
    if number == 0:
        return "0"
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def normalize_timestamp(value: str) -> str:
    """Normalize an offset-aware ISO-8601 timestamp to UTC with a ``Z`` suffix."""
    if not isinstance(value, str):
        raise CanonicalizationError("Timestamp must be an ISO-8601 string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanonicalizationError("Timestamp is not valid ISO-8601.") from exc
    if parsed.tzinfo is None:
        raise CanonicalizationError("Timestamp must include an explicit UTC offset.")
    utc_value = parsed.astimezone(UTC)
    rendered = utc_value.strftime("%Y-%m-%dT%H:%M:%S")
    if utc_value.microsecond:
        rendered += f".{utc_value.microsecond:06d}".rstrip("0")
    return f"{rendered}Z"
