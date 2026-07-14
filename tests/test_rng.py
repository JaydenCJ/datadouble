"""Tests for the deterministic per-column RNG derivation."""

from __future__ import annotations

from datadouble.rng import derive_rng, derive_seed


def test_same_inputs_give_same_seed_and_stream():
    assert derive_seed(42, "amount", "value") == derive_seed(42, "amount", "value")
    a = [derive_rng(42, "amount", "value").random() for _ in range(3)]
    b = [derive_rng(42, "amount", "value").random() for _ in range(3)]
    assert a == b


def test_labels_isolate_streams():
    # Independence per column is what makes twins reorder-stable, and null
    # placement must never share a stream with value generation.
    assert derive_seed(42, "amount", "value") != derive_seed(42, "qty", "value")
    assert derive_seed(42, "amount", "null") != derive_seed(42, "amount", "value")


def test_base_seed_changes_every_stream():
    assert derive_seed(1, "amount", "value") != derive_seed(2, "amount", "value")
    assert derive_rng(1, "a").random() != derive_rng(2, "a").random()
