#!/usr/bin/env bash
# Smoke test for datadouble: profile -> twin -> generate -> compare, driving
# the real CLI end to end. Self-contained: pure stdlib, no network, idempotent
# (works from a clean tree, no install required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

# The package has zero runtime dependencies, so running from src/ needs no install.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/datadouble-smoke.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

ORDERS="$ROOT/examples/orders.csv"
echo "[smoke] python: $("$PYTHON" --version 2>&1)"

# 1. The runnable demo: profile, twin, self-comparison, determinism claims.
demo_out="$("$PYTHON" "$ROOT/examples/twin_demo.py" "$WORKDIR/demo")" \
  || fail "twin_demo.py exited non-zero"
echo "$demo_out" | sed 's/^/[demo] /'
echo "$demo_out" | grep -q "seed 42 twins byte-identical: True" \
  || fail "demo twins were not byte-identical"
echo "$demo_out" | grep -q "TWIN OK" || fail "demo twin drifted out of tolerance"
echo "$demo_out" | grep -q "DEMO OK" || fail "demo did not finish"

# 2. CLI profile: valid JSON that never leaks a source value.
"$PYTHON" -m datadouble profile "$ORDERS" -o "$WORKDIR/profile.json" 2>/dev/null \
  || fail "profile command exited non-zero"
grep -q '"format": "datadouble/profile"' "$WORKDIR/profile.json" \
  || fail "profile.json missing format marker"
if grep -q "example.test" "$WORKDIR/profile.json"; then
  fail "profile.json leaked a source email address"
fi
if grep -q "ORD-1" "$WORKDIR/profile.json"; then
  fail "profile.json leaked a source order id"
fi

# 3. CLI twin: seeded determinism, byte for byte.
"$PYTHON" -m datadouble twin "$ORDERS" -o "$WORKDIR/a.csv" --seed 7 2>/dev/null
"$PYTHON" -m datadouble twin "$ORDERS" -o "$WORKDIR/b.csv" --seed 7 2>/dev/null
"$PYTHON" -m datadouble twin "$ORDERS" -o "$WORKDIR/c.csv" --seed 8 2>/dev/null
cmp -s "$WORKDIR/a.csv" "$WORKDIR/b.csv" || fail "same seed produced different twins"
cmp -s "$WORKDIR/a.csv" "$WORKDIR/c.csv" && fail "different seeds produced identical twins"
lines="$(wc -l < "$WORKDIR/a.csv")"
[ "$lines" -eq 201 ] || fail "twin should have 201 lines (header + 200 rows), got $lines"
head -n 1 "$WORKDIR/a.csv" | grep -q "^order_id,created,region" \
  || fail "twin header does not match the source"

# 4. CLI generate: rows from the profile alone, original CSV not consulted.
"$PYTHON" -m datadouble generate "$WORKDIR/profile.json" --rows 25 --seed 3 \
  -o "$WORKDIR/gen.csv" 2>/dev/null || fail "generate command exited non-zero"
lines="$(wc -l < "$WORKDIR/gen.csv")"
[ "$lines" -eq 26 ] || fail "generate --rows 25 should emit 26 lines, got $lines"

# 5. CLI compare: original vs twin passes (exit 0)...
compare_out="$("$PYTHON" -m datadouble compare "$ORDERS" "$WORKDIR/a.csv")" \
  || fail "compare original-vs-twin should exit 0"
echo "$compare_out" | sed 's/^/[compare] /'
echo "$compare_out" | grep -q "TWIN OK" || fail "compare did not report TWIN OK"

# 6. ...and a deliberately drifted table fails (exit 1) with a named column.
"$PYTHON" - "$ORDERS" "$WORKDIR/drift.csv" <<'PY'
import csv, sys
with open(sys.argv[1], newline="") as fh:
    rows = list(csv.reader(fh))
for row in rows[1:]:
    row[2] = "north"          # collapse the region mix
    row[4] = str(float(row[4]) + 900)  # shift the amount distribution
with open(sys.argv[2], "w", newline="") as fh:
    csv.writer(fh, lineterminator="\n").writerows(rows)
PY
set +e
drift_out="$("$PYTHON" -m datadouble compare "$ORDERS" "$WORKDIR/drift.csv")"
drift_rc=$?
set -e
[ "$drift_rc" -eq 1 ] || fail "compare on drifted data should exit 1, got $drift_rc"
echo "$drift_out" | grep -q "DRIFT" || fail "compare did not report DRIFT"
echo "$drift_out" | grep -Eq "region.*DRIFT" || fail "drifted column not named"

# 7. --version agrees with the package.
version_out="$("$PYTHON" -m datadouble --version)"
pkg_version="$("$PYTHON" -c 'import datadouble; print(datadouble.__version__)')"
[ "$version_out" = "datadouble $pkg_version" ] \
  || fail "--version mismatch: '$version_out' vs package '$pkg_version'"

echo "SMOKE OK"
