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
    behavior_mode: str = "native",
    behavior_reference_target: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    if behavior_mode not in {"native", "source-equivalent"}:
        raise ValueError(f"unsupported behavior evidence mode: {behavior_mode}")
    if behavior_mode == "source-equivalent":
        if not behavior_reference_target or behavior_reference_target == target:
            raise ValueError(
                "source-equivalent behavior evidence needs a different reference target"
            )
    elif behavior_reference_target is not None:
        raise ValueError("native behavior evidence cannot name a reference target")
    evidence_details = dict(details or {})
    behavior_details: dict[str, str] = {"mode": behavior_mode}
    if behavior_reference_target is not None:
        behavior_details["referenceTarget"] = behavior_reference_target
    evidence_details["behavior"] = behavior_details
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
            "details": evidence_details,
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
    details = value.get("details")
    behavior_details = details.get("behavior") if isinstance(details, dict) else None
    if not isinstance(behavior_details, dict):
        raise VerificationError(f"behavior provenance is missing from {path}")
    mode = behavior_details.get("mode")
    reference = behavior_details.get("referenceTarget")
    if mode == "native":
        if reference is not None:
            raise VerificationError(f"native behavior evidence has a reference target in {path}")
    elif mode == "source-equivalent":
        if not isinstance(reference, str) or not reference or reference == target:
            raise VerificationError(f"invalid source-equivalent reference target in {path}")
    else:
        raise VerificationError(f"invalid behavior provenance mode in {path}")
    return value
