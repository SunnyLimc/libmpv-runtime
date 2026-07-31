from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from .errors import IntegrityError
from .models import Candidate, CandidateAsset, SourceRule

_USER_AGENT = "libmpv-runtime/0.2 (+https://github.com/SunnyLimc/libmpv-runtime)"


def _github_json(path: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise IntegrityError(f"GitHub request failed for {path}: {error}") from error


def discover(rule: SourceRule) -> Candidate:
    if rule.release != "latest":
        raise IntegrityError(f"unsupported release selector for {rule.name}: {rule.release}")
    value = _github_json(f"/repos/{rule.repository}/releases/latest")
    if not isinstance(value, dict):
        raise IntegrityError(f"GitHub returned an invalid release for {rule.repository}")
    raw_assets = value.get("assets")
    if not isinstance(raw_assets, list):
        raise IntegrityError(f"release has no assets: {rule.repository}")

    selected: list[CandidateAsset] = []
    for pattern_text in rule.asset_patterns:
        pattern = re.compile(pattern_text)
        matches = [
            item
            for item in raw_assets
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and pattern.fullmatch(item["name"])
        ]
        if len(matches) != 1:
            names = sorted(
                item["name"]
                for item in raw_assets
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            )
            raise IntegrityError(
                f"{rule.name} pattern {pattern_text!r} matched {len(matches)} assets; "
                f"release contains: {', '.join(names)}"
            )
        item = matches[0]
        digest = item.get("digest")
        sha256 = digest.removeprefix("sha256:") if isinstance(digest, str) else None
        selected.append(
            CandidateAsset.from_dict(
                {
                    "name": item.get("name"),
                    "url": item.get("browser_download_url"),
                    "sha256": sha256,
                    "size": item.get("size"),
                }
            )
        )

    fields = {
        "releaseTag": value.get("tag_name"),
        "releaseUrl": value.get("html_url"),
        "targetCommitish": value.get("target_commitish"),
        "publishedAt": value.get("published_at"),
    }
    if not all(isinstance(item, str) and item for item in fields.values()):
        raise IntegrityError(f"release metadata is incomplete: {rule.repository}")
    release_id = value.get("id")
    if not isinstance(release_id, int) or release_id <= 0:
        raise IntegrityError(f"release id is invalid: {rule.repository}")
    return Candidate(
        source=rule.name,
        repository=rule.repository,
        release_tag=str(fields["releaseTag"]),
        release_id=release_id,
        release_url=str(fields["releaseUrl"]),
        target_commitish=str(fields["targetCommitish"]),
        published_at=str(fields["publishedAt"]),
        discovered_at=datetime.now(UTC).isoformat(),
        assets=tuple(selected),
    )
