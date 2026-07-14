"""Tests for column kind inference."""

from __future__ import annotations

import pytest

from datadouble.inference import (
    detect_temporal_format,
    infer_kind,
    is_null,
    looks_float,
    looks_int,
)


def test_is_null_recognizes_common_spellings_only():
    for token in ["", "  ", "null", "NULL", "None", "NA", "n/a", "NaN", "nil"]:
        assert is_null(token), token
    # Treating "0" or "-" as null would corrupt numeric and text columns.
    assert not is_null("0")
    assert not is_null("-")


def test_looks_int_accepts_integers_rejects_padding_and_junk():
    for v in ["0", "7", "-13", "+4", "123456789012345"]:
        assert looks_int(v), v
    # "007" and "08540" are codes; int() round-tripping would eat the zero.
    for v in ["007", "08540", "1.0", "1e3", "12a", " 1", "１２"]:
        assert not looks_int(v), v


def test_looks_float_accepts_numbers_rejects_words():
    for v in ["1.5", ".5", "3.", "-0.25", "2e-3", "1.5E+10", "7"]:
        assert looks_float(v), v
    # float() would accept "inf"/"nan"; the profiler must not.
    for v in ["inf", "-inf", "nan", "1,5", "", "1.2.3"]:
        assert not looks_float(v), v


def test_detect_temporal_formats():
    assert detect_temporal_format(["2026-01-31", "2026-02-01"]) == ("date", "%Y-%m-%d")
    assert detect_temporal_format(["2026/01/31"]) == ("date", "%Y/%m/%d")
    assert detect_temporal_format(["01/31/2026", "02/01/2026"]) == (
        "date",
        "%m/%d/%Y",
    )
    assert detect_temporal_format(["2026-01-31 08:30:00"]) == (
        "datetime",
        "%Y-%m-%d %H:%M:%S",
    )
    assert detect_temporal_format(["2026-01-31T08:30:00"]) == (
        "datetime",
        "%Y-%m-%dT%H:%M:%S",
    )


def test_mixed_formats_are_not_temporal():
    # One format must fit every cell; a mixture demotes the column.
    assert detect_temporal_format(["2026-01-31", "01/31/2026"]) is None
    assert detect_temporal_format(["2026-13-40"]) is None


def test_low_cardinality_numbers_become_categorical():
    # 3 status codes over 200 rows: resampling {200, 404, 500} verbatim is
    # more faithful than interpolating a quantile grid between them.
    values = ["200"] * 150 + ["404"] * 40 + ["500"] * 10
    assert infer_kind(values) == ("categorical", None)


def test_numeric_kinds():
    ints = [str(v) for v in range(100)]
    assert infer_kind(ints) == ("int", None)
    floats = [f"{v}.5" for v in range(100)]
    assert infer_kind(floats) == ("float", None)
    # A single decimal value makes the whole column float.
    assert infer_kind(ints[:99] + ["1.5"]) == ("float", None)


def test_moderate_cardinality_strings_are_categorical():
    values = (["north", "south", "east", "west"] * 25)[:100]
    assert infer_kind(values) == ("categorical", None)


def test_high_cardinality_strings_are_text():
    values = [f"user-{i}@example.test" for i in range(100)]
    assert infer_kind(values) == ("text", None)


def test_cat_cap_pushes_columns_to_text():
    values = [f"tag{i}" for i in range(20)] * 5
    assert infer_kind(values, cat_cap=32)[0] == "categorical"
    assert infer_kind(values, cat_cap=10)[0] == "text"


def test_infer_kind_requires_values():
    with pytest.raises(ValueError):
        infer_kind([])
