"""Tests for CSV reading, delimiter sniffing, and writing."""

from __future__ import annotations

import pytest

from datadouble.csvio import read_csv, sniff_delimiter, write_csv
from datadouble.errors import CSVFormatError

from conftest import write_csv_file


def test_roundtrip_comma(tmp_path):
    path = write_csv_file(tmp_path / "t.csv", ["a", "b"], [["1", "x"], ["2", "y"]])
    header, rows, delimiter = read_csv(path)
    assert header == ["a", "b"]
    assert rows == [["1", "x"], ["2", "y"]]
    assert delimiter == ","


def test_sniffs_alternative_delimiters(tmp_path):
    for delimiter in (";", "\t", "|"):
        path = write_csv_file(
            tmp_path / "t.csv", ["a", "b"], [["1", "x"], ["2", "y"]], delimiter
        )
        header, rows, sniffed = read_csv(path)
        assert sniffed == delimiter, repr(delimiter)
        assert header == ["a", "b"]
        assert rows[0] == ["1", "x"]


def test_single_column_falls_back_to_comma():
    # csv.Sniffer cannot find a delimiter in one-column data; we must not
    # let it invent one out of letters.
    assert sniff_delimiter("name\nalpha\nbeta\n") == ","


def test_reads_utf8_bom(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbfa,b\n1,2\n")
    header, rows, _ = read_csv(str(path))
    assert header == ["a", "b"]  # BOM must not stick to the first name
    assert rows == [["1", "2"]]


def test_skips_completely_blank_lines(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,2\n\n3,4\n\n", encoding="utf-8")
    _, rows, _ = read_csv(str(path))
    assert rows == [["1", "2"], ["3", "4"]]


def test_ragged_row_reports_line_number(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,2\n1,2,3\n", encoding="utf-8")
    with pytest.raises(CSVFormatError, match=r"line 3 has 3 fields, expected 2"):
        read_csv(str(path))


def test_empty_file_and_blank_header_raise(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(CSVFormatError, match="empty"):
        read_csv(str(empty))
    blank = tmp_path / "blank.csv"
    blank.write_text(" , \n1,2\n", encoding="utf-8")
    with pytest.raises(CSVFormatError, match="blank header"):
        read_csv(str(blank))


def test_missing_file_raises_csv_error(tmp_path):
    with pytest.raises(CSVFormatError, match="cannot read"):
        read_csv(str(tmp_path / "nope.csv"))


def test_quoted_fields_roundtrip(tmp_path):
    # Embedded delimiter and newline must survive a write/read cycle.
    rows = [["hello, world", "line1\nline2"]]
    out = tmp_path / "q.csv"
    write_csv(str(out), ["msg", "body"], rows)
    header, back, _ = read_csv(str(out))
    assert header == ["msg", "body"]
    assert back == rows


def test_write_to_stdout(capsys):
    write_csv(None, ["a"], [["1"], ["2"]])
    assert capsys.readouterr().out == "a\n1\n2\n"


def test_multi_character_delimiter_is_rejected(tmp_path):
    # csv.reader would raise a bare TypeError here; the library must catch
    # the mistake earlier, with a message that says how to fix it.
    path = write_csv_file(tmp_path / "t.csv", ["a", "b"], [["1", "x"]])
    with pytest.raises(CSVFormatError, match="single character"):
        read_csv(path, delimiter=";;")


def test_write_to_missing_directory_raises_csv_error(tmp_path):
    # A typo'd output directory must surface as a clean input error (which
    # the CLI maps to exit 2), never as a raw FileNotFoundError traceback.
    with pytest.raises(CSVFormatError, match="cannot write"):
        write_csv(str(tmp_path / "no-such-dir" / "out.csv"), ["a"], [["1"]])
