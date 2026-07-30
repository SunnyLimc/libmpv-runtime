from __future__ import annotations

import argparse
from pathlib import Path

from .android import combine_aar
from .build import build_target
from .config import load_repository
from .darwin import verify_darwin_package_lock
from .errors import RuntimeToolError
from .evidence import write_evidence
from .package import package_target
from .prepare import prepare_target
from .release import create_release_index
from .verify import verify_target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="libmpv-runtime",
        description="Build and verify cross-platform libmpv runtime artifacts.",
    )
    parser.add_argument("--root", type=Path, help="repository root (auto-detected by default)")
    commands = parser.add_subparsers(dest="command", required=True)

    lock = commands.add_parser("lock", help="lock-file operations")
    lock_commands = lock.add_subparsers(dest="lock_command", required=True)
    lock_commands.add_parser("validate", help="validate all lock and target invariants")
    verify_darwin = lock_commands.add_parser(
        "verify-darwin",
        help="verify a Darwin builder package lock against the runtime lock",
    )
    verify_darwin.add_argument("--path", required=True, type=Path)

    target = commands.add_parser("target", help="target operations")
    target_commands = target.add_subparsers(dest="target_command", required=True)
    target_commands.add_parser("list", help="list build targets")

    source = commands.add_parser("source", help="prepare verified builder sources")
    source_commands = source.add_subparsers(dest="source_command", required=True)
    prepare = source_commands.add_parser("prepare")
    prepare.add_argument("--target", required=True)
    prepare.add_argument("--clean", action="store_true")

    build = commands.add_parser("build", help="build and stage a target")
    build.add_argument("--target", required=True)
    build.add_argument("--clean", action="store_true")
    build.add_argument("--dry-run", action="store_true")

    verify = commands.add_parser("verify", help="verify a staged target")
    verify.add_argument("--target", required=True)
    verify.add_argument("--stage", type=Path)

    package = commands.add_parser("package", help="verify and package a target")
    package.add_argument("--target", required=True)
    package.add_argument("--stage", type=Path)
    package.add_argument("--output", type=Path)

    evidence = commands.add_parser("evidence", help="write machine-readable build evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    record = evidence_commands.add_parser("record")
    record.add_argument("--target", required=True)
    record.add_argument("--output", type=Path)
    record.add_argument("--filters", nargs="+", required=True)
    record.add_argument("--structure", action=argparse.BooleanOptionalAction, default=True)
    record.add_argument("--behavior", action=argparse.BooleanOptionalAction, default=True)
    record.add_argument("--consumer", action=argparse.BooleanOptionalAction, default=True)
    record.add_argument(
        "--behavior-mode",
        choices=("native", "source-equivalent"),
        default="native",
    )
    record.add_argument("--behavior-reference-target")

    release = commands.add_parser("release", help="release metadata operations")
    release_commands = release.add_subparsers(dest="release_command", required=True)
    index = release_commands.add_parser("index")
    index.add_argument("--output", type=Path, required=True)
    index.add_argument("artifacts", nargs="+", type=Path)

    android = commands.add_parser("android", help="Android aggregate package operations")
    android_commands = android.add_subparsers(dest="android_command", required=True)
    aar = android_commands.add_parser("combine-aar")
    aar.add_argument("--output", required=True, type=Path)
    aar.add_argument("jars", nargs="+", type=Path)

    return parser


def _execute(arguments: argparse.Namespace) -> int:
    config = load_repository(arguments.root)
    if arguments.command == "lock":
        if arguments.lock_command == "verify-darwin":
            verify_darwin_package_lock(config, arguments.path)
            print(arguments.path)
            return 0
        print(
            f"valid: runtime {config.lock.runtime_version}, "
            f"{len(config.targets)} targets, {len(config.lock.builders)} builders"
        )
        return 0
    if arguments.command == "target":
        for target in sorted(config.targets.values(), key=lambda value: value.name):
            print(f"{target.name}\t{target.runner}\t{target.package}\t{target.load_name}")
        return 0
    if arguments.command == "source":
        target = config.target(arguments.target)
        print(prepare_target(config, target, clean=arguments.clean))
        return 0
    if arguments.command == "build":
        target = config.target(arguments.target)
        print(
            build_target(
                config,
                target,
                clean=arguments.clean,
                dry_run=arguments.dry_run,
            )
        )
        return 0
    if arguments.command == "verify":
        target = config.target(arguments.target)
        print(verify_target(config, target, arguments.stage))
        return 0
    if arguments.command == "package":
        target = config.target(arguments.target)
        print(package_target(config, target, stage=arguments.stage, output=arguments.output))
        return 0
    if arguments.command == "evidence":
        target = config.target(arguments.target)
        output = arguments.output or config.build_dir / "evidence" / f"{target.name}.json"
        write_evidence(
            output,
            target=target.name,
            filters=arguments.filters,
            structure=arguments.structure,
            behavior=arguments.behavior,
            consumer=arguments.consumer,
            behavior_mode=arguments.behavior_mode,
            behavior_reference_target=arguments.behavior_reference_target,
        )
        print(output)
        return 0
    if arguments.command == "release":
        output = create_release_index(
            arguments.artifacts,
            arguments.output,
            config,
        )
        print(output)
        return 0
    if arguments.command == "android":
        output = combine_aar(
            arguments.jars,
            arguments.output,
            config.lock.source_date_epoch,
        )
        print(output)
        return 0
    raise AssertionError(f"unhandled command: {arguments.command}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        return _execute(parser.parse_args(argv))
    except (RuntimeToolError, OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
