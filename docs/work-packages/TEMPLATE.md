# WP-NN — <short title>

| Field | Value |
|---|---|
| Status | draft / ready / in progress / in review / done |
| Suggested executor | `agent:claude` / `agent:jules` / `agent:antigravity` / `agent:ollama` |
| Branch | `wp/NN-<slug>` |
| Issue | #<number> |
| Depends on | WP-.. (or none) |
| Estimated effort | <hours> |

## Goal

One paragraph. What exists after this WP that did not exist before, and why it matters
for the project (which analysis or capability it unlocks).

## Contract

Exact public surface the WP must implement. Signatures, dataclasses, schemas, CLI flags,
YAML keys. Copy from `docs/CONTRACT.md` where applicable; do not paraphrase.

```python
# example
class SidraSource(Source):
    def fetch_raw(self, spec: SeriesSpec, since: date | None) -> RawResponse: ...
    def parse(self, raw: RawResponse, spec: SeriesSpec) -> pd.DataFrame: ...
```

Output shape (columns, dtypes, conventions that apply, e.g. `period` = period start).

## Files you may change

- `src/econbase/sources/<name>.py` (new)
- `catalog/br/<name>.yaml`
- `tests/fixtures/<name>/*`

Everything else is out of scope. Protected files (AGENTS.md §3) are never in this list.

## Acceptance tests (already in the repository, currently failing)

- `tests/test_<name>.py::test_...` — what it checks.
- `tests/test_<name>.py::test_...` — what it checks.

Run: `uv run pytest tests/test_<name>.py -q`

## Fixtures and data

How to record the HTTP fixtures (`respx`), which requests, where they live. Which catalog
entries to add, with `license`, `redistributable`, `expected_lag_days`, `freq`, `unit`.

## Definition of done

- [ ] Acceptance tests pass; full suite green; `ruff check` and `ruff format --check` clean
- [ ] Only listed files changed; no new dependencies beyond those listed here: <none>
- [ ] Docstrings on public functions
- [ ] Fixtures recorded and committed
- [ ] "Result" section below filled in
- [ ] PR opened to `main` with this WP linked

## Notes for the executor

Pitfalls, source quirks (rate limits, chunking windows, encoding), references to methodology
docs, decisions already taken that must not be revisited.

## Result (filled in by the executor)

What was delivered, deviations from the contract (should be none), open questions for the
architect, follow-up WPs suggested.
