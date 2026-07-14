# Profile format (version 1)

A profile is the JSON document written by `datadouble profile` and consumed
by `datadouble generate`. It is the **only artifact derived from your
data** — review it before sharing, exactly as you would a redacted
document. The file is written with sorted keys, 2-space indentation, and a
trailing newline, so it is byte-stable and diffs cleanly in git.

## Top level

```json
{
  "format": "datadouble/profile",
  "version": 1,
  "rows": 200,
  "delimiter": ",",
  "columns": [ ... ]
}
```

| Key | Type | Meaning |
|---|---|---|
| `format` | string | always `"datadouble/profile"`; rejects unrelated JSON early |
| `version` | int | schema version; this build reads exactly `1` |
| `rows` | int | source row count; the default twin size |
| `delimiter` | string (1 char) | delimiter used when `generate` writes CSV |
| `columns` | array | one object per column, in source order |

## Column object

```json
{
  "name": "amount",
  "kind": "float",
  "null_rate": 0.02,
  "null_token": "",
  "unique": false,
  "payload": { "quantiles": [4.4, 21.9, 60.3, 121.7, 236.9], "decimals": 2 }
}
```

Common fields:

| Key | Type | Meaning |
|---|---|---|
| `name` | string | column name; also keys the per-column random streams |
| `kind` | string | one of `int` `float` `date` `datetime` `categorical` `text` `empty` |
| `null_rate` | number | fraction of source cells that were null tokens |
| `null_token` | string | the most common null spelling observed (emitted verbatim) |
| `unique` | bool | all non-null source values were distinct; generation re-enforces it for `int` and `text` |
| `payload` | object | kind-specific summary, below |

## Payloads by kind

| Kind | Payload | Notes |
|---|---|---|
| `int` | `quantiles` | `bins + 1` non-decreasing empirical quantiles |
| `float` | `quantiles`, `decimals` | `decimals` is `null` when the source used scientific notation |
| `date` | `quantiles`, `format` | quantiles over proleptic ordinals; `format` is the strftime pattern |
| `datetime` | `quantiles`, `format` | quantiles over naive seconds since 1970-01-01 (no timezone math) |
| `categorical` | `values` | `[[value, count], ...]`, most common first — **values are verbatim** |
| `text` | `masks` | `[[mask, count], ...]` structure masks — concrete strings never stored |
| `empty` | `{}` | every source cell was a null token |

## Structure masks

A mask keeps punctuation, whitespace, and symbols verbatim and replaces
ASCII letters with `a`/`A`, digits with `9`, and other letters with `x`:

```text
ORD-2041          ->  AAA-9999
ana@example.test  ->  aaa@aaaaaaa.aaaa
+81 (0) 90        ->  +99 (9) 99
```

Values longer than 48 characters collapse into a `LEN:<n>` bucket, and only
the 64 most common masks are kept — rarer shapes are dropped rather than
memorialized, so a one-off value cannot be identified by its unique shape.

## Guarantees consumed by `generate`

- Same profile + same seed + same row count → byte-identical CSV output,
  on any machine and any supported Python version.
- Each column draws from independent streams keyed by `(seed, name,
  purpose)`, so reordering columns, adding columns, or editing one
  column's `null_rate` never changes another column's values.
- Hand-edited profiles are fully validated on load; every error message
  names the offending column and key.
