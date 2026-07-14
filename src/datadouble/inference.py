"""Column type inference over raw CSV cells.

A CSV gives us strings; this module decides what those strings *are*. The
decision drives which statistical summary the profiler keeps:

========== =============================================================
kind       summary kept in the profile
========== =============================================================
int        quantile grid over the integer values
float      quantile grid + observed decimal precision
date       quantile grid over proleptic ordinals + the strftime format
datetime   quantile grid over epoch seconds + the strftime format
categorical exact value frequency table (values are copied verbatim)
text       structure-mask frequency table (concrete strings never kept)
empty      nothing — every cell was a null token
========== =============================================================

Inference is intentionally conservative and rule-ordered: a column is only
numeric/temporal when *every* non-null cell parses, so one stray value
demotes the column to categorical or text rather than corrupting a grid.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Sequence, Tuple

__all__ = [
    "NULL_TOKENS",
    "DATE_FORMATS",
    "DATETIME_FORMATS",
    "DEFAULT_CAT_CAP",
    "is_null",
    "looks_int",
    "looks_float",
    "detect_temporal_format",
    "infer_kind",
]

# Cells whose stripped, lowercased form is in this set count as null. "0" and
# "-" are deliberately absent: both appear as real data far too often.
NULL_TOKENS = frozenset({"", "null", "none", "na", "n/a", "nan", "nil"})

# ASCII-only on purpose: full-width digits would pass ``\d`` under Unicode
# matching and then round-trip through int() into a different string.
_INT_RE = re.compile(r"[+-]?[0-9]+\Z", re.ASCII)
_FLOAT_RE = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z", re.ASCII
)

# Tried in order; the first format that parses every non-null cell wins.
# Ambiguous day/month data therefore resolves to the earlier format.
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y")
DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M",
)

# A column with more distinct values than this can never be categorical;
# beyond it, resampling a verbatim value table stops being a distribution
# summary and starts being a copy of the data.
DEFAULT_CAT_CAP = 32


def is_null(cell: str) -> bool:
    """True when ``cell`` should be treated as a missing value."""
    return cell.strip().lower() in NULL_TOKENS


def looks_int(value: str) -> bool:
    """True for a plain base-10 integer literal.

    Zero-padded values like ``007`` or ``08540`` are rejected: they are
    codes, not numbers, and ``int()`` round-tripping would eat the padding.
    """
    if _INT_RE.fullmatch(value) is None:
        return False
    digits = value.lstrip("+-")
    return not (len(digits) > 1 and digits[0] == "0")


def looks_float(value: str) -> bool:
    """True for a decimal or scientific-notation float literal.

    Plain integers also pass (a mixed ``1`` / ``2.5`` column is a float
    column), but ``inf`` / ``nan`` spellings do not: the regex requires
    digits, so ``float()`` on an accepted value can never go non-finite.
    """
    return _FLOAT_RE.fullmatch(value) is not None


def detect_temporal_format(
    values: Sequence[str],
) -> Optional[Tuple[str, str]]:
    """Return ``(kind, strftime_format)`` if every value parses, else None.

    ``kind`` is ``"date"`` or ``"datetime"``. Each candidate format is
    abandoned at its first failing cell, so a non-temporal column costs at
    most one failed parse per format.
    """
    for kind, formats in (("date", DATE_FORMATS), ("datetime", DATETIME_FORMATS)):
        for fmt in formats:
            if _all_parse(values, fmt):
                return kind, fmt
    return None


def _all_parse(values: Sequence[str], fmt: str) -> bool:
    for v in values:
        try:
            datetime.strptime(v, fmt)
        except ValueError:
            return False
    return True


def infer_kind(
    values: Sequence[str], cat_cap: int = DEFAULT_CAT_CAP
) -> Tuple[str, Optional[str]]:
    """Classify the non-null cells of one column.

    Returns ``(kind, temporal_format)``; the format is only set for
    ``date`` / ``datetime`` kinds. ``values`` must be non-empty and already
    filtered of nulls — the all-null "empty" kind is the caller's case.

    Rule order:

    1. Very low cardinality (at most ``max(2, n/20)`` distinct values, and
       never above ``cat_cap``) is categorical outright — status codes,
       flags, and booleans are more faithfully resampled from their exact
       value table than force-fit into a numeric shape.
    2. All-int, then all-float, then a shared date/datetime format.
    3. Moderate cardinality (``<= cat_cap`` distinct values covering at
       most half the rows) is categorical.
    4. Everything else is mask-based text.
    """
    n = len(values)
    if n == 0:
        raise ValueError("infer_kind needs at least one non-null value")
    distinct = len(set(values))
    if distinct <= min(cat_cap, max(2, n // 20)):
        return "categorical", None
    if all(looks_int(v) for v in values):
        return "int", None
    if all(looks_float(v) for v in values):
        return "float", None
    temporal = detect_temporal_format(values)
    if temporal is not None:
        return temporal
    if distinct <= cat_cap and distinct * 2 <= n:
        return "categorical", None
    return "text", None
