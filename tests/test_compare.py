"""Tests for the twin-vs-original comparison engine."""

from __future__ import annotations

import pytest

from datadouble.compare import Tolerances, compare_tables, render_report
from datadouble.generate import generate_table
from datadouble.profile import build_profile

from conftest import make_sample_table


def test_identical_tables_pass_with_zero_metrics(sample_table):
    header, rows = sample_table
    report = compare_tables(header, rows, header, rows)
    assert report.ok
    assert all(col.value == 0.0 for col in report.columns)


def test_generated_twin_passes_default_but_not_zero_tolerances(sample_table):
    header, rows = sample_table
    profile = build_profile(header, rows)
    twin_header, twin_rows = generate_table(profile, seed=42)
    report = compare_tables(header, rows, twin_header, twin_rows)
    assert report.ok, render_report(report)
    # Sampling noise never survives zero tolerance.
    strict = Tolerances(max_null_delta=0.0, max_tv=0.0, max_shift=0.0)
    assert not compare_tables(header, rows, twin_header, twin_rows, tolerances=strict).ok


def test_shifted_numeric_column_is_flagged(sample_table):
    header, rows = sample_table
    shifted = [[r[0], str(float(r[1]) + 5000.0)] + r[2:] for r in rows]
    report = compare_tables(header, rows, header, shifted)
    amount = next(c for c in report.columns if c.name == "amount")
    assert amount.metric == "q-shift"
    assert not amount.ok
    assert not report.ok


def test_categorical_mix_drift_is_flagged(sample_table):
    header, rows = sample_table
    skewed = [[r[0], r[1], "north"] + r[3:] for r in rows]  # collapse the mix
    report = compare_tables(header, rows, header, skewed)
    region = next(c for c in report.columns if c.name == "region")
    assert region.metric == "tv"
    assert not region.ok
    assert "differ" in region.note or "type drift" in region.note


def test_null_rate_drift_is_flagged(sample_table):
    header, rows = sample_table
    no_nulls = [r[:5] + [r[5] or "basic"] for r in rows]
    report = compare_tables(header, rows, header, no_nulls)
    plan = next(c for c in report.columns if c.name == "plan")
    assert not plan.ok
    assert "null rate" in plan.note


def test_type_drift_is_flagged(sample_table):
    header, rows = sample_table
    worded = [[("x" if i % 2 else r[0]), *r[1:]] for i, r in enumerate(rows)]
    report = compare_tables(header, rows, header, worded)
    id_col = next(c for c in report.columns if c.name == "id")
    assert not id_col.ok
    assert "type drift" in id_col.note


def test_int_float_boundary_still_compares_numerically(sample_table):
    # A twin can legitimately land as float where the source was int-like;
    # that must be scored on the numbers, not failed as a type change.
    header = ["v"]
    rows_a = [[str(v)] for v in range(200)]
    rows_b = [[f"{v}.0"] for v in range(200)]
    report = compare_tables(header, rows_a, header, rows_b)
    col = report.columns[0]
    assert (col.kind_a, col.kind_b) == ("int", "float")
    assert col.metric == "q-shift"
    assert col.ok


def test_missing_and_extra_columns_fail_the_report(sample_table):
    header, rows = sample_table
    header_b = header[:-1] + ["surprise"]
    report = compare_tables(header, rows, header_b, rows)
    assert report.only_in_a == ["plan"]
    assert report.only_in_b == ["surprise"]
    assert not report.ok


def test_render_report_shows_columns_and_verdict(sample_table):
    header, rows = sample_table
    good = render_report(compare_tables(header, rows, header, rows))
    assert "TWIN OK" in good
    assert "id" in good and "q-shift" in good and "tv" in good

    shifted = [[r[0], str(float(r[1]) + 5000.0)] + r[2:] for r in rows]
    bad = render_report(compare_tables(header, rows, header, shifted))
    assert "DRIFT" in bad
