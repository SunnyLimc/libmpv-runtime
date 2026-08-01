from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from libmpv_runtime import acquire as acquire_module
from libmpv_runtime import discover as discover_module
from libmpv_runtime import evidence as evidence_module
from libmpv_runtime import plan as plan_module
from libmpv_runtime import process as process_module
from libmpv_runtime import validate as validate_module
from libmpv_runtime.errors import BuildError, IntegrityError, VerificationError
from libmpv_runtime.models import RepositoryConfig
from libmpv_runtime.plan import candidate_from_plan, create_plan, load_plan, repository_revision
from libmpv_runtime.process import capture, find_json_object, run
from libmpv_runtime.validate import validate_linux_system


def test_plan_creation_uses_one_discovery_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    config: RepositoryConfig,
    validation_plan: Path,
    tmp_path: Path,
) -> None:
    existing = load_plan(validation_plan)
    monkeypatch.setattr(plan_module, "discover_many", lambda _: existing.candidates)
    output = tmp_path / "created-plan.json"
    create_plan(config, repository_revision(config.root), output)
    assert set(load_plan(output).candidates) == set(config.sources)
    with pytest.raises(IntegrityError, match="already exists"):
        create_plan(config, repository_revision(config.root), output)
    assert candidate_from_plan(config, output, "windows_libmpv").source == "windows_libmpv"
    with pytest.raises(IntegrityError, match="has no source"):
        candidate_from_plan(config, output, "missing")


def test_repository_revision_rejects_non_commit_environment(
    monkeypatch: pytest.MonkeyPatch, config: RepositoryConfig
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "not-a-commit")
    with pytest.raises(IntegrityError, match="full commit SHA"):
        repository_revision(config.root)


def test_asset_download_uses_no_repository_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"release bytes"
    observed: dict[str, Any] = {}

    class Response:
        def __init__(self) -> None:
            self.remaining = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _: int) -> bytes:
            chunk, self.remaining = self.remaining, b""
            return chunk

    def urlopen(request: object, timeout: int) -> Response:
        observed["request"] = request
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setenv("GH_TOKEN", "must-not-leak")
    monkeypatch.setattr(acquire_module.urllib.request, "urlopen", urlopen)
    destination = tmp_path / "runtime.bin"
    acquire_module._download(
        "https://github.com/example/runtime/releases/download/v1/runtime.bin",
        destination,
    )
    request = observed["request"]
    assert destination.read_bytes() == payload
    assert request.get_header("Authorization") is None
    with pytest.raises(IntegrityError, match="must use https"):
        acquire_module._download("https://example.com/runtime.bin", destination)


def test_legacy_asset_digest_is_streamed_and_size_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"legacy release bytes"

    class Response:
        def __init__(self) -> None:
            self.remaining = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _: int) -> bytes:
            chunk, self.remaining = self.remaining, b""
            return chunk

    monkeypatch.setattr(
        discover_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )
    url = "https://github.com/example/runtime/releases/download/v1/runtime.bin"
    assert (
        discover_module.release_asset_sha256(url, len(payload))
        == hashlib.sha256(payload).hexdigest()
    )
    with pytest.raises(IntegrityError, match="size changed"):
        discover_module.release_asset_sha256(url, len(payload) + 1)


def test_linux_validator_loads_the_required_soname_and_api(
    monkeypatch: pytest.MonkeyPatch, config: RepositoryConfig
) -> None:
    class Api:
        restype: object | None = None

        def __call__(self) -> int:
            return (2 << 16) | 5

    class Library:
        mpv_client_api_version = Api()

    monkeypatch.setattr(validate_module.ctypes.util, "find_library", lambda _: "libmpv.so.2")
    monkeypatch.setattr(validate_module.ctypes, "CDLL", lambda _: Library())
    monkeypatch.setattr(
        validate_module.platform,
        "freedesktop_os_release",
        lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"},
    )
    value = validate_linux_system(config, "ubuntu-24.04", "a" * 64)
    assert value["clientApi"] == "2.5"
    assert value["runtimePackages"] == ["libmpv2"]
    assert value["osRelease"] == {"id": "ubuntu", "versionId": "24.04"}
    monkeypatch.setattr(
        validate_module.platform,
        "freedesktop_os_release",
        lambda: {"ID": "debian", "VERSION_ID": "12"},
    )
    with pytest.raises(VerificationError, match="does not match host"):
        validate_linux_system(config, "ubuntu-24.04", "a" * 64)


def test_process_wrapper_preserves_environment_and_normalizes_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    def success(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout=" output \n")

    monkeypatch.setattr(process_module.subprocess, "run", success)
    run(["tool", "arg"], cwd=tmp_path, env={"TASK_VALUE": "set"})
    assert calls[0]["env"]["TASK_VALUE"] == "set"
    assert capture(["tool"], cwd=tmp_path) == "output"

    def failure(*_: object, **__: object) -> None:
        raise subprocess.CalledProcessError(9, ["tool"])

    monkeypatch.setattr(process_module.subprocess, "run", failure)
    with pytest.raises(BuildError, match="exit code 9"):
        run(["tool"], cwd=tmp_path)
    assert capture(["tool"], cwd=tmp_path) == ""


def test_machine_json_parser_ignores_bootstrap_output() -> None:
    output = 'Downloading tool...\n{\n  "frameworkVersion": "3.44.7"\n}\nReady\n'
    assert find_json_object(output, required_key="frameworkVersion") == {
        "frameworkVersion": "3.44.7"
    }
    assert find_json_object(output, required_key="packages") is None


def test_dependency_and_flutter_observation_parse_machine_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_capture(command: list[str], *, cwd: Path) -> str:
        if command[:2] == ["dart", "pub"]:
            return json.dumps(
                {
                    "packages": [
                        {"name": "media_kit", "version": "1.2.6"},
                        {"name": "media_kit_video", "version": "2.0.1"},
                    ]
                }
            )
        return json.dumps({"frameworkVersion": "3.44.7"})

    monkeypatch.setattr(evidence_module, "capture", fake_capture)
    assert evidence_module._package_versions(tmp_path)["media_kit"] == "1.2.6"
    assert evidence_module._flutter_version() == "3.44.7"
