# Security policy

Report build-pipeline, binary-loading, or supply-chain vulnerabilities through
GitHub private vulnerability reporting for this repository. Do not open a
public issue containing an exploit, signing material, or a poisoned artifact.

Release artifacts are valid only when their SHA-256 checksum matches
`SHA256SUMS`, their manifest names the expected commit, and their GitHub
artifact attestation verifies for this repository.
