"""Unit tests for the pure statistics helpers in datadouble.stats."""

from __future__ import annotations

import pytest

from datadouble.stats import (
    MASK_MAX_LEN,
    MASK_TABLE_CAP,
    frequency_table,
    mask_of,
    mask_table,
    max_decimals,
    quantile_grid,
    sample_quantile_grid,
    total_variation,
)


def test_quantile_grid_endpoints_are_min_and_max():
    grid = quantile_grid([5.0, 1.0, 9.0, 3.0], bins=4)
    assert grid[0] == 1.0
    assert grid[-1] == 9.0


def test_quantile_grid_median_and_interpolation():
    # R-7 rule: median of [0, 10] is 5; quartiles of [0,1,2,3] interpolate.
    assert quantile_grid([0.0, 10.0], bins=2)[1] == 5.0
    assert quantile_grid([0.0, 1.0, 2.0, 3.0], bins=4) == [0.0, 0.75, 1.5, 2.25, 3.0]


def test_quantile_grid_single_value_repeats():
    assert quantile_grid([7.0], bins=4) == [7.0] * 5


def test_quantile_grid_rejects_bad_input():
    with pytest.raises(ValueError):
        quantile_grid([], bins=4)
    with pytest.raises(ValueError):
        quantile_grid([1.0], bins=0)


def test_sample_quantile_grid_inverts_the_grid():
    grid = [10.0, 20.0, 30.0]
    assert sample_quantile_grid(grid, 0.0) == 10.0
    # u is drawn from [0, 1); the max is approached but reachable at u=1.
    assert sample_quantile_grid(grid, 1.0) == 30.0
    assert sample_quantile_grid(grid, 0.5) == 20.0
    assert sample_quantile_grid([0.0, 100.0], 0.25) == 25.0


def test_sample_quantile_grid_clamps_out_of_range_draws():
    # Defensive: hand-edited profiles must not crash the sampler.
    grid = [1.0, 2.0]
    assert sample_quantile_grid(grid, -0.5) == 1.0
    assert sample_quantile_grid(grid, 1.5) == 2.0


def test_frequency_table_orders_by_count_then_value():
    table = frequency_table(["b", "a", "b", "c", "a", "b"])
    assert table == [("b", 3), ("a", 2), ("c", 1)]
    # Ties break alphabetically so profiles are order-independent.
    assert frequency_table(["y", "x"]) == [("x", 1), ("y", 1)]


def test_total_variation_bounds_and_edge_cases():
    same = [("a", 2), ("b", 2)]
    assert total_variation(same, same) == 0.0
    assert total_variation([("a", 1)], [("b", 1)]) == 1.0
    # Half the mass moved from a to b -> distance 0.5.
    assert total_variation([("a", 2)], [("a", 1), ("b", 1)]) == pytest.approx(0.5)
    assert total_variation([], []) == 0.0
    assert total_variation([], [("a", 1)]) == 1.0


def test_mask_of_letters_digits_and_structure():
    assert mask_of("ORD-2041") == "AAA-9999"
    assert mask_of("ana@example.test") == "aaa@aaaaaaa.aaaa"
    # Punctuation and whitespace are structure and survive verbatim.
    assert mask_of("+81 (0) 90") == "+99 (9) 99"


def test_mask_of_non_ascii_letters_become_x():
    assert mask_of("café") == "aaax"
    assert mask_of("東京2丁目") == "xx9xx"


def test_mask_table_buckets_long_values_and_caps_entries():
    long_value = "w" * (MASK_MAX_LEN + 10)
    table = dict(mask_table([long_value, "ab"]))
    assert table[f"LEN:{MASK_MAX_LEN + 10}"] == 1
    assert table["aa"] == 1
    # One distinct mask per value: the table must stop at the cap.
    values = [f"{'v' * (i + 1)}" for i in range(MASK_TABLE_CAP + 20)]
    assert len(mask_table(values)) == MASK_TABLE_CAP


def test_max_decimals_mixed_and_scientific():
    assert max_decimals(["1", "2.50", "3.125"]) == 3
    assert max_decimals(["1", "2"]) == 0
    # Scientific notation forces the cap: precision is not fixed-decimal.
    assert max_decimals(["1.5", "2e-3"], cap=9) == 9
