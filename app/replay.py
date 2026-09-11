"""
replay.py
---------
Live-feed replay: drips the three demo report CSVs (data/replay/*.csv) into
the `reports` collection with realistic, compressed pacing, then loops
forever with a small per-cycle jitter so repeats are never bit-identical.

This simulates an incident unfolding live, for demo purposes. It only ever
writes to `reports` -- the same collection /reports/* and /ingest/* write to
-- it never creates incidents itself (this app has no automatic
report -> incident fusion yet).

Pacing:  gap = clamp((next_ts - prev_ts) / compression_factor, 0.5s, 6.0s)
so ~2 hours of real escalation compresses into ~2 minutes (compression=60)
without any single silence dragging on, and without bursts collapsing to 0.

Looping: cycle 1 plays the CSVs' authored order exactly. Cycle 2+ adds a
small random jitter to each timestamp before re-sorting, so the order is
never bit-for-bit identical on repeat -- if someone notices a report they've
seen before, `GET /replay/status` / the frontend badge already say why.

Runs as a single asyncio background task on the API server's own event loop
(no separate process, no extra infra). Only one replay loop runs at a time;
starting again cancels whatever was running and starts fresh.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import random
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .db import reports, utcnow, write_audit

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "replay"
SOURCE_FILES = {
    "citizen_reports": DATA_DIR / "citizen_reports.csv",
    "ground_team": DATA_DIR / "ground_team.csv",
    "social_media": DATA_DIR / "social_media.csv",
}

MIN_GAP_S = 0.5
MAX_GAP_S = 6.0
DEFAULT_COMPRESSION = 60.0
JITTER_SECONDS = 20.0  # applied to timestamps from cycle 2 onward, before re-sorting


def _load_source_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_type, path in SOURCE_FILES.items():
        if not path.exists():
            raise FileNotFoundError(f"missing replay source file: {path}")
        with path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows.append(
                    {
                        "report_id": r["report_id"],
                        "source_type": source_type,
                        "timestamp": dt.datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S"),
                        "location": (r.get("location") or "").strip() or None,
                        "text": r["text"],
                    }
                )
    if not rows:
        raise RuntimeError("no replay rows loaded from data/replay/*.csv")
    return rows


def _sequence_for_cycle(base_rows: list[dict[str, Any]], cycle: int) -> list[dict[str, Any]]:
    if cycle <= 1:
        return sorted(base_rows, key=lambda r: r["timestamp"])
    jittered = [
        {**r, "_play_ts": r["timestamp"] + dt.timedelta(seconds=random.uniform(-JITTER_SECONDS, JITTER_SECONDS))}
        for r in base_rows
    ]
    return sorted(jittered, key=lambda r: r["_play_ts"])


def _gap_seconds(prev_ts: dt.datetime, next_ts: dt.datetime, compression: float) -> float:
    raw = (next_ts - prev_ts).total_seconds() / compression
    return max(MIN_GAP_S, min(MAX_GAP_S, raw))


def _insert_report(row: dict[str, Any], cycle: int) -> str:
    """Blocking (pymongo) -- called via asyncio.to_thread so it never stalls
    the event loop other requests are running on."""
    rid = uuid.uuid4().hex
    doc = {
        "_id": rid,
        "source_type": row["source_type"],
        "created_by": "live-feed-replay",
        "created_at": utcnow(),
        "status": "new",
        "text": row["text"],
        "replay_report_id": row["report_id"],
        "replay_cycle": cycle,
    }
    if row["location"]:
        doc["location"] = row["location"]
    reports().insert_one(doc)
    return rid


@dataclass
class ReplayState:
    running: bool = False
    cycle: int = 0
    reports_ingested_this_cycle: int = 0
    total_reports_per_cycle: int = 0
    compression_factor: float = DEFAULT_COMPRESSION
    started_by: str | None = None
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


state = ReplayState()


async def _run(compression_factor: float) -> None:
    try:
        base_rows = _load_source_rows()
        state.total_reports_per_cycle = len(base_rows)
        state.error = None
        while True:
            state.cycle += 1
            state.reports_ingested_this_cycle = 0
            sequence = _sequence_for_cycle(base_rows, state.cycle)

            prev_ts: dt.datetime | None = None
            for row in sequence:
                if prev_ts is not None:
                    await asyncio.sleep(_gap_seconds(prev_ts, row["timestamp"], compression_factor))
                prev_ts = row["timestamp"]

                await asyncio.to_thread(_insert_report, row, state.cycle)
                state.reports_ingested_this_cycle += 1
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced via /replay/status, not swallowed
        state.error = f"{exc.__class__.__name__}: {exc}"
        raise
    finally:
        state.running = False


def start(compression_factor: float, started_by: str) -> dict:
    stop()  # idempotent: replaces whatever was already running
    state.running = True
    state.cycle = 0
    state.reports_ingested_this_cycle = 0
    state.total_reports_per_cycle = 0
    state.compression_factor = compression_factor
    state.started_by = started_by
    state.error = None
    state.task = asyncio.create_task(_run(compression_factor))
    write_audit(started_by, "replay:start", {"compression_factor": compression_factor})
    return status()


def stop(stopped_by: str | None = None) -> bool:
    """Stops the loop WITHOUT touching any data. (POST /reset is the separate,
    destructive "clear everything" control.)"""
    was_running = state.running
    if state.task is not None:
        state.task.cancel()
        state.task = None
    state.running = False
    if was_running and stopped_by:
        write_audit(stopped_by, "replay:stop", {"cycle": state.cycle})
    return was_running


def status() -> dict:
    return {
        "running": state.running,
        "cycle": state.cycle,
        "reports_ingested_this_cycle": state.reports_ingested_this_cycle,
        "total_reports_per_cycle": state.total_reports_per_cycle,
        "compression_factor": state.compression_factor,
        "error": state.error,
    }
