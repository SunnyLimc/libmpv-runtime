from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import VerificationError
from .files import read_json, write_json


def write_evidence(
    path: Path,
    *,
    target: str,
    filters: list[str],
    structure: bool,
    behavior: bool,
    consumer: bool,
    details: dict[str, Any] | None = None,
) -> None:
    write_json(
        path,
        {
            "schemaVersion": 1,
            "target": target,
            "filters": sorted(filters),
            "checks": {
                "structure": structure,
                "behavior": behavior,
                "consumer": consumer,
            },
            "details": details or {},
        },
    )


def load_evidence(path: Path, target: str, required_filters: tuple[str, ...]) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise VerificationError(f"invalid evidence schema: {path}")
    if value.get("target") != target:
        raise VerificationError(f"evidence target mismatch in {path}")
    filters = value.get("filters")
    if not isinstance(filters, list) or not all(isinstance(item, str) for item in filters):
        raise VerificationError(f"invalid filters in {path}")
    missing = set(required_filters) - set(filters)
    if missing:
        raise VerificationError(f"evidence is missing filters: {', '.join(sorted(missing))}")
    checks = value.get("checks")
    if not isinstance(checks, dict):
        raise VerificationError(f"invalid checks in {path}")
    failed = [
        name for name in ("structure", "behavior", "consumer") if checks.get(name) is not True
    ]
    if failed:
        raise VerificationError(f"evidence checks failed: {', '.join(failed)}")
    return value
