from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from econbase.cli import app

runner = CliRunner()


def test_init_prints_paths(data_dir: Path) -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert str(data_dir.resolve()) in result.output
    assert "fred key : missing" in result.output
    assert (data_dir / "lake").is_dir()


def test_list_and_search(catalog_root: Path, data_dir: Path) -> None:
    result = runner.invoke(app, ["list", "--catalog", str(catalog_root)])
    assert result.exit_code == 0, result.output
    assert "static:ipca" in result.output and "3 series" in result.output
    result = runner.invoke(app, ["search", "selic", "--catalog", str(catalog_root)])
    assert result.exit_code == 0 and "1 match" in result.output


def test_check_on_empty_store_is_not_stale(catalog_root: Path, data_dir: Path) -> None:
    result = runner.invoke(app, ["check", "--catalog", str(catalog_root)])
    assert result.exit_code == 0, result.output
    assert "no_data" in result.output


def test_rebuild_db_and_gc(data_dir: Path) -> None:
    result = runner.invoke(app, ["rebuild-db"])
    assert result.exit_code == 0 and "rebuilt" in result.output
    assert (data_dir / "db" / "econbase.duckdb").exists()
    result = runner.invoke(app, ["gc", "--days", "0"])
    assert result.exit_code == 0 and "0 item(s) removed" in result.output


def test_update_without_connectors_fails_cleanly(catalog_root: Path, data_dir: Path) -> None:
    result = runner.invoke(app, ["update", "--catalog", str(catalog_root)])
    assert result.exit_code == 1
    assert "no connector registered" in result.output


def test_bad_catalog_path(data_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["list", "--catalog", str(tmp_path / "missing")])
    assert result.exit_code == 1
