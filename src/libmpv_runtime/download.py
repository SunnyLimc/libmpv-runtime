from __future__ import annotations

import os
import tarfile
import urllib.request
from pathlib import Path

from .errors import IntegrityError
from .files import sha256_file
from .models import BuilderLock


def _archive_suffix(url: str) -> str:
    for suffix in (".tar.gz", ".tar.xz", ".tgz", ".zip"):
        if url.endswith(suffix):
            return suffix
    return ".archive"


def download_url_verified(
    *,
    key: str,
    url: str,
    sha256: str,
    cache_dir: Path,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / f"{key}-{sha256[:16]}{_archive_suffix(url)}"
    if destination.is_file() and sha256_file(destination) == sha256:
        return destination
    if destination.exists():
        destination.unlink()

    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "libmpv-runtime/0.1 (+https://github.com/SunnyLimc/libmpv-runtime)"},
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            temporary.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    actual = sha256_file(temporary)
    if actual != sha256:
        temporary.unlink(missing_ok=True)
        raise IntegrityError(f"SHA-256 mismatch for {key}: expected {sha256}, got {actual}")
    temporary.replace(destination)
    return destination


def download_verified(builder: BuilderLock, cache_dir: Path) -> Path:
    return download_url_verified(
        key=f"{builder.key}-{builder.revision}",
        url=builder.url,
        sha256=builder.sha256,
        cache_dir=cache_dir,
    )


def extract_tar(archive: Path, destination: Path, *, strip_components: int) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:*") as tar:
        members: list[tarfile.TarInfo] = []
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) <= strip_components:
                continue
            relative = Path(*parts[strip_components:])
            if relative.is_absolute() or ".." in relative.parts:
                raise IntegrityError(f"unsafe archive member: {member.name}")
            copied = tarfile.TarInfo(relative.as_posix())
            copied.size = member.size
            copied.mode = member.mode
            copied.mtime = member.mtime
            copied.type = member.type
            copied.linkname = member.linkname
            copied.uid = member.uid
            copied.gid = member.gid
            copied.uname = member.uname
            copied.gname = member.gname
            copied.pax_headers = dict(member.pax_headers)
            copied.offset = member.offset
            copied.offset_data = member.offset_data
            members.append(copied)
        tar.extractall(destination, members=members, filter="data")
