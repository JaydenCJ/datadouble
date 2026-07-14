"""Tests for deterministic twin generation."""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from datadouble.errors import GenerationError
from datadouble.generate import generate_rows, generate_table
from datadouble.profile import TableProfile, build_profile
from datadouble.stats import frequency_table, mask_of, total_variation

from conftest import make_sample_table


def _column(rows, index):
    return [r[index] for r in rows]


@pytest.fixture(scope="module")
def profile():
    header, rows = make_sample_table(rows=400, seed=1)
    return build_profile(header, rows)


def test_same_seed_is_byte_identical_and_seeds_matter(profile):
    a = generate_rows(profile, 200, seed=42)
    b = generate_rows(profile, 200, seed=42)
    assert a == b
    assert generate_rows(profile, 200, seed=1) != generate_rows(profile, 200, seed=2)


def test_longer_run_is_prefix_stable(profile):
    # Growing a twin must not reshuffle the rows you already shipped.
    short = generate_rows(profile, 100, seed=7)
    longer = generate_rows(profile, 300, seed=7)
    assert longer[:100] == short


def test_null_rate_is_preserved(profile):
    rows = generate_rows(profile, 3000, seed=3)
    plan_idx = [c.name for c in profile.columns].index("plan")
    twin_null_rate = sum(1 for r in rows if r[plan_idx] == "") / len(rows)
    source_rate = profile.column("plan").null_rate
    assert abs(twin_null_rate - source_rate) < 0.03


def test_int_column_emits_integers_in_observed_range():
    # Duplicated values on purpose: uniqueness repair (which may step just
    # outside the range) must not kick in here.
    rows = [[str(100 + (i * 37) % 250)] for i in range(400)]
    profile = build_profile(["n"], rows)
    col = profile.column("n")
    assert col.kind == "int" and col.unique is False
    grid = col.payload["quantiles"]
    values = _column(generate_rows(profile, 500, seed=4), 0)
    for v in values:
        assert re.fullmatch(r"-?\d+", v), v
        assert grid[0] <= int(v) <= grid[-1]


def test_float_column_respects_decimal_precision(profile):
    values = _column(generate_rows(profile, 200, seed=5), 1)
    assert all(re.fullmatch(r"-?\d+\.\d{2}", v) for v in values)


def test_categorical_emits_only_observed_values(profile):
    observed = {v for v, _ in profile.column("region").payload["values"]}
    values = _column(generate_rows(profile, 500, seed=6), 2)
    assert set(values) <= observed


def test_categorical_frequencies_are_close(profile):
    values = _column(generate_rows(profile, 4000, seed=8), 2)
    tv = total_variation(
        profile.column("region").payload["values"], frequency_table(values)
    )
    assert tv < 0.05


def test_date_column_keeps_format_and_range(profile):
    values = _column(generate_rows(profile, 300, seed=9), 3)
    parsed = [datetime.strptime(v, "%Y-%m-%d") for v in values]  # format holds
    grid = profile.column("signup").payload["quantiles"]
    assert all(grid[0] <= d.date().toordinal() <= grid[-1] for d in parsed)


def test_datetime_column_round_trips():
    rows = [[f"2026-03-{d:02d} 12:{d:02d}:00"] for d in range(1, 29)]
    profile = build_profile(["ts"], rows)
    assert profile.column("ts").kind == "datetime"
    out = _column(generate_rows(profile, 50, seed=10), 0)
    for v in out:
        datetime.strptime(v, "%Y-%m-%d %H:%M:%S")


def test_text_column_reproduces_masks_but_not_values(profile):
    header, rows = make_sample_table(rows=400, seed=1)
    source = set(_column(rows, 4))
    twin = _column(generate_rows(profile, 400, seed=11), 4)
    assert {mask_of(v) for v in twin} == {"AA-999"}
    # Fresh characters: at most a handful of coincidental collisions.
    assert sum(1 for v in twin if v in source) < len(twin) * 0.05


def test_unique_columns_stay_unique(profile):
    rows = [[f"INV-{1000 + i}"] for i in range(300)]
    text_profile = build_profile(["invoice"], rows)
    assert text_profile.column("invoice").unique is True
    text_twin = _column(generate_rows(text_profile, 300, seed=12), 0)
    assert len(set(text_twin)) == len(text_twin)
    # Same guarantee for integer keys ("id" is 400 distinct ints).
    int_twin = _column(generate_rows(profile, 400, seed=13), 0)
    assert len(set(int_twin)) == len(int_twin)


def test_columns_are_independent_of_order(profile):
    # Streams are keyed by column name, so a reordered profile generates
    # exactly the same values for every column.
    reordered = TableProfile(
        rows=profile.rows,
        delimiter=profile.delimiter,
        columns=list(reversed(profile.columns)),
    )
    original = generate_rows(profile, 150, seed=14)
    flipped = generate_rows(reordered, 150, seed=14)
    n = len(profile.columns)
    for i in range(n):
        assert _column(flipped, n - 1 - i) == _column(original, i)


def test_null_rate_change_never_reshuffles_values(profile):
    # The k-th non-null cell must be the same value whatever the null rate.
    plan = profile.column("plan")
    dense = TableProfile(
        rows=profile.rows,
        delimiter=profile.delimiter,
        columns=[
            type(plan)(plan.name, plan.kind, 0.0, plan.null_token, plan.unique, plan.payload)
        ],
    )
    sparse_values = [
        v
        for v in _column(generate_rows(profile, 200, seed=15), 5)
        if v != ""
    ]
    dense_values = _column(generate_rows(dense, 200, seed=15), 0)
    assert sparse_values == dense_values[: len(sparse_values)]


def test_empty_kind_column_emits_null_token():
    profile = build_profile(["gone"], [["NA"], ["NA"], ["NA"]])
    rows = generate_rows(profile, 10, seed=16)
    assert rows == [["NA"]] * 10


def test_negative_row_count_raises(profile):
    with pytest.raises(GenerationError, match="rows must be >= 0"):
        generate_rows(profile, -1)


def test_generate_table_defaults_to_source_row_count(profile):
    header, rows = generate_table(profile, seed=17)
    assert header == [c.name for c in profile.columns]
    assert len(rows) == profile.rows


def test_hand_edited_len_mask_without_digits_fills_literally():
    # "LEN:junk" passes profile validation (it is a [string, count] entry),
    # so generation must degrade to a literal-style fill, not crash on int().
    profile = build_profile(["note"], [["alpha one"], ["beta twos"], ["gama tres"]])
    profile.columns[0].payload["masks"] = [["LEN:junk", 1]]
    rows = generate_rows(profile, 4, seed=9)
    # The mask has no a/A/9/x slots, so it fills verbatim; the column is
    # unique, so the deterministic suffix repair keeps the rows distinct.
    assert [r[0] for r in rows] == [
        "LEN:junk", "LEN:junk-2", "LEN:junk-3", "LEN:junk-4"
    ]
