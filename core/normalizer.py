"""Key normalization (F-07). STUB - real implementation is task A5."""
from __future__ import annotations

KEY_TYPES = ("transaction_id", "email", "url", "ip", "phone", "other")
MAX_LEN = 2048


def normalize(value: str, key_type: str) -> str:
    """Return the canonical key. Raises ValueError for empty / > 2048 chars input."""
    raise NotImplementedError("A5")
