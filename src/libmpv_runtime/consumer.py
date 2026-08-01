from __future__ import annotations

import platform
from pathlib import Path

from .errors import VerificationError
from .models import RepositoryConfig
from .plan import load_plan, verify_plan
from .process import capture, find_json_object, run
from .workspace import PipelineWorkspace


def _flutter_version(root: Path) -> str:
    value = find_json_object(
        capture(["flutter", "--version", "--machine"], cwd=root),
        required_key="frameworkVersion",
    )
    if value is None:
        raise VerificationError("flutter --version returned no machine-readable version")
    version = value.get("frameworkVersion")
    if not isinstance(version, str) or not version:
        raise VerificationError("Flutter framework version is missing")
    return version


def _command(root: Path, group: str) -> list[str]:
    system = platform.system().lower()
    if group == "windows" and system == "windows":
        return ["pwsh", "-NoProfile", "-File", str(root / "scripts/consumer/windows.ps1")]
    if group == "android" and system == "windows":
        return ["pwsh", "-NoProfile", "-File", str(root / "scripts/consumer/android.ps1")]
    if group == "android" and system in {"linux", "darwin"}:
        return ["bash", str(root / "scripts/consumer/android.sh")]
    if group == "apple" and system == "darwin":
        return ["bash", str(root / "scripts/consumer/darwin.sh")]
    raise VerificationError(f"cannot run {group} consumer on {platform.system()}")


def run_consumer(
    config: RepositoryConfig,
    plan_path: Path,
    group: str,
    artifacts: dict[str, list[Path]],
    work: Path,
    reports: dict[str, Path],
    profile_name: str,
) -> dict[str, Path]:
    plan = load_plan(plan_path)
    verify_plan(config, plan)
    try:
        profile = plan.consumers[profile_name]
    except KeyError as error:
        raise VerificationError(
            f"validation plan has no consumer profile: {profile_name}"
        ) from error
    observed_flutter = _flutter_version(config.root)
    if observed_flutter != plan.toolchain.flutter:
        raise VerificationError(
            f"Flutter version mismatch: expected {plan.toolchain.flutter}, got {observed_flutter}"
        )
    expected_targets = {
        "windows": {"windows-x86_64"},
        "android": {"android"},
        "apple": {"macos", "ios"},
    }
    if group not in expected_targets or set(artifacts) != expected_targets[group]:
        raise VerificationError(f"consumer artifact set is invalid for {group}")
    if set(reports) != expected_targets[group]:
        raise VerificationError(f"consumer report set is invalid for {group}")
    for paths in artifacts.values():
        if not paths or any(not path.is_file() for path in paths):
            raise VerificationError(f"consumer artifact is missing for {group}")
    workspace = PipelineWorkspace.fresh(config.root, work)
    environment = {
        "LIBMPV_RUNTIME_ROOT": str(config.root),
        "LIBMPV_RUNTIME_WORK": str(workspace.path),
        "LIBMPV_RUNTIME_PLAN": str(plan_path.resolve()),
        "LIBMPV_RUNTIME_PROFILE": profile_name,
        "LIBMPV_RUNTIME_MEDIA_KIT": profile.media_kit,
        "LIBMPV_RUNTIME_MEDIA_KIT_VIDEO": profile.media_kit_video,
    }
    if group == "windows":
        environment["LIBMPV_RUNTIME_ARTIFACT"] = str(artifacts["windows-x86_64"][0])
        environment["LIBMPV_RUNTIME_REPORT"] = str(reports["windows-x86_64"])
    elif group == "android":
        environment["LIBMPV_RUNTIME_ARTIFACT"] = str(artifacts["android"][0])
        environment["LIBMPV_RUNTIME_REPORT"] = str(reports["android"])
    else:
        environment["LIBMPV_RUNTIME_MACOS_ARTIFACTS"] = "\n".join(
            str(path) for path in artifacts["macos"]
        )
        environment["LIBMPV_RUNTIME_IOS_ARTIFACTS"] = "\n".join(
            str(path) for path in artifacts["ios"]
        )
        environment["LIBMPV_RUNTIME_MACOS_REPORT"] = str(reports["macos"])
        environment["LIBMPV_RUNTIME_IOS_REPORT"] = str(reports["ios"])
    run(_command(config.root, group), cwd=config.root, env=environment)
    missing = [target for target, path in reports.items() if not path.is_file()]
    if missing:
        raise VerificationError(f"consumer did not create reports: {', '.join(missing)}")
    return reports
