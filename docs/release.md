# Release and promotion

An accepted runtime is named `runtime-YYYYMMDD.N`. It contains complete Windows,
Android, macOS, and iOS artifacts. Linux contributes five sealed system-runtime
reports, never a bundled library.

## Workflow protocol

1. `quality.yml` runs formatting, linting, strict typing, an 80% coverage gate,
   wheel construction, shell parsing, and workflow linting.
2. `discover.yml` resolves all release channels once and uploads exactly one
   immutable `validation-plan` artifact for 14 days.
3. `validate.yml` accepts the discovery run ID. Every native job verifies that
   the plan belongs to its checkout before intake. Windows, Android, Apple, and
   all five Linux profiles emit sealed outputs; a required fan-in job creates a
   single `validated-runtime` artifact and `validation-index.json`.
4. `promote.yml` accepts one successful validation run ID and an immutable
   promotion ID. It verifies workflow name, result, commit SHA, every indexed
   byte, every target, every Linux profile, and the original plan before it
   assembles a release.

Promotion targets the `release` environment; repository administrators should
protect it before the first publication. All release assets are attested.
GitHub publication is staged as a draft and made visible only after every asset
is prepared and uploaded. The workflow does not discover, download, normalize,
or rerun a validator.

## Failure and rollback

A missing upstream digest, changed byte, target mismatch, incomplete consumer
profile, failed filter, or absent Linux profile stops the run. No fallback build
or partial release is produced. The previous immutable promotion remains the
rollback point.

“Do not pin builder versions” applies only to selecting upstream release
channels. A validation plan and promotion pin every selected release, commit,
asset digest, control-plane revision, toolchain, evidence document, and consumer
URL.

No workflow is triggered by another workflow. Discovery, validation, and
promotion are explicit checkpoints, which keeps review and release authority
clear and prevents a scheduled upstream change from publishing automatically.
