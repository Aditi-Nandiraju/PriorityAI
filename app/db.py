"""
db.py
-----
Database access with a graceful in-memory fallback.

At import time we connect to MongoDB (Atlas) and immediately call
`server_info()` to force a real handshake. If that fails -- unreachable cluster,
bad venue wifi, wrong URI -- we flip `MONGO_AVAILABLE = False` and serve every
collection from a plain in-process store instead, so the app still runs and
demos with degraded (non-persistent) storage rather than crashing.

Callers never branch on this. They call `users()`, `audit_log()`, etc. and get
back something that quacks like a pymongo collection either way.

Collections
    users       {_id, username, password_hash, role, created_at}
    reports     raw ingested reports (source-shaped payloads)
    incidents   structured incidents with computed severity/priority
    resources   inventory pools {_id, resource_type, label, quantity}
    audit_log   {timestamp, username, action, details}   (append-only)
    simulations stored allocation plans from POST /simulate
    files       registry of CSVs ingested via /ingest/{source_type} (metadata only)
"""
from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from types import SimpleNamespace
from typing import Any, Iterable

from pymongo import ASCENDING, MongoClient, ReturnDocument

from .config import MONGO_DB, MONGO_TIMEOUT_MS, MONGO_URI

COLLECTION_NAMES = ("users", "reports", "incidents", "resources", "audit_log", "simulations", "files")


# --------------------------------------------------------------------------- #
# in-memory fallback: a minimal subset of the pymongo collection API
# --------------------------------------------------------------------------- #
class _MemCursor:
    def __init__(self, docs: Iterable[dict]):
        self._docs = [dict(d) for d in docs]

    def sort(self, key: str, direction: int = ASCENDING) -> "_MemCursor":
        self._docs.sort(
            key=lambda d: (d.get(key) is None, d.get(key)),
            reverse=direction < 0,
        )
        return self

    def limit(self, n: int) -> "_MemCursor":
        if n:
            self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(dict(d) for d in self._docs)


class _MemCollection:
    """Supports only the operations this codebase actually uses."""

    def __init__(self, name: str):
        self.name = name
        self._docs: list[dict] = []

    @staticmethod
    def _match(doc: dict, flt: dict) -> bool:
        return all(doc.get(k) == v for k, v in flt.items())

    def find(self, flt: dict | None = None) -> _MemCursor:
        flt = flt or {}
        return _MemCursor(d for d in self._docs if self._match(d, flt))

    def find_one(self, flt: dict | None = None) -> dict | None:
        flt = flt or {}
        for d in self._docs:
            if self._match(d, flt):
                return dict(d)
        return None

    def insert_one(self, doc: dict):
        doc = dict(doc)
        doc.setdefault("_id", _uuid.uuid4().hex)
        self._docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    def insert_many(self, docs: Iterable[dict]):
        ids = [self.insert_one(d).inserted_id for d in docs]
        return SimpleNamespace(inserted_ids=ids)

    def find_one_and_update(self, flt: dict, update: dict, return_document=ReturnDocument.AFTER):
        for d in self._docs:
            if self._match(d, flt):
                before = dict(d)
                d.update(update.get("$set", {}))
                return dict(d) if return_document == ReturnDocument.AFTER else before
        return None

    def estimated_document_count(self) -> int:
        return len(self._docs)

    def count_documents(self, flt: dict | None = None) -> int:
        flt = flt or {}
        return sum(1 for d in self._docs if self._match(d, flt))

    def delete_many(self, flt: dict | None = None):
        flt = flt or {}
        keep = [d for d in self._docs if not self._match(d, flt)]
        removed = len(self._docs) - len(keep)
        self._docs = keep
        return SimpleNamespace(deleted_count=removed)

    def create_index(self, *_a, **_k):  # no-op in memory
        return None


# --------------------------------------------------------------------------- #
# connection
# --------------------------------------------------------------------------- #
MONGO_AVAILABLE: bool = False
_client: MongoClient | None = None
_db = None
_mem: dict[str, _MemCollection] = {name: _MemCollection(name) for name in COLLECTION_NAMES}


def _connect() -> None:
    global _client, _db, MONGO_AVAILABLE
    try:
        _client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=MONGO_TIMEOUT_MS,
            uuidRepresentation="standard",
        )
        _client.server_info()  # force a real connection check now, not on first query
        _db = _client[MONGO_DB]
        MONGO_AVAILABLE = True
        print("Connected to MongoDB Atlas")
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        MONGO_AVAILABLE = False
        _client = None
        _db = None
        print(
            "MongoDB unavailable, using in-memory fallback for this session. "
            f"({exc.__class__.__name__}: {str(exc).splitlines()[0][:160]})"
        )


_connect()


def _coll(name: str):
    if MONGO_AVAILABLE and _db is not None:
        return _db[name]
    return _mem[name]


# convenience accessors -----------------------------------------------------
def users():
    return _coll("users")


def reports():
    return _coll("reports")


def incidents():
    return _coll("incidents")


def resources():
    return _coll("resources")


def audit_log():
    return _coll("audit_log")


def files():
    """Registry of files ingested via /ingest/{source_type} -- metadata only
    (filename, source, who/when, what came of it), not the raw bytes."""
    return _coll("files")


def simulations():
    return _coll("simulations")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def ping() -> bool:
    """True if the live Mongo connection is currently usable."""
    if not (MONGO_AVAILABLE and _client is not None):
        return False
    try:
        _client.admin.command("ping")
        return True
    except Exception:
        return False


def storage_mode() -> str:
    return "mongodb" if MONGO_AVAILABLE else "in-memory-fallback"


def ensure_indexes() -> None:
    if not MONGO_AVAILABLE:
        return
    users().create_index([("username", ASCENDING)], unique=True)
    reports().create_index([("created_at", ASCENDING)])
    incidents().create_index([("created_at", ASCENDING)])
    resources().create_index([("resource_type", ASCENDING)])
    audit_log().create_index([("timestamp", ASCENDING)])
    files().create_index([("uploaded_at", ASCENDING)])


def write_audit(username: str, action: str, details: dict[str, Any] | None = None) -> None:
    """
    Append exactly one row to audit_log. Every mutating endpoint calls this
    after its mutation succeeds -- including the unauthenticated /ingest/*
    endpoints, which pass username="anonymous". Routes upstream never branch on
    the storage backend; that choice is made here.
    """
    audit_log().insert_one(
        {
            "_id": _uuid.uuid4().hex,
            "timestamp": utcnow(),
            "username": username,
            "action": action,
            "details": details or {},
        }
    )
