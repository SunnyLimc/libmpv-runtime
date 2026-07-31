from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import VerificationError
from .files import read_json, write_json


def create_structure_evidence(
    path: Path,
    *,
    target: str,
    filters: tuple[str, ...],
    details: dict[str, Any],
    provenance: Any,
) -> Path:
    write_json(
        path,
        {
            "schemaVersion": 2,
            "target": target,
            "requiredFilters": list(filters),
            "checks": {"structure": True, "behavior": False, "consumer": False},
            "structure": details,
            "behavior": None,
            "consumer": None,
            "provenance": provenance,
        },
    )
    return path


def _load(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schemaVersion") != 2:
        raise VerificationError(f"invalid evidence schema: {path}")
    checks = value.get("checks")
    if not isinstance(checks, dict):
        raise VerificationError(f"evidence checks are missing: {path}")
    return value


def record_behavior(
    path: Path,
    *,
    filters: list[str],
    measured_gain_db: float,
    mode: str,
    reference_target: str | None,
) -> Path:
    value = _load(path)
    required = value.get("requiredFilters")
    if not isinstance(required, list) or set(required) - set(filters):
        raise VerificationError("behavior probe did not exercise every required filter")
    if mode not in {"native", "source-equivalent"}:
        raise VerificationError(f"invalid behavior mode: {mode}")
    target = value.get("target")
    if mode == "native" and reference_target is not None:
        raise VerificationError("native behavior cannot reference another target")
    if mode == "source-equivalent" and (not reference_target or reference_target == target):
        raise VerificationError("source-equivalent behavior needs a different target")
    checks = value["checks"]
    assert isinstance(checks, dict)
    checks["behavior"] = True
    value["behavior"] = {
        "mode": mode,
        "referenceTarget": reference_target,
        "filters": sorted(filters),
        "measuredGainDb": measured_gain_db,
    }
    write_json(path, value)
    return path


def record_consumer(path: Path, *, details: dict[str, Any]) -> Path:
    value = _load(path)
    checks = value["checks"]
    assert isinstance(checks, dict)
    checks["consumer"] = True
    value["consumer"] = details
    write_json(path, value)
    return path


def load_releasable_evidence(path: Path, target: str, filters: tuple[str, ...]) -> dict[str, Any]:
    value = _load(path)
    if value.get("target") != target:
        raise VerificationError(f"evidence target mismatch: {path}")
    if value.get("requiredFilters") != list(filters):
        raise VerificationError(f"evidence contract mismatch: {path}")
    checks = value["checks"]
    assert isinstance(checks, dict)
    failed = [
        name for name in ("structure", "behavior", "consumer") if checks.get(name) is not True
    ]
    if failed:
        raise VerificationError(f"evidence is not releasable; failed: {', '.join(failed)}")
    return value
