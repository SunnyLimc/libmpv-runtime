from __future__ import annotations

from libmpv_runtime.discover import discover, discover_many
from libmpv_runtime.models import SourceRule


def _release(*assets: dict[str, object]) -> dict[str, object]:
    return {
        "id": 42,
        "tag_name": "v9",
        "html_url": "https://github.com/example/runtime/releases/tag/v9",
        "target_commitish": "main",
        "published_at": "2026-08-01T00:00:00Z",
        "assets": list(assets),
    }


def _asset(name: str, *, digest: str | None = "a" * 64) -> dict[str, object]:
    return {
        "name": name,
        "browser_download_url": f"https://github.com/example/runtime/releases/download/v9/{name}",
        "digest": f"sha256:{digest}" if digest else None,
        "size": 123,
    }


def test_discovery_seals_release_commit_and_github_asset_digest() -> None:
    calls: list[str] = []

    def request(path: str) -> object:
        calls.append(path)
        if path.endswith("/releases/latest"):
            return _release(_asset("runtime-x86_64.zip"))
        return {"sha": "b" * 40}

    candidate = discover(
        SourceRule(
            name="example",
            repository="example/runtime",
            release="latest",
            asset_patterns=(r"^runtime-x86_64\.zip$",),
        ),
        request=request,
    )
    assert candidate.release_id == 42
    assert candidate.release_tag == "v9"
    assert candidate.commit_sha == "b" * 40
    assert candidate.assets[0].sha256 == "a" * 64
    assert calls == [
        "/repos/example/runtime/releases/latest",
        "/repos/example/runtime/commits/v9",
    ]


def test_discovery_fetches_shared_repository_once() -> None:
    calls: list[str] = []

    def request(path: str) -> object:
        calls.append(path)
        if path.endswith("/releases/latest"):
            return _release(_asset("macos.tar.gz"), _asset("ios.tar.gz"))
        return {"sha": "c" * 40}

    rules = tuple(
        SourceRule(
            name=name,
            repository="example/runtime",
            release="latest",
            asset_patterns=(rf"^{name.removeprefix('darwin_')}\.tar\.gz$",),
        )
        for name in ("darwin_macos", "darwin_ios")
    )
    candidates = discover_many(rules, request=request)
    assert set(candidates) == {"darwin_macos", "darwin_ios"}
    assert len([path for path in calls if path.endswith("/releases/latest")]) == 1
    assert len([path for path in calls if "/commits/" in path]) == 1


def test_discovery_hashes_legacy_assets_before_sealing_plan() -> None:
    def request(path: str) -> object:
        if path.endswith("/releases/latest"):
            return _release(_asset("runtime.zip", digest=None))
        return {"sha": "d" * 40}

    rule = SourceRule(
        name="example",
        repository="example/runtime",
        release="latest",
        asset_patterns=(r"^runtime\.zip$",),
    )
    hashed: list[tuple[str, int]] = []

    def asset_digest(url: str, size: int) -> str:
        hashed.append((url, size))
        return "e" * 64

    candidate = discover(rule, request=request, asset_digest=asset_digest)
    assert candidate.assets[0].sha256 == "e" * 64
    assert hashed == [
        (
            "https://github.com/example/runtime/releases/download/v9/runtime.zip",
            123,
        )
    ]
