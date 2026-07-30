from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_repository
from .errors import ConfigurationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m libmpv_runtime.query")
    parser.add_argument("--root", type=Path)
    parser.add_argument("kind", choices=("source", "builder", "runtime"))
    parser.add_argument("name")
    parser.add_argument("field")
    arguments = parser.parse_args(argv)
    config = load_repository(arguments.root)
    owner: object | None
    if arguments.kind == "source":
        owner = config.lock.sources.get(arguments.name)
    elif arguments.kind == "builder":
        owner = config.lock.builders.get(arguments.name)
    else:
        owner = config.lock
        if arguments.name != "lock":
            owner = None
    if owner is None or not hasattr(owner, arguments.field):
        raise ConfigurationError(
            f"unknown query: {arguments.kind}.{arguments.name}.{arguments.field}"
        )
    value = getattr(owner, arguments.field)
    if isinstance(value, tuple):
        print("\n".join(str(item) for item in value))
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
