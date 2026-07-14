"""Tests for profile building, serialization, and validation."""

from __future__ import annotations

import json

import pytest

from datadouble.errors import CSVFormatError, ProfileFormatError
from datadouble.profile import (
    ProfileOptions,
    build_profile,
    dump_profile,
    load_profile,
)

from conftest import make_sample_table


def _kinds(profile):
    return {col.name: col.kind for col in profile.columns}


def test_kinds_inferred_on_mixed_table(sample_table):
    header, rows = sample_table
    profile = build_profile(header, rows)
    assert _kinds(profile) == {
        "id": "int",
        "amount": "float",
        "region": "categorical",
        "signup": "date",
        "code": "text",
        "plan": "categorical",
    }


def test_null_rate_and_row_count(sample_table):
    header, rows = sample_table
    profile = build_profile(header, rows)
    assert profile.rows == len(rows)
    plan = profile.column("plan")
    nulls = sum(1 for r in rows if r[5] == "")
    assert plan.null_rate == pytest.approx(nulls / len(rows))
    assert profile.column("id").null_rate == 0.0


def test_null_token_keeps_most_common_spelling():
    header = ["v"]
    rows = [["NA"], ["NA"], [""], ["x"], ["y"], ["z"], ["w"]]
    profile = build_profile(header, rows)
    assert profile.column("v").null_token == "NA"


def test_unique_flag_set_only_when_all_distinct(sample_table):
    header, rows = sample_table
    profile = build_profile(header, rows)
    assert profile.column("id").unique is True
    assert profile.column("region").unique is False


def test_float_decimals_recorded():
    profile = build_profile(["p"], [["1.50"], ["2.125"], ["3.0"]])
    assert profile.column("p").payload["decimals"] == 3
    sci = build_profile(["p"], [["1.5e-3"], ["2e4"], ["3.0"]])
    assert sci.column("p").payload["decimals"] is None


def test_quantile_grid_spans_observed_range():
    rows = [[str(v)] for v in range(101)]
    profile = build_profile(["n"], rows, ProfileOptions(bins=4))
    grid = profile.column("n").payload["quantiles"]
    assert grid == [0.0, 25.0, 50.0, 75.0, 100.0]


def test_all_null_and_zero_row_columns_are_empty_kind():
    profile = build_profile(["gone"], [[""], ["null"], ["NA"]])
    col = profile.column("gone")
    assert col.kind == "empty"
    assert col.null_rate == 1.0
    # A header-only CSV profiles the same way.
    headerless = build_profile(["a", "b"], [])
    assert headerless.rows == 0
    assert all(c.kind == "empty" and c.null_rate == 1.0 for c in headerless.columns)


def test_roundtrip_dump_load_preserves_everything(sample_table):
    header, rows = sample_table
    original = build_profile(header, rows, delimiter=";")
    loaded = load_profile(dump_profile(original))
    assert loaded.rows == original.rows
    assert loaded.delimiter == ";"
    for a, b in zip(original.columns, loaded.columns):
        assert (a.name, a.kind, a.null_rate, a.null_token, a.unique) == (
            b.name,
            b.kind,
            b.null_rate,
            b.null_token,
            b.unique,
        )
        assert json.loads(json.dumps(a.payload)) == b.payload


def test_dump_is_canonical_and_stable(sample_table):
    header, rows = sample_table
    profile = build_profile(header, rows)
    text = dump_profile(profile)
    assert text == dump_profile(profile)  # byte-stable
    assert text.endswith("\n")
    doc = json.loads(text)
    assert doc["format"] == "datadouble/profile"
    assert doc["version"] == 1


def test_text_payload_contains_masks_not_values(sample_table):
    # The privacy contract: free-text cells never appear in the profile.
    header, rows = sample_table
    profile = build_profile(header, rows)
    text = dump_profile(profile)
    for row in rows:
        assert row[4] not in text  # every "code" value is masked
    masks = dict(profile.column("code").payload["masks"])
    assert list(masks) == ["AA-999"]


def test_duplicate_column_names_rejected():
    with pytest.raises(CSVFormatError, match="duplicate column name 'a'"):
        build_profile(["a", "a"], [["1", "2"]])


def test_options_are_validated():
    with pytest.raises(ProfileFormatError, match="bins"):
        ProfileOptions(bins=0)
    with pytest.raises(ProfileFormatError, match="cat_cap"):
        ProfileOptions(cat_cap=0)


def test_load_rejects_malformed_documents(sample_table):
    cases = [
        (lambda d: d.update(format="other/thing"), '"format"'),
        (lambda d: d.update(version=99), '"version"'),
        (lambda d: d.update(rows=-1), '"rows"'),
        (lambda d: d.update(delimiter=",,"), '"delimiter"'),
        (lambda d: d.update(columns=[]), '"columns"'),
        (lambda d: d["columns"][0].update(kind="fancy"), '"kind"'),
        (lambda d: d["columns"][0].update(null_rate=1.5), '"null_rate"'),
        (lambda d: d["columns"][0].update(unique="yes"), '"unique"'),
    ]
    header, rows = sample_table
    pristine = dump_profile(build_profile(header, rows))
    for mutate, message in cases:
        doc = json.loads(pristine)
        mutate(doc)
        with pytest.raises(ProfileFormatError, match=message):
            load_profile(json.dumps(doc))


def test_load_rejects_broken_payloads(sample_table):
    header, rows = sample_table
    base = json.loads(dump_profile(build_profile(header, rows)))

    doc = json.loads(json.dumps(base))
    id_col = next(c for c in doc["columns"] if c["name"] == "id")
    id_col["payload"]["quantiles"] = [3.0, 1.0]  # decreasing grid
    with pytest.raises(ProfileFormatError, match="non-decreasing"):
        load_profile(json.dumps(doc))

    doc = json.loads(json.dumps(base))
    region = next(c for c in doc["columns"] if c["name"] == "region")
    region["payload"]["values"] = [["north", 0]]  # zero count
    with pytest.raises(ProfileFormatError, match="positive count"):
        load_profile(json.dumps(doc))


def test_load_rejects_non_json():
    with pytest.raises(ProfileFormatError, match="not valid JSON"):
        load_profile("{not json")
