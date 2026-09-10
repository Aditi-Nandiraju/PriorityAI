"""
config.py
---------
The ONLY place the app reads process environment. Everything else imports from
here. Values come from the project-root `.env` (via python-dotenv), then the real
environment, then a safe default.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


def _env(*names: str, default: str | None = None) -> str | None:
    """First non-empty value among `names`, else `default`."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return default


# --- Mongo -----------------------------------------------------------------
# The Atlas onboarding .env calls it MONGODB_URI; accept MONGO_URI too.
MONGO_URI: str = _env("MONGODB_URI", "MONGO_URI", default="mongodb://localhost:27017")
MONGO_DB: str = _env("MONGODB_DB", "MONGO_DB", default="priorityai")
MONGO_TIMEOUT_MS: int = int(_env("MONGODB_TIMEOUT_MS", default="3000"))

# --- Auth ----------------------------------------------------------------
JWT_SECRET: str = _env("JWT_SECRET", default="dev-only-change-me")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = int(_env("PRIORITYAI_JWT_EXPIRE_MINUTES", default="720"))

# --- Seeding -------------------------------------------------------------
SEED_DEFAULT_RESOURCES: bool = _env("PRIORITYAI_SEED_RESOURCES", default="1") != "0"

IS_DEV_SECRET: bool = JWT_SECRET == "dev-only-change-me"
