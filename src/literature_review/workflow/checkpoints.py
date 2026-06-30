from __future__ import annotations

import hashlib
import json
from typing import Any


def fingerprint_inputs(data: Any) -> str:
    canonical_json = json.dumps(
        data,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


__all__ = ["fingerprint_inputs"]
