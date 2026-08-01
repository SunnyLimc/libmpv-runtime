from __future__ import annotations

from pathlib import Path

import pytest

from libmpv_runtime.cli import main
from libmpv_runtime.files import read_json, sha256_file, write_json
from libmpv_runtime.models import RepositoryConfig


def _args(repository_root: Path, *values: str) -> list[str]:
    return ["--root", str(repository_root), *values]


def test_cli_exposes_contract_sources_and_plan_metadata(
    repository_root: Path,
    validation_plan: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(_args(repository_root, "contract", "validate")) == 0
    assert "schema 3" in capsys.readouterr().out
    assert main(_args(repository_root, "contract", "list")) == 0
    assert "windows-x86_64" in capsys.readouterr().out
    assert main(_args(repository_root, "source", "list")) == 0
    assert "zhongfly/mpv-winbuild" in capsys.readouterr().out
    assert main(_args(repository_root, "plan", "verify", "--path", str(validation_plan))) == 0
    output = tmp_path / "github-output"
    assert (
        main(
            _args(
                repository_root,
                "plan",
                "export",
                "--path",
                str(validation_plan),
                "--github-output",
                str(output),
            )
        )
        == 0
    )
    exported = output.read_text(encoding="utf-8")
    assert f"plan-sha256={sha256_file(validation_plan)}" in exported
    assert "flutter-version=3.44.7" in exported
    assert "python-version=3.12" in exported
    assert "android-emulator-api=35" in exported


def test_cli_packages_stage_and_generates_selected_dropin(
    repository_root: Path, tmp_path: Path
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "libmpv-runtime.json").write_text("{}\n", encoding="utf-8")
    dist = tmp_path / "dist"
    assert (
        main(
            _args(
                repository_root,
                "artifact",
                "package",
                "--artifact",
                "windows-x86_64",
                "--stage",
                str(stage),
                "--output",
                str(dist),
            )
        )
        == 0
    )
    bundle = dist / "libmpv-runtime-windows-x86_64.zip"
    assert bundle.is_file()
    candidate = tmp_path / "candidate.json"
    assert (
        main(
            _args(
                repository_root,
                "packages",
                "candidate-manifest",
                "--id",
                "runtime-20000101.1",
                "--artifact",
                f"windows-x86_64={bundle}",
                "--base-url",
                "http://127.0.0.1:8000",
                "--output",
                str(candidate),
            )
        )
        == 0
    )
    packages = tmp_path / "packages"
    assert (
        main(
            _args(
                repository_root,
                "packages",
                "generate",
                "--promotion",
                str(candidate),
                "--platform",
                "windows",
                "--output",
                str(packages),
            )
        )
        == 0
    )
    assert (packages / "media_kit_libs_windows_video/windows/CMakeLists.txt").is_file()


def test_cli_derives_source_equivalent_behavior(
    config: RepositoryConfig,
    repository_root: Path,
    validation_plan: Path,
    tmp_path: Path,
) -> None:
    reference = tmp_path / "macos-behavior.json"
    write_json(
        reference,
        {
            "schemaVersion": 1,
            "kind": "behavior",
            "target": "macos",
            "mode": "native",
            "planSha256": sha256_file(validation_plan),
            "architectures": list(config.artifact("macos").behavior_architectures),
            "filters": [],
        },
    )
    output = tmp_path / "ios-behavior.json"
    assert (
        main(
            _args(
                repository_root,
                "behavior",
                "derive",
                "--plan",
                str(validation_plan),
                "--target",
                "ios",
                "--reference-report",
                str(reference),
                "--output",
                str(output),
            )
        )
        == 0
    )
    assert read_json(output)["referenceTarget"] == "macos"


def test_cli_reports_invalid_target_without_traceback(repository_root: Path) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            _args(
                repository_root,
                "artifact",
                "package",
                "--artifact",
                "unknown",
                "--stage",
                "missing",
                "--output",
                "missing",
            )
        )
    assert error.value.code == 2
