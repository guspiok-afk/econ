# ADR-0004 — DSGE in Python; Julia out of scope with explicit adoption triggers

Date: 2026-09-03 · Status: accepted

## Context
Research on 2026-09-03: adding Julia costs 75–155 h fixed plus 3–6 h/month, 3–5 GB disk,
10–25 min cold precompile, and benefits only the DSGE module (MacroModelling.jl is the one
mature, active package, single maintainer). For DFM, BVAR/SVAR, local projections and X-13,
Python is stronger. The data layer cannot move (FredData.jl 2018, DBnomics.jl 2022, no SIDRA
client). First-order solve gains are 1.5–3.9× on sub-millisecond solves.

## Decision
DSGE in Python: gEconpy first, fallback a ~200-line gensys/Klein solver on statsmodels
`MLEModel`/PyMC, cross-validated against Dynare 7.1 on Octave. `econmodels[dsge]` is an
optional extra.

## Triggers to reopen
(a) second/third-order perturbation with gradient-based estimation; (b) estimation with
occasionally binding constraints (ZLB); (c) need for a ready library of medium-scale models
(SW07, NAWM). If adopted: Julia only in the DSGE module, Parquet as the interface, separate
Linux CI job, pinned `Project.toml`/`Manifest.toml` and juliaup version.
