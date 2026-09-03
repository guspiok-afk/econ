# ADR-0006 — Two packages in one repository, one pyproject, dict registries

Date: 2026-09-03 · Status: accepted

## Context
The analyses dictate which series enter the catalog and this changes weekly at the start;
separate repositories would create versioning friction. A three-package uv workspace with
entry points and semantic-release solves a distribution problem for a team and sibling repos
that do not exist yet.

## Decision
`src/econbase` (data) and `src/econmodels` (analyses) in one `pyproject.toml`. `econmodels`
imports only `econbase.api` and `econbase.schemas`. Connectors and models register in plain
dict registries. Analysis-heavy dependencies live in optional extras.

## Trigger to split
A sibling repository needs to pin `econbase` independently, or a second contributor appears.
Then move `src/econbase` to `packages/econbase/src/econbase` (import paths unchanged) as a uv
workspace member (~3 h).
