from __future__ import annotations


class RuntimeToolError(Exception):
    """Base error for expected command failures."""


class ConfigurationError(RuntimeToolError):
    """The repository configuration is invalid."""


class IntegrityError(RuntimeToolError):
    """A downloaded or staged input failed integrity verification."""


class BuildError(RuntimeToolError):
    """A native build command failed."""


class VerificationError(RuntimeToolError):
    """A runtime artifact did not satisfy its declared contract."""
