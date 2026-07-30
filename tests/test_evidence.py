from __future__ import annotations

from pathlib import Path

import pytest

from libmpv_runtime.errors import VerificationError
from libmpv_runtime.evidence import load_evidence, write_evidence
from libmpv_runtime.files import read_json, write_json


def test_native_evidence_records_explicit_provenance(tmp_path: Path) -> None:
    path = tmp_path / "native.json"
    write_evidence(
        path,
        target="linux-x86_64",
        filters=["volume"],
        structure=True,
        behavior=True,
        consumer=True,
    )
    assert read_json(path)["details"]["behavior"] == {"mode": "native"}


def test_source_equivalent_evidence_records_reference_target(tmp_path: Path) -> None:
    path = tmp_path / "equivalent.json"
    write_evidence(
        path,
        target="android-arm64-v8a",
        filters=["volume"],
        structure=True,
        behavior=True,
        consumer=True,
        behavior_mode="source-equivalent",
        behavior_reference_target="android-x86_64",
    )
    assert read_json(path)["details"]["behavior"] == {
        "mode": "source-equivalent",
        "referenceTarget": "android-x86_64",
    }


def test_source_equivalent_evidence_rejects_self_reference(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="different reference target"):
        write_evidence(
            tmp_path / "invalid.json",
            target="android-x86_64",
            filters=["volume"],
            structure=True,
            behavior=True,
            consumer=True,
            behavior_mode="source-equivalent",
            behavior_reference_target="android-x86_64",
        )


def test_loading_evidence_rejects_missing_provenance(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    write_json(
        path,
        {
            "schemaVersion": 1,
            "target": "linux-x86_64",
            "filters": ["volume"],
            "checks": {"structure": True, "behavior": True, "consumer": True},
            "details": {},
        },
    )
    with pytest.raises(VerificationError, match="behavior provenance is missing"):
        load_evidence(path, "linux-x86_64", ("volume",))


def test_loading_evidence_rejects_unknown_provenance_mode(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    write_json(
        path,
        {
            "schemaVersion": 1,
            "target": "linux-x86_64",
            "filters": ["volume"],
            "checks": {"structure": True, "behavior": True, "consumer": True},
            "details": {"behavior": {"mode": "borrowed"}},
        },
    )
    with pytest.raises(VerificationError, match="invalid behavior provenance mode"):
        load_evidence(path, "linux-x86_64", ("volume",))
