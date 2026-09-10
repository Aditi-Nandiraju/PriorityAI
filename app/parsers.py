"""
parsers.py
----------
Turn the two bulk ingestion formats into normalised report dicts:

  * paste  - one text blob, split into reports on blank-line delimiters
  * CSV    - one file, one report per row, source-aware columns

CSV columns not valid for the given source (e.g. a `phone` column on a
citizen_reports upload) are dropped and reported back, never stored.
"""
from __future__ import annotations

import csv
import io
import re

from .models import INGEST_EXTRA_COLUMNS

_BASE_COLS = {"text", "location", "occurred_at"}
_BLANK_LINE = re.compile(r"\n\s*\n")


def split_paste(text: str) -> list[str]:
    """Split pasted text into report bodies on one-or-more blank lines."""
    return [chunk.strip() for chunk in _BLANK_LINE.split(text.strip()) if chunk.strip()]


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def parse_ingest_csv(raw: bytes, source_type: str) -> tuple[list[dict], list[str]]:
    """
    Returns (report_dicts, dropped_columns).

    Raises ValueError on an unreadable file or a missing `text` column.
    """
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV appears to be empty")

    fields = {(f or "").strip() for f in reader.fieldnames}
    if "text" not in fields:
        raise ValueError("CSV must contain a 'text' column")

    allowed = _BASE_COLS | INGEST_EXTRA_COLUMNS[source_type]
    dropped = sorted(fields - allowed)
    extra_cols = INGEST_EXTRA_COLUMNS[source_type]

    rows: list[dict] = []
    for raw_row in reader:
        row = {(k or "").strip(): (v or "") for k, v in raw_row.items()}
        body = row.get("text", "").strip()
        if not body:
            continue
        doc: dict = {"text": body}
        if row.get("location", "").strip():
            doc["location"] = row["location"].strip()
        if row.get("occurred_at", "").strip():
            doc["occurred_at"] = row["occurred_at"].strip()
        for col in extra_cols:
            val = row.get(col, "").strip()
            if val:
                doc[col] = _truthy(val) if col == "verified" else val
        rows.append(doc)

    return rows, dropped
