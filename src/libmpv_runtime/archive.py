from __future__ import annotations

import gzip
import os
import stat
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .files import sha256_file


def _normalized_mode(path: Path) -> int:
    if path.is_symlink():
        return 0o777
    if path.is_dir():
        return 0o755
    executable = path.stat().st_mode & stat.S_IXUSR
    return 0o755 if executable else 0o644


def deterministic_zip(source: Path, destination: Path, epoch: int) -> None:
    moment = datetime.fromtimestamp(epoch, tz=UTC)
    zip_time = (
        max(1980, min(2107, moment.year)),
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second - (moment.second % 2),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            for path in sorted(source.rglob("*")):
                relative = path.relative_to(source).as_posix()
                if path.is_symlink():
                    content = os.readlink(path).replace("\\", "/").encode()
                elif path.is_dir():
                    relative += "/"
                    content = b""
                else:
                    content = path.read_bytes()
                info = zipfile.ZipInfo(relative, date_time=zip_time)
                info.create_system = 3
                if path.is_symlink():
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                else:
                    info.external_attr = (_normalized_mode(path) & 0xFFFF) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def deterministic_tar_gz(source: Path, destination: Path, epoch: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        with (
            temporary.open("wb") as raw,
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9) as gz,
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as archive,
        ):
            for path in sorted(source.rglob("*")):
                relative = path.relative_to(source).as_posix()
                info = archive.gettarinfo(str(path), arcname=relative)
                info.uid = 0
                info.gid = 0
                info.uname = "root"
                info.gname = "root"
                info.mtime = epoch
                info.mode = _normalized_mode(path)
                if info.issym() or info.islnk():
                    info.linkname = info.linkname.replace("\\", "/")
                if not path.is_symlink() and path.is_file():
                    with path.open("rb") as file:
                        archive.addfile(info, file)
                else:
                    archive.addfile(info)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def checksum_sidecar(artifact: Path) -> Path:
    sidecar = artifact.with_name(f"{artifact.name}.sha256")
    sidecar.write_text(
        f"{sha256_file(artifact)}  {artifact.name}\n", encoding="ascii", newline="\n"
    )
    return sidecar
