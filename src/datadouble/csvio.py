"""CSV reading and writing on top of the standard library ``csv`` module.

Responsibilities kept deliberately small:

- Read a CSV into ``(header, rows, delimiter)`` with delimiter sniffing
  restricted to the four delimiters that occur in practice (``,;\\t|``).
- Validate structure early: a missing header, an empty file, or a row whose
  field count disagrees with the header raises :class:`CSVFormatError` with
  the 1-based line number.
- Write rows back out with the same delimiter, to a path or to stdout.

Files are read as UTF-8 with an optional BOM (``utf-8-sig``), which covers
exports from spreadsheet software without mangling the first header cell.
"""

from __future__ import annotations

import csv
import io
import sys
from typing import List, Optional, Sequence, Tuple

from .errors import CSVFormatError

__all__ = ["read_csv", "write_csv", "sniff_delimiter", "CANDIDATE_DELIMITERS"]

CANDIDATE_DELIMITERS = ",;\t|"

# Sniff on a bounded prefix so a multi-gigabyte file does not get slurped
# twice; 64 KiB is far more than csv.Sniffer needs to settle.
_SNIFF_BYTES = 64 * 1024


def sniff_delimiter(sample: str) -> str:
    """Guess the delimiter of ``sample``, falling back to a comma.

    ``csv.Sniffer`` is only consulted with the candidate set pinned down;
    left unconstrained it happily picks letters out of single-column files.
    """
    try:
        return csv.Sniffer().sniff(sample, delimiters=CANDIDATE_DELIMITERS).delimiter
    except csv.Error:
        return ","


def read_csv(
    path: str,
    delimiter: Optional[str] = None,
) -> Tuple[List[str], List[List[str]], str]:
    """Read ``path`` and return ``(header, rows, delimiter)``.

    Every cell comes back as a string; type interpretation is the job of
    :mod:`datadouble.inference`. Raises :class:`CSVFormatError` for an
    unreadable or structurally broken file.
    """
    if delimiter is not None and len(delimiter) != 1:
        raise CSVFormatError(
            f"delimiter must be a single character, got {delimiter!r} "
            f"(for a tab, pass a literal tab character)"
        )
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            if delimiter is None:
                sample = fh.read(_SNIFF_BYTES)
                delimiter = sniff_delimiter(sample)
                fh.seek(0)
            return _parse(fh, delimiter, path)
    except OSError as exc:
        raise CSVFormatError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise CSVFormatError(f"{path} is not valid UTF-8: {exc}") from exc


def _parse(
    fh: io.TextIOBase, delimiter: str, path: str
) -> Tuple[List[str], List[List[str]], str]:
    reader = csv.reader(fh, delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise CSVFormatError(f"{path} is empty (no header row)") from None
    if not any(cell.strip() for cell in header):
        raise CSVFormatError(f"{path} has a blank header row")

    width = len(header)
    rows: List[List[str]] = []
    for lineno, row in enumerate(reader, start=2):
        if not row:  # skip completely blank lines, a common trailing artifact
            continue
        if len(row) != width:
            raise CSVFormatError(
                f"{path}: line {lineno} has {len(row)} fields, "
                f"expected {width} (per header)"
            )
        rows.append(row)
    return header, rows, delimiter


def write_csv(
    path: Optional[str],
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    delimiter: str = ",",
) -> None:
    """Write ``header`` + ``rows`` to ``path``, or to stdout when ``None``.

    Uses ``\\n`` line endings and minimal quoting so output is stable and
    diff-friendly across platforms. Raises :class:`CSVFormatError` when
    ``path`` cannot be written (missing directory, no permission).
    """
    if path is None:
        _write(sys.stdout, header, rows, delimiter)
        return
    try:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            _write(fh, header, rows, delimiter)
    except OSError as exc:
        raise CSVFormatError(f"cannot write {path}: {exc.strerror or exc}") from exc


def _write(
    fh: io.TextIOBase,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    delimiter: str,
) -> None:
    writer = csv.writer(fh, delimiter=delimiter, lineterminator="\n")
    writer.writerow(list(header))
    for row in rows:
        writer.writerow(list(row))
