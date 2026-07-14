"""Table profiles: the JSON contract between analysis and generation.

A profile is the *only* thing datadouble keeps from your data. It contains,
per column: the inferred kind, the null rate, the observed null token, a
uniqueness flag, and one kind-specific statistical summary (quantile grid,
value table, or mask table). Concrete free-text strings are never stored —
only their structure masks — which is what makes a profile shareable when
the CSV itself is not.

The JSON document is versioned (``format`` / ``version`` markers), written
with sorted keys and a trailing newline so it diffs cleanly in git, and
validated field-by-field on load so a hand-edited profile fails with a
message naming the offending column and key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from . import stats
from .errors import CSVFormatError, ProfileFormatError
from .inference import infer_kind, is_null

__all__ = [
    "PROFILE_FORMAT",
    "PROFILE_VERSION",
    "KINDS",
    "EPOCH",
    "ProfileOptions",
    "ColumnProfile",
    "TableProfile",
    "build_profile",
    "dump_profile",
    "load_profile",
    "read_profile",
    "write_profile",
]

PROFILE_FORMAT = "datadouble/profile"
PROFILE_VERSION = 1
KINDS = ("int", "float", "date", "datetime", "categorical", "text", "empty")

# Datetimes are profiled as naive seconds since this epoch; no timezone
# conversion ever happens, so what was written is what round-trips.
EPOCH = datetime(1970, 1, 1)


@dataclass(frozen=True)
class ProfileOptions:
    """Tunables for profile building.

    ``bins`` is the quantile-grid resolution for numeric and temporal
    columns: more bins track the empirical shape more closely at the cost
    of a larger profile. ``cat_cap`` bounds how many distinct values a
    categorical column may have before it falls through to text masks.
    """

    bins: int = 32
    cat_cap: int = 32

    def __post_init__(self) -> None:
        if self.bins < 1:
            raise ProfileFormatError("bins must be >= 1")
        if self.cat_cap < 1:
            raise ProfileFormatError("cat_cap must be >= 1")


@dataclass
class ColumnProfile:
    """Everything datadouble remembers about one column."""

    name: str
    kind: str
    null_rate: float
    null_token: str
    unique: bool
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TableProfile:
    """A whole table: source row count, delimiter, and column profiles."""

    rows: int
    delimiter: str
    columns: List[ColumnProfile]

    def column(self, name: str) -> Optional[ColumnProfile]:
        """Look up a column profile by name, or None."""
        for col in self.columns:
            if col.name == name:
                return col
        return None


def build_profile(
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    options: Optional[ProfileOptions] = None,
    delimiter: str = ",",
) -> TableProfile:
    """Profile a parsed CSV table.

    ``header`` and ``rows`` are what :func:`datadouble.csvio.read_csv`
    returns. Column names must be unique — deterministic generation keys
    its per-column random streams by name, so duplicates would silently
    produce twin columns with identical values.
    """
    opts = options or ProfileOptions()
    if not header:
        raise CSVFormatError("cannot profile a table with no columns")
    seen: set = set()
    for name in header:
        if name in seen:
            raise CSVFormatError(
                f"duplicate column name {name!r}; rename it before profiling"
            )
        seen.add(name)
    columns = [
        _build_column(name, [row[i] for row in rows], opts)
        for i, name in enumerate(header)
    ]
    return TableProfile(rows=len(rows), delimiter=delimiter, columns=columns)


def _build_column(
    name: str, cells: Sequence[str], opts: ProfileOptions
) -> ColumnProfile:
    nulls = [c for c in cells if is_null(c)]
    values = [c for c in cells if not is_null(c)]
    null_rate = len(nulls) / len(cells) if cells else 1.0
    # Emit the null spelling the source actually used (most common wins).
    null_token = stats.frequency_table(nulls)[0][0] if nulls else ""

    if not values:
        return ColumnProfile(name, "empty", null_rate, null_token, False, {})

    kind, fmt = infer_kind(values, cat_cap=opts.cat_cap)
    unique = len(set(values)) == len(values)
    payload = _build_payload(kind, fmt, values, opts)
    return ColumnProfile(name, kind, null_rate, null_token, unique, payload)


def _build_payload(
    kind: str,
    fmt: Optional[str],
    values: Sequence[str],
    opts: ProfileOptions,
) -> Dict[str, Any]:
    if kind == "int":
        nums = [float(int(v)) for v in values]
        return {"quantiles": stats.quantile_grid(nums, opts.bins)}
    if kind == "float":
        nums = [float(v) for v in values]
        # Scientific notation has no fixed decimal count; None means
        # "format freely" at generation time.
        decimals: Optional[int]
        if any("e" in v.lower() for v in values):
            decimals = None
        else:
            decimals = stats.max_decimals(values)
        return {"quantiles": stats.quantile_grid(nums, opts.bins), "decimals": decimals}
    if kind == "date":
        assert fmt is not None
        ordinals = [
            float(datetime.strptime(v, fmt).date().toordinal()) for v in values
        ]
        return {"quantiles": stats.quantile_grid(ordinals, opts.bins), "format": fmt}
    if kind == "datetime":
        assert fmt is not None
        seconds = [
            (datetime.strptime(v, fmt) - EPOCH).total_seconds() for v in values
        ]
        return {"quantiles": stats.quantile_grid(seconds, opts.bins), "format": fmt}
    if kind == "categorical":
        return {"values": stats.frequency_table(values)}
    return {"masks": stats.mask_table(values)}


# --------------------------------------------------------------------------
# Serialization


def dump_profile(profile: TableProfile) -> str:
    """Serialize a profile to canonical JSON (sorted keys, 2-space indent)."""
    doc = {
        "format": PROFILE_FORMAT,
        "version": PROFILE_VERSION,
        "rows": profile.rows,
        "delimiter": profile.delimiter,
        "columns": [
            {
                "name": col.name,
                "kind": col.kind,
                "null_rate": col.null_rate,
                "null_token": col.null_token,
                "unique": col.unique,
                "payload": col.payload,
            }
            for col in profile.columns
        ],
    }
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_profile(text: str) -> TableProfile:
    """Parse and validate a profile JSON document."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProfileFormatError(f"profile is not valid JSON: {exc}") from exc
    return _from_dict(doc)


