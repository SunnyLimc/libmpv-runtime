from __future__ import annotations

from libmpv_runtime import discover as discover_module
from libmpv_runtime.discover import discover
from libmpv_runtime.models import SourceRule


def test_discovery_records_exact_release_and_asset_identity(monkeypatch: object) -> None:
    response = {
        "id": 42,
        "tag_name": "v9",
        "html_url": "https://github.com/example/runtime/releases/tag/v9",
        "target_commitish": "abc123",
        "published_at": "2026-08-01T00:00:00Z",
        "assets": [
            {
                "name": "runtime-x86_64.zip",
                "browser_download_url": "https://github.com/example/runtime/releases/download/v9/runtime-x86_64.zip",
                "digest": "sha256:" + "a" * 64,
                "size": 123,
            }
        ],
    }
    monkeypatch.setattr(discover_module, "_github_json", lambda _: response)  # type: ignore[attr-defined]
    candidate = discover(
        SourceRule(
            name="example",
            repository="example/runtime",
            release="latest",
            asset_patterns=(r"^runtime-x86_64\.zip$",),
        )
    )
    assert candidate.release_id == 42
    assert candidate.release_tag == "v9"
    assert candidate.target_commitish == "abc123"
    assert candidate.assets[0].sha256 == "a" * 64
    assert candidate.to_dict()["assets"][0]["url"].endswith("runtime-x86_64.zip")
