from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any

from .errors import IntegrityError


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"cannot read JSON {path}: {error}") from error


def ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise IntegrityError(f"path escapes {resolved_root}: {resolved}")
    return resolved


def remove_tree(path: Path, *, root: Path) -> None:
    resolved = ensure_within(path, root)
    if resolved == root.resolve():
        raise IntegrityError(f"refusing to remove root directory: {root}")
    if not path.exists():
        return

    def on_error(function: object, failing_path: str, _: object) -> None:
        os.chmod(failing_path, stat.S_IWRITE)
        assert callable(function)
        function(failing_path)

    shutil.rmtree(path, onerror=on_error)


def copy_tree_files(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        output = destination / relative
        if path.is_dir():
            output.mkdir(parents=True, exist_ok=True)
        elif path.is_symlink():
            output.parent.mkdir(parents=True, exist_ok=True)
            output.symlink_to(os.readlink(path))
        elif path.is_file():
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output)
