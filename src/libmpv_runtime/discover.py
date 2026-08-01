from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .errors import IntegrityError
from .models import Candidate, CandidateAsset, SourceRule

_USER_AGENT = "libmpv-runtime/0.3 (+https://github.com/SunnyLimc/libmpv-runtime)"
GitHubJson = Callable[[str], Any]
AssetDigest = Callable[[str, int], str]


def github_json(path: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(2**attempt)
    raise IntegrityError(f"GitHub request failed for {path}: {last_error}") from last_error


def release_asset_sha256(url: str, expected_size: int) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise IntegrityError(f"release asset URL must use https://github.com: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    last_error: Exception | None = None
    observed_size = 0
    digest = hashlib.sha256()
    for attempt in range(3):
        observed_size = 0
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    observed_size += len(chunk)
            break
        except (OSError, urllib.error.URLError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(2**attempt)
    else:
        raise IntegrityError(f"cannot hash release asset {url}: {last_error}") from last_error
    if observed_size != expected_size:
        raise IntegrityError(
            f"release asset size changed while hashing: expected {expected_size}, "
            f"got {observed_size}"
        )
    return digest.hexdigest()


def _commit_sha(repository: str, release_tag: str, request: GitHubJson) -> str:
    encoded = urllib.parse.quote(release_tag, safe="")
    value = request(f"/repos/{repository}/commits/{encoded}")
    sha = value.get("sha") if isinstance(value, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise IntegrityError(f"cannot resolve release tag to a commit: {repository}@{release_tag}")
    return sha


def _candidate(
    rule: SourceRule,
    release: dict[str, Any],
    commit_sha: str,
    asset_digest: AssetDigest,
) -> Candidate:
    raw_assets = release.get("assets")
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
        size = item.get("size")
        url = item.get("browser_download_url")
        if sha256 is None:
            if not isinstance(size, int) or size <= 0 or not isinstance(url, str):
                raise IntegrityError(f"release asset metadata is incomplete: {rule.name}")
            sha256 = asset_digest(url, size)
        asset = CandidateAsset.from_dict(
            {
                "name": item.get("name"),
                "url": url,
                "sha256": sha256,
                "size": size,
            }
        )
        selected.append(asset)

    fields = {
        "releaseTag": release.get("tag_name"),
        "releaseUrl": release.get("html_url"),
        "targetCommitish": release.get("target_commitish"),
        "publishedAt": release.get("published_at"),
    }
    if not all(isinstance(item, str) and item for item in fields.values()):
        raise IntegrityError(f"release metadata is incomplete: {rule.repository}")
    release_id = release.get("id")
    if not isinstance(release_id, int) or release_id <= 0:
        raise IntegrityError(f"release id is invalid: {rule.repository}")
    return Candidate(
        source=rule.name,
        repository=rule.repository,
        release_tag=str(fields["releaseTag"]),
        release_id=release_id,
        release_url=str(fields["releaseUrl"]),
        target_commitish=str(fields["targetCommitish"]),
        commit_sha=commit_sha,
        published_at=str(fields["publishedAt"]),
        discovered_at=datetime.now(UTC).isoformat(),
        assets=tuple(selected),
    )


def discover_many(
    rules: tuple[SourceRule, ...],
    *,
    request: GitHubJson = github_json,
    asset_digest: AssetDigest = release_asset_sha256,
) -> dict[str, Candidate]:
    repositories: dict[str, list[SourceRule]] = {}
    for rule in rules:
        if rule.release != "latest":
            raise IntegrityError(f"unsupported release selector for {rule.name}: {rule.release}")
        repositories.setdefault(rule.repository, []).append(rule)

    result: dict[str, Candidate] = {}
    for repository, repository_rules in sorted(repositories.items()):
        value = request(f"/repos/{repository}/releases/latest")
        if not isinstance(value, dict):
            raise IntegrityError(f"GitHub returned an invalid release for {repository}")
        tag = value.get("tag_name")
        if not isinstance(tag, str) or not tag:
            raise IntegrityError(f"release tag is missing: {repository}")
        commit_sha = _commit_sha(repository, tag, request)
        for rule in repository_rules:
            result[rule.name] = _candidate(rule, value, commit_sha, asset_digest)
    return result


def discover(
    rule: SourceRule,
    *,
    request: GitHubJson = github_json,
    asset_digest: AssetDigest = release_asset_sha256,
) -> Candidate:
    return discover_many((rule,), request=request, asset_digest=asset_digest)[rule.name]
