from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .acquire import acquire, load_candidate
from .config import load_repository
from .discover import discover
from .errors import RuntimeToolError
from .evidence import record_behavior, record_consumer
from .files import write_json
from .generate import create_candidate_manifest, generate_packages
from .normalize import normalize
from .package import package_stage
from .promotion import assemble
from .validate import validate_linux_system, validate_structure


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="libmpv-runtime",
        description="Discover, validate and promote upstream libmpv runtime artifacts.",
    )
    parser.add_argument("--root", type=Path, help="repository root (auto-detected by default)")
    commands = parser.add_subparsers(dest="command", required=True)

    contract = commands.add_parser("contract", help="runtime contract operations")
    contract_commands = contract.add_subparsers(dest="contract_command", required=True)
    contract_commands.add_parser("validate")
    contract_commands.add_parser("list")

    source = commands.add_parser("source", help="upstream source operations")
    source_commands = source.add_subparsers(dest="source_command", required=True)
    source_commands.add_parser("list")

    candidate = commands.add_parser("candidate", help="candidate discovery and intake")
    candidate_commands = candidate.add_subparsers(dest="candidate_command", required=True)
    discover_command = candidate_commands.add_parser("discover")
    discover_command.add_argument("--source", action="append")
    discover_command.add_argument("--output", required=True, type=Path)
    acquire_command = candidate_commands.add_parser("acquire")
    acquire_command.add_argument("--candidate", required=True, type=Path)
    acquire_command.add_argument("--output", required=True, type=Path)

    normalize_command = commands.add_parser("normalize", help="create a canonical runtime stage")
    normalize_command.add_argument("--artifact", required=True)
    normalize_command.add_argument("--intake", required=True, type=Path, action="append")
    normalize_command.add_argument("--output", required=True, type=Path)

    validate = commands.add_parser("validate", help="validation operations")
    validate_commands = validate.add_subparsers(dest="validate_command", required=True)
    artifact_validation = validate_commands.add_parser("artifact")
    artifact_validation.add_argument("--artifact", required=True)
    artifact_validation.add_argument("--stage", required=True, type=Path)
    artifact_validation.add_argument("--evidence", required=True, type=Path)
    linux_validation = validate_commands.add_parser("linux")
    linux_validation.add_argument("--profile", required=True)
    linux_validation.add_argument("--output", type=Path)

    evidence = commands.add_parser("evidence", help="record a completed native gate")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    behavior = evidence_commands.add_parser("behavior")
    behavior.add_argument("--path", required=True, type=Path)
    behavior.add_argument("--filters", nargs="+", required=True)
    behavior.add_argument("--measured-gain-db", required=True, type=float)
    behavior.add_argument("--mode", choices=("native", "source-equivalent"), default="native")
    behavior.add_argument("--reference-target")
    consumer = evidence_commands.add_parser("consumer")
    consumer.add_argument("--path", required=True, type=Path)
    consumer.add_argument("--detail", action="append", default=[])

    package = commands.add_parser("package", help="package a canonical stage")
    package.add_argument("--artifact", required=True)
    package.add_argument("--stage", required=True, type=Path)
    package.add_argument("--output", required=True, type=Path)

    promotion = commands.add_parser("promotion", help="immutable promotion operations")
    promotion_commands = promotion.add_subparsers(dest="promotion_command", required=True)
    promotion_assemble = promotion_commands.add_parser("assemble")
    promotion_assemble.add_argument("--id", required=True)
    promotion_assemble.add_argument("--artifact", action="append", required=True)
    promotion_assemble.add_argument("--evidence", action="append", required=True)
    promotion_assemble.add_argument("--linux-report", action="append", required=True, type=Path)
    promotion_assemble.add_argument("--output", required=True, type=Path)

    packages = commands.add_parser("packages", help="MediaKit drop-in package operations")
    packages_commands = packages.add_subparsers(dest="packages_command", required=True)
    packages_manifest = packages_commands.add_parser("candidate-manifest")
    packages_manifest.add_argument("--id", required=True)
    packages_manifest.add_argument("--artifact", action="append", required=True)
    packages_manifest.add_argument("--base-url", required=True)
    packages_manifest.add_argument("--output", required=True, type=Path)
    packages_generate = packages_commands.add_parser("generate")
    packages_generate.add_argument("--promotion", required=True, type=Path)
    packages_generate.add_argument("--output", required=True, type=Path)
    packages_generate.add_argument(
        "--platform", action="append", choices=("android", "windows", "ios", "macos")
    )
    return parser


