"""Deterministic sampling of synthetic rows from a table profile.

Given a :class:`~datadouble.profile.TableProfile` and a seed, this module
emits string cells that follow each column's recorded distribution:

- numeric and temporal columns invert their quantile grid (inverse-CDF
  sampling), so skew and heavy tails survive without any fitted model;
- categorical columns resample their exact value table;
- text columns pick a structure mask by frequency and fill it with fresh
  random characters — shape survives, the original strings do not.

Determinism contract (see :mod:`datadouble.rng`): same profile + same seed
+ same row count means byte-identical output, on any machine. Each column
draws from two independent streams (null placement and values), keyed by
column name, so twins are also *prefix-stable*: generating 1,000 rows and
then 10,000 rows with the same seed agrees on the first 1,000.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta
from itertools import accumulate
from random import Random
from typing import Any, Callable, List, Optional, Tuple

from .errors import GenerationError
from .profile import EPOCH, ColumnProfile, TableProfile
from .rng import derive_rng
from .stats import sample_quantile_grid

__all__ = ["generate_rows", "generate_table"]

_LOWER = "abcdefghijklmnopqrstuvwxyz"
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DIGITS = "0123456789"

# How many fresh samples a unique column tries before falling back to a
# deterministic repair (increment for ints, numeric suffix for text).
_UNIQUE_RETRIES = 32

_MIN_ORDINAL = 1
_MAX_ORDINAL = date.max.toordinal()
_MIN_SECONDS = (datetime.min - EPOCH).total_seconds() + 1
_MAX_SECONDS = (datetime.max - EPOCH).total_seconds() - 1

_Sampler = Callable[[Random], str]


def generate_table(
    profile: TableProfile, rows: Optional[int] = None, seed: int = 0
) -> Tuple[List[str], List[List[str]]]:
    """Generate ``(header, rows)`` for a whole profile.

    ``rows`` defaults to the source table's row count, so a twin is
    the same size as the original unless you ask otherwise.
    """
    n = profile.rows if rows is None else rows
    return [col.name for col in profile.columns], generate_rows(profile, n, seed)


def generate_rows(
    profile: TableProfile, rows: int, seed: int = 0
) -> List[List[str]]:
    """Generate ``rows`` synthetic rows (lists of string cells)."""
    if rows < 0:
        raise GenerationError(f"rows must be >= 0, got {rows}")
    columns = [_generate_column(col, rows, seed) for col in profile.columns]
    if not columns:
        raise GenerationError("profile has no columns")
    return [list(cells) for cells in zip(*columns)]


def _generate_column(col: ColumnProfile, rows: int, seed: int) -> List[str]:
    # Independent streams: re-rolling null placement (a different null_rate)
    # must never reshuffle the sequence of non-null values, and vice versa.
    null_rng = derive_rng(seed, col.name, "null")
    value_rng = derive_rng(seed, col.name, "value")
    sampler = _make_sampler(col)

    # Uniqueness is enforced best-effort where it matters (IDs, keys) and
    # can be repaired without breaking the column's format.
    enforce_unique = col.unique and col.kind in ("int", "text")
    seen: set = set()

    out: List[str] = []
    for _ in range(rows):
        if null_rng.random() < col.null_rate:
            out.append(col.null_token)
            continue
        value = sampler(value_rng)
        if enforce_unique:
            value = _dedupe(value, sampler, value_rng, seen, col.kind)
            seen.add(value)
        out.append(value)
    return out


def _dedupe(
    value: str, sampler: _Sampler, rng: Random, seen: set, kind: str
) -> str:
    if value not in seen:
        return value
    for _ in range(_UNIQUE_RETRIES):
        value = sampler(rng)
        if value not in seen:
            return value
    if kind == "int":
        n = int(value)
        while str(n) in seen:
            n += 1
        return str(n)
    suffix = 2
    while f"{value}-{suffix}" in seen:
        suffix += 1
    return f"{value}-{suffix}"


# --------------------------------------------------------------------------
# Per-kind samplers


def _make_sampler(col: ColumnProfile) -> _Sampler:
    """Compile a column profile into a value sampler.

    Raises :class:`GenerationError` for internally inconsistent payloads
    (which :func:`datadouble.profile.load_profile` should have rejected).
    """
    if col.kind == "int":
        return _int_sampler(col)
    if col.kind == "float":
        return _float_sampler(col)
    if col.kind == "date":
        return _date_sampler(col)
    if col.kind == "datetime":
        return _datetime_sampler(col)
    if col.kind == "categorical":
        table = _Weighted(col.payload.get("values"), "values", col.name)
        return lambda rng: table.pick(rng)
    if col.kind == "text":
        table = _Weighted(col.payload.get("masks"), "masks", col.name)
        return lambda rng: _fill_mask(table.pick(rng), rng)
    if col.kind == "empty":
        # An all-null column has null_rate 1.0; if a hand-edited profile
        # lowers it, emitting the null token keeps generation total.
        return lambda rng: col.null_token
    raise GenerationError(f"column {col.name!r}: unknown kind {col.kind!r}")


def _grid_of(col: ColumnProfile) -> List[float]:
    grid = col.payload.get("quantiles")
    if not isinstance(grid, list) or len(grid) < 2:
        raise GenerationError(f"column {col.name!r}: missing quantile grid")
    return [float(q) for q in grid]


def _int_sampler(col: ColumnProfile) -> _Sampler:
    grid = _grid_of(col)
    return lambda rng: str(int(round(sample_quantile_grid(grid, rng.random()))))


def _float_sampler(col: ColumnProfile) -> _Sampler:
    grid = _grid_of(col)
    decimals = col.payload.get("decimals")

    def sample(rng: Random) -> str:
        value = sample_quantile_grid(grid, rng.random())
        if decimals is None:
            # Source used scientific notation; %g keeps magnitude honest.
            return f"{value:g}"
        return f"{value:.{decimals}f}"

    return sample


def _date_sampler(col: ColumnProfile) -> _Sampler:
    grid = _grid_of(col)
    fmt = str(col.payload.get("format"))

    def sample(rng: Random) -> str:
        ordinal = int(round(sample_quantile_grid(grid, rng.random())))
        ordinal = min(max(ordinal, _MIN_ORDINAL), _MAX_ORDINAL)
        return date.fromordinal(ordinal).strftime(fmt)

    return sample


def _datetime_sampler(col: ColumnProfile) -> _Sampler:
    grid = _grid_of(col)
    fmt = str(col.payload.get("format"))

    def sample(rng: Random) -> str:
        seconds = round(sample_quantile_grid(grid, rng.random()))
        seconds = min(max(seconds, _MIN_SECONDS), _MAX_SECONDS)
        return (EPOCH + timedelta(seconds=seconds)).strftime(fmt)

    return sample


class _Weighted:
    """Cumulative-weight table for O(log n) frequency-proportional picks."""

    def __init__(self, table: Any, what: str, column: str) -> None:
        if not isinstance(table, (list, tuple)) or not table:
            raise GenerationError(f"column {column!r}: empty {what} table")
        self.items: List[str] = [str(item) for item, _ in table]
        self.cumulative: List[int] = list(accumulate(int(c) for _, c in table))
        if self.cumulative[-1] <= 0:
            raise GenerationError(f"column {column!r}: {what} counts must be > 0")

    def pick(self, rng: Random) -> str:
        # rng.random() < 1.0, so the target is strictly below the total and
        # bisect_right can never run off the end of the table.
        target = rng.random() * self.cumulative[-1]
        return self.items[bisect_right(self.cumulative, target)]


# --------------------------------------------------------------------------
# Mask filling


def _fill_mask(mask: str, rng: Random) -> str:
    """Materialize a structure mask with fresh random characters.

    ``a``/``A``/``9`` slots get a random letter or digit; ``x`` slots
    (non-ASCII letters in the source) are filled from ASCII lowercase —
    the honest trade of v0.1: script identity is not preserved, shape is.
    Every other character is structure and is kept verbatim.
    """
    # Digits are checked so a hand-edited "LEN:junk" mask degrades to a
    # literal fill instead of crashing generation mid-table.
    if mask.startswith("LEN:") and mask[4:].isdigit():
        return _fill_length(int(mask[4:]), rng)
    out: List[str] = []
    for ch in mask:
        if ch == "9":
            out.append(rng.choice(_DIGITS))
        elif ch in ("a", "x"):
            out.append(rng.choice(_LOWER))
        elif ch == "A":
            out.append(rng.choice(_UPPER))
        else:
            out.append(ch)
    return "".join(out)


def _fill_length(length: int, rng: Random) -> str:
    """Fill an over-long text bucket: word-shaped lowercase filler."""
    out: List[str] = []
    run = 0
    for i in range(max(length, 0)):
        breakable = run >= 3 and 0 < i < length - 1 and out[-1] != " "
        if breakable and rng.random() < 0.18:
            out.append(" ")
            run = 0
        else:
            out.append(rng.choice(_LOWER))
            run += 1
    return "".join(out)
