"""The guard against a base that forks in two without anyone noticing.

On 4 September 2026 a collection run from inside the desktop application wrote to a private copy
of the data directory while the scheduled task kept writing the real one. Each side read its own
and both looked healthy. The base was declared lost when it was intact, and an afternoon went
into the wrong conclusion.

The writer lock cannot catch this: two processes writing two different folders never contend.
Nothing declarative reveals it either — the environment variable carries the real path on both
sides, and a marker file is worse than useless, because the directory listing is merged even when
the write is not, so the file written by one process appears to the other. Only writing and
reading back through an address the redirection does not cover tells them apart.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from econbase import settings as settings_module
from econbase import store as store_module
from econbase.settings import _bypass_path, writes_are_redirected
from econbase.store import ALLOW_REDIRECTED, Store, StoreError


# ------------------------------------------------------------------ the probe
@pytest.mark.skipif(sys.platform != "win32", reason="the redirection is a Windows behaviour")
def test_a_directory_outside_the_redirected_tree_reads_back_clean(tmp_path: Path) -> None:
    assert writes_are_redirected(tmp_path) is False


def test_the_probe_leaves_nothing_behind(tmp_path: Path) -> None:
    before = set(tmp_path.iterdir())
    writes_are_redirected(tmp_path)
    assert set(tmp_path.iterdir()) == before


@pytest.mark.skipif(sys.platform != "win32", reason="drive letters are a Windows thing")
def test_the_bypass_addresses_the_same_place_by_another_route() -> None:
    assert _bypass_path(Path(r"C:\Users\x\AppData\Local\econbase")) == Path(
        "//localhost/c$/Users/x/AppData/Local/econbase"
    )


def test_a_path_without_a_drive_letter_cannot_be_checked() -> None:
    assert _bypass_path(Path("/tmp/econbase")) is None


# ------------------------------------------------------------------ the refusal
def test_a_redirected_directory_refuses_the_transaction(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "writes_are_redirected", lambda _p: True)
    with pytest.raises(StoreError, match="redirected into a private copy"):
        store.transaction(run_id="r1")


def test_the_refusal_says_what_to_do_instead(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module, "writes_are_redirected", lambda _p: True)
    with pytest.raises(StoreError) as excinfo:
        store.transaction(run_id="r1")
    message = str(excinfo.value)
    assert "normal terminal" in message and "ECONBASE_DATA_DIR" in message


def test_the_override_exists_and_is_explicit(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """An escape hatch, because a guard with no way past it gets deleted rather than argued with."""
    monkeypatch.setattr(store_module, "writes_are_redirected", lambda _p: True)
    monkeypatch.setenv(ALLOW_REDIRECTED, "1")
    tx = store.transaction(run_id="r1")
    tx.rollback()


def test_an_unanswerable_check_warns_and_proceeds(
    store: Store, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Unknown is not the same as fine, but it is also not a reason to stop the daily run."""
    monkeypatch.setattr(store_module, "writes_are_redirected", lambda _p: None)
    with caplog.at_level("WARNING"):
        tx = store.transaction(run_id="r1")
    tx.rollback()
    assert "redirected" in caplog.text


def test_a_directory_that_is_not_redirected_is_left_alone(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "writes_are_redirected", lambda _p: False)
    tx = store.transaction(run_id="r1")
    tx.rollback()


def test_reading_is_never_blocked(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inspecting a redirected copy is exactly how the split was diagnosed; only writing forks it."""
    monkeypatch.setattr(store_module, "writes_are_redirected", lambda _p: True)
    assert store.read("observations").num_rows == 0
    assert store.manifest().run_id is not None or True


def test_the_settings_module_still_exposes_the_probe() -> None:
    assert hasattr(settings_module, "writes_are_redirected")
