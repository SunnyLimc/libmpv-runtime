from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .files import read_json, sha256_file, write_json
from .models import Candidate

_USER_AGENT = "libmpv-runtime/0.2 (+https://github.com/SunnyLimc/libmpv-runtime)"


def load_candidate(path: Path) -> Candidate:
    return Candidate.from_dict(read_json(path))


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    temporary = destination.with_name(f"{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    try:
        with (
            urllib.request.urlopen(request, timeout=180) as response,
            temporary.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except (OSError, urllib.error.URLError):
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(destination)


def acquire(candidate: Candidate, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    observed_assets: list[dict[str, Any]] = []
    for asset in candidate.assets:
        if Path(asset.name).name != asset.name:
            raise IntegrityError(f"unsafe asset name: {asset.name}")
        destination = output / asset.name
        reusable = destination.is_file() and destination.stat().st_size == asset.size
        if reusable and asset.sha256:
            reusable = sha256_file(destination) == asset.sha256
        if not reusable:
            destination.unlink(missing_ok=True)
            _download(asset.url, destination)
        actual_size = destination.stat().st_size
        actual_sha256 = sha256_file(destination)
        if actual_size != asset.size:
            raise IntegrityError(
                f"size mismatch for {asset.name}: expected {asset.size}, got {actual_size}"
            )
        if asset.sha256 and actual_sha256 != asset.sha256:
            destination.unlink(missing_ok=True)
            raise IntegrityError(
                f"SHA-256 mismatch for {asset.name}: expected {asset.sha256}, got {actual_sha256}"
            )
        observed_assets.append(
            {
                "name": asset.name,
                "url": asset.url,
                "sha256": actual_sha256,
                "size": actual_size,
                "path": asset.name,
            }
        )
    manifest = output / "intake.json"
    write_json(
        manifest,
        {
            "schemaVersion": 1,
            "candidate": candidate.to_dict(),
            "assets": observed_assets,
        },
    )
    return manifest


def load_intake(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise IntegrityError(f"invalid intake manifest: {path}")
    candidate = Candidate.from_dict(value.get("candidate"))
    assets = value.get("assets")
    if not isinstance(assets, list) or len(assets) != len(candidate.assets):
        raise IntegrityError(f"intake asset list is invalid: {path}")
    expected = {asset.name: asset for asset in candidate.assets}
    for item in assets:
        if not isinstance(item, dict) or item.get("name") not in expected:
            raise IntegrityError(f"intake contains an unexpected asset: {path}")
        name = item["name"]
        local = path.parent / str(item.get("path"))
        sha256 = item.get("sha256")
        size = item.get("size")
        if (
            not local.is_file()
            or not isinstance(sha256, str)
            or sha256_file(local) != sha256
            or not isinstance(size, int)
            or local.stat().st_size != size
        ):
            raise IntegrityError(f"intake asset is missing or changed: {name}")
    return value
