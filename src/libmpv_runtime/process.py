from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from .errors import BuildError


def format_command(command: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> None:
    printable = format_command(command)
    print(f"+ ({cwd}) {printable}", flush=True)
    if dry_run:
        return
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        subprocess.run(command, cwd=cwd, env=merged_env, check=True)
    except FileNotFoundError as error:
        raise BuildError(f"command is not installed: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise BuildError(
            f"command failed with exit code {error.returncode}: {printable}"
        ) from error


def capture(command: Sequence[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()
