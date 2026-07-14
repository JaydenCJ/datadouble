"""Exception hierarchy for datadouble.

Every error raised by the library derives from :class:`DatadoubleError`, so
callers can catch one type at the boundary. The CLI maps these to exit code 2
(usage / input problems) while keeping the messages human-readable.
"""

from __future__ import annotations

__all__ = [
    "DatadoubleError",
    "CSVFormatError",
    "ProfileFormatError",
    "GenerationError",
]


class DatadoubleError(Exception):
    """Base class for all datadouble errors."""


class CSVFormatError(DatadoubleError):
    """The input CSV could not be read or is structurally invalid.

    Raised for unreadable files, empty files, and rows whose field count
    does not match the header.
    """


class ProfileFormatError(DatadoubleError):
    """A profile JSON document is missing fields, mistyped, or unsupported.

    The message always names the offending key or column so a hand-edited
    profile can be fixed without reading source code.
    """


class GenerationError(DatadoubleError):
    """A column profile cannot be turned into a value sampler.

    This indicates an internally inconsistent profile (for example a
    categorical column with an empty value table) rather than bad user input.
    """