def _pairs(values: list[str], owner: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        key, separator, raw_path = value.partition("=")
        if not separator or not key or not raw_path or key in result:
            raise ValueError(f"{owner} must use unique TARGET=PATH values: {value}")
        result[key] = Path(raw_path)
    return result


def _artifact_pairs(values: list[str]) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for value in values:
        target, separator, raw_path = value.partition("=")
        if not separator or not target or not raw_path:
            raise ValueError(f"artifact must use TARGET=PATH: {value}")
        result.setdefault(target, []).append(Path(raw_path))
    return result


def _details(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        if not separator or not key or key in result:
            raise ValueError(f"detail must use unique KEY=VALUE values: {value}")
        result[key] = raw
    return result


def _execute(arguments: argparse.Namespace) -> int:
    config = load_repository(arguments.root)
    if arguments.command == "contract":
        if arguments.contract_command == "validate":
            print(
                f"valid: schema {config.contract.schema_version}, "
                f"{len(config.contract.artifacts)} bundled artifacts, Linux system runtime"
            )
        else:
            for artifact in config.contract.artifacts.values():
                print(
                    f"{artifact.name}\t{artifact.platform}\t"
                    f"{','.join(artifact.architectures)}\t{','.join(artifact.sources)}"
                )
            print(f"linux-system\tlinux\tsoname={config.contract.linux.soname_major}\tsystem")
        return 0
    if arguments.command == "source":
        for source in config.sources.values():
            print(f"{source.name}\t{source.repository}\t{source.release}")
        return 0
    if arguments.command == "candidate":
        if arguments.candidate_command == "discover":
            names = arguments.source or sorted(config.sources)
            arguments.output.mkdir(parents=True, exist_ok=True)
            for name in names:
                candidate = discover(config.source(name))
                destination = arguments.output / f"{name}.json"
                write_json(destination, candidate.to_dict())
                print(destination)
        else:
            print(acquire(load_candidate(arguments.candidate), arguments.output))
        return 0
    if arguments.command == "normalize":
        artifact = config.artifact(arguments.artifact)
        print(normalize(config, artifact, arguments.intake, arguments.output))
        return 0
    if arguments.command == "validate":
        if arguments.validate_command == "artifact":
            print(
                validate_structure(
                    config,
                    config.artifact(arguments.artifact),
                    arguments.stage,
                    arguments.evidence,
                )
            )
        else:
            result = validate_linux_system(config, arguments.profile)
            if arguments.output:
                write_json(arguments.output, result)
                print(arguments.output)
            else:
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if arguments.command == "evidence":
        if arguments.evidence_command == "behavior":
            print(
                record_behavior(
                    arguments.path,
                    filters=arguments.filters,
                    measured_gain_db=arguments.measured_gain_db,
                    mode=arguments.mode,
                    reference_target=arguments.reference_target,
                )
            )
        else:
            print(record_consumer(arguments.path, details=_details(arguments.detail)))
        return 0
    if arguments.command == "package":
        for path in package_stage(
            config.artifact(arguments.artifact), arguments.stage, arguments.output
        ):
            print(path)
        return 0
    if arguments.command == "promotion":
        print(
            assemble(
                config,
                arguments.id,
                _artifact_pairs(arguments.artifact),
                _pairs(arguments.evidence, "evidence"),
                arguments.linux_report,
                arguments.output,
            )
        )
        return 0
    if arguments.command == "packages":
        if arguments.packages_command == "candidate-manifest":
            print(
                create_candidate_manifest(
                    arguments.id,
                    _artifact_pairs(arguments.artifact),
                    arguments.base_url,
                    arguments.output,
                )
            )
        else:
            platforms = tuple(arguments.platform) if arguments.platform else None
            print(generate_packages(arguments.promotion, arguments.output, platforms))
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
