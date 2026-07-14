"""datadouble — generate a synthetic twin of your CSV.

The twin preserves each column's distribution and null rate but contains
none of the original free-text values. Everything is seeded, offline, and
standard-library only. Typical API round trip:

    from datadouble import build_profile, generate_rows, read_csv, write_csv

    header, rows, delimiter = read_csv("orders.csv")
    profile = build_profile(header, rows)
    twin = generate_rows(profile, rows=len(rows), seed=42)
    write_csv("orders_twin.csv", header, twin, delimiter)

The same workflow is available from the command line as ``datadouble twin``;
see ``datadouble --help``.
"""

from .compare import (
    ColumnComparison,
    CompareReport,
    Tolerances,
    compare_tables,
    render_report,
)
from .csvio import read_csv, write_csv
from .errors import (
    CSVFormatError,
    DatadoubleError,
    GenerationError,
    ProfileFormatError,
)
from .generate import generate_rows, generate_table
from .profile import (
    ColumnProfile,
    ProfileOptions,
    TableProfile,
    build_profile,
    dump_profile,
    load_profile,
    read_profile,
    write_profile,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # profiling
    "ProfileOptions",
    "ColumnProfile",
    "TableProfile",
    "build_profile",
    "dump_profile",
    "load_profile",
    "read_profile",
    "write_profile",
    # generation
    "generate_rows",
    "generate_table",
    # comparison
    "Tolerances",
    "ColumnComparison",
    "CompareReport",
    "compare_tables",
    "render_report",
    # CSV I/O
    "read_csv",
    "write_csv",
    # errors
    "DatadoubleError",
    "CSVFormatError",
    "ProfileFormatError",
    "GenerationError",
]
