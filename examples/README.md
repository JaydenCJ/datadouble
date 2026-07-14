# Examples

- `orders.csv` — 200 invented order rows exercising every column kind:
  masked ids, ISO dates, categoricals, 2-decimal amounts, emails on the
  reserved `example.test` domain, and a coupon column that is ~62% null.
- `twin_demo.py` — the full round trip: profile the table, generate the
  twin twice to demonstrate seeded determinism, then score the twin
  against the original. Prints `DEMO OK` when every claim checks out.

Run from the repository root:

```bash
pip install -e .
python examples/twin_demo.py
```

`scripts/smoke.sh` drives this demo (plus every CLI subcommand) end to end
and prints `SMOKE OK`.
