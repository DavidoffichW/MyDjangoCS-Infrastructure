"""Bounded correlation identifiers safe for response headers."""

import re
import uuid

_CORRELATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


def correlation_id(supplied: str) -> str:
    return supplied if _CORRELATION_ID.fullmatch(supplied) else uuid.uuid4().hex
