from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .archive import checksum_sidecar, deterministic_tar_gz, deterministic_zip
from .errors import IntegrityError
from .models import ArtifactContract

_EPOCH = 315532800


def package_stage(artifact: ArtifactContract, stage: Path, output: Path) -> list[Path]:
    if not stage.is_dir():
        raise IntegrityError(f"stage directory does not exist: {stage}")
    output.mkdir(parents=True, exist_ok=True)
    packaged: list[Path] = []
    if artifact.package == "zip":
        destination = output / f"libmpv-runtime-{artifact.name}.zip"
        deterministic_zip(stage, destination, _EPOCH)
        packaged.append(destination)
    elif artifact.package == "xcframeworks":
        bundle = output / f"libmpv-runtime-{artifact.name}.tar.gz"
        deterministic_tar_gz(stage, bundle, _EPOCH)
        packaged.append(bundle)
        for framework in sorted(stage.glob("*.xcframework")):
            with tempfile.TemporaryDirectory(prefix="libmpv-runtime-xcframework-") as temporary:
                root = Path(temporary)
                shutil.copytree(framework, root / framework.name, symlinks=True)
                destination = output / f"libmpv-runtime-{artifact.name}-{framework.stem}.zip"
                deterministic_zip(root, destination, _EPOCH)
                packaged.append(destination)
    else:
        raise IntegrityError(f"unsupported package type: {artifact.package}")
    for path in packaged:
        checksum_sidecar(path)
    return packaged
