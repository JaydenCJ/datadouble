"""Statistical comparison between two CSV tables (original vs twin).

``datadouble compare`` answers the question a reviewer will ask about any
synthetic stand-in: *how close is it, really?* Both tables are profiled
with the same options and each shared column gets one distance metric:

- **q-shift** for numeric and temporal columns: the mean absolute gap
  between the two quantile grids, normalized by the observed span. 0 means
  the empirical distributions coincide at every grid point.
- **tv** (total variation distance) for categorical columns (over exact
  values) and text columns (over structure masks). 0 identical, 1 disjoint.

Null rates are always compared. Everything is scored against explicit
:class:`Tolerances`, and the report's ``ok`` flag maps to the CLI exit
code, so ``compare`` slots directly into a CI gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .profile import ColumnProfile, ProfileOptions, build_profile
from .stats import total_variation

__all__ = [
    "Tolerances",
    "ColumnComparison",
    "CompareReport",
    "compare_tables",
    "render_report",
]

_NUMERIC_KINDS = ("int", "float", "date", "datetime")


@dataclass(frozen=True)
class Tolerances:
    """Pass/fail thresholds for a column comparison.

    Defaults are calibrated for "twin of the same table at similar size":
    tight enough to catch a wrong column or a broken generator, loose
    enough that ordinary sampling noise on a few hundred rows passes.
    """

    max_null_delta: float = 0.05
    max_tv: float = 0.15
    max_shift: float = 0.10


@dataclass
class ColumnComparison:
    """Verdict for one shared column."""

    name: str
    kind_a: str
    kind_b: str
    null_a: float
    null_b: float
    metric: str  # "q-shift", "tv", or "-" when no metric applies
    value: float
    ok: bool
    note: str = ""


@dataclass
class CompareReport:
    """Full comparison result for two tables."""

    rows_a: int
    rows_b: int
    columns: List[ColumnComparison] = field(default_factory=list)
    only_in_a: List[str] = field(default_factory=list)
    only_in_b: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every shared column passes and no column is missing."""
        return (
            not self.only_in_a
            and not self.only_in_b
            and all(col.ok for col in self.columns)
        )


def compare_tables(
    header_a: Sequence[str],
    rows_a: Sequence[Sequence[str]],
    header_b: Sequence[str],
    rows_b: Sequence[Sequence[str]],
    options: Optional[ProfileOptions] = None,
    tolerances: Optional[Tolerances] = None,
) -> CompareReport:
    """Profile both tables with identical options and score each column."""
    opts = options or ProfileOptions()
    tol = tolerances or Tolerances()
    profile_a = build_profile(header_a, rows_a, opts)
    profile_b = build_profile(header_b, rows_b, opts)

    names_b = set(header_b)
    report = CompareReport(rows_a=len(rows_a), rows_b=len(rows_b))
    report.only_in_a = [n for n in header_a if n not in names_b]
    report.only_in_b = [n for n in header_b if n not in set(header_a)]

    for col_a in profile_a.columns:
        col_b = profile_b.column(col_a.name)
        if col_b is None:
            continue
        report.columns.append(_compare_column(col_a, col_b, tol))
    return report


def _compare_column(
    a: ColumnProfile, b: ColumnProfile, tol: Tolerances
) -> ColumnComparison:
    null_delta = abs(a.null_rate - b.null_rate)
    null_ok = null_delta <= tol.max_null_delta
    notes: List[str] = []
    if not null_ok:
        notes.append(f"null rate drifted by {null_delta:.3f}")

    metric, value, metric_ok = _metric(a, b, tol, notes)
    return ColumnComparison(
        name=a.name,
        kind_a=a.kind,
        kind_b=b.kind,
        null_a=a.null_rate,
        null_b=b.null_rate,
        metric=metric,
        value=value,
        ok=null_ok and metric_ok,
        note="; ".join(notes),
    )


