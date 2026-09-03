"""Parquet-as-truth store with atomic manifest promotion and a disposable DuckDB view cache.

Rules (ADR-0001):

* Every table is a set of Parquet files listed in ``lake/manifest.json``. Readers resolve
  files from the manifest, never by globbing.
* Writers stage files under ``lake/_staging/<run_id>/`` and, on commit, move them into place
  and swap the manifest atomically. Files are never modified in place; old files stay until
  :meth:`Store.gc`.
* ``observations`` is partitioned by ``source``
  (``observations/source=<src>/part-<run_id>.parquet``); each partition is
  rewritten whole. Other tables are single-file and rewritten whole.
* ``db/econbase.duckdb`` contains only views over the manifest files and is rebuilt on demand.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from econbase import schemas

log = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
DB_NAME = "econbase.duckdb"
LOCK_NAME = ".writer.lock"


class StoreError(RuntimeError):
    """Storage-level failure (lock, corrupt manifest, unknown table, ...)."""


@dataclass
class Manifest:
    """The list of live files per table plus provenance of the last commit."""

    schema_version: str = schemas.SCHEMA_VERSION
    catalog_hash: str | None = None
    run_id: str | None = None
    created_at: str | None = None
    files: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            prev = path.with_name(f"{path.name}.prev")
            raise StoreError(
                f"corrupt manifest {path}: {exc}. "
                + (
                    f"Recover the previous run with: copy {prev} to {path}"
                    if prev.exists()
                    else "No .prev backup found; rebuild from raw/ or the backup copy."
                )
            ) from exc
        return cls(
            schema_version=data.get("schema_version", schemas.SCHEMA_VERSION),
            catalog_hash=data.get("catalog_hash"),
            run_id=data.get("run_id"),
            created_at=data.get("created_at"),
            files={k: sorted(v) for k, v in (data.get("files") or {}).items()},
        )

    def dump(self, path: Path) -> None:
        """Write durably: fsynced temp file, previous manifest kept, then ``os.replace``.

        The ``.prev`` copy is the recovery path if a crash between write and rename ever
        leaves the live manifest unreadable (:meth:`load` falls back to it).
        """
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(self), indent=2, sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            try:
                shutil.copy2(path, path.with_name(f"{path.name}.prev"))
            except OSError:  # a missing backup must never block a valid commit
                log.warning("could not refresh %s.prev", path.name)
        os.replace(tmp, path)

    def files_for(self, table: str) -> list[str]:
        return list(self.files.get(table, []))

    def all_files(self) -> set[str]:
        return {f for files in self.files.values() for f in files}


def _duck_type(t: pa.DataType) -> str:
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        return "VARCHAR"
    if pa.types.is_date(t):
        return "DATE"
    if pa.types.is_floating(t):
        return "DOUBLE"
    if pa.types.is_int32(t):
        return "INTEGER"
    if pa.types.is_integer(t):
        return "BIGINT"
    if pa.types.is_boolean(t):
        return "BOOLEAN"
    if pa.types.is_timestamp(t):
        return "TIMESTAMPTZ" if t.tz else "TIMESTAMP"
    if pa.types.is_list(t):
        return f"{_duck_type(t.value_type)}[]"
    raise StoreError(f"no DuckDB type mapping for {t}")


def _as_id_list(series_ids: Iterable[str]) -> list[str]:
    """Series-id filters must be a collection, never a bare string (which would iterate chars)."""
    if isinstance(series_ids, str):
        raise StoreError(f"series_ids must be a collection, got the string {series_ids!r}")
    return list(series_ids)


def _fsync_file(path: Path) -> None:
    """Best-effort flush of a closed file to disk (Windows needs a writable handle)."""
    try:
        with open(path, "r+b") as fh:
            os.fsync(fh.fileno())
    except OSError as exc:  # never fail a write because the platform refused an fsync
        log.debug("fsync skipped for %s: %s", path, exc)


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


class WriterLock:
    """Exclusive, advisory lock for the single writer (ADR-0003).

    One process at a time may write the lake. The lock is a file created with ``O_EXCL``; it
    records the pid and run id so a leftover lock names its owner. A lock older than
    ``stale_after`` is taken over (a crashed run never blocks the scheduler forever).
    """

    def __init__(self, path: Path, *, run_id: str, stale_after: dt.timedelta | None = None) -> None:
        self.path = path
        self.run_id = run_id
        self.stale_after = stale_after or dt.timedelta(hours=6)
        self._held = False

    def _payload(self) -> str:
        return json.dumps(
            {
                "pid": os.getpid(),
                "run_id": self.run_id,
                "acquired_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            }
        )

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = dt.datetime.now(dt.UTC).timestamp() - self.path.stat().st_mtime
            if age <= self.stale_after.total_seconds():
                try:
                    owner = self.path.read_text(encoding="utf-8").strip()
                except OSError:
                    owner = "unknown"
                raise StoreError(
                    f"another writer holds {self.path} ({owner}); "
                    "wait for it to finish, or delete the file if no update is running"
                ) from None
            log.warning("taking over stale writer lock %s (age %.0f s)", self.path, age)
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(self._payload())
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        self._held = False

    def __enter__(self) -> WriterLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class Store:
    """Access to one data directory. Cheap to construct; holds no open connections."""

    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw"
        self.lake_dir = self.data_dir / "lake"
        self.db_dir = self.data_dir / "db"
        self.staging_dir = self.lake_dir / "_staging"
        for d in (self.raw_dir, self.lake_dir, self.db_dir, self.staging_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ manifest & files
    @property
    def manifest_path(self) -> Path:
        return self.lake_dir / MANIFEST_NAME

    @property
    def db_path(self) -> Path:
        return self.db_dir / DB_NAME

    @property
    def lock_path(self) -> Path:
        """Writer lock: held by the single process allowed to modify the lake."""
        return self.lake_dir / LOCK_NAME

    def manifest(self) -> Manifest:
        return Manifest.load(self.manifest_path)

    def files(self, table: str, partition: str | None = None) -> list[Path]:
        """Absolute paths of the live files of ``table`` (optionally one ``col=value`` partition).

        Partition paths are matched by prefix; hive auto-detection is disabled on read.
        """
        if table not in schemas.TABLES:
            raise StoreError(f"unknown table {table!r}")
        rels = self.manifest().files_for(table)
        if partition is not None:
            prefix = f"{table}/{partition}/"
            rels = [r for r in rels if r.startswith(prefix)]
        return [self.lake_dir / r for r in rels]

    # ------------------------------------------------------------------ reading
    def _select_sql(self, table: str, files: Sequence[Path]) -> str:
        schema = schemas.TABLES[table]
        if not files:
            cols = ", ".join(f'CAST(NULL AS {_duck_type(f.type)}) AS "{f.name}"' for f in schema)
            return f"SELECT {cols} WHERE false"
        lst = ", ".join(_sql_str(p.as_posix()) for p in files)
        return (
            f"SELECT * FROM read_parquet([{lst}], union_by_name = true, hive_partitioning = false)"
        )

    def _install_views(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("SET TimeZone = 'UTC'")
        for table in schemas.TABLES:
            con.execute(
                f'CREATE OR REPLACE VIEW "{table}" AS {self._select_sql(table, self.files(table))}'
            )
        con.execute(
            "CREATE OR REPLACE VIEW obs_latest AS "
            "SELECT * FROM observations WHERE realtime_end IS NULL"
        )
        con.execute(
            "CREATE OR REPLACE VIEW obs_first_release AS "
            "SELECT * FROM observations "
            "QUALIFY row_number() OVER (PARTITION BY series_id, period "
            "ORDER BY realtime_start) = 1"
        )
        con.execute(
            "CREATE OR REPLACE MACRO obs_asof(d) AS TABLE "
            "SELECT * FROM observations WHERE realtime_start <= d "
            "AND (realtime_end IS NULL OR realtime_end > d)"
        )

    def connect(self) -> duckdb.DuckDBPyConnection:
        """In-memory connection with every table view and the as-of macro installed."""
        con = duckdb.connect()
        self._install_views(con)
        return con

    def query(self, sql: str, params: Sequence[object] | None = None) -> pa.Table:
        """Run SQL against the views and return Arrow."""
        con = self.connect()
        try:
            return con.execute(sql, list(params) if params else None).to_arrow_table()
        finally:
            con.close()

    def read(self, table: str, *, partition: str | None = None) -> pa.Table:
        """Whole table (or one partition) as Arrow, cast to the contract schema."""
        files = self.files(table, partition)
        con = duckdb.connect()
        try:
            con.execute("SET TimeZone = 'UTC'")
            result = con.execute(self._select_sql(table, files)).to_arrow_table()
        finally:
            con.close()
        return schemas.ensure_schema(result, schemas.TABLES[table], table)

    def observations(
        self,
        series_ids: Iterable[str] | None = None,
        *,
        asof: dt.date | None = None,
        include_history: bool = False,
    ) -> pa.Table:
        """Observations: current values by default, as of a date, or the full bitemporal history."""
        where: list[str] = []
        params: list[object] = []
        if series_ids is not None:
            ids = _as_id_list(series_ids)
            if not ids:
                return schemas.empty_table(schemas.OBSERVATIONS)
            where.append("series_id IN (" + ", ".join("?" for _ in ids) + ")")
            params.extend(ids)
        if include_history:
            src = "observations"
        elif asof is not None:
            src = "obs_asof(?)"
            params.insert(0, asof)
        else:
            src = "obs_latest"
        sql = f"SELECT * FROM {src}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY series_id, period, realtime_start"
        return schemas.ensure_schema(self.query(sql, params), schemas.OBSERVATIONS, "observations")

    def first_release(self, series_ids: Iterable[str] | None = None) -> pa.Table:
        """The row as first published per (series, period), including a NULL first value."""
        sql = "SELECT * FROM obs_first_release"
        params: list[object] = []
        if series_ids is not None:
            ids = _as_id_list(series_ids)
            if not ids:
                return schemas.empty_table(schemas.OBSERVATIONS)
            sql += " WHERE series_id IN (" + ", ".join("?" for _ in ids) + ")"
            params.extend(ids)
        result = self.query(sql + " ORDER BY series_id, period", params)
        return schemas.ensure_schema(result, schemas.OBSERVATIONS, "observations")

    # ------------------------------------------------------------------ writing
    def transaction(self, *, run_id: str, catalog_hash: str | None = None) -> Transaction:
        return Transaction(self, run_id=run_id, catalog_hash=catalog_hash)

    def rebuild_db(self) -> Path:
        """Recreate ``db/econbase.duckdb`` with views over the current manifest."""
        for p in (self.db_path, self.db_path.with_suffix(".duckdb.wal")):
            if p.exists():
                try:
                    p.unlink()
                except PermissionError as exc:
                    raise StoreError(
                        f"{p} is open in another process; close readers and retry"
                    ) from exc
        con = duckdb.connect(str(self.db_path))
        try:
            self._install_views(con)
        finally:
            con.close()
        return self.db_path

    def gc(self, *, older_than_days: int = 7, now: dt.datetime | None = None) -> list[Path]:
        """Delete Parquet files no manifest references and stale staging dirs older than N days.

        Runs under the writer lock so a concurrent commit cannot have its just-promoted files
        judged against a manifest read a moment earlier.
        """
        now = now or dt.datetime.now(dt.UTC)
        cutoff = now.timestamp() - older_than_days * 86400
        deleted: list[Path] = []
        with WriterLock(self.lock_path, run_id=f"gc-{int(now.timestamp())}"):
            live = self.manifest().all_files()
            for path in self.lake_dir.rglob("*.parquet"):
                if self.staging_dir in path.parents:
                    continue
                rel = path.relative_to(self.lake_dir).as_posix()
                if rel in live:
                    continue
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted.append(path)
            for d in list(self.staging_dir.iterdir()) if self.staging_dir.exists() else []:
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    deleted.append(d)
            for tmp in self.lake_dir.glob(f"{MANIFEST_NAME}.tmp-*"):
                if tmp.stat().st_mtime < cutoff:
                    tmp.unlink()
                    deleted.append(tmp)
        return deleted


class Transaction:
    """Stage files for one run, then promote them with a single atomic manifest swap.

    Use as a context manager: a clean exit commits, an exception rolls back.
    """

    def __init__(self, store: Store, *, run_id: str, catalog_hash: str | None) -> None:
        self.store = store
        self.run_id = run_id
        self.catalog_hash = catalog_hash
        self._lock = WriterLock(store.lock_path, run_id=run_id)
        self._lock.acquire()
        try:
            # optimistic guard: the manifest must not move under us between here and commit
            self._base_run_id = store.manifest().run_id
            self.staging = store.staging_dir / run_id
            self.staging.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._lock.release()
            raise
        self._staged: list[tuple[Path, str]] = []  # (staged path, final relative path)
        self._replace_prefixes: dict[str, set[str]] = {}  # table -> prefixes replaced
        self.committed = False

    def _stage(self, table: str, rel: str, data: pa.Table) -> None:
        data = schemas.ensure_schema(data, schemas.TABLES[table], table)
        staged = self.staging / rel
        staged.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(data, staged, compression="zstd")
        _fsync_file(staged)  # durable before any manifest can point at it
        self._staged.append((staged, rel))

    def replace_partition(self, table: str, value: str, data: pa.Table) -> None:
        """Replace all files of one ``col=value`` partition with ``data``."""
        col = schemas.PARTITIONED.get(table)
        if col is None:
            raise StoreError(f"table {table!r} is not partitioned")
        prefix = f"{table}/{col}={value}/"
        self._stage(table, f"{prefix}part-{self.run_id}.parquet", data)
        self._replace_prefixes.setdefault(table, set()).add(prefix)

    def replace_table(self, table: str, data: pa.Table) -> None:
        """Replace every file of a non-partitioned table with a single new file."""
        if table in schemas.PARTITIONED:
            raise StoreError(f"table {table!r} is partitioned; use replace_partition")
        self._stage(table, f"{table}/part-{self.run_id}.parquet", data)
        self._replace_prefixes.setdefault(table, set()).add(f"{table}/")

    def append_table(self, table: str, data: pa.Table) -> None:
        """Append rows to a non-partitioned table (read current + concat + replace)."""
        current = self.store.read(table)
        data = schemas.ensure_schema(data, schemas.TABLES[table], table)
        combined = pa.concat_tables([current, data]) if current.num_rows else data
        self.replace_table(table, combined)

    def commit(self) -> Manifest:
        if self.committed:
            raise StoreError("transaction already committed")
        manifest = self.store.manifest()
        if manifest.run_id != self._base_run_id:
            raise StoreError(
                f"the manifest changed during this run (was {self._base_run_id!r}, "
                f"now {manifest.run_id!r}); another writer committed. Refusing to overwrite it."
            )
        # 1. move staged files into the lake (new names, never overwriting live files)
        for staged, rel in self._staged:
            final = self.store.lake_dir / rel
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, final)
        # 2. compute the new file lists
        files = {t: list(v) for t, v in manifest.files.items()}
        for table, prefixes in self._replace_prefixes.items():
            kept, dropped = [], []
            for f in files.get(table, []):
                (dropped if any(f.startswith(p) for p in prefixes) else kept).append(f)
            files[table] = kept
            for rel in dropped:  # gc ages orphans from when they became garbage, not from write
                orphan = self.store.lake_dir / rel
                if orphan.exists():
                    with contextlib.suppress(OSError):
                        os.utime(orphan, None)
        for _, rel in self._staged:
            table = rel.split("/", 1)[0]
            files.setdefault(table, []).append(rel)
        for t in files:
            files[t] = sorted(set(files[t]))
        # 3. atomic manifest swap
        new = Manifest(
            schema_version=schemas.SCHEMA_VERSION,
            catalog_hash=self.catalog_hash
            if self.catalog_hash is not None
            else manifest.catalog_hash,
            run_id=self.run_id,
            created_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            files=files,
        )
        new.dump(self.store.manifest_path)
        self.committed = True
        shutil.rmtree(self.staging, ignore_errors=True)
        self._lock.release()
        return new

    def rollback(self) -> None:
        shutil.rmtree(self.staging, ignore_errors=True)
        self._lock.release()

    def __enter__(self) -> Transaction:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.rollback()
            return
        if not self.committed:
            self.commit()
