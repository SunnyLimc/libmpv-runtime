from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, IntegrityError


def _text(value: Any, owner: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{owner} must be a non-empty string")
    return value


def _texts(value: Any, owner: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ConfigurationError(f"{owner} must be a non-empty string array")
    if len(value) != len(set(value)):
        raise ConfigurationError(f"{owner} contains duplicates")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    name: str
    platform: str
    architectures: tuple[str, ...]
    sources: tuple[str, ...]
    package: str
    load_names: tuple[str, ...]

    @classmethod
    def from_table(cls, name: str, value: dict[str, Any]) -> ArtifactContract:
        owner = f"artifact.{name}"
        return cls(
            name=name,
            platform=_text(value.get("platform"), f"{owner}.platform"),
            architectures=_texts(value.get("architectures"), f"{owner}.architectures"),
            sources=_texts(value.get("sources"), f"{owner}.sources"),
            package=_text(value.get("package"), f"{owner}.package"),
            load_names=_texts(value.get("load_names"), f"{owner}.load_names"),
        )


@dataclass(frozen=True, slots=True)
class LinuxProfile:
    name: str
    runtime_packages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LinuxContract:
    soname_major: int
    loader_candidates: tuple[str, ...]
    build_packages: tuple[str, ...]
    profiles: dict[str, LinuxProfile]


@dataclass(frozen=True, slots=True)
class RuntimeContract:
    schema_version: int
    minimum_media_kit: str
    minimum_media_kit_video: str
    required_audio_filters: tuple[str, ...]
    artifacts: dict[str, ArtifactContract]
    linux: LinuxContract


@dataclass(frozen=True, slots=True)
class SourceRule:
    name: str
    repository: str
    release: str
    asset_patterns: tuple[str, ...]

    @classmethod
    def from_table(cls, name: str, value: dict[str, Any]) -> SourceRule:
        owner = f"source.{name}"
        return cls(
            name=name,
            repository=_text(value.get("repository"), f"{owner}.repository"),
            release=_text(value.get("release"), f"{owner}.release"),
            asset_patterns=_texts(value.get("asset_patterns"), f"{owner}.asset_patterns"),
        )


@dataclass(frozen=True, slots=True)
class CandidateAsset:
    name: str
    url: str
    sha256: str | None
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "sha256": self.sha256,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, value: Any) -> CandidateAsset:
        if not isinstance(value, dict):
            raise IntegrityError("candidate asset must be an object")
        name = value.get("name")
        url = value.get("url")
        sha256 = value.get("sha256")
        size = value.get("size")
        if not isinstance(name, str) or not name:
            raise IntegrityError("candidate asset name is missing")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise IntegrityError(f"candidate asset URL is invalid: {name}")
        if sha256 is not None and (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(char not in "0123456789abcdef" for char in sha256)
        ):
            raise IntegrityError(f"candidate asset SHA-256 is invalid: {name}")
        if not isinstance(size, int) or size <= 0:
            raise IntegrityError(f"candidate asset size is invalid: {name}")
        return cls(name=name, url=url, sha256=sha256, size=size)


@dataclass(frozen=True, slots=True)
class Candidate:
    source: str
    repository: str
    release_tag: str
    release_id: int
    release_url: str
    target_commitish: str
    published_at: str
    discovered_at: str
    assets: tuple[CandidateAsset, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "source": self.source,
            "repository": self.repository,
            "releaseTag": self.release_tag,
            "releaseId": self.release_id,
            "releaseUrl": self.release_url,
            "targetCommitish": self.target_commitish,
            "publishedAt": self.published_at,
            "discoveredAt": self.discovered_at,
            "assets": [asset.to_dict() for asset in self.assets],
        }

    @classmethod
    def from_dict(cls, value: Any) -> Candidate:
        if not isinstance(value, dict) or value.get("schemaVersion") != 1:
            raise IntegrityError("invalid candidate schema")
        text_fields = {
            key: value.get(key)
            for key in (
                "source",
                "repository",
                "releaseTag",
                "releaseUrl",
                "targetCommitish",
                "publishedAt",
                "discoveredAt",
            )
        }
        if not all(isinstance(item, str) and item for item in text_fields.values()):
            raise IntegrityError("candidate contains an invalid text field")
        release_id = value.get("releaseId")
        assets = value.get("assets")
        if not isinstance(release_id, int) or release_id <= 0:
            raise IntegrityError("candidate releaseId is invalid")
        if not isinstance(assets, list) or not assets:
            raise IntegrityError("candidate assets are missing")
        return cls(
            source=str(text_fields["source"]),
            repository=str(text_fields["repository"]),
            release_tag=str(text_fields["releaseTag"]),
            release_id=release_id,
            release_url=str(text_fields["releaseUrl"]),
            target_commitish=str(text_fields["targetCommitish"]),
            published_at=str(text_fields["publishedAt"]),
            discovered_at=str(text_fields["discoveredAt"]),
            assets=tuple(CandidateAsset.from_dict(item) for item in assets),
        )


@dataclass(frozen=True, slots=True)
class RepositoryConfig:
    root: Path
    contract: RuntimeContract
    sources: dict[str, SourceRule]

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"

    @property
    def work_dir(self) -> Path:
        return self.root / "work"

    @property
    def build_dir(self) -> Path:
        return self.root / "build"

    @property
    def dist_dir(self) -> Path:
        return self.root / "dist"

    def artifact(self, name: str) -> ArtifactContract:
        try:
            return self.contract.artifacts[name]
        except KeyError as error:
            choices = ", ".join(sorted(self.contract.artifacts))
            raise ConfigurationError(
                f"unknown artifact {name!r}; choose one of: {choices}"
            ) from error

    def source(self, name: str) -> SourceRule:
        try:
            return self.sources[name]
        except KeyError as error:
            choices = ", ".join(sorted(self.sources))
            raise ConfigurationError(
                f"unknown source {name!r}; choose one of: {choices}"
            ) from error
