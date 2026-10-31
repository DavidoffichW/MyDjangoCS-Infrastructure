"""Portable little-endian observation binary format (not a native ABI)."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .canonical import canonical_decimal
from .errors import IntegrityError, SchemaError
from .memory import MemoryArena
from .schema import Observation

MAGIC = b"MDSOBS\x00\x00"
FORMAT_VERSION = 1
MAX_RECORDS = 10_000
HEADER = struct.Struct("<8sHHII32s")
RECORD = struct.Struct("<16sqqBB6x")
MISSING_SENTINEL = -(2**63)
QUALITY_CODES = {"observed": 1, "anomalous": 2, "missing": 3}
QUALITY_NAMES = {value: key for key, value in QUALITY_CODES.items()}
VALUE_SCALE = Decimal("1000000")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class BinaryObservation:
    sensor_id: str
    timestamp: str
    value: str | None
    missing: bool
    quality: str


def _timestamp_millis(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.microsecond % 1000:
        raise SchemaError("Binary timestamps support millisecond precision.")
    elapsed = parsed.astimezone(UTC) - EPOCH
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )


def encode_observations(
    observations: list[Observation] | tuple[Observation, ...],
    *,
    arena: MemoryArena | None = None,
) -> bytes:
    if not observations or len(observations) > MAX_RECORDS:
        raise SchemaError(f"Binary format accepts 1 to {MAX_RECORDS} records.")
    payload = bytearray()
    for item in sorted(observations, key=lambda row: (row.sensor_id, row.timestamp)):
        try:
            sensor = item.sensor_id.encode("ascii", "strict")
        except UnicodeEncodeError as exc:
            raise SchemaError("Binary sensor identifiers must be ASCII.") from exc
        if len(sensor) > 15:
            raise SchemaError("Binary sensor identifiers are limited to 15 ASCII bytes.")
        if item.value is None:
            scaled = MISSING_SENTINEL
        else:
            decimal_value = Decimal(item.value) * VALUE_SCALE
            if decimal_value != decimal_value.to_integral_value():
                raise SchemaError("Binary values support at most six fractional places.")
            scaled = int(decimal_value)
            if scaled == MISSING_SENTINEL or not -(2**63) <= scaled <= 2**63 - 1:
                raise SchemaError("Binary value exceeds signed 64-bit range.")
        payload.extend(
            RECORD.pack(
                sensor.ljust(16, b"\x00"),
                _timestamp_millis(item.timestamp),
                scaled,
                int(item.missing),
                QUALITY_CODES[item.quality],
            )
        )
    checksum = hashlib.sha256(payload).digest()
    header = HEADER.pack(MAGIC, FORMAT_VERSION, 0, len(observations), len(payload), checksum)
    output = header + payload
    owned_arena = arena or MemoryArena(max_bytes=len(output))
    handle = owned_arena.allocate("u8", len(output))
    try:
        with owned_arena.exclusive(handle) as writer:
            writer.write(0, output)
        owned_arena.seal(handle)
        with owned_arena.shared(handle) as reader:
            return reader.read()
    finally:
        owned_arena.release(handle)


def decode_observations(raw: bytes) -> tuple[BinaryObservation, ...]:
    if len(raw) < HEADER.size:
        raise SchemaError("Binary payload is shorter than its header.")
    magic, version, flags, count, payload_length, checksum = HEADER.unpack_from(raw)
    if magic != MAGIC or version != FORMAT_VERSION or flags != 0:
        raise SchemaError("Unsupported binary magic, version or flags.")
    if not 1 <= count <= MAX_RECORDS:
        raise SchemaError("Binary record count is outside the supported limit.")
    if payload_length != count * RECORD.size or len(raw) != HEADER.size + payload_length:
        raise SchemaError("Binary payload length is inconsistent with its record count.")
    payload = raw[HEADER.size:]
    if hashlib.sha256(payload).digest() != checksum:
        raise IntegrityError("Binary payload checksum mismatch.")
    records = []
    for offset in range(0, len(payload), RECORD.size):
        sensor_raw, milliseconds, scaled, missing_flag, quality_code = RECORD.unpack_from(
            payload, offset
        )
        if missing_flag not in {0, 1} or quality_code not in QUALITY_NAMES:
            raise SchemaError("Binary record contains an unknown flag or quality code.")
        try:
            sensor_id = sensor_raw.rstrip(b"\x00").decode("ascii", "strict")
        except UnicodeDecodeError as exc:
            raise SchemaError("Binary sensor identifier is not ASCII.") from exc
        if not sensor_id:
            raise SchemaError("Binary sensor identifier must not be empty.")
        missing = bool(missing_flag)
        if missing != (scaled == MISSING_SENTINEL):
            raise SchemaError("Binary missing flag and sentinel disagree.")
        timestamp = (EPOCH + timedelta(milliseconds=milliseconds)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        value = None if missing else canonical_decimal(Decimal(scaled) / VALUE_SCALE)
        quality = QUALITY_NAMES[quality_code]
        if missing and quality != "missing":
            raise SchemaError("Binary missing record has a non-missing quality code.")
        records.append(
            BinaryObservation(
                sensor_id=sensor_id,
                timestamp=timestamp,
                value=value,
                missing=missing,
                quality=quality,
            )
        )
    return tuple(records)
