from __future__ import annotations

import json
import re
from pathlib import Path


def test_media_kit_contract_matches_target_load_names(
    repository_root: Path,
    config: object,
) -> None:
    contract = json.loads((repository_root / "contracts" / "media-kit.json").read_text())
    by_platform = contract["platforms"]
    assert by_platform["android"]["library"] == config.target("android-arm64-v8a").load_name
    assert by_platform["windows"]["library"] == config.target("windows-x86_64").load_name
    assert config.target("linux-x86_64").load_name in by_platform["linux"]["candidates"]
    assert by_platform["macos"]["library"] == config.target("macos-universal").load_name
    assert by_platform["ios"]["library"] == config.target("ios-universal").load_name
    assert "mpv_lavc_set_java_vm" in by_platform["android"]["requiredSymbols"]


def test_workflow_actions_are_pinned_to_full_commits(repository_root: Path) -> None:
    pattern = re.compile(r"^\s*uses:\s+[^@\s]+@([^\s#]+)", re.MULTILINE)
    workflows = sorted((repository_root / ".github" / "workflows").glob("*.yml"))
    assert workflows
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        references = pattern.findall(text)
        assert references, workflow
        assert all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references)


def test_windows_container_is_digest_pinned(repository_root: Path) -> None:
    workflow = (repository_root / ".github" / "workflows" / "runtime.yml").read_text()
    assert re.search(r"ghcr\.io/[^@\s]+@sha256:[0-9a-f]{64}", workflow)
    assert "ghcr.io/shinchiro/archlinux:latest" not in workflow


def test_workflow_toolchains_match_lock(repository_root: Path, config: object) -> None:
    workflow = (repository_root / ".github" / "workflows" / "runtime.yml").read_text()
    for key in (
        "windows_container",
        "meson",
        "linux_image",
        "linux_arm_image",
        "apple_image",
        "xcode_path",
    ):
        assert str(config.lock.toolchains[key]) in workflow


def test_darwin_builder_uses_path_flake_for_ignored_worktree(
    repository_root: Path,
) -> None:
    patch = (
        repository_root / "patches" / "darwin" / "0001-enable-lgpl-dsp-filters.patch"
    ).read_text()
    assert "+\t\t$(if $(TARGET),path:.#$(TARGET),path:.)" in patch


def test_platform_patches_enforce_lgpl_and_required_filters(repository_root: Path) -> None:
    filters = (
        "loudnorm",
        "dynaudnorm",
        "acompressor",
        "alimiter",
        "volume",
        "aresample",
        "ebur128",
        "astats",
    )
    for platform in ("android", "darwin", "windows"):
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((repository_root / "patches" / platform).glob("*.patch"))
        )
        assert "disable-gpl" in text or "-Dgpl=false" in text
        for filter_name in filters:
            assert filter_name in text
    linux = (repository_root / "patches" / "linux" / "0001-lgpl-only.patch").read_text()
    assert "--disable-gpl --disable-nonfree --enable-version3" in linux


def test_patches_do_not_add_moving_source_references(repository_root: Path) -> None:
    moving = re.compile(
        r"(?:GIT_TAG\s+(?:main|master|develop|release/)|"
        r"raw/(?:main|master|develop)|"
        r"archive/(?:refs/heads/)?(?:main|master|develop))"
    )
    for patch in sorted((repository_root / "patches").rglob("*.patch")):
        added_lines = "\n".join(
            line[1:]
            for line in patch.read_text(encoding="utf-8").splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        assert moving.search(added_lines) is None, patch


def test_behavior_probe_uses_decoded_pcm_output(repository_root: Path) -> None:
    probe = (repository_root / "probes" / "native" / "mpv_dsp_probe.c").read_text()
    assert '"ao", "pcm"' in probe
    assert '"ao-pcm-file", output_path' in probe
    assert '"af", audio_filter' in probe
    common = (repository_root / "scripts" / "build" / "common.sh").read_text()
    assert "verify-gain" in common
    assert "--expected-db -6.0206" in common


def test_windows_build_bootstraps_toolchain_before_mpv(repository_root: Path) -> None:
    script = (repository_root / "scripts" / "build" / "windows.sh").read_text()
    toolchain = 'cmake --build "$build_dir" --target gcc --parallel'
    runtime = 'cmake --build "$build_dir" --target mpv --parallel'
    assert "-DCOMPILER_TOOLCHAIN=gcc" in script
    assert script.index(toolchain) < script.index(runtime)


def test_builds_locate_ffmpeg_config_by_filter_declarations(
    repository_root: Path,
) -> None:
    common = (repository_root / "scripts" / "build" / "common.sh").read_text()
    assert "find_ffmpeg_config_header()" in common
    assert "CONFIG_LOUDNORM_FILTER" in common
    for platform in ("linux", "windows"):
        script = (repository_root / "scripts" / "build" / f"{platform}.sh").read_text()
        assert "find_ffmpeg_config_header" in script
        assert "ffbuild/config.h" not in script


def test_android_verifies_16k_elf_load_alignment(repository_root: Path) -> None:
    script = (repository_root / "scripts" / "build" / "android.sh").read_text()
    common = (repository_root / "scripts" / "build" / "common.sh").read_text()
    assert "require_elf_load_alignment()" in common
    assert 'require_elf_load_alignment "$readelf" "$library" 16384' in script
