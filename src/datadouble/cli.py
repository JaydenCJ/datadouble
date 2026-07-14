"""Command-line interface for datadouble.

Four subcommands cover the whole workflow:

- ``profile``  — summarize a CSV into a shareable JSON profile
- ``twin``     — one-shot: profile a CSV and emit a synthetic twin
- ``generate`` — emit rows from a saved profile (no access to the original)
- ``compare``  — score two CSVs column-by-column; exit 1 on drift

Exit codes: 0 success, 1 ``compare`` found drift, 2 usage or input error.
All work is local and offline; nothing is uploaded anywhere, ever.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .compare import Tolerances, compare_tables, render_report
from .csvio import read_csv, write_csv
from .errors import DatadoubleError
from .generate import generate_table
from .profile import (
    ProfileOptions,
    build_profile,
    dump_profile,
    read_profile,
    write_profile,
)

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datadouble",
        description=(
            "Generate a synthetic twin of your CSV, preserving per-column "
            "distributions and null rates. Seeded, offline, zero dependencies."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"datadouble {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser(
        "profile",
        help="summarize a CSV into a JSON profile (safe to share)",
        description="Summarize a CSV into a JSON profile. Free-text values "
        "are reduced to structure masks; they are never stored verbatim.",
    )
    p.add_argument("input", help="path to the source CSV")
    p.add_argument("-o", "--out", help="write the profile here (default: stdout)")
    _add_profile_options(p)
    p.set_defaults(func=_cmd_profile)

    p = sub.add_parser(
        "twin",
        help="profile a CSV and emit a synthetic twin in one step",
        description="Profile a CSV and immediately generate a synthetic twin "
        "with the same columns, distributions, and null rates.",
    )
    p.add_argument("input", help="path to the source CSV")
    p.add_argument("-o", "--out", help="write the twin CSV here (default: stdout)")
    p.add_argument(
        "--rows", type=int, default=None, help="twin row count (default: same as source)"
    )
    p.add_argument("--seed", type=int, default=0, help="random seed (default: 0)")
    _add_profile_options(p)
    p.set_defaults(func=_cmd_twin)

    p = sub.add_parser(
        "generate",
        help="emit rows from a saved profile, without the original CSV",
        description="Generate a synthetic CSV from a saved profile. The "
        "original data is not needed — only the profile JSON.",
    )
    p.add_argument("profile", help="path to a profile JSON written by 'profile'")
    p.add_argument("-o", "--out", help="write the CSV here (default: stdout)")
    p.add_argument(
        "--rows",
        type=int,
        default=None,
        help="row count (default: the profiled source's row count)",
    )
    p.add_argument("--seed", type=int, default=0, help="random seed (default: 0)")
    p.set_defaults(func=_cmd_generate)

    p = sub.add_parser(
        "compare",
        help="score two CSVs column-by-column; exit 1 on drift",
        description="Profile two CSVs with identical options and report a "
        "per-column distance. Exits 1 when any column is out of tolerance.",
    )
    p.add_argument("a", help="the reference CSV (usually the original)")
    p.add_argument("b", help="the candidate CSV (usually the twin)")
    p.add_argument(
        "--max-null-delta",
        type=float,
        default=Tolerances.max_null_delta,
        help=f"allowed |null rate difference| (default: {Tolerances.max_null_delta})",
    )
    p.add_argument(
        "--max-tv",
        type=float,
        default=Tolerances.max_tv,
        help=f"allowed total variation distance (default: {Tolerances.max_tv})",
    )
    p.add_argument(
        "--max-shift",
        type=float,
        default=Tolerances.max_shift,
        help=f"allowed normalized quantile shift (default: {Tolerances.max_shift})",
    )
    _add_profile_options(p)
    p.set_defaults(func=_cmd_compare)

    return parser


def _add_profile_options(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--bins",
        type=int,
        default=ProfileOptions.bins,
        help=f"quantile grid resolution (default: {ProfileOptions.bins})",
    )
    p.add_argument(
        "--cat-cap",
        type=int,
        default=ProfileOptions.cat_cap,
        help=f"max distinct values for a categorical column (default: {ProfileOptions.cat_cap})",
    )
    p.add_argument(
        "--delimiter",
        default=None,
        help="field delimiter of the input (default: sniffed)",
    )


def main(argv: Optional[List[str]] = None) -> int:
    """Run the CLI; returns the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except DatadoubleError as exc:
        print(f"datadouble: error: {exc}", file=sys.stderr)
        return 2


# --------------------------------------------------------------------------
# Subcommands


def _options(args: argparse.Namespace) -> ProfileOptions:
    return ProfileOptions(bins=args.bins, cat_cap=args.cat_cap)


def _count(n: int, noun: str) -> str:
    """``1 row`` / ``2 rows`` — spare the logs from "1 rows"."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _cmd_profile(args: argparse.Namespace) -> int:
    header, rows, delimiter = read_csv(args.input, delimiter=args.delimiter)
    profile = build_profile(header, rows, _options(args), delimiter=delimiter)
    if args.out is None:
        sys.stdout.write(dump_profile(profile))
    else:
        write_profile(args.out, profile)
        print(
            f"wrote {args.out} ({_count(profile.rows, 'row')}, "
            f"{_count(len(profile.columns), 'column')} profiled)",
            file=sys.stderr,
        )
    return 0


def _cmd_twin(args: argparse.Namespace) -> int:
    header, rows, delimiter = read_csv(args.input, delimiter=args.delimiter)
    profile = build_profile(header, rows, _options(args), delimiter=delimiter)
    out_header, out_rows = generate_table(profile, rows=args.rows, seed=args.seed)
    write_csv(args.out, out_header, out_rows, delimiter=delimiter)
    if args.out is not None:
        print(
            f"wrote {args.out} ({_count(len(out_rows), 'row')}, "
            f"{_count(len(out_header), 'column')}, seed {args.seed})",
            file=sys.stderr,
        )
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    profile = read_profile(args.profile)
    out_header, out_rows = generate_table(profile, rows=args.rows, seed=args.seed)
    write_csv(args.out, out_header, out_rows, delimiter=profile.delimiter)
    if args.out is not None:
        print(
            f"wrote {args.out} ({_count(len(out_rows), 'row')}, "
            f"{_count(len(out_header), 'column')}, seed {args.seed})",
            file=sys.stderr,
        )
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    header_a, rows_a, _ = read_csv(args.a, delimiter=args.delimiter)
    header_b, rows_b, _ = read_csv(args.b, delimiter=args.delimiter)
    report = compare_tables(
        header_a,
        rows_a,
        header_b,
        rows_b,
        options=_options(args),
        tolerances=Tolerances(
            max_null_delta=args.max_null_delta,
            max_tv=args.max_tv,
            max_shift=args.max_shift,
        ),
    )
    sys.stdout.write(render_report(report))
    return 0 if report.ok else 1
