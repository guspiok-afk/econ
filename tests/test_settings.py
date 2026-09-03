from __future__ import annotations

import sys
from pathlib import Path

import pytest

from econbase.settings import DEFAULT_TZ, Settings, default_data_dir


def test_default_data_dir_is_outside_repo_and_per_user() -> None:
    d = default_data_dir()
    assert d.parts[-2:] == ("econbase", "data")
    if sys.platform == "win32":
        assert "AppData" in d.parts or "Local" in d.parts
    else:
        assert ".local" in d.parts or "share" in d.parts


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ECONBASE_DATA_DIR", str(tmp_path / "x"))
    s = Settings(_env_file=None)
    assert s.data_dir == (tmp_path / "x").resolve()


def test_blank_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ECONBASE_DATA_DIR", "")
    monkeypatch.setenv("FRED_API_KEY", "")
    monkeypatch.setenv("ECONBASE_TZ", "")
    monkeypatch.setenv("ECONBASE_HTTP_TIMEOUT", "")
    s = Settings(_env_file=None)
    assert s.data_dir == default_data_dir().resolve()
    assert s.fred_api_key is None
    assert s.econbase_tz == DEFAULT_TZ
    assert s.econbase_http_timeout == 30.0
