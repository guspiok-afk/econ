"""``econbase`` command line: update | check | rebuild-db | gc | list | search | init.

Every command is idempotent and returns a non-zero exit code on failure, so the scheduler
scripts can chain them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer

from econbase import __version__
from econbase.catalog import Catalog, CatalogError
from econbase.settings import Settings, get_settings
from econbase.store import Store, StoreError

app = typer.Typer(
    help="Open-data economic database with real-time vintages.",
    no_args_is_help=True,
    add_completion=False,
)

CatalogOpt = Annotated[
    Path, typer.Option("--catalog", help="Catalog directory (YAML).", show_default=True)
]


def _catalog(path: Path) -> Catalog:
    try:
        return Catalog.load(path)
    except CatalogError as exc:
        typer.secho(f"catalog error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


def _store(settings: Settings) -> Store:
    return Store(settings.data_dir)


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


@app.command()
def init() -> None:
    """Create the data directory layout and print the paths in use."""
    settings = get_settings()
    store = _store(settings)
    typer.echo(f"data dir : {store.data_dir}")
    typer.echo(f"raw      : {store.raw_dir}")
    typer.echo(f"lake     : {store.lake_dir}")
    typer.echo(f"db       : {store.db_path}")
    typer.echo(f"tz       : {settings.econbase_tz}")
    typer.echo(f"fred key : {'set' if settings.fred_api_key else 'missing'}")


@app.command("list")
def list_(
    catalog: CatalogOpt = Path("catalog"),
    source: Annotated[str | None, typer.Option(help="Only this source.")] = None,
) -> None:
    """List catalog series (id, entity, concept, freq, title)."""
    cat = _catalog(catalog)
    specs = cat.by_source(source) if source else list(cat.series.values())
    if not specs:
        typer.echo("no series in catalog")
        return
    width = max(len(s.series_id) for s in specs)
    for s in sorted(specs, key=lambda s: s.series_id):
        typer.echo(
            f"{s.series_id:<{width}}  {s.entity_id}  {s.freq}  {s.concept_id or '-':<28}  {s.title}"
        )
    typer.echo(f"{len(specs)} series, {len(cat.sources)} sources, catalog {cat.catalog_hash[:12]}")


@app.command()
def search(text: str, catalog: CatalogOpt = Path("catalog")) -> None:
    """Case-insensitive search over id, title, concept and unit."""
    cat = _catalog(catalog)
    needle = text.lower()
    hits = [
        s
        for s in cat.series.values()
        if needle in s.series_id.lower()
        or needle in s.title.lower()
        or needle in (s.concept_id or "").lower()
        or needle in s.unit.lower()
    ]
    for s in sorted(hits, key=lambda s: s.series_id):
        typer.echo(f"{s.series_id}  {s.entity_id}  {s.freq}  {s.title}")
    typer.echo(f"{len(hits)} match(es)")


@app.command()
def check(
    catalog: CatalogOpt = Path("catalog"),
    fail_on_stale: Annotated[bool, typer.Option(help="Exit 2 when any series is stale.")] = True,
) -> None:
    """Report freshness per series against expected publication lags."""
    from econbase import pipeline

    settings = get_settings()
    cat = _catalog(catalog)
    report = pipeline.check(_store(settings), cat)
    if report.empty:
        typer.echo("no series in catalog")
        return
    typer.echo(report.to_string(index=False))
    counts = report["status"].value_counts().to_dict()
    typer.echo(f"summary: {counts}")
    if fail_on_stale and counts.get("stale", 0) > 0:
        raise typer.Exit(code=2)


@app.command()
def update(
    catalog: CatalogOpt = Path("catalog"),
    source: Annotated[list[str] | None, typer.Option(help="Only these sources.")] = None,
    series: Annotated[list[str] | None, typer.Option(help="Only these series ids.")] = None,
    trigger: Annotated[str, typer.Option(help="manual | scheduler | ci")] = "manual",
) -> None:
    """Fetch every selected series, archive raw bodies, apply bitemporal diffs, commit one run."""
    from econbase import pipeline
    from econbase.sources import build_registry

    settings = get_settings()
    cat = _catalog(catalog)
    store = _store(settings)
    registry = build_registry(settings)
    summary = pipeline.update(
        store,
        cat,
        registry,
        series_ids=series or None,
        source_names=source or None,
        tz=settings.econbase_tz,
        trigger=trigger,
        package_version=__version__,
        git_sha=_git_sha(),
    )
    frame = summary.to_frame()
    if not frame.empty:
        cols = ["series_id", "rows_fetched", "rows_new", "rows_revised", "rows_closed", "error"]
        typer.echo(frame[cols].to_string(index=False))
    typer.echo(
        f"run {summary.run_id} ({summary.status}): "
        f"{len(summary.outcomes)} series, {summary.n_errors} error(s)"
    )
    if summary.n_errors:
        raise typer.Exit(code=1)


@app.command("rebuild-db")
def rebuild_db() -> None:
    """Recreate the DuckDB view cache from the manifest."""
    settings = get_settings()
    try:
        path = _store(settings).rebuild_db()
    except StoreError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    typer.echo(f"rebuilt {path}")


@app.command()
def gc(
    days: Annotated[int, typer.Option(help="Delete unreferenced files older than N days.")] = 7,
) -> None:
    """Delete Parquet files no manifest references (and stale staging dirs)."""
    settings = get_settings()
    deleted = _store(settings).gc(older_than_days=days)
    for p in deleted:
        typer.echo(f"deleted {p}")
    typer.echo(f"{len(deleted)} item(s) removed")


if __name__ == "__main__":  # pragma: no cover
    app()
