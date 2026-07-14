"""Pure statistics helpers: quantiles, frequency tables, and string masks.

Everything in this module is deterministic and side-effect free; it operates
on plain Python lists so it can be unit-tested without fixtures.

The two ideas that carry the whole tool live here:

- **Quantile grids.** A numeric column is summarized as ``bins + 1`` evenly
  spaced quantiles of its empirical distribution. Sampling later inverts that
  grid (inverse-CDF with linear interpolation), which reproduces the original
  shape — skew, heavy tails, plateaus — without fitting any model.
- **Structure masks.** A free-text value is reduced to a mask that keeps
  punctuation verbatim but replaces every letter with ``a``/``A`` and every
  digit with ``9``. ``ORD-2041`` becomes ``AAA-9999``; ``ana@example.test``
  becomes ``aaa@aaaaaaa.aaaa``. Generation fills masks with fresh random
  characters, so shape survives while the concrete strings never leave the
  original file.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Sequence, Tuple

__all__ = [
    "quantile_grid",
    "sample_quantile_grid",
    "frequency_table",
    "total_variation",
    "mask_of",
    "mask_table",
    "max_decimals",
]

# Masks longer than this collapse into a length bucket; per-character masks of
# huge free-text fields would bloat profiles without adding useful structure.
MASK_MAX_LEN = 48

# Only the most common masks are kept; the tail is represented by its share of
# probability mass and generated from the kept masks. 64 covers realistic
# structured columns (IDs, codes, emails, phone numbers) comfortably.
MASK_TABLE_CAP = 64


def quantile_grid(values: Sequence[float], bins: int) -> List[float]:
    """Return ``bins + 1`` evenly spaced empirical quantiles of ``values``.

    Uses the "linear" interpolation rule (the numpy/R-7 default): quantile
    ``p`` sits at fractional rank ``p * (n - 1)`` of the sorted data. The
    grid always starts at the minimum and ends at the maximum, so generated
    values can never leave the observed range.
    """
    if not values:
        raise ValueError("quantile_grid needs at least one value")
    if bins < 1:
        raise ValueError("bins must be >= 1")
    ordered = sorted(values)
    n = len(ordered)
    grid: List[float] = []
    for i in range(bins + 1):
        rank = (i / bins) * (n - 1)
        lo = int(rank)
        hi = min(lo + 1, n - 1)
        frac = rank - lo
        grid.append(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)
    return grid


def sample_quantile_grid(grid: Sequence[float], u: float) -> float:
    """Invert a quantile grid at uniform draw ``u`` in ``[0, 1)``.

    This is inverse-CDF sampling with linear interpolation between adjacent
    grid points — the exact mirror of :func:`quantile_grid`.
    """
    bins = len(grid) - 1
    if bins < 1:
        return float(grid[0])
    pos = min(max(u, 0.0), 1.0) * bins
    lo = min(int(pos), bins - 1)
    frac = pos - lo
    return grid[lo] * (1.0 - frac) + grid[lo + 1] * frac


def frequency_table(values: Sequence[str]) -> List[Tuple[str, int]]:
    """Count distinct values, most common first, ties broken by value.

    The secondary sort keeps profiles deterministic regardless of input row
    order, which in turn keeps twin output deterministic.
    """
    counts = Counter(values)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def total_variation(
    a: Sequence[Tuple[str, int]], b: Sequence[Tuple[str, int]]
) -> float:
    """Total variation distance between two frequency tables, in ``[0, 1]``.

    0 means identical distributions; 1 means disjoint supports. Empty tables
    count as identical to other empty tables and maximally distant from
    non-empty ones.
    """
    ta, tb = sum(c for _, c in a), sum(c for _, c in b)
    if ta == 0 and tb == 0:
        return 0.0
    if ta == 0 or tb == 0:
        return 1.0
    pa: Dict[str, float] = {v: c / ta for v, c in a}
    pb: Dict[str, float] = {v: c / tb for v, c in b}
    keys = set(pa) | set(pb)
    return 0.5 * sum(abs(pa.get(k, 0.0) - pb.get(k, 0.0)) for k in keys)


def mask_of(value: str) -> str:
    """Reduce ``value`` to a structure mask.

    ASCII letters become ``a``/``A``, digits become ``9``, other letters
    (accented, CJK, ...) become ``x``, and everything else — punctuation,
    whitespace, symbols — is kept verbatim because it *is* the structure.
    """
    out: List[str] = []
    for ch in value:
        if ch.isdigit():
            out.append("9")
        elif "a" <= ch <= "z":
            out.append("a")
        elif "A" <= ch <= "Z":
            out.append("A")
        elif ch.isalpha():
            out.append("x")
        else:
            out.append(ch)
    return "".join(out)


def mask_table(values: Sequence[str]) -> List[Tuple[str, int]]:
    """Build a capped frequency table of structure masks for ``values``.

    Values longer than :data:`MASK_MAX_LEN` are bucketed as ``LEN:<n>`` so a
    long free-text column still round-trips with plausible lengths. Only the
    :data:`MASK_TABLE_CAP` most common masks are kept; dropping the long tail
    both bounds profile size and avoids memorializing one-off values whose
    exact shape could identify them.
    """
    masks = [
        mask_of(v) if len(v) <= MASK_MAX_LEN else f"LEN:{len(v)}" for v in values
    ]
    return frequency_table(masks)[:MASK_TABLE_CAP]


def max_decimals(values: Sequence[str], cap: int = 9) -> int:
    """Largest number of decimal places used by any value, capped.

    Scientific notation counts as ``cap`` decimals — its precision is not
    representable as a fixed decimal count, so we keep full float formatting.
    """
    worst = 0
    for v in values:
        s = v.strip().lower()
        if "e" in s:
            return cap
        if "." in s:
            worst = max(worst, len(s.split(".", 1)[1]))
            if worst >= cap:
                return cap
    return worst