def write_profile(path: str, profile: TableProfile) -> None:
    """Write a profile to ``path`` as canonical JSON.

    Raises :class:`ProfileFormatError` when ``path`` cannot be written
    (missing directory, no permission) — the mirror of :func:`read_profile`.
    """
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dump_profile(profile))
    except OSError as exc:
        raise ProfileFormatError(
            f"cannot write profile {path}: {exc.strerror or exc}"
        ) from exc


def read_profile(path: str) -> TableProfile:
    """Read and validate a profile from ``path``."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise ProfileFormatError(
            f"cannot read profile {path}: {exc.strerror or exc}"
        ) from exc
    return load_profile(text)


# --------------------------------------------------------------------------
# Validation


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ProfileFormatError(message)


def _from_dict(doc: Any) -> TableProfile:
    _expect(isinstance(doc, dict), "profile root must be a JSON object")
    _expect(
        doc.get("format") == PROFILE_FORMAT,
        f'profile "format" must be {PROFILE_FORMAT!r}, got {doc.get("format")!r}',
    )
    _expect(
        doc.get("version") == PROFILE_VERSION,
        f'unsupported profile "version" {doc.get("version")!r}'
        f" (this build reads version {PROFILE_VERSION})",
    )
    rows = doc.get("rows")
    _expect(
        isinstance(rows, int) and not isinstance(rows, bool) and rows >= 0,
        '"rows" must be a non-negative integer',
    )
    delimiter = doc.get("delimiter")
    _expect(
        isinstance(delimiter, str) and len(delimiter) == 1,
        '"delimiter" must be a single-character string',
    )
    raw_columns = doc.get("columns")
    _expect(
        isinstance(raw_columns, list) and len(raw_columns) > 0,
        '"columns" must be a non-empty list',
    )
    columns = [_column_from_dict(raw, i) for i, raw in enumerate(raw_columns)]
    return TableProfile(rows=rows, delimiter=delimiter, columns=columns)


def _column_from_dict(raw: Any, index: int) -> ColumnProfile:
    where = f"columns[{index}]"
    _expect(isinstance(raw, dict), f"{where} must be a JSON object")
    name = raw.get("name")
    _expect(
        isinstance(name, str) and name.strip() != "",
        f'{where}: "name" must be a non-empty string',
    )
    where = f"column {name!r}"
    kind = raw.get("kind")
    _expect(kind in KINDS, f'{where}: "kind" must be one of {", ".join(KINDS)}')
    null_rate = raw.get("null_rate")
    _expect(
        isinstance(null_rate, (int, float))
        and not isinstance(null_rate, bool)
        and 0.0 <= null_rate <= 1.0,
        f'{where}: "null_rate" must be a number in [0, 1]',
    )
    null_token = raw.get("null_token")
    _expect(isinstance(null_token, str), f'{where}: "null_token" must be a string')
    unique = raw.get("unique")
    _expect(isinstance(unique, bool), f'{where}: "unique" must be a boolean')
    payload = raw.get("payload")
    _expect(isinstance(payload, dict), f'{where}: "payload" must be an object')
    _validate_payload(kind, payload, where)
    return ColumnProfile(name, kind, float(null_rate), null_token, unique, payload)


def _validate_payload(kind: str, payload: Dict[str, Any], where: str) -> None:
    if kind in ("int", "float", "date", "datetime"):
        grid = payload.get("quantiles")
        _expect(
            isinstance(grid, list)
            and len(grid) >= 2
            and all(
                isinstance(q, (int, float)) and not isinstance(q, bool) for q in grid
            ),
            f'{where}: "quantiles" must be a list of at least 2 numbers',
        )
        _expect(
            all(grid[i] <= grid[i + 1] for i in range(len(grid) - 1)),
            f'{where}: "quantiles" must be non-decreasing',
        )
    if kind == "float":
        decimals = payload.get("decimals")
        _expect(
            decimals is None
            or (
                isinstance(decimals, int)
                and not isinstance(decimals, bool)
                and decimals >= 0
            ),
            f'{where}: "decimals" must be null or a non-negative integer',
        )
    if kind in ("date", "datetime"):
        fmt = payload.get("format")
        _expect(
            isinstance(fmt, str) and "%" in fmt,
            f'{where}: "format" must be a strftime format string',
        )
    if kind == "categorical":
        _validate_table(payload.get("values"), "values", where)
    if kind == "text":
        _validate_table(payload.get("masks"), "masks", where)


def _validate_table(table: Any, key: str, where: str) -> None:
    _expect(
        isinstance(table, list) and len(table) > 0,
        f'{where}: "{key}" must be a non-empty list',
    )
    for entry in table:
        _expect(
            isinstance(entry, (list, tuple))
            and len(entry) == 2
            and isinstance(entry[0], str)
            and isinstance(entry[1], int)
            and not isinstance(entry[1], bool)
            and entry[1] > 0,
            f'{where}: every "{key}" entry must be [string, positive count]',
        )
