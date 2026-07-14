"""End-to-end CLI tests driving datadouble.cli.main in-process."""

from __future__ import annotations

import json

import pytest

import datadouble
from datadouble.cli import main

from conftest import make_sample_table, write_csv_file


def test_version_and_help(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"datadouble {datadouble.__version__}"
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for command in ("profile", "twin", "generate", "compare"):
        assert command in out


def test_profile_to_stdout_is_valid_json(orders_csv, capsys):
    assert main(["profile", orders_csv]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["format"] == "datadouble/profile"
    assert {c["name"] for c in doc["columns"]} >= {"order_id", "amount", "region"}


def test_profile_writes_file_with_summary_on_stderr(orders_csv, tmp_path, capsys):
    out = tmp_path / "p.json"
    assert main(["profile", orders_csv, "-o", str(out)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "columns profiled" in captured.err
    assert json.loads(out.read_text())["rows"] == 200


def test_twin_defaults_to_source_row_count(orders_csv, tmp_path):
    out = tmp_path / "twin.csv"
    assert main(["twin", orders_csv, "-o", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert len(lines) == 201  # header + 200 rows
    assert lines[0] == "order_id,created,region,status,amount,qty,email,coupon"


def test_twin_is_deterministic_per_seed_and_honors_rows(orders_csv, tmp_path):
    a, b, c = (tmp_path / n for n in ("a.csv", "b.csv", "c.csv"))
    main(["twin", orders_csv, "-o", str(a), "--rows", "7", "--seed", "5"])
    main(["twin", orders_csv, "-o", str(b), "--rows", "7", "--seed", "5"])
    main(["twin", orders_csv, "-o", str(c), "--rows", "7", "--seed", "6"])
    assert len(a.read_text().splitlines()) == 8  # header + 7 rows
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes() != c.read_bytes()


def test_twin_preserves_input_delimiter(tmp_path):
    header, rows = make_sample_table(rows=60)
    src = write_csv_file(tmp_path / "src.csv", header, rows, delimiter=";")
    out = tmp_path / "twin.csv"
    assert main(["twin", src, "-o", str(out)]) == 0
    assert out.read_text().splitlines()[0] == ";".join(header)


def test_generate_needs_only_the_profile(orders_csv, tmp_path, capsys):
    # The workflow that unblocks sharing: profile leaves, data stays.
    prof = tmp_path / "p.json"
    main(["profile", orders_csv, "-o", str(prof)])
    capsys.readouterr()
    assert main(["generate", str(prof), "--rows", "12", "--seed", "3"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 13
    assert lines[0].startswith("order_id,")


def test_compare_ok_exits_zero(orders_csv, tmp_path, capsys):
    twin = tmp_path / "twin.csv"
    main(["twin", orders_csv, "-o", str(twin), "--seed", "42"])
    capsys.readouterr()
    assert main(["compare", orders_csv, str(twin)]) == 0
    assert "TWIN OK" in capsys.readouterr().out


def test_compare_drift_exits_one(orders_csv, tmp_path, capsys):
    header, rows = make_sample_table(rows=40)
    other = write_csv_file(tmp_path / "other.csv", header, rows)
    assert main(["compare", orders_csv, other]) == 1
    assert "DRIFT" in capsys.readouterr().out


def test_compare_tolerance_flags_are_applied(orders_csv, tmp_path, capsys):
    twin = tmp_path / "twin.csv"
    main(["twin", orders_csv, "-o", str(twin), "--seed", "42"])
    capsys.readouterr()
    # Impossible tolerances turn the same comparison into a failure.
    assert (
        main(
            [
                "compare", orders_csv, str(twin),
                "--max-tv", "0", "--max-shift", "0", "--max-null-delta", "0",
            ]
        )
        == 1
    )
    assert "DRIFT" in capsys.readouterr().out


def test_missing_input_exits_two_with_message(tmp_path, capsys):
    assert main(["twin", str(tmp_path / "absent.csv")]) == 2
    assert "datadouble: error:" in capsys.readouterr().err


def test_broken_profile_exits_two(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "other"}', encoding="utf-8")
    assert main(["generate", str(bad)]) == 2
    assert '"format"' in capsys.readouterr().err


def test_unwritable_output_exits_two_with_message(orders_csv, tmp_path, capsys):
    # Exit code 1 is reserved for compare-found drift; I/O failures must be
    # exit 2 with a one-line error, not a traceback with an ambiguous code.
    target = str(tmp_path / "no-such-dir" / "twin.csv")
    assert main(["twin", orders_csv, "-o", target]) == 2
    assert "cannot write" in capsys.readouterr().err


def test_multi_character_delimiter_exits_two(orders_csv, capsys):
    assert main(["profile", orders_csv, "--delimiter", ";;"]) == 2
    assert "single character" in capsys.readouterr().err
