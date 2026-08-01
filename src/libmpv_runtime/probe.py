from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Any

from .errors import VerificationError
from .files import read_json, sha256_file, sha256_json, write_json
from .models import Intake, RepositoryConfig, ValidationPlan
from .pcm import verify_gain
from .plan import load_plan, verify_plan
from .process import run
from .workspace import PipelineWorkspace

_SAFE_FILTER = re.compile(r"^[a-z0-9_]+$")


def _write_probe_plan(config: RepositoryConfig, path: Path) -> None:
    lines = ["name\texpression\n"]
    for item in config.contract.probe.filters:
        if (
            not _SAFE_FILTER.fullmatch(item.name)
            or "\t" in item.expression
            or "\n" in item.expression
        ):
            raise VerificationError(f"probe filter is not script-safe: {item.name}")
        lines.append(f"{item.name}\t{item.expression}\n")
    path.write_text("".join(lines), encoding="utf-8", newline="\n")


def _verify_stage(
    config: RepositoryConfig,
    plan: ValidationPlan,
    target: str,
    stage: Path,
) -> dict[str, Any]:
    provenance = read_json(stage / "libmpv-runtime.json")
    if (
        not isinstance(provenance, dict)
        or provenance.get("schemaVersion") != 2
        or provenance.get("artifact") != target
    ):
        raise VerificationError(f"{target} probe stage provenance is invalid")
    raw_intakes = provenance.get("intakes")
    if not isinstance(raw_intakes, list):
        raise VerificationError(f"{target} probe stage has no intakes")
    intakes = [Intake.from_dict(value) for value in raw_intakes]
    expected_sources = set(config.artifact(target).sources)
    if {intake.candidate.source for intake in intakes} != expected_sources:
        raise VerificationError(f"{target} probe stage source set is invalid")
    if any(intake.candidate != plan.candidates.get(intake.candidate.source) for intake in intakes):
        raise VerificationError(f"{target} probe stage belongs to another validation plan")
    return provenance


def _script_command(root: Path, target: str) -> list[str]:
    system = platform.system().lower()
    if target == "windows-x86_64" and system == "windows":
        return ["pwsh", "-NoProfile", "-File", str(root / "scripts/probe/windows.ps1")]
    if target == "android" and system == "windows":
        return [
            "pwsh",
            "-NoProfile",
            "-File",
            str(root / "scripts/probe/android-emulator.ps1"),
        ]
    if target == "android" and system in {"linux", "darwin"}:
        return ["bash", str(root / "scripts/probe/android-emulator.sh")]
    if target == "macos" and system == "darwin":
        return ["bash", str(root / "scripts/probe/darwin.sh")]
    if target == "linux-system" and system == "linux":
        return ["bash", str(root / "scripts/probe/linux-system.sh")]
    raise VerificationError(f"cannot run {target} probe on {platform.system()}")


def _verify_outputs(
    config: RepositoryConfig,
    target: str,
    plan_path: Path,
    output: Path,
    report: Path,
    stage_provenance: dict[str, Any] | None,
) -> Path:
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    files: list[dict[str, object]] = []
    for item in config.contract.probe.filters:
        path = output / f"{item.name}.wav"
        if not path.is_file() or path.stat().st_size <= 44:
            raise VerificationError(f"probe output is missing or empty: {item.name}")
        files.append(
            {
                "name": item.name,
                "expression": item.expression,
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    observed = verify_gain(
        output / "input.wav",
        output / "volume-http.wav",
        expected_db=config.contract.probe.expected_gain_db,
        tolerance_db=config.contract.probe.gain_tolerance_db,
    )
    architectures = (
        ["system"]
        if target == "linux-system"
        else list(config.artifact(target).behavior_architectures)
    )
    mode = "native" if target == "linux-system" else config.artifact(target).behavior_mode
    write_json(
        report,
        {
            "schemaVersion": 1,
            "kind": "behavior",
            "target": target,
            "mode": mode,
            "referenceTarget": None,
            "planSha256": sha256_file(plan_path),
            "architectures": architectures,
            "filters": files,
            "expectedGainDb": config.contract.probe.expected_gain_db,
            "gainToleranceDb": config.contract.probe.gain_tolerance_db,
            "measuredGainDb": observed,
            "httpRange": True,
            "filterAfterLoad": True,
            "stageProvenanceSha256": (
                sha256_json(stage_provenance) if stage_provenance is not None else None
            ),
        },
    )
    return report


def run_probe(
    config: RepositoryConfig,
    target: str,
    plan_path: Path,
    stage: Path | None,
    work: Path,
    report: Path,
) -> Path:
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    if target != "linux-system" and (stage is None or not stage.is_dir()):
        raise VerificationError(f"probe stage does not exist: {stage}")
    if target == "linux-system":
        stage_provenance = None
    else:
        assert stage is not None
        stage_provenance = _verify_stage(config, plan, target, stage)
    workspace = PipelineWorkspace.fresh(config.root, work)
    output = workspace.directory("output")
    binary = workspace.directory("bin")
    probe_plan = workspace.path / "probe-plan.tsv"
    _write_probe_plan(config, probe_plan)
    environment = {
        "LIBMPV_RUNTIME_ROOT": str(config.root),
        "LIBMPV_RUNTIME_STAGE": str(stage or ""),
        "LIBMPV_RUNTIME_WORK": str(workspace.path),
        "LIBMPV_RUNTIME_OUTPUT": str(output),
        "LIBMPV_RUNTIME_BIN": str(binary),
        "LIBMPV_RUNTIME_PROBE_PLAN": str(probe_plan),
        "LIBMPV_RUNTIME_HTTP_FILTER": config.contract.probe.http_after_load_filter,
        "LIBMPV_RUNTIME_ANDROID_MIN_SDK": str(plan.toolchain.android_min_sdk),
    }
    run(_script_command(config.root, target), cwd=config.root, env=environment)
    return _verify_outputs(
        config,
        target,
        plan_path,
        output,
        report,
        stage_provenance,
    )
