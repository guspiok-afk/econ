"""The scheduled job is the only writer, and nothing else exercises it.

A renamed CLI command would break the twice-daily run silently: the script keeps going by
design, so the failure would show up only as data that quietly stopped arriving. These tests
tie the script to the command surface it calls.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.main import get_command

from econbase.cli import app

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "scripts" / "daily.ps1"
BACKUP = ROOT / "scripts" / "backup.ps1"


def test_the_scripts_exist() -> None:
    assert DAILY.is_file() and BACKUP.is_file()


def commands_called() -> set[str]:
    text = DAILY.read_text(encoding="utf-8")
    return set(re.findall(r"econbase\.cli\s+([a-z][a-z-]*)", text))


def test_every_command_the_script_calls_still_exists() -> None:
    registered = set(get_command(app).commands)
    called = commands_called()
    assert called, "the daily script calls no CLI command at all"
    unknown = sorted(called - registered)
    assert not unknown, (
        f"scripts/daily.ps1 calls {unknown}, which the CLI no longer has; "
        "the scheduled run would fail silently"
    )


@pytest.mark.parametrize("command", ["update", "rebuild-db", "check"])
def test_the_routine_still_does_the_three_things_that_matter(command: str) -> None:
    """Fetch, refresh the query cache, then report freshness — in that order."""
    assert command in commands_called(), f"the daily routine no longer calls {command}"


def test_the_order_is_fetch_then_rebuild_then_check() -> None:
    """The cache names concrete files, so it must be rebuilt after the fetch replaces them."""
    text = DAILY.read_text(encoding="utf-8")
    positions = {c: text.index(f"econbase.cli {c}") for c in ("update", "rebuild-db", "check")}
    assert positions["update"] < positions["rebuild-db"] < positions["check"]


def test_the_run_is_recorded_as_scheduled() -> None:
    """runs.trigger separates the scheduled writer from a manual one."""
    assert "--trigger scheduler" in DAILY.read_text(encoding="utf-8")


def test_a_failing_step_does_not_cancel_the_rest() -> None:
    """One source being down must not stop the backup of the other fifty-four series."""
    text = DAILY.read_text(encoding="utf-8")
    assert '$ErrorActionPreference = "Continue"' in text


def test_the_backup_never_copies_a_live_database() -> None:
    text = BACKUP.read_text(encoding="utf-8")
    assert "*.duckdb" in text and "_staging" in text, (
        "the backup must exclude the live DuckDB file and the in-flight staging directory"
    )
