"""
seed.py
-------
Startup seeding.

  * Resources: the default inventory is seeded whenever the `resources`
    collection is empty (both storage modes) so /simulate has something to work
    with out of the box.

  * Users: only auto-seeded when running on the IN-MEMORY FALLBACK, where there
    is no persistence and therefore no chance to run the seed script. With a
    real Mongo connection, create accounts with `python scripts/seed_users.py`
    (see DEFAULT_USERS below for the demo set).
"""
from __future__ import annotations

import uuid

from resource_rules import DEFAULT_INVENTORY

from .auth import hash_password
from .config import SEED_DEFAULT_RESOURCES
from .db import MONGO_AVAILABLE, resources, users, utcnow

DEFAULT_USERS = [
    {"username": "admin", "password": "admin123", "role": "admin"},
    {"username": "operator", "password": "operator123", "role": "operator"},
    {"username": "viewer", "password": "viewer123", "role": "operator"},
]


def seed_users_if_fallback() -> list[str]:
    if MONGO_AVAILABLE or users().estimated_document_count() > 0:
        return []
    created = []
    for u in DEFAULT_USERS:
        users().insert_one(
            {
                "_id": uuid.uuid4().hex,
                "username": u["username"],
                "password_hash": hash_password(u["password"]),
                "role": u["role"],
                "created_at": utcnow(),
            }
        )
        created.append(u["username"])
    return created


def seed_resources_if_empty() -> int:
    if not SEED_DEFAULT_RESOURCES or resources().estimated_document_count() > 0:
        return 0
    resources().insert_many(
        {
            "_id": uuid.uuid4().hex,
            "resource_type": rtype,
            "label": rtype.replace("_", " ").title(),
            "quantity": qty,
            "created_at": utcnow(),
        }
        for rtype, qty in DEFAULT_INVENTORY.items()
    )
    return len(DEFAULT_INVENTORY)


def run_seed() -> dict:
    return {
        "users_created": seed_users_if_fallback(),
        "resource_pools_created": seed_resources_if_empty(),
    }
