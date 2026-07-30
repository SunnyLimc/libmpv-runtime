from __future__ import annotations

import os
from pathlib import Path

from .files import remove_tree
from .models import RepositoryConfig, Target
from .prepare import prepare_target
from .process import run


def build_target(
    config: RepositoryConfig,
    target: Target,
    *,
    clean: bool = False,
    dry_run: bool = False,
) -> Path:
    target_work = config.work_dir / target.name
    builder = target_work / "builder"
    if not dry_run:
        builder = prepare_target(config, target, clean=clean)
    stage = config.build_dir / "stage" / target.name
    evidence = config.build_dir / "evidence" / f"{target.name}.json"
    if clean and stage.exists():
        remove_tree(stage, root=config.build_dir)
    stage.mkdir(parents=True, exist_ok=True)
    evidence.parent.mkdir(parents=True, exist_ok=True)

    script = config.root / "scripts" / "build" / f"{target.platform}.sh"
    environment = {
        "LIBMPV_RUNTIME_ROOT": str(config.root),
        "LIBMPV_RUNTIME_TARGET": target.name,
        "LIBMPV_RUNTIME_ARCH": target.architecture,
        "LIBMPV_RUNTIME_BUILDER": str(builder),
        "LIBMPV_RUNTIME_WORK": str(target_work),
        "LIBMPV_RUNTIME_STAGE": str(stage),
        "LIBMPV_RUNTIME_EVIDENCE": str(evidence),
        "LIBMPV_RUNTIME_VERSION": config.lock.runtime_version,
        "SOURCE_DATE_EPOCH": str(config.lock.source_date_epoch),
        "PYTHONUTF8": "1",
    }
    command = ["bash", str(script)]
    if os.name == "nt" and target.platform not in {"windows"} and not dry_run:
        # Native builds are intentionally run on their declared CI host. The
        # dry-run remains usable from every development platform.
        print(f"target {target.name} expects runner {target.runner}")
    run(command, cwd=config.root, env=environment, dry_run=dry_run)
    return stage
