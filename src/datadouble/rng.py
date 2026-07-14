"""Deterministic, column-scoped random number generation.

datadouble's determinism guarantee is: *same profile + same seed + same row
count -> byte-identical output*. To make that guarantee robust, each column
gets its own :class:`random.Random` stream derived from the base seed, the
column name, and a purpose label. Consequences:

- Reordering columns in a profile does not change any column's values.
- Adding or removing a column leaves every other column's output untouched.
- Null placement uses a separate stream from value generation, so changing a
  column's null rate never reshuffles its non-null values.

The derivation hashes the inputs with SHA-256 and seeds a Mersenne Twister
with the first 8 bytes. ``random.Random`` seeded with an int is stable across
CPython versions, so twins are reproducible across machines.
"""

from __future__ import annotations

import hashlib
import random

__all__ = ["derive_rng", "derive_seed"]

# Unit separator: cannot appear in a seed's decimal form and is vanishingly
# unlikely in a column name, so concatenation cannot collide two keys.
_SEP = "\x1f"


def derive_seed(base_seed: int, *labels: str) -> int:
    """Derive a 64-bit child seed from a base seed and one or more labels."""
    key = _SEP.join([str(base_seed), *labels]).encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:8], "big")


def derive_rng(base_seed: int, *labels: str) -> random.Random:
    """Return an independent ``random.Random`` stream for ``labels``."""
    return random.Random(derive_seed(base_seed, *labels))
