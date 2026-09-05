"""A page that shows the base to a person, and says where to look first.

Sixty-nine charts are not a way to check sixty-nine series. What finds a wrong unit, a broken
connector or a series that quietly stopped is an audit that ranks them, so the reader spends
attention where something is off rather than scrolling.

The page is one self-contained HTML file with its data inlined: no server, no network, and it
opens from a pen drive. Everything the store holds is fair game locally; publishing it is a
separate decision, because a third of the catalog is marked ``redistributable: false``.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from econbase import pipeline, schemas
from econbase.catalog import Catalog
from econbase.store import Store

MAX_POINTS = 600
#: Below this many observations a robust jump test is noise, not evidence.
MIN_FOR_JUMP = 24
#: A change this many times the series own typical move is worth a human look.
JUMP_FACTOR = 12.0
#: Consecutive identical values that suggest a series stopped moving rather than being stable.
FLAT_RUN = 12

_SEV_ORDER = {"alto": 0, "medio": 1, "baixo": 2}
_MONTHLY = {"D": "MS", "B": "MS", "W": "MS"}


def _sev_rank(sev: str) -> int:
    return _SEV_ORDER.get(sev, 9)


@dataclass(slots=True)
class Finding:
    series_id: str
    kind: str
    severity: str  # alto | medio | baixo
    message: str


@dataclass(slots=True)
class Report:
    generated_at: dt.datetime
    series: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)


def _chart_points(values: pd.DataFrame, freq: str) -> list[list[Any]]:
    """Downsample for display without inventing anything: coarser frequency, then a cap."""
    s = values.set_index("period")["value"].dropna()
    if s.empty:
        return []
    s.index = pd.DatetimeIndex(pd.to_datetime(pd.Series(list(s.index))))
    rule = _MONTHLY.get(freq)
    if rule is not None:
        s = s.resample(rule).last().dropna()
    if len(s) > MAX_POINTS:
        step = int(np.ceil(len(s) / MAX_POINTS))
        s = s.iloc[::step]
    return [[d.date().isoformat(), round(float(v), 6)] for d, v in s.items()]


def _expected_index(start: dt.date, end: dt.date, freq: str) -> pd.DatetimeIndex | None:
    rule = {"M": "MS", "Q": "QS", "A": "YS", "W": "W-MON"}.get(freq)
    if rule is None:
        return None
    return pd.date_range(start, end, freq=rule)


def _audit(series_id: str, spec: Any, obs: pd.DataFrame, freshness: str | None) -> list[Finding]:
    """What is worth a human look, ranked. Silence here is the normal case."""
    out: list[Finding] = []

    if obs.empty:
        out.append(Finding(series_id, "sem_dados", "alto", "nenhuma observacao armazenada"))
        return out

    values = obs["value"].astype(float)
    present = values.dropna()
    if present.empty:
        out.append(
            Finding(series_id, "tudo_nulo", "alto", f"{len(obs)} periodos, nenhum valor numerico")
        )
        return out

    if freshness == "stale":
        out.append(Finding(series_id, "parada", "alto", "ultima observacao alem do prazo esperado"))

    periods = pd.DatetimeIndex(pd.to_datetime(obs["period"]))
    expected = _expected_index(periods.min().date(), periods.max().date(), spec.freq)
    if expected is not None:
        missing = len(expected) - len(periods.unique())
        if missing > 0:
            share = missing / max(len(expected), 1)
            out.append(
                Finding(
                    series_id,
                    "lacuna",
                    "alto" if share > 0.05 else "medio",
                    f"{missing} periodo(s) ausente(s) na grade {spec.freq} ({share:.1%})",
                )
            )

    periods_present = periods[values.notna().to_numpy()]
    if len(present) >= MIN_FOR_JUMP:
        d = present.diff().to_numpy()[1:]
        moves = np.abs(d)
        # Scale of ordinary variation, measured without the candidate spike: dropping the two
        # largest moves stops an outlier from setting the yardstick it is judged against.
        trimmed = np.sort(moves)[:-2] if len(moves) > 2 else moves
        scale = float(np.median(trimmed)) if len(trimmed) else 0.0
        if len(d) >= 2:
            # An isolated spike goes out and comes straight back; a regime change does not, which
            # is why the plain "biggest move" test buried everything under Brazilian inflation in
            # 1990. What survives still cannot tell a corrupted point from a real shock — April
            # 2020 looks exactly like a bad tick — so this is a list to eyeball, not an alarm.
            there, back = d[:-1], d[1:]
            reverts = np.where(
                np.sign(there) * np.sign(back) < 0, np.minimum(abs(there), abs(back)), 0.0
            )
            worst = float(reverts.max()) if len(reverts) else 0.0
            # With no ordinary variation at all — a rate that never moved — any move out and back
            # is by definition unusual, and dividing by zero would hide it.
            unusual = worst > JUMP_FACTOR * scale if scale > 0 else worst > 0
            if unusual:
                pos = int(np.argmax(reverts)) + 1
                stamp = str(periods_present[pos].date()) if pos < len(periods_present) else "?"
                times = f", {worst / scale:.0f}x o tipico" if scale > 0 else ", numa serie parada"
                out.append(
                    Finding(
                        series_id,
                        "pico_isolado",
                        "baixo",
                        f"movimento isolado de {worst:,.4g} em {stamp}{times} "
                        "— confira se e real (abril de 2020 e 1990 aparecem aqui legitimamente)",
                    )
                )

    # A flat stretch is only news when it is unusual *for this series*. A policy rate held for a
    # year is policy; the same run in an activity index is a connector that stopped.
    runs_len, prev, run = [], None, 0
    for v in present.to_numpy():
        if prev is not None and v == prev:
            run += 1
        else:
            if run:
                runs_len.append(run)
            run = 1
        prev = v
    trailing = run
    historical = max(runs_len[:-1], default=0) if runs_len else 0
    if trailing >= FLAT_RUN and trailing > max(historical, FLAT_RUN - 1):
        out.append(
            Finding(
                series_id,
                "estagnada",
                "medio",
                f"ultimos {trailing} valores identicos ({present.iloc[-1]:,.6g}); "
                f"a maior sequencia anterior foi {historical}",
            )
        )

    return out


def collect(store: Store, catalog: Catalog, *, today: dt.date | None = None) -> Report:
    """Everything the page needs, as plain Python data."""
    today = today or dt.date.today()
    obs = schemas.to_pandas(store.read("observations"))
    stored = schemas.to_pandas(store.read("series"))
    fresh = pipeline.check(store, catalog, today=today)
    fresh_by_id: dict[str, str] = (
        dict(zip(fresh["series_id"], fresh["status"], strict=True)) if len(fresh) else {}
    )

    latest = obs[obs["realtime_end"].isna()] if len(obs) else obs
    report = Report(generated_at=dt.datetime.now(dt.UTC))

    for series_id, spec in sorted(catalog.series.items()):
        mine = (
            latest[latest["series_id"] == series_id].sort_values("period")
            if len(latest)
            else latest
        )
        every = obs[obs["series_id"] == series_id] if len(obs) else obs
        revisions = int(len(every) - len(mine))
        status = fresh_by_id.get(series_id)
        findings = _audit(series_id, spec, mine, status)
        report.findings.extend(findings)

        row = stored[stored["series_id"] == series_id] if len(stored) else stored
        values = mine["value"].astype(float).dropna() if len(mine) else pd.Series(dtype=float)
        report.series.append(
            {
                "series_id": series_id,
                "title": spec.title,
                "concept": spec.concept_id,
                "entity": spec.entity_id,
                "source": spec.source,
                "unit": spec.unit,
                "freq": spec.freq,
                "seasonal_adj": bool(spec.seasonal_adj),
                "license": spec.license,
                "redistributable": bool(spec.redistributable),
                "source_url": spec.source_url,
                "expected_lag_days": spec.expected_lag_days,
                "status": status or "desconhecido",
                "n_obs": len(mine),
                "revisions": revisions,
                "first_period": str(mine["period"].min()) if len(mine) else None,
                "last_period": str(mine["period"].max()) if len(mine) else None,
                "last_value": float(values.iloc[-1]) if len(values) else None,
                "min": float(values.min()) if len(values) else None,
                "max": float(values.max()) if len(values) else None,
                "last_updated": str(row.iloc[0]["last_updated"]) if len(row) else None,
                "points": _chart_points(mine[["period", "value"]], spec.freq) if len(mine) else [],
                "findings": [f.kind for f in findings],
                "worst": min((f.severity for f in findings), key=_sev_rank, default=None),
            }
        )

    runs = schemas.to_pandas(store.read("runs"))
    if len(runs):
        recent = runs.sort_values("started_at", ascending=False).head(10)
        report.runs = [
            {
                "run_id": r["run_id"],
                "started_at": str(r["started_at"]),
                "trigger": r["trigger"],
                "status": r["status"],
                "n_series": int(r["n_series"]),
                "n_errors": int(r["n_errors"]),
            }
            for _, r in recent.iterrows()
        ]

    report.totals = {
        "series": len(report.series),
        "observations": len(obs),
        "open_intervals": len(latest),
        "sources": len({s["source"] for s in report.series}),
        "findings": len(report.findings),
        "high": sum(1 for f in report.findings if f.severity == "alto"),
        "stale": sum(1 for s in report.series if s["status"] == "stale"),
        "earliest": min(
            (s["first_period"] for s in report.series if s["first_period"]), default=None
        ),
        "latest": max((s["last_period"] for s in report.series if s["last_period"]), default=None),
    }
    return report


def payload_for(report: Report, *, redistributable_only: bool = False) -> dict[str, Any]:
    """The JSON the page reads. Restricted series lose their values, never their metadata."""
    return {
        "generated_at": report.generated_at.isoformat(timespec="seconds"),
        "totals": report.totals,
        "runs": report.runs,
        "findings": [
            {
                "series_id": f.series_id,
                "kind": f.kind,
                "severity": f.severity,
                "message": f.message,
            }
            for f in sorted(report.findings, key=lambda f: (_sev_rank(f.severity), f.series_id))
        ],
        "series": [
            {
                **s,
                "points": []
                if (redistributable_only and not s["redistributable"])
                else s["points"],
            }
            for s in report.series
        ],
        "trimmed": redistributable_only,
    }


def build(
    store: Store,
    catalog: Catalog,
    out_path: Path,
    *,
    today: dt.date | None = None,
    redistributable_only: bool = False,
) -> Path:
    """Write the page as one self-contained file and return its path."""
    report = collect(store, catalog, today=today)
    data = payload_for(report, redistributable_only=redistributable_only)
    template = (Path(__file__).parent / "report_template.html").read_text(encoding="utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        template.replace("__DATA__", json.dumps(data, default=str, ensure_ascii=False)),
        encoding="utf-8",
    )
    return out_path
