from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .download import download_url_verified, extract_tar
from .errors import IntegrityError
from .models import RepositoryConfig

_LICENSE_NAMES = frozenset(
    {
        "Copyright",
        "COPYING",
        "COPYING.GPLv3",
        "COPYING.LGPLv2.1",
        "COPYING.LGPLv3",
        "LICENSE",
        "LICENSE.GPL",
        "LICENSE.LGPL",
        "LICENSE.md",
        "LICENSE.txt",
    }
)


def collect_core_licenses(config: RepositoryConfig, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("mpv", "ffmpeg"):
        source = config.lock.sources[name]
        if not source.sha256:
            raise IntegrityError(f"source.{name} needs an archive hash for license collection")
        archive = download_url_verified(
            key=f"source-{name}-{source.version}",
            url=source.url,
            sha256=source.sha256,
            cache_dir=config.cache_dir / "sources",
        )
        with tempfile.TemporaryDirectory(prefix=f"license-{name}-") as temporary:
            extracted = Path(temporary)
            extract_tar(archive, extracted, strip_components=1)
            copied = 0
            for path in sorted(extracted.iterdir()):
                if path.is_file() and path.name in _LICENSE_NAMES:
                    shutil.copy2(path, destination / f"{name}-{path.name}.txt")
                    copied += 1
            if copied == 0:
                raise IntegrityError(f"no recognized license files in source.{name}")
