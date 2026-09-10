"""
scripts/seed_users.py
---------------------
Create the initial operator/admin accounts directly in MongoDB. There is no
public signup flow -- this is how users are provisioned.

Safe to re-run: a username that already exists is left untouched.

    python scripts/seed_users.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402  (path shim must come first)
from app.auth import hash_password  # noqa: E402
from app.db import users, utcnow  # noqa: E402
from app.seed import DEFAULT_USERS  # noqa: E402


def main() -> int:
    if not db.MONGO_AVAILABLE:
        print(
            "ERROR: MongoDB is not reachable, so seeding would only write to a\n"
            "       throwaway in-memory store. Fix MONGODB_URI in .env and retry.",
            file=sys.stderr,
        )
        return 1

    print(f"Seeding users into '{db.MONGO_DB}' ...")
    created, skipped = [], []
    for u in DEFAULT_USERS:
        if users().find_one({"username": u["username"]}):
            skipped.append(u["username"])
            continue
        users().insert_one(
            {
                "username": u["username"],
                "password_hash": hash_password(u["password"]),
                "role": u["role"],
                "created_at": utcnow(),
            }
        )
        created.append(f"{u['username']} ({u['role']})")

    print(f"  created: {created or '-'}")
    print(f"  skipped (already exist): {skipped or '-'}")
    print("\nDemo credentials:")
    for u in DEFAULT_USERS:
        print(f"  {u['username']:<10} / {u['password']}   [{u['role']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
