from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from .errors import BuildError


def find_json_object(output: str, *, required_key: str) -> dict[str, object] | None:
    """Find a JSON object in command output that may include bootstrap noise."""
    decoder = json.JSONDecoder()
    for offset, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and required_key in value:
            return value
    return None


def tool_command(name: str, *arguments: str) -> list[str]:
    """Resolve SDK command shims that are batch files on Windows."""
    executable = f"{name}.bat" if os.name == "nt" else name
    return [executable, *arguments]


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
