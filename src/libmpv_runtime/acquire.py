from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import IntegrityError
from .files import read_json, sha256_file, write_json
from .models import Candidate, Intake, IntakeAsset

_USER_AGENT = "libmpv-runtime/0.3 (+https://github.com/SunnyLimc/libmpv-runtime)"


def load_candidate(path: Path) -> Candidate:
    return Candidate.from_dict(read_json(path))


def _download(url: str, destination: Path) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise IntegrityError(f"release asset URL must use https://github.com: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    temporary = destination.with_name(f"{destination.name}.partial")
    last_error: Exception | None = None
    for attempt in range(3):
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
            break
        except (OSError, urllib.error.URLError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(2**attempt)
    else:
        assert last_error is not None
        raise last_error
    temporary.replace(destination)


def acquire(candidate: Candidate, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    observed_assets: list[IntakeAsset] = []
    for asset in candidate.assets:
        if Path(asset.name).name != asset.name:
            raise IntegrityError(f"unsafe asset name: {asset.name}")
        destination = output / asset.name
        if asset.sha256 is None:
            raise IntegrityError(f"candidate asset is not immutable: {asset.name}")
        reusable = (
            destination.is_file()
            and destination.stat().st_size == asset.size
            and sha256_file(destination) == asset.sha256
        )
        if not reusable:
            destination.unlink(missing_ok=True)
            _download(asset.url, destination)
        actual_size = destination.stat().st_size
        actual_sha256 = sha256_file(destination)
        if actual_size != asset.size:
            raise IntegrityError(
                f"size mismatch for {asset.name}: expected {asset.size}, got {actual_size}"
            )
        if actual_sha256 != asset.sha256:
            destination.unlink(missing_ok=True)
            raise IntegrityError(
                f"SHA-256 mismatch for {asset.name}: expected {asset.sha256}, got {actual_sha256}"
            )
        observed_assets.append(
            IntakeAsset(
                name=asset.name,
                url=asset.url,
                sha256=actual_sha256,
                size=actual_size,
                path=asset.name,
            )
        )
    manifest = output / "intake.json"
    write_json(manifest, Intake(candidate=candidate, assets=tuple(observed_assets)).to_dict())
    return manifest


def load_intake(path: Path) -> Intake:
    intake = Intake.from_dict(read_json(path))
    for asset in intake.assets:
        local = path.parent / asset.path
        if (
            not local.is_file()
            or sha256_file(local) != asset.sha256
            or local.stat().st_size != asset.size
        ):
            raise IntegrityError(f"intake asset is missing or changed: {asset.name}")
    return intake
