from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from .archive import checksum_sidecar, deterministic_zip
from .errors import IntegrityError

_ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86")


def combine_aar(jars: list[Path], output: Path, epoch: int) -> Path:
    if len(jars) != len(_ABIS):
        raise IntegrityError(f"expected {len(_ABIS)} Android ABI JARs, got {len(jars)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="libmpv-runtime-aar-") as temporary:
        root = Path(temporary)
        seen: set[str] = set()
        classes: dict[str, bytes] = {}
        metadata = root / "assets" / "libmpv-runtime"
        metadata.mkdir(parents=True)
        for jar in jars:
            if not jar.is_file():
                raise IntegrityError(f"Android JAR is missing: {jar}")
            with zipfile.ZipFile(jar) as archive:
                library_entries = [
                    name
                    for name in archive.namelist()
                    if name.startswith("lib/") and not name.endswith("/")
                ]
                abis = {Path(name).parts[1] for name in library_entries}
                if len(abis) != 1:
                    raise IntegrityError(f"{jar} must contain exactly one ABI, got {sorted(abis)}")
                abi = abis.pop()
                if abi not in _ABIS or abi in seen:
                    raise IntegrityError(f"unexpected or duplicate ABI {abi} in {jar}")
                seen.add(abi)
                names = {Path(name).name for name in library_entries}
                for required in ("libmpv.so", "libmediakitandroidhelper.so"):
                    if required not in names:
                        raise IntegrityError(f"{jar} is missing {required}")
                for name in library_entries:
                    destination = root / "jni" / abi / Path(name).name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(name))
                for name in sorted(
                    value
                    for value in archive.namelist()
                    if value.endswith(".class") and not value.startswith("META-INF/")
                ):
                    content = archive.read(name)
                    existing = classes.setdefault(name, content)
                    if existing != content:
                        raise IntegrityError(f"Android class differs between ABI JARs: {name}")
                manifest_name = "META-INF/libmpv-runtime/build-manifest.json"
                if manifest_name not in archive.namelist():
                    raise IntegrityError(f"{jar} is missing {manifest_name}")
                metadata_prefix = "META-INF/libmpv-runtime/"
                for name in sorted(
                    value
                    for value in archive.namelist()
                    if value.startswith(metadata_prefix) and not value.endswith("/")
                ):
                    relative = Path(name.removeprefix(metadata_prefix))
                    destination = metadata / abi / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(name))
        if seen != set(_ABIS):
            raise IntegrityError(f"missing Android ABIs: {sorted(set(_ABIS) - seen)}")

        (root / "AndroidManifest.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
            'package="dev.libmpv.runtime" />\n',
            encoding="utf-8",
            newline="\n",
        )
        (root / "R.txt").write_text("", encoding="utf-8")
        (root / "consumer-rules.pro").write_text(
            "-keep class com.alexmercerind.mediakitandroidhelper.** { *; }\n",
            encoding="utf-8",
            newline="\n",
        )
        classes_dir = root / ".classes"
        classes_dir.mkdir()
        for name, content in sorted(classes.items()):
            destination = classes_dir / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        expected_class = "com/alexmercerind/mediakitandroidhelper/MediaKitAndroidHelper.class"
        if expected_class not in classes:
            raise IntegrityError(f"Android JARs are missing {expected_class}")
        deterministic_zip(classes_dir, root / "classes.jar", epoch)
        shutil.rmtree(classes_dir)
        deterministic_zip(root, output, epoch)
    checksum_sidecar(output)
    return output
