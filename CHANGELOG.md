# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-13

### Added

- Column kind inference over raw CSV cells: `int`, `float`, `date`,
  `datetime`, `categorical`, `text`, and `empty`, with conservative
  rule-ordered detection (zero-padded numbers stay text, `inf`/`nan`
  spellings are rejected, one strftime format must fit every cell).
- Versioned JSON profile format (`datadouble/profile`, version 1) storing
  per column: null rate, observed null token, uniqueness flag, and one
  statistical summary — quantile grid, value frequency table, or
  structure-mask table. Free-text values are never stored verbatim.
- Deterministic generation with per-column random streams derived from
  SHA-256 of (seed, column name, purpose): twins are byte-identical per
  seed, independent of column order, prefix-stable when the row count
  grows, and re-rolling a null rate never reshuffles the non-null values.
- Distribution-faithful samplers: inverse-CDF over empirical quantile
  grids for numbers and dates (decimal precision and strftime format
  preserved), frequency-proportional resampling for categoricals, and
  mask filling with fresh characters for text, with best-effort
  uniqueness enforcement for integer and text key columns.
- Twin-vs-original comparison engine: normalized quantile shift for
  numeric/temporal columns, total variation distance for categorical
  values and text masks, null-rate deltas, configurable tolerances, and
  an aligned plain-text report.
- `datadouble` CLI with four subcommands: `profile`, `twin`, `generate`
  (rebuild a twin from the profile alone), and `compare` (exit 1 on
  drift, for CI gates). Delimiter sniffing for `,` `;` tab and `|`,
  UTF-8 BOM handling, and structural CSV validation with line numbers.
- Runnable example (`examples/orders.csv` + `examples/twin_demo.py`) and
  a documented profile schema in `docs/profile-format.md`.
- 95 deterministic, offline tests and `scripts/smoke.sh`, an end-to-end
  CLI smoke test that prints `SMOKE OK`.

### Notes

- The repository ships no CI workflow; verification is local —
  `pip install -e '.[dev]' && pytest && bash scripts/smoke.sh`.
- Columns are modeled independently in this release; cross-column
  correlations are not preserved.

[0.1.0]: https://github.com/JaydenCJ/datadouble/releases/tag/v0.1.0
