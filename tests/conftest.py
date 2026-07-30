from __future__ import annotations

from pathlib import Path

import pytest

from libmpv_runtime.config import load_repository
from libmpv_runtime.models import RepositoryConfig


@pytest.fixture
def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def config(repository_root: Path) -> RepositoryConfig:
    return load_repository(repository_root)
