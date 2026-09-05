"""Runtime settings: environment variables and an optional ``.env`` file.

Only three things are configurable and all of them have safe defaults. The data directory
defaults to a per-user local folder that is never inside a cloud-synced tree (see ADR-0001).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TZ = "America/Sao_Paulo"
#: ``.env`` next to the installed package's repository root, so a scheduled task started from
#: any working directory still finds the maintainer's configuration.
REPO_ENV = Path(__file__).resolve().parents[2] / ".env"


def _main_worktree_env(repo_root: Path) -> Path | None:
    """``.env`` of the main working tree, when this checkout is a git worktree.

    Agents work in their own worktrees so they never disturb each other's checkout, but ``.env``
    is deliberately untracked and therefore exists only in the main tree. Without this the FRED
    key is invisible from every worktree, and the failure reads as a missing key rather than as
    a missing file.
    """
    marker = repo_root / ".git"
    if not marker.is_file():
        return None
    try:
        line = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = Path(line.split(":", 1)[1].strip())
    # .../<main tree>/.git/worktrees/<name>  ->  <main tree>
    for parent in gitdir.parents:
        if parent.name == ".git":
            return parent.parent / ".env"
    return None


MAIN_TREE_ENV = _main_worktree_env(REPO_ENV.parent)


def default_data_dir() -> Path:
    """Per-user data directory outside the repository and outside synced folders."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "econbase" / "data"


class Settings(BaseSettings):
    """Settings read from the environment (case-insensitive) and from ``.env``."""

    model_config = SettingsConfigDict(
        # later files win, so the local .env still overrides the shared one
        env_file=tuple(p for p in (MAIN_TREE_ENV, REPO_ENV, Path(".env")) if p is not None),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    econbase_data_dir: Path | None = None
    econbase_tz: str | None = DEFAULT_TZ
    econbase_http_timeout: float = 30.0
    fred_api_key: str | None = None

    @field_validator("econbase_data_dir", "fred_api_key", "econbase_tz", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("econbase_http_timeout", mode="before")
    @classmethod
    def _blank_timeout(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return 30.0
        return value

    @field_validator("econbase_tz", mode="after")
    @classmethod
    def _tz_default(cls, value: str | None) -> str:
        return value or DEFAULT_TZ

    @property
    def data_dir(self) -> Path:
        """Resolved data directory (configured or default)."""
        return (self.econbase_data_dir or default_data_dir()).expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings instance (cached)."""
    return Settings()
