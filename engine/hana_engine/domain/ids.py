"""ULID generation.

ULIDs are used instead of UUIDv4 for every primary key in the knowledge base.
They are 26 characters of Crockford base32, lexicographically sortable by
creation time, which keeps SQLite's B-tree indexes from fragmenting when tens of
thousands of entities are inserted during a single analysis run.
"""

from __future__ import annotations

import os
import time

# Crockford base32: no I, L, O or U, so IDs cannot be misread out loud.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ENCODED_TIME_LENGTH = 10
_ENCODED_RANDOM_LENGTH = 16
ULID_LENGTH = _ENCODED_TIME_LENGTH + _ENCODED_RANDOM_LENGTH


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid(timestamp_ms: int | None = None) -> str:
    """Return a new ULID string.

    ``timestamp_ms`` is only meant for tests that need deterministic ordering.
    """
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    randomness = int.from_bytes(os.urandom(10), "big")
    return _encode(timestamp_ms, _ENCODED_TIME_LENGTH) + _encode(
        randomness, _ENCODED_RANDOM_LENGTH
    )


def is_ulid(value: str) -> bool:
    """Return True when ``value`` looks like a ULID produced by :func:`new_ulid`."""
    if len(value) != ULID_LENGTH:
        return False
    return all(char in _ALPHABET for char in value)


def timestamp_of(ulid: str) -> int:
    """Extract the millisecond timestamp encoded in a ULID."""
    if not is_ulid(ulid):
        raise ValueError(f"not a ULID: {ulid!r}")
    value = 0
    for char in ulid[:_ENCODED_TIME_LENGTH]:
        value = (value << 5) | _ALPHABET.index(char)
    return value
