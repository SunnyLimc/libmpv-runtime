# Security policy

Report build-pipeline, binary-loading, or supply-chain vulnerabilities through
GitHub private vulnerability reporting for this repository. Do not open a
public issue containing an exploit, signing material, or a poisoned artifact.

Release artifacts are valid only when their SHA-256 checksum matches
`SHA256SUMS`, `promotion.json` names the immutable release asset, and the
embedded intake evidence identifies the expected upstream release and bytes.
