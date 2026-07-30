# Release policy

## Versioning

The repository version identifies a complete platform set. Upstream component
versions are recorded independently in every artifact manifest.

## Required release assets

- one normalized archive for every supported target;
- Android combined AAR and ABI JARs;
- Apple XCFramework archives;
- `SHA256SUMS`;
- `release-index.json`;
- SPDX 2.3 SBOMs;
- source-lock and corresponding-source metadata;
- GitHub artifact attestations.

## Reproducibility

Archives normalize entry order, timestamps, uid/gid, and permissions using
`source_date_epoch` from the lock. Bit-for-bit equality is checked between two
packaging passes in CI. Native compiler output may still contain platform
toolchain identifiers; those are captured in the build manifest.

## Promotion

A tag does not rebuild unreviewed source. Release assembly downloads artifacts
produced for the exact tag commit, verifies their embedded commit and checksums,
then creates the GitHub release. A missing or failed target blocks promotion.
