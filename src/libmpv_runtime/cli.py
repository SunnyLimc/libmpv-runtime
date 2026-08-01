from __future__ import annotations

import argparse
import json
from pathlib import Path

from .acquire import acquire
from .config import load_repository
from .consumer import run_consumer
from .errors import RuntimeToolError
from .evidence import (
    create_consumer_report,
    derive_behavior_report,
    seal_evidence,
    seal_linux_evidence,
)
from .files import sha256_file, write_json
from .generate import create_candidate_manifest, generate_packages
from .normalize import normalize
from .package import package_stage
from .plan import (
    candidate_from_plan,
    create_plan,
    load_plan,
    repository_revision,
    verify_plan,
)
from .probe import run_probe
from .promotion import assemble
from .validate import validate_linux_system, validate_structure
from .validation import seal_validation_run, verify_validation_run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="libmpv-runtime",
        description="Seal and promote validated upstream libmpv runtime artifacts.",
    )
    parser.add_argument("--root", type=Path, help="repository root (auto-detected by default)")
    commands = parser.add_subparsers(dest="command", required=True)

    contract = commands.add_parser("contract", help="runtime contract operations")
    contract_commands = contract.add_subparsers(dest="contract_command", required=True)
    contract_commands.add_parser("validate")
    contract_commands.add_parser("list")

    source = commands.add_parser("source", help="upstream source operations")
    source.add_subparsers(dest="source_command", required=True).add_parser("list")

    plan = commands.add_parser("plan", help="immutable validation plan operations")
    plan_commands = plan.add_subparsers(dest="plan_command", required=True)
    plan_create = plan_commands.add_parser("create")
    plan_create.add_argument("--revision")
    plan_create.add_argument("--output", required=True, type=Path)
    plan_verify = plan_commands.add_parser("verify")
    plan_verify.add_argument("--path", required=True, type=Path)
    plan_verify.add_argument("--revision")
    plan_export = plan_commands.add_parser("export")
    plan_export.add_argument("--path", required=True, type=Path)
    plan_export.add_argument("--github-output", required=True, type=Path)

    intake = commands.add_parser("intake", help="verified upstream byte intake")
    intake_commands = intake.add_subparsers(dest="intake_command", required=True)
    intake_acquire = intake_commands.add_parser("acquire")
    intake_acquire.add_argument("--plan", required=True, type=Path)
    intake_acquire.add_argument("--source", required=True)
    intake_acquire.add_argument("--output", required=True, type=Path)

    stage = commands.add_parser("stage", help="canonical runtime stage operations")
    stage_commands = stage.add_subparsers(dest="stage_command", required=True)
    stage_normalize = stage_commands.add_parser("normalize")
    stage_normalize.add_argument("--artifact", required=True)
    stage_normalize.add_argument("--intake", required=True, type=Path, action="append")
    stage_normalize.add_argument("--output", required=True, type=Path)
    stage_validate = stage_commands.add_parser("validate")
    stage_validate.add_argument("--artifact", required=True)
    stage_validate.add_argument("--stage", required=True, type=Path)
    stage_validate.add_argument("--report", required=True, type=Path)

    linux = commands.add_parser("linux", help="distribution runtime validation")
    linux_commands = linux.add_subparsers(dest="linux_command", required=True)
    linux_validate = linux_commands.add_parser("validate")
    linux_validate.add_argument("--plan", required=True, type=Path)
    linux_validate.add_argument("--profile", required=True)
    linux_validate.add_argument("--report", required=True, type=Path)

    probe = commands.add_parser("probe", help="decoded PCM behavior probes")
    probe_commands = probe.add_subparsers(dest="probe_command", required=True)
    probe_run = probe_commands.add_parser("run")
    probe_run.add_argument("--plan", required=True, type=Path)
    probe_run.add_argument(
        "--target",
        required=True,
        choices=("windows-x86_64", "android", "macos", "linux-system"),
    )
    probe_run.add_argument("--stage", type=Path)
    probe_run.add_argument("--work", required=True, type=Path)
    probe_run.add_argument("--report", required=True, type=Path)

    behavior = commands.add_parser("behavior", help="behavior evidence derivation")
    behavior_commands = behavior.add_subparsers(dest="behavior_command", required=True)
    behavior_derive = behavior_commands.add_parser("derive")
    behavior_derive.add_argument("--plan", required=True, type=Path)
    behavior_derive.add_argument("--target", required=True)
    behavior_derive.add_argument("--reference-report", required=True, type=Path)
    behavior_derive.add_argument("--output", required=True, type=Path)

    consumer = commands.add_parser("consumer", help="real Flutter consumer gates")
    consumer_commands = consumer.add_subparsers(dest="consumer_command", required=True)
    consumer_run = consumer_commands.add_parser("run")
    consumer_run.add_argument("--plan", required=True, type=Path)
    consumer_run.add_argument("--group", required=True, choices=("windows", "android", "apple"))
    consumer_run.add_argument("--artifact", action="append", required=True)
    consumer_run.add_argument("--report", action="append", required=True)
    consumer_run.add_argument("--profile", default="current")
    consumer_run.add_argument("--work", required=True, type=Path)
    consumer_report = consumer_commands.add_parser("report")
    consumer_report.add_argument("--plan", required=True, type=Path)
    consumer_report.add_argument("--target", required=True)
    consumer_report.add_argument("--profile", required=True)
    consumer_report.add_argument("--app", required=True, type=Path)
    consumer_report.add_argument("--artifact", action="append", required=True, type=Path)
    consumer_report.add_argument("--detail", action="append", default=[])
    consumer_report.add_argument("--output", required=True, type=Path)

    evidence = commands.add_parser("evidence", help="seal immutable gate evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_seal = evidence_commands.add_parser("seal")
    evidence_seal.add_argument("--plan", required=True, type=Path)
    evidence_seal.add_argument("--target", required=True)
    evidence_seal.add_argument("--structure", required=True, type=Path)
    evidence_seal.add_argument("--behavior", required=True, type=Path)
    evidence_seal.add_argument("--consumer", action="append", required=True)
    evidence_seal.add_argument("--output", required=True, type=Path)
    linux_seal = evidence_commands.add_parser("seal-linux")
    linux_seal.add_argument("--plan", required=True, type=Path)
    linux_seal.add_argument("--profile", required=True)
    linux_seal.add_argument("--structure", required=True, type=Path)
    linux_seal.add_argument("--behavior", required=True, type=Path)
    linux_seal.add_argument("--output", required=True, type=Path)

    validation = commands.add_parser("validation", help="complete validation run operations")
    validation_commands = validation.add_subparsers(dest="validation_command", required=True)
    validation_seal = validation_commands.add_parser("seal")
    validation_seal.add_argument("--plan", required=True, type=Path)
    validation_seal.add_argument("--input", required=True, type=Path)
    validation_seal.add_argument("--output", required=True, type=Path)
    validation_verify = validation_commands.add_parser("verify")
    validation_verify.add_argument("--path", required=True, type=Path)

    artifact = commands.add_parser("artifact", help="runtime artifact packaging")
    artifact_commands = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_package = artifact_commands.add_parser("package")
    artifact_package.add_argument("--artifact", required=True)
    artifact_package.add_argument("--stage", required=True, type=Path)
    artifact_package.add_argument("--output", required=True, type=Path)

    promotion = commands.add_parser("promotion", help="immutable promotion operations")
    promotion_commands = promotion.add_subparsers(dest="promotion_command", required=True)
    promotion_assemble = promotion_commands.add_parser("assemble")
    promotion_assemble.add_argument("--id", required=True)
    promotion_assemble.add_argument("--plan", required=True, type=Path)
    promotion_assemble.add_argument("--artifact", action="append", required=True)
    promotion_assemble.add_argument("--evidence", action="append", required=True)
    promotion_assemble.add_argument("--linux-evidence", action="append", required=True, type=Path)
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


def _details(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        if not separator or not key or not raw or key in result:
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
                    f"{','.join(artifact.architectures)}\t{artifact.behavior_mode}"
                )
            print(f"linux-system\tlinux\tsoname={config.contract.linux.soname_major}\tsystem")
        return 0
    if arguments.command == "source":
        for source in config.sources.values():
            print(f"{source.name}\t{source.repository}\t{source.release}")
        return 0
    if arguments.command == "plan":
        if arguments.plan_command == "create":
            revision = arguments.revision or repository_revision(config.root)
            print(create_plan(config, revision, arguments.output))
        elif arguments.plan_command == "verify":
            plan = load_plan(arguments.path)
            verify_plan(config, plan, revision=arguments.revision)
            print(f"valid: {sha256_file(arguments.path)}")
        else:
            plan = load_plan(arguments.path)
            verify_plan(config, plan)
            profile = plan.consumers["current"]
            with arguments.github_output.open("a", encoding="utf-8", newline="\n") as output:
                output.write(f"flutter-version={plan.toolchain.flutter}\n")
                output.write(f"media-kit-version={profile.media_kit}\n")
                output.write(f"media-kit-video-version={profile.media_kit_video}\n")
                output.write(f"python-version={plan.toolchain.python}\n")
                output.write(f"android-emulator-api={plan.toolchain.android_emulator_api}\n")
                output.write(f"plan-sha256={sha256_file(arguments.path)}\n")
        return 0
    if arguments.command == "intake":
        candidate = candidate_from_plan(config, arguments.plan, arguments.source)
        print(acquire(candidate, arguments.output))
        return 0
    if arguments.command == "stage":
        artifact = config.artifact(arguments.artifact)
        if arguments.stage_command == "normalize":
            print(normalize(config, artifact, arguments.intake, arguments.output))
        else:
            print(validate_structure(config, artifact, arguments.stage, arguments.report))
        return 0
    if arguments.command == "linux":
        plan = load_plan(arguments.plan)
        verify_plan(config, plan)
        result = validate_linux_system(config, arguments.profile, sha256_file(arguments.plan))
        write_json(arguments.report, result)
        print(arguments.report)
        return 0
    if arguments.command == "probe":
        print(
            run_probe(
                config,
                arguments.target,
                arguments.plan,
                arguments.stage,
                arguments.work,
                arguments.report,
            )
        )
        return 0
    if arguments.command == "behavior":
        print(
            derive_behavior_report(
                config,
                arguments.plan,
                arguments.target,
                arguments.reference_report,
                arguments.output,
            )
        )
        return 0
    if arguments.command == "consumer":
        if arguments.consumer_command == "run":
            reports = run_consumer(
                config,
                arguments.plan,
                arguments.group,
                _artifact_pairs(arguments.artifact),
                arguments.work,
                _pairs(arguments.report, "report"),
                arguments.profile,
            )
            for report in reports.values():
                print(report)
        else:
            print(
                create_consumer_report(
                    config,
                    arguments.plan,
                    arguments.target,
                    arguments.profile,
                    arguments.app,
                    arguments.artifact,
                    _details(arguments.detail),
                    arguments.output,
                )
            )
        return 0
    if arguments.command == "evidence":
        if arguments.evidence_command == "seal":
            print(
                seal_evidence(
                    config,
                    arguments.plan,
                    arguments.target,
                    arguments.structure,
                    arguments.behavior,
                    _pairs(arguments.consumer, "consumer"),
                    arguments.output,
                )
            )
        else:
            print(
                seal_linux_evidence(
                    config,
                    arguments.plan,
                    arguments.profile,
                    arguments.structure,
                    arguments.behavior,
                    arguments.output,
                )
            )
        return 0
    if arguments.command == "artifact":
        for path in package_stage(
            config.artifact(arguments.artifact), arguments.stage, arguments.output
        ):
            print(path)
        return 0
    if arguments.command == "validation":
        if arguments.validation_command == "seal":
            print(seal_validation_run(config, arguments.plan, arguments.input, arguments.output))
        else:
            print(json.dumps(verify_validation_run(config, arguments.path), sort_keys=True))
        return 0
    if arguments.command == "promotion":
        print(
            assemble(
                config,
                arguments.id,
                arguments.plan,
                _artifact_pairs(arguments.artifact),
                _pairs(arguments.evidence, "evidence"),
                arguments.linux_evidence,
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
            print(generate_packages(config, arguments.promotion, arguments.output, platforms))
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
