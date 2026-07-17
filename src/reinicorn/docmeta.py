"""Read/write provenance fields in the `**Field:** value` doc header block.

The header block is the run of `**Field:** value` lines directly after the
`# title` heading (blank lines allowed between heading and block). Fields in
the body are never touched.
"""

from __future__ import annotations

import re

# Header-field vocabulary — the ONLY place these strings are defined.
# Implementation code imports these; tests assert the raw literals on
# purpose (pinning the on-disk format against constant typos).
FIELD_STATUS = "Status"
FIELD_REVIEW_PR = "Review-PR"
FIELD_APPROVED_BY = "Approved-by"
FIELD_REVIEW_CANCELLED = "Review-cancelled"

STATUS_DRAFT = "draft"
STATUS_IN_REVIEW = "in-review"
STATUS_APPROVED = "approved"

_FIELD_LINE = re.compile(r"^\*\*([A-Za-z-]+):\*\*\s*(.*)$")

# A block qualifies as a header only if it contains a provenance anchor —
# body prose in **Word:** style (e.g. "**Why:** ...") never does.
_ANCHOR_FIELDS = frozenset({"Date", "Author", "Created", FIELD_STATUS, "Origin"})


def _header_span(lines: list[str]) -> tuple[int, int]:
    """(start, end) line indexes of the header field block (end exclusive).

    Returns (i, i) with i = insertion point when no block exists.
    """
    i = 0
    # Skip title heading and leading blanks
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith("# ")):
        i += 1
    start = i
    names: list[str] = []
    while i < len(lines) and (m := _FIELD_LINE.match(lines[i])):
        names.append(m.group(1))
        i += 1
    if not _ANCHOR_FIELDS.intersection(names):
        return start, start  # bold-colon prose, not a header block
    return start, i


def get_field(text: str, field: str) -> str | None:
    lines = text.splitlines()
    start, end = _header_span(lines)
    for line in lines[start:end]:
        m = _FIELD_LINE.match(line)
        if m and m.group(1) == field:
            return m.group(2).strip()
    return None


def set_field(text: str, field: str, value: str) -> str:
    lines = text.splitlines()
    start, end = _header_span(lines)
    for i in range(start, end):
        m = _FIELD_LINE.match(lines[i])
        if m and m.group(1) == field:
            lines[i] = f"**{field}:** {value}"
            break
    else:
        lines.insert(end, f"**{field}:** {value}")
        # When starting a new header block, keep a blank separator so the
        # field line doesn't merge into a following body paragraph.
        if start == end and end + 1 < len(lines) and lines[end + 1].strip():
            lines.insert(end + 1, "")
    out = "\n".join(lines)
    return out + "\n" if text.endswith("\n") else out


def remove_field(text: str, field: str) -> str:
    lines = text.splitlines()
    start, end = _header_span(lines)
    kept = [
        line for i, line in enumerate(lines)
        if not (start <= i < end
                and (m := _FIELD_LINE.match(line))
                and m.group(1) == field)
    ]
    if kept == lines:
        return text
    out = "\n".join(kept)
    return out + "\n" if text.endswith("\n") else out
