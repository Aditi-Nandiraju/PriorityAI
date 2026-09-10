"""
scripts/check_mongo_connection.py
---------------------------------
Standalone end-to-end check of the MongoDB Atlas setup: .env -> Atlas ->
read/write permission on the `priorityai` database.

Run this FIRST after any MongoDB-related change (new cluster, edited .env,
changed Database Access role) - before testing the app itself. If the app's
routes break later, a green run here means the database layer isn't the cause.

    python scripts/check_mongo_connection.py

Exit code 0 = fully verified, 1 = failed (with a specific reason).
"""
from __future__ import annotations

import datetime
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The final status line uses check/cross glyphs; Windows consoles default to
# cp1252 and would raise UnicodeEncodeError on them.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - older/odd stdouts
    pass

from pymongo import MongoClient  # noqa: E402
from pymongo.errors import (  # noqa: E402
    ConfigurationError,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from app.config import MONGO_DB, MONGO_URI  # noqa: E402  (path shim first)

PASS_LINE = "✓ MongoDB connection fully verified — read/write working"
FAIL_PREFIX = "✗ MongoDB connection failed: "


def _redacted(uri: str) -> str:
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", uri)


def _first_line(exc: Exception, limit: int = 220) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:limit] + ("..." if len(text) > limit else "")


def fail(reason: str) -> int:
    print()
    print(FAIL_PREFIX + reason)
    return 1


def _diagnose_op_failure(exc: OperationFailure, during: str) -> str:
    code = exc.code
    low = str(exc).lower()
    is_authz = code == 13 or "not authorized" in low or "unauthorized" in low
    is_authn = (not is_authz) and (code in (18, 8000) or "auth" in low)

    if is_authn:
        return (
            f"authentication failure while {during} — the username/password in "
            f"MONGODB_URI is wrong. Fix it in .env and check Atlas → Database Access.\n"
            f"   detail: {_first_line(exc)}"
        )
    if is_authz:
        return (
            f"authorization failure while {during} — connected and authenticated "
            f"fine, but this user has no read/write role on '{MONGO_DB}'. In Atlas → "
            f"Database Access, give the user 'Read and write to any database' (or "
            f"readWrite on {MONGO_DB}).\n"
            f"   detail: {_first_line(exc)}"
        )
    return f"database error while {during}: {_first_line(exc)}"


def main() -> int:
    print(f"URI      : {_redacted(MONGO_URI)}")
    print(f"database : {MONGO_DB}")
    print("connecting (forcing a server_info() round-trip, 5s timeout) ...")

    # --- 2/3: build the client AND force a real round-trip -----------------
    # For mongodb+srv:// URIs pymongo does the SRV DNS lookup during
    # MongoClient(...) construction, so both steps sit in one try block.
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        info = client.server_info()
    except ServerSelectionTimeoutError as exc:
        detail = _first_line(exc)
        if "bad auth" in detail.lower() or "authentication failed" in detail.lower():
            return fail(
                "authentication failed — wrong username/password in MONGODB_URI. "
                "Check Atlas → Database Access.\n"
                f"   detail: {detail}"
            )
        return fail(
            "cannot reach Atlas within 5s — DNS or network failure. Check your "
            "internet / venue wifi, and that this machine's IP is allowed under "
            "Atlas → Network Access.\n"
            f"   detail: {detail}"
        )
    except ConfigurationError as exc:
        return fail(
            "cannot resolve the cluster hostname (SRV DNS lookup failed). Check the "
            "host in MONGODB_URI, or that DNS is reachable.\n"
            f"   detail: {_first_line(exc)}"
        )
    except OperationFailure as exc:
        return fail(_diagnose_op_failure(exc, "authenticating"))
    except PyMongoError as exc:
        return fail(f"could not connect: {_first_line(exc)}")

    print(f"✓ connected — MongoDB server version {info.get('version', '?')}")
    print(f"✓ will read/write database '{MONGO_DB}'")

    db = client[MONGO_DB]

    # --- 4: prove write + read + delete ------------------------------------
    test = db["connection_test"]
    doc = {
        "_id": f"conntest-{uuid.uuid4().hex}",
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "source": "check_mongo_connection.py",
    }
    try:
        test.insert_one(doc)
        print(f"✓ write  OK — inserted {doc['_id']}")

        back = test.find_one({"_id": doc["_id"]})
        if not back:
            return fail("wrote a document but could not read it back")
        print(f"✓ read   OK — {back}")

        test.delete_one({"_id": doc["_id"]})
        print("✓ delete OK — test document removed")

        if test.estimated_document_count() == 0:
            db.drop_collection("connection_test")
    except OperationFailure as exc:
        return fail(_diagnose_op_failure(exc, "reading/writing the test document"))
    except PyMongoError as exc:
        return fail(f"read/write test failed: {_first_line(exc)}")

    # --- 5: list existing collections -------------------------------------
    try:
        collections = sorted(db.list_collection_names())
    except OperationFailure as exc:
        return fail(_diagnose_op_failure(exc, "listing collections"))

    print(f"\ncollections in '{MONGO_DB}': {collections or '(none yet)'}")
    for name in ("users", "audit_log"):
        state = "present" if name in collections else "not created yet (run scripts/seed_users.py)"
        print(f"  - {name}: {state}")

    print()
    print(PASS_LINE)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(fail("interrupted"))
