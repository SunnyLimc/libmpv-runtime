# Release and promotion

## Identity

An accepted set is named `runtime-YYYYMMDD.N`. The identifier is immutable and
contains complete Windows, Android, macOS, and iOS assets. Linux contributes a
compatibility contract and validation reports, not a bundled library.

“Do not pin builder versions” applies only to upstream candidate selection.
Every promoted byte and every consumer URL is pinned by promotion ID and
SHA-256. Upstream `latest` never appears in a generated MediaKit package.

## Workflows

1. `quality.yml` is hermetic and performs no upstream downloads.
2. `discover.yml` resolves release channels and retains candidate JSON for 14
   days. Discovery cannot publish.
3. `validate.yml` downloads exact candidate assets, normalizes them, performs
   native and Flutter consumer gates, and uploads short-lived validation
   artifacts. It never builds mpv.
4. `promote.yml` is given one successful validation run ID. It refuses missing
   or incomplete evidence, copies the exact validated artifacts, creates
   `promotion.json` and `SHA256SUMS`, generates drop-in package zips, and creates
   the GitHub release. The validated Linux profile report is copied into the
   release and bound by its SHA-256 in `promotion.json`.

If any upstream, structure, filter, decoded-PCM, online source, or consumer gate
fails, no promotion is created. The previous release remains usable and there
is no automatic fallback compile.

## Local validation during runner limits

Windows and Android candidate jobs use the same scripts as GitHub Actions.
WSL validates the distribution-owned Linux runtime. Apple structure can be
checked anywhere after intake, while native Apple behavior and simulator
consumer gates remain macOS-runner requirements. A promotion cannot turn a
missing native gate into a pass.
