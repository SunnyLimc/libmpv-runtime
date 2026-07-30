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
    assert "libc++_shared.so" in by_platform["android"]["runtimeDependencies"]


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
    quality = (repository_root / ".github" / "workflows" / "quality.yml").read_text()
    assert f"actionlint@v{config.lock.toolchains['actionlint']}" in quality


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
    patch = (
        repository_root / "patches" / "windows" / "0001-modern-lgpl-dsp-runtime.patch"
    ).read_text()
    toolchain = 'cmake --build "$build_dir" --target gcc --parallel 1'
    runtime = 'cmake --build "$build_dir" --target mpv --parallel'
    assert "-DCOMPILER_TOOLCHAIN=gcc" in script
    assert script.index(toolchain) < script.index(runtime)
    assert 'VERSION_GREATER_EQUAL "1.3.0"' in patch
    assert "+    URL https://ftp.gnu.org/gnu/gcc/gcc-14.2.0/gcc-14.2.0.tar.xz" in patch
    assert "+    URL https://mirrorservice.org/sites/sourceware.org/pub/gcc/snapshots" not in patch
    assert "+        --disable-werror" in patch
    assert "+    LOG_OUTPUT_ON_FAILURE 1" in patch
    assert "gcc-build-*.log" in script
    assert 'CXXFLAGS="-O2 -g -std=gnu++11"' in script
    assert 'mingw_prefix="$toolchain_root/$target_triplet"' in script
    assert 'require_file "$mingw_prefix/lib/crt2.o"' in script
    assert "LIBMPV_RUNTIME_WINDOWS_TOOLCHAIN_ONLY:-0" in script


def test_windows_workflow_retains_failed_cross_build_logs(repository_root: Path) -> None:
    workflow = (repository_root / ".github" / "workflows" / "runtime.yml").read_text()
    assert "actions/cache/restore@" in workflow
    assert "actions/cache/save@" in workflow
    assert "Bootstrap pinned Windows toolchain" in workflow
    assert 'LIBMPV_RUNTIME_WINDOWS_TOOLCHAIN_ONLY: "1"' in workflow
    assert "Upload Windows cross-build diagnostics" in workflow
    assert "if: failure()" in workflow
    assert "work/windows-x86_64/builder/build_x86_64/**/*.log" in workflow


def test_builds_locate_ffmpeg_config_by_filter_declarations(
    repository_root: Path,
) -> None:
    common = (repository_root / "scripts" / "build" / "common.sh").read_text()
    assert "find_ffmpeg_config_header()" in common
    assert "CONFIG_LOUDNORM_FILTER" in common
    assert "config_components.h config.h" in common
    for platform in ("android", "linux", "windows"):
        script = (repository_root / "scripts" / "build" / f"{platform}.sh").read_text()
        assert "find_ffmpeg_config_header" in script
        assert "ffbuild/config.h" not in script


def test_macos_probe_reconstructs_standard_mpv_header_layout(
    repository_root: Path,
) -> None:
    script = (repository_root / "scripts" / "build" / "macos.sh").read_text()
    assert 'mkdir -p "$probe_include/mpv"' in script
    assert '"$frameworks/Mpv.framework/Headers/"*.h "$probe_include/mpv/"' in script
    assert 'compile_native_probe "$probe_include"' in script


def test_ios_consumer_imports_the_packaged_framework(
    repository_root: Path,
) -> None:
    consumer = (repository_root / "probes" / "native" / "apple_consumer.c").read_text()
    script = (repository_root / "scripts" / "build" / "ios.sh").read_text()
    assert "#include <Mpv/Mpv.h>" in consumer
    assert '-F"$frameworks"' in script
    assert "Mpv.framework/Headers" not in script


def test_android_verifies_16k_elf_load_alignment(repository_root: Path) -> None:
    script = (repository_root / "scripts" / "build" / "android.sh").read_text()
    common = (repository_root / "scripts" / "build" / "common.sh").read_text()
    patch = (
        repository_root / "patches" / "android" / "0001-pin-lgpl-dsp-runtime.patch"
    ).read_text()
    assert "require_elf_load_alignment()" in common
    assert 'require_elf_load_alignment "$readelf" "$library" 16384' in script
    assert '"$nm" -D "$abi_dir/libmpv.so" >"$mpv_symbols"' in script
    assert 'libmpv.so" | grep -q' not in script
    assert 'bash "$LIBMPV_RUNTIME_ROOT/scripts/probe/android-emulator.sh"' in script
    assert "+\t-Diconv=disabled -Dlua=enabled" in patch
    assert "+dep_mpv=(ffmpeg libass lua libplacebo)" in patch


def test_android_emulator_uses_kvm_and_skips_ui_setup(repository_root: Path) -> None:
    workflow = (repository_root / ".github" / "workflows" / "runtime.yml").read_text()
    assert "Enable KVM for emulator" in workflow
    assert "sudo udevadm trigger --name-match=kvm" in workflow
    assert "disable-linux-hw-accel: false" in workflow
    assert "disable-animations: false" in workflow
    assert "-no-snapshot" in workflow


def test_private_release_has_plan_safe_attestation_gate(repository_root: Path) -> None:
    workflow = (repository_root / ".github" / "workflows" / "runtime.yml").read_text()
    assert "actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d # v4" in workflow
    assert "artifact-metadata: write" in workflow
    assert "github.event.repository.visibility == 'public'" in workflow
    assert "vars.ENABLE_GITHUB_ATTESTATIONS == 'true'" in workflow
    assert "Explain unavailable GitHub attestations" in workflow


def test_bundled_dependency_trees_contribute_license_notices(
    repository_root: Path,
) -> None:
    common = (repository_root / "scripts" / "build" / "common.sh").read_text()
    android = (repository_root / "scripts" / "build" / "android.sh").read_text()
    windows = (repository_root / "scripts" / "build" / "windows.sh").read_text()
    assert "copy_source_tree_licenses()" in common
    assert "buildscripts/deps" in android
    assert 'copy_source_tree_licenses "$LIBMPV_RUNTIME_STAGE/LICENSES" "$source_cache"' in windows
    darwin_patch = (
        repository_root / "patches" / "darwin" / "0001-enable-lgpl-dsp-filters.patch"
    ).read_text()
    assert 'licenseBundle = pkgs.runCommand "libmpv-darwin-transitive-licenses"' in darwin_patch
    for platform in ("ios", "macos"):
        script = (repository_root / "scripts" / "build" / f"{platform}.sh").read_text()
        assert 'result/LICENSES" "$LIBMPV_RUNTIME_STAGE/"' in script


def test_headless_macos_coreaudio_includes_string_helpers(repository_root: Path) -> None:
    darwin_patch = (
        repository_root / "patches" / "darwin" / "0001-enable-lgpl-dsp-filters.patch"
    ).read_text()
    assert "mpv-fix-headless-coreaudio.patch" in darwin_patch
    assert "features['coreaudio'] and not features['cocoa']" in darwin_patch
    assert "sources += files('osdep/utils-mac.c')" in darwin_patch