def _metric(
    a: ColumnProfile, b: ColumnProfile, tol: Tolerances, notes: List[str]
) -> Tuple[str, float, bool]:
    if a.kind == "empty" and b.kind == "empty":
        return "-", 0.0, True

    # int/float is a soft boundary (a twin can legitimately land on either
    # side for borderline data), so that pair still compares numerically.
    numeric_pair = a.kind in _NUMERIC_KINDS and b.kind in _NUMERIC_KINDS
    if a.kind != b.kind and not (a.kind in ("int", "float") and b.kind in ("int", "float")):
        notes.append(f"type drift: {a.kind} -> {b.kind}")
        return "-", 1.0, False

    if numeric_pair:
        fmt_a, fmt_b = a.payload.get("format"), b.payload.get("format")
        if fmt_a != fmt_b:
            notes.append(f"format drift: {fmt_a} -> {fmt_b}")
            return "-", 1.0, False
        value = _quantile_shift(a.payload["quantiles"], b.payload["quantiles"])
        ok = value <= tol.max_shift
        if not ok:
            notes.append(f"distribution shifted by {value:.3f} of span")
        return "q-shift", value, ok

    if a.kind == "categorical":
        value = total_variation(a.payload["values"], b.payload["values"])
        ok = value <= tol.max_tv
        if not ok:
            notes.append(f"value mix differs (tv {value:.3f})")
        return "tv", value, ok

    # text: compare structure-mask distributions.
    value = total_variation(a.payload["masks"], b.payload["masks"])
    ok = value <= tol.max_tv
    if not ok:
        notes.append(f"string shapes differ (tv {value:.3f})")
    return "tv", value, ok


def _quantile_shift(grid_a: Sequence[float], grid_b: Sequence[float]) -> float:
    """Mean absolute grid gap, normalized by the wider observed span."""
    n = min(len(grid_a), len(grid_b))
    a, b = list(grid_a)[:n], list(grid_b)[:n]
    span = max(a[-1] - a[0], b[-1] - b[0])
    if span <= 0:
        # Both columns are constant; either they agree exactly or they are
        # entirely different values.
        return 0.0 if a == b else 1.0
    return sum(abs(x - y) for x, y in zip(a, b)) / n / span


# --------------------------------------------------------------------------
# Rendering


def render_report(report: CompareReport) -> str:
    """Render a report as an aligned, plain-ASCII text table."""
    headers = ("column", "type", "nulls a->b", "metric", "status")
    rows: List[Tuple[str, str, str, str, str]] = []
    for col in report.columns:
        kind = col.kind_a if col.kind_a == col.kind_b else f"{col.kind_a}->{col.kind_b}"
        metric = "-" if col.metric == "-" else f"{col.metric} {col.value:.3f}"
        status = "ok" if col.ok else "DRIFT"
        if col.note:
            status = f"{status}  ({col.note})"
        rows.append(
            (col.name, kind, f"{col.null_a:.3f}->{col.null_b:.3f}", metric, status)
        )

    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    lines = [
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip(),
        "  ".join("-" * w for w in widths),
    ]
    for r in rows:
        lines.append("  ".join(r[i].ljust(widths[i]) for i in range(len(r))).rstrip())

    lines.append("")
    lines.append(f"rows: {report.rows_a} -> {report.rows_b}")
    for name in report.only_in_a:
        lines.append(f"missing in b: {name}")
    for name in report.only_in_b:
        lines.append(f"extra in b:   {name}")
    passed = sum(1 for c in report.columns if c.ok)
    total = len(report.columns)
    noun = "column" if total == 1 else "columns"
    if report.ok:
        lines.append(f"TWIN OK: {passed}/{total} shared {noun} within tolerance")
    else:
        failed = total - passed
        lines.append(
            f"DRIFT: {failed}/{total} shared {noun} out of tolerance"
            if failed
            else "DRIFT: column sets differ"
        )
    return "\n".join(lines) + "\n"
