"""Canonical JSON shared with the TypeScript Creator runtime.

The format mirrors ``agent_runtime/shared/canonical.ts``: recursively sorted
object keys, compact JSON and UTF-8 content hashing. Creator event idempotency
must compare content, never Python object identity or PostgreSQL JSONB text.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any


def canonical_json(value: Any) -> str:
    if value is None or isinstance(value, (str, bool, int)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON does not allow non-finite numbers")
        if value == 0:
            return "0"
        rendered = repr(value).lower()
        if "e" not in rendered:
            if rendered.endswith(".0"):
                return rendered[:-2]
            return rendered
        mantissa, exponent_text = rendered.split("e", 1)
        exponent = int(exponent_text)
        if 1e-6 <= abs(value) < 1e21:
            return format(Decimal(rendered), "f")
        if mantissa.endswith(".0"):
            mantissa = mantissa[:-2]
        sign = "+" if exponent >= 0 else "-"
        return f"{mantissa}e{sign}{abs(exponent)}"
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            + ":"
            + canonical_json(value[key])
            for key in sorted(value)
        ) + "}"
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def content_hash(value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
