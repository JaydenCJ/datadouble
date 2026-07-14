"""End-to-end demo: profile orders.csv, generate a twin, score the twin.

Run from the repository root (after ``pip install -e .``, or with
``PYTHONPATH=src``):

    python examples/twin_demo.py [workdir]

Writes ``orders_twin.csv`` and ``orders_profile.json`` into ``workdir``
(default: a directory named ``out`` next to this script) and prints
``DEMO OK`` when every claim checks out.
"""

import sys
from pathlib import Path

from datadouble import (
    build_profile,
    compare_tables,
    dump_profile,
    generate_table,
    read_csv,
    render_report,
    write_csv,
    write_profile,
)

HERE = Path(__file__).resolve().parent


def main() -> int:
    workdir = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "out"
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. Read and profile the source table.
    header, rows, delimiter = read_csv(str(HERE / "orders.csv"))
    profile = build_profile(header, rows, delimiter=delimiter)
    print(f"source: {len(rows)} rows, {len(header)} columns")
    kinds = ", ".join(f"{c.name}={c.kind}" for c in profile.columns)
    print(f"inferred kinds: {kinds}")

    # 2. The profile is the only artifact derived from the data.
    profile_path = workdir / "orders_profile.json"
    write_profile(str(profile_path), profile)
    print(f"profile: {profile_path} ({len(dump_profile(profile))} bytes)")

    # 3. Generate a twin — twice, to demonstrate seeded determinism.
    twin_header, twin_rows = generate_table(profile, seed=42)
    _, twin_rows_again = generate_table(profile, seed=42)
    identical = twin_rows == twin_rows_again
    print(f"seed 42 twins byte-identical: {identical}")

    twin_path = workdir / "orders_twin.csv"
    write_csv(str(twin_path), twin_header, twin_rows, delimiter)
    print(f"twin: {twin_path} ({len(twin_rows)} rows)")

    # 4. Score the twin against the original.
    report = compare_tables(header, rows, twin_header, twin_rows)
    print(render_report(report), end="")

    if not identical:
        print("DEMO FAILED: twins were not identical", file=sys.stderr)
        return 1
    if not report.ok:
        print("DEMO FAILED: twin drifted out of tolerance", file=sys.stderr)
        return 1
    print("DEMO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
