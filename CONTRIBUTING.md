# Contributing to datadouble

Thanks for your interest in contributing. Issues, discussions, and pull
requests are all welcome.

## Development setup

Prerequisite: Python 3.9 or newer. The runtime has zero dependencies;
`pytest` is the only development dependency.

```bash
git clone https://github.com/JaydenCJ/datadouble
cd datadouble
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the checks

```bash
pytest                 # 95 deterministic, offline tests
bash scripts/smoke.sh  # end-to-end: profile -> twin -> generate -> compare
```

Both must pass before a pull request is reviewed; `scripts/smoke.sh` drives
the real CLI against `examples/orders.csv` and must print `SMOKE OK`. The
whole suite runs offline in a few seconds and needs no credentials.

## Before you open a pull request

1. Run `pytest` — the full suite must pass.
2. Run `bash scripts/smoke.sh` — it must print `SMOKE OK`.
3. Add tests for behavior changes; keep logic in pure, unit-testable
   modules (`stats`, `inference`, `profile`, `generate`, `compare`).
4. Keep the determinism contract: same profile + seed + row count must stay
   byte-identical. Anything that changes generated output is a breaking
   change and needs a CHANGELOG entry saying so.

## Ground rules

- **No new runtime dependencies.** The package is standard-library only;
  that is the headline feature. Test-only dependencies belong in the
  `dev` extra and need justification in the PR.
- **No network calls, no telemetry.** datadouble must keep working on an
  air-gapped machine.
- **Privacy contract changes need docs.** Anything that puts more source
  data into a profile must update `docs/profile-format.md` and the
  "Privacy model" section of the README in the same pull request.
- **Profile format changes need a version bump.** Anything that changes
  the meaning of an existing field must bump `PROFILE_VERSION`.
- **Keep the three READMEs aligned.** `README.md`, `README.zh.md`, and
  `README.ja.md` are line-for-line translations; update all three when you
  change one (English is the authoritative version).
- Code comments and doc comments are written in English.

## Reporting bugs

Please include `datadouble --version` output, the exact command line, and —
since profiles contain no raw text values by design — the profile JSON plus
a description of the source column that misbehaved. A minimal CSV that
reproduces the problem is even better.

## Security

Please do not report potential privacy leaks (a profile retaining source
values it should not) in public issues; use GitHub's private vulnerability
reporting on this repository instead.
