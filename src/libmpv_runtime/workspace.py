from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import IntegrityError
from .files import ensure_within, remove_tree

_MARKER = ".libmpv-runtime-workspace"


@dataclass(frozen=True, slots=True)
class PipelineWorkspace:
    root: Path
    path: Path

    @classmethod
    def fresh(cls, root: Path, path: Path) -> PipelineWorkspace:
        resolved_root = root.resolve()
        resolved = ensure_within(path, resolved_root)
        if resolved == resolved_root:
            raise ValueError("pipeline workspace cannot be the repository root")
        if resolved.exists() and not (resolved / _MARKER).is_file():
            raise IntegrityError(f"refusing to replace an unowned workspace: {resolved}")
        remove_tree(resolved, root=resolved_root)
        resolved.mkdir(parents=True)
        (resolved / _MARKER).write_text("owned\n", encoding="ascii", newline="\n")
        return cls(root=resolved_root, path=resolved)

    def directory(self, name: str) -> Path:
        if not name or Path(name).name != name:
            raise ValueError(f"invalid workspace directory name: {name}")
        path = self.path / name
        path.mkdir(parents=True, exist_ok=True)
        return path
