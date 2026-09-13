"""
fusion.py
---------
Report-to-report fusion: groups newly-ingested reports that are probably
describing the same real-world event, using sentence-embedding similarity.

Scope, deliberately narrow: incidents in this project are created manually
(POST /incidents/manual, with an operator picking incident_type + structural
flags) - there is no free-text field on an incident to fuse a report against,
and no automatic flag-extraction from text. So this module does NOT create,
merge, or score incidents; it only tags `reports` documents with a
`cluster_id` so an operator scanning the Ingest/reports view can see "these 6
reports across social_media/ground_team/citizen_reports are probably the same
event" before manually creating one incident from them, instead of reading
every report one at a time. Severity, confidence, and priority are computed
exactly as before and never touch this module - the two non-negotiable
project rules (severity/confidence are separate dimensions; the live
scoring/allocation path stays deterministic, non-ML) are unaffected.

Trigger point: on every new report, synchronously, at insertion time (called
from app/main.py's _insert_report and app/replay.py's _insert_report). Not a
periodic/batch job - with the MiniLM model this is single-digit milliseconds
of CPU per report after the one-time model load, which is cheap enough to pay
inline and gives the operator an immediately up-to-date view.

Model: sentence-transformers "all-MiniLM-L6-v2", loaded lazily (first call
only) so importing this module - or starting the API - never pays the load
cost, and a machine that has never ingested a report never needs the model or
even a working internet connection for it.

Clustering: connected components, not k-means/DBSCAN - there's no fixed
cluster count, and "these two reports are the same event" should be
transitive (A~B and B~C implies A,B,C together) rather than distance-from-a-
centroid. A new report joins the cluster of every existing report within
CLUSTER_WINDOW_HOURS whose embedding clears SIMILARITY_THRESHOLD; if it
bridges two previously-separate clusters, those clusters are merged (all
their reports relabelled to one surviving id, chosen deterministically as the
lexicographically-smallest of the merged ids, so repeated merges are
idempotent).

Known gaps (surfaced to the user, not silently glossed over):
  - SIMILARITY_THRESHOLD is a reasonable default, not calibrated against any
    labeled "same event" dataset - none exists for this project.
  - Does not extract structured flags from text; an operator still manually
    fills out POST /incidents/manual after reading a cluster.
  - O(n) comparisons per new report against recent reports (no vector index)
    - fine at hackathon/demo scale (hundreds of reports), not built to scale.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from .db import reports

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None  # lazy singleton

SIMILARITY_THRESHOLD = 0.62
CLUSTER_WINDOW_HOURS = 6

FUSION_AVAILABLE = True  # flipped to False if the model can't be loaded (no internet, missing dep, ...)
_load_error: str | None = None


def _get_model():
    global _model, FUSION_AVAILABLE, _load_error
    if _model is None and FUSION_AVAILABLE:
        try:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(_MODEL_NAME)
        except Exception as exc:  # noqa: BLE001 - fusion is a nice-to-have, never worth crashing ingestion
            FUSION_AVAILABLE = False
            _load_error = f"{exc.__class__.__name__}: {exc}"
    return _model


def embed_text(text: str) -> list[float] | None:
    model = _get_model()
    if model is None:
        return None
    return model.encode(text, normalize_embeddings=True).tolist()


def _cosine(a: list[float], b: list[float]) -> float:
    # embeddings are already L2-normalised (normalize_embeddings=True), so the
    # dot product alone *is* the cosine similarity - the full formula is kept
    # here anyway so this function is correct even if that ever changes.
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _naive(ts: _dt.datetime) -> _dt.datetime:
    """MongoDB round-trips datetimes as naive UTC (no tzinfo) regardless of
    what was written, while callers here pass tz-aware `utcnow()` values -
    comparing the two raises TypeError. Strip tzinfo on both sides so the
    comparison always works, in-memory fallback or real Mongo."""
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


def fuse_report(report_id: str, text: str, created_at: _dt.datetime) -> dict[str, Any] | None:
    """
    Embed this report, compare it against other recent reports that already
    have an embedding, and assign/merge cluster ids by connected components.
    Mutates the report's own document (embedding, cluster_id) plus, on a
    merge, every other report moving to the surviving cluster id.

    Returns None (and touches nothing) if the embedding model isn't available
    - ingestion must never fail because fusion couldn't run. Otherwise returns
    {"cluster_id", "matched_report_ids", "merged_clusters"}.
    """
    embedding = embed_text(text)
    if embedding is None:
        return None

    cutoff = _naive(created_at - _dt.timedelta(hours=CLUSTER_WINDOW_HOURS))
    candidates = [
        r
        for r in reports().find({})
        if r["_id"] != report_id and r.get("embedding") and r.get("created_at") and _naive(r["created_at"]) >= cutoff
    ]

    matched_report_ids: list[str] = []
    matched_cluster_ids: set[str] = set()
    for r in candidates:
        if _cosine(embedding, r["embedding"]) >= SIMILARITY_THRESHOLD:
            matched_report_ids.append(r["_id"])
            matched_cluster_ids.add(r.get("cluster_id") or r["_id"])

    merged_clusters: list[str] = []
    if matched_cluster_ids:
        cluster_id = sorted(matched_cluster_ids)[0]
        merged_clusters = sorted(matched_cluster_ids - {cluster_id})
        if merged_clusters:
            for r in reports().find({}):
                if r.get("cluster_id") in merged_clusters:
                    reports().find_one_and_update({"_id": r["_id"]}, {"$set": {"cluster_id": cluster_id}})
    else:
        cluster_id = report_id  # seeds a brand-new, single-report cluster

    reports().find_one_and_update(
        {"_id": report_id},
        {"$set": {"embedding": embedding, "cluster_id": cluster_id}},
    )

    return {
        "cluster_id": cluster_id,
        "matched_report_ids": sorted(set(matched_report_ids)),
        "merged_clusters": merged_clusters,
    }


def list_clusters(min_size: int = 2) -> list[dict[str, Any]]:
    """Group all reports by cluster_id for the operator-facing cluster view.
    Only clusters with >= min_size reports are worth showing (a cluster of one
    is just an unmatched report, not a fusion result)."""
    by_cluster: dict[str, list[dict]] = {}
    for r in reports().find({}):
        cid = r.get("cluster_id")
        if not cid:
            continue
        by_cluster.setdefault(cid, []).append(r)

    clusters = []
    for cid, docs in by_cluster.items():
        if len(docs) < min_size:
            continue
        docs.sort(key=lambda d: _naive(d["created_at"]) if d.get("created_at") else _dt.datetime.min)
        clusters.append(
            {
                "cluster_id": cid,
                "size": len(docs),
                "source_types": sorted({d.get("source_type") for d in docs if d.get("source_type")}),
                "locations": sorted({d.get("location") for d in docs if d.get("location")}),
                "first_seen": docs[0].get("created_at"),
                "last_seen": docs[-1].get("created_at"),
                "reports": [
                    {
                        "id": d["_id"],
                        "source_type": d.get("source_type"),
                        "location": d.get("location"),
                        "text": d.get("text"),
                        "created_at": d.get("created_at"),
                    }
                    for d in docs
                ],
            }
        )
    clusters.sort(key=lambda c: _naive(c["last_seen"]) if c["last_seen"] else _dt.datetime.min, reverse=True)
    return clusters
