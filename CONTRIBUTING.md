# Contributing

Build inputs are supply-chain inputs. Changes to `runtime.lock.toml`, patches,
workflows, licenses, probes, or packaging policy require:

1. a focused explanation in the pull request;
2. `python -m pytest`;
3. `libmpv-runtime lock validate`;
4. the affected real platform build and runtime probe;
5. inspection of the generated manifest, SBOM, and checksums.

Do not weaken a verification gate to make an artifact pass. If a platform
cannot demonstrate the capability, mark the target unsupported until the
runtime or probe is fixed.
