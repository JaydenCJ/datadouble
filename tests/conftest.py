"""Shared fixtures and factories for the datadouble test suite.

Everything here is deterministic: tables are built from seeded
``random.Random`` instances, files live in pytest's ``tmp_path``, and no
test touches the network or the wall clock.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import List, Sequence, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

Table = Tuple[List[str], List[List[str]]]


def make_sample_table(rows: int = 400, seed: int = 1) -> Table:
    """A mixed-kind table exercising every inferred column kind.

    Columns: unique int id, 2-decimal float, weighted categorical, ISO
    date, masked text code, and a nullable categorical (~30% nulls).
    """
    rng = random.Random(seed)
    header = ["id", "amount", "region", "signup", "code", "plan"]
    out: List[List[str]] = []
    regions = ["north", "south", "east", "west"]
    weights = [0.4, 0.3, 0.2, 0.1]
    plans = ["basic", "pro", "team"]
    for i in range(rows):
        day = int(rng.triangular(0, 364, 90))
        month, dom = 1 + day // 31, 1 + day % 28
        out.append(
            [
                str(1000 + i),
                f"{rng.triangular(1.0, 500.0, 40.0):.2f}",
                rng.choices(regions, weights)[0],
                f"2025-{month:02d}-{dom:02d}",
                f"{rng.choice('ABCDEFGH')}{rng.choice('ABCDEFGH')}-"
                f"{rng.randrange(100, 999)}",
                rng.choices(plans)[0] if rng.random() > 0.3 else "",
            ]
        )
    return header, out


def write_csv_file(
    path: Path,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    delimiter: str = ",",
) -> str:
    """Write a CSV fixture and return its path as a string."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter, lineterminator="\n")
        writer.writerow(list(header))
        writer.writerows([list(r) for r in rows])
    return str(path)


@pytest.fixture()
def sample_table() -> Table:
    return make_sample_table()


@pytest.fixture()
def orders_csv() -> str:
    """The committed example fixture (200 realistic order rows)."""
    return str(REPO_ROOT / "examples" / "orders.csv")
