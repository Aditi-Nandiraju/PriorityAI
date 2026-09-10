"""
scripts/atlas_sanity.py
-----------------------
Confirm the app and MongoDB Compass are pointed at the SAME Atlas data before
building anything further on top.

  1. connects with the app's own config,
  2. writes a marker row into audit_log,
  3. reads it straight back,
  4. tells you exactly what to look for in Compass.

    python scripts/atlas_sanity.py
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.config import MONGO_URI  # noqa: E402
from app.db import audit_log, utcnow  # noqa: E402


def _redacted_uri(uri: str) -> str:
    if "@" in uri:
        scheme, rest = uri.split("://", 1)
        return f"{scheme}://***:***@{rest.split('@', 1)[1]}"
    return uri


def main() -> int:
    print(f"storage mode : {db.storage_mode()}")
    print(f"URI          : {_redacted_uri(MONGO_URI)}")
    print(f"database     : {db.MONGO_DB}")

    if not db.MONGO_AVAILABLE:
        print("\nNot connected to Atlas - nothing to cross-check with Compass.", file=sys.stderr)
        return 1

    marker = uuid.uuid4().hex
    doc = {
        "_id": f"sanity-{marker}",
        "timestamp": utcnow(),
        "username": "sanity-check",
        "action": "sanity_check",
        "details": {"marker": marker, "note": "atlas_sanity.py cross-check"},
    }
    audit_log().insert_one(doc)
    print(f"\ninserted audit_log row  _id = {doc['_id']}")

    back = audit_log().find_one({"_id": doc["_id"]})
    ok = bool(back) and back["details"]["marker"] == marker
    print(f"read back               {'OK' if ok else 'FAILED'}")
    total = audit_log().count_documents({})
    print(f"audit_log documents now : {total}")

    print(
        "\nIn Compass (connected to the SAME URI):\n"
        f"  database   : {db.MONGO_DB}\n"
        "  collection : audit_log\n"
        f"  filter     : {{ \"details.marker\": \"{marker}\" }}\n"
        "You should see exactly one matching document. If you do, the app and\n"
        "Compass are on the same data."
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
