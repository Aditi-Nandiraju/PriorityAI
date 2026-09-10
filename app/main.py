"""
main.py
-------
PriorityAI FastAPI application.

Auth model
    - GET reads and POST /ingest/* and POST /auth/login are open.
    - Every other mutating endpoint requires a Bearer JWT.
    - POST/PUT /resources additionally require role == "admin".
    - Every mutating endpoint (including the open /ingest/*, as "anonymous")
      appends one row to the audit_log collection.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import ReturnDocument

from resource_rules import INCIDENT_TYPES, RESOURCE_REQUIREMENTS
from severity_rules import (
    SEVERITY_BINS,
    SEVERITY_CLASSES,
    SEVERITY_MAX,
    SEVERITY_WEIGHTS,
    severity_breakdown,
)

from .allocation import allocate, compute_priority, default_confidence
from .auth import authenticate, create_access_token, get_current_user, require_admin
from .config import IS_DEV_SECRET
from .db import (
    audit_log,
    ensure_indexes,
    incidents,
    ping,
    reports,
    resources,
    simulations,
    storage_mode,
    utcnow,
    write_audit,
)
from .models import (
    IncidentManualRequest,
    LoginRequest,
    ManualReportRequest,
    PasteReportsRequest,
    ResourceCreate,
    ResourceUpdate,
    TokenResponse,
)
from .parsers import parse_ingest_csv, split_paste
from .seed import run_seed

SOURCE_TYPES = ("social_media", "ground_team", "citizen_reports")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # db.py already printed "Connected to MongoDB Atlas" / the fallback line.
    ensure_indexes()
    seeded = run_seed()
    if seeded["users_created"]:
        print(f"[seed] fallback users created: {seeded['users_created']} (default passwords)")
    if seeded["resource_pools_created"]:
        print(f"[seed] resource pools created: {seeded['resource_pools_created']}")
    if storage_mode() == "mongodb" and _no_users():
        print("[hint] no users found - run:  python scripts/seed_users.py")
    if IS_DEV_SECRET:
        print("[WARN] JWT_SECRET not set (using dev default); add it to .env before deploying")
    yield


def _no_users() -> bool:
    try:
        from .db import users

        return users().estimated_document_count() == 0
    except Exception:
        return False


app = FastAPI(title="PriorityAI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.exception_handler(Exception)
async def _unhandled(request, exc: Exception):
    # Without this, an unhandled 500 escapes past CORSMiddleware with no
    # Access-Control-Allow-Origin header, and the browser reports the request
    # as an opaque "Failed to fetch" instead of showing the real error.
    import traceback

    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"internal error: {exc.__class__.__name__}: {exc}"},
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _clean(doc: dict[str, Any]) -> dict[str, Any]:
    if not doc:
        return doc
    out = dict(doc)
    out["id"] = str(out.pop("_id"))
    return out


def _incident_out(doc: dict[str, Any]) -> dict[str, Any]:
    """_clean plus the incident type's resource requirement (derived, never
    stored, so it always tracks resource_rules.py)."""
    out = _clean(doc)
    out["required_resources"] = dict(RESOURCE_REQUIREMENTS.get(doc.get("incident_type"), {}))
    return out


def _active_incident_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": d["_id"],
            "incident_type": d["incident_type"],
            "severity_class": d.get("severity_class", "LOW"),
            "priority_score": float(d.get("priority_score", 0.0)),
        }
        for d in incidents().find({"status": "active"})
    ]


def _inventory_map() -> dict[str, int]:
    inv: dict[str, int] = {}
    for pool in resources().find():
        inv[pool["resource_type"]] = inv.get(pool["resource_type"], 0) + int(pool.get("quantity", 0))
    return inv


def _insert_report(payload: dict, source_type: str, created_by: str) -> str:
    rid = uuid.uuid4().hex
    reports().insert_one(
        {
            "_id": rid,
            "source_type": source_type,
            "created_by": created_by,
            "created_at": utcnow(),
            "status": "new",
            **payload,
        }
    )
    return rid


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #
@app.get("/")
def root():
    return {"service": "PriorityAI API", "storage": storage_mode(), "mongo_ok": ping()}


@app.get("/health")
def health():
    return {"storage": storage_mode(), "mongo_ok": ping()}


@app.get("/severity/config")
def severity_config():
    """Weights + thresholds behind compute_severity - lets the UI's live
    flag->score preview stay in sync with the backend formula."""
    low, medium, high = SEVERITY_BINS
    return {
        "weights": SEVERITY_WEIGHTS,
        "max": SEVERITY_MAX,
        "bins": {"medium_at": low, "high_at": medium, "critical_at": high},
        "classes": list(SEVERITY_CLASSES),
        "incident_types": list(INCIDENT_TYPES),
    }


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = authenticate(body.username, body.password)
    if not user:
        raise HTTPException(401, "invalid username or password")
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(access_token=token, username=user["username"], role=user["role"])


# --------------------------------------------------------------------------- #
# ingestion (open)
# --------------------------------------------------------------------------- #
@app.post("/ingest/{source_type}")
async def ingest_csv(source_type: str, file: UploadFile = File(...)):
    if source_type not in SOURCE_TYPES:
        raise HTTPException(404, f"unknown source_type; expected one of {list(SOURCE_TYPES)}")
    raw = await file.read()
    try:
        rows, dropped = parse_ingest_csv(raw, source_type)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    ids = [_insert_report(row, source_type, "anonymous") for row in rows]
    write_audit(
        "anonymous",
        f"ingest:{source_type}",
        {"file": file.filename, "reports_created": len(ids), "dropped_columns": dropped},
    )
    return {
        "source_type": source_type,
        "reports_created": len(ids),
        "report_ids": ids,
        "dropped_columns": dropped,
    }


# --------------------------------------------------------------------------- #
# reports (JWT)
# --------------------------------------------------------------------------- #
@app.post("/reports/paste")
def paste_reports(body: PasteReportsRequest, user: dict = Depends(get_current_user)):
    chunks = split_paste(body.text)
    if not chunks:
        raise HTTPException(422, "no report text found after splitting on blank lines")
    extra = {"location": body.location} if body.location else {}
    ids = [_insert_report({"text": c, **extra}, body.source_type, user["username"]) for c in chunks]
    write_audit(
        user["username"],
        "reports:paste",
        {"source_type": body.source_type, "reports_created": len(ids)},
    )
    return {"reports_created": len(ids), "report_ids": ids}


@app.post("/reports/manual")
def manual_report(report: ManualReportRequest, user: dict = Depends(get_current_user)):
    payload = report.model_dump(exclude_none=True)
    source_type = payload.pop("source_type")
    rid = _insert_report(payload, source_type, user["username"])
    write_audit(user["username"], "reports:manual", {"source_type": source_type, "report_id": rid})
    return {"id": rid, "source_type": source_type}


@app.get("/reports")
def list_reports(
    source_type: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
):
    query = {"source_type": source_type} if source_type else {}
    docs = reports().find(query).sort("created_at", -1).limit(limit)
    return [_clean(d) for d in docs]


# --------------------------------------------------------------------------- #
# incidents
# --------------------------------------------------------------------------- #
@app.post("/incidents/manual")
def manual_incident(body: IncidentManualRequest, user: dict = Depends(get_current_user)):
    flags = {k: bool(v) for k, v in body.flags.items()}
    breakdown = severity_breakdown(flags)
    conf_inputs = body.confidence.model_dump(exclude_none=True) if body.confidence else None
    confidence_score = default_confidence(conf_inputs)
    severity_class = breakdown["class"]
    priority_score = compute_priority(severity_class, confidence_score)

    iid = uuid.uuid4().hex
    doc = {
        "_id": iid,
        "incident_type": body.incident_type,
        "location": body.location,
        "flags": flags,
        "severity_score": breakdown["score"],
        "severity_class": severity_class,
        "severity_breakdown": breakdown,
        "confidence_inputs": conf_inputs,
        "confidence_score": confidence_score,
        "priority_score": priority_score,
        "notes": body.notes,
        "status": "active",
        "source": "manual",
        "created_by": user["username"],
        "created_at": utcnow(),
    }
    incidents().insert_one(doc)
    write_audit(
        user["username"],
        "incidents:manual",
        {
            "incident_id": iid,
            "incident_type": body.incident_type,
            "severity_class": severity_class,
            "severity_score": breakdown["score"],
            "priority_score": priority_score,
        },
    )
    return _incident_out(doc)


@app.get("/incidents")
def list_incidents(
    status: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
):
    query = {"status": status} if status else {}
    docs = incidents().find(query).sort("priority_score", -1).limit(limit)
    return [_incident_out(d) for d in docs]


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    doc = incidents().find_one({"_id": incident_id})
    if not doc:
        raise HTTPException(404, "incident not found")
    return _incident_out(doc)


@app.get("/incidents/{incident_id}/allocation")
def incident_allocation(
    incident_id: str,
    method: str = Query("optimal", pattern="^(optimal|greedy)$"),
):
    """Read-only what-if: run the allocation over the current active queue +
    inventory and return just THIS incident's row. No auth, no audit, no writes
    - it is a preview, not a decision."""
    doc = incidents().find_one({"_id": incident_id})
    if not doc:
        raise HTTPException(404, "incident not found")

    required = dict(RESOURCE_REQUIREMENTS.get(doc.get("incident_type"), {}))
    if doc.get("status") != "active":
        return {
            "incident_id": incident_id,
            "method": method,
            "required_resources": required,
            "allocation": None,
            "note": f"incident status is {doc.get('status')!r}; only active incidents are simulated",
        }

    plan = allocate(method, _active_incident_payload(), _inventory_map())
    row = next((a for a in plan["allocations"] if a["incident_id"] == incident_id), None)
    return {
        "incident_id": incident_id,
        "method": method,
        "required_resources": required,
        "allocation": row,
        "plan_summary": plan["summary"],
    }


# --------------------------------------------------------------------------- #
# resources
# --------------------------------------------------------------------------- #
@app.get("/resources")
def list_resources():
    pools = [_clean(d) for d in resources().find().sort("resource_type", 1)]
    return {"pools": pools, "inventory": _inventory_map()}


@app.post("/resources", status_code=201)
def create_resource(body: ResourceCreate, user: dict = Depends(require_admin)):
    rid = uuid.uuid4().hex
    doc = {
        "_id": rid,
        "resource_type": body.resource_type,
        "label": body.label or body.resource_type.replace("_", " ").title(),
        "quantity": body.quantity,
        "created_by": user["username"],
        "created_at": utcnow(),
    }
    resources().insert_one(doc)
    write_audit(
        user["username"],
        "resources:create",
        {"resource_id": rid, "resource_type": body.resource_type, "quantity": body.quantity},
    )
    return _clean(doc)


@app.put("/resources/{resource_id}")
def update_resource(resource_id: str, body: ResourceUpdate, user: dict = Depends(require_admin)):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "no fields to update")
    updated = resources().find_one_and_update(
        {"_id": resource_id},
        {"$set": changes},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(404, "resource not found")
    write_audit(
        user["username"],
        "resources:update",
        {"resource_id": resource_id, "changes": changes},
    )
    return _clean(updated)


# --------------------------------------------------------------------------- #
# simulation
# --------------------------------------------------------------------------- #
@app.get("/simulate/preview")
def simulate_preview(method: str = Query("optimal", pattern="^(optimal|greedy)$")):
    """Read-only allocation plan for display purposes (the board highlights
    under-resourced incidents from this). No auth, no audit, no persistence -
    POST /simulate is the version an operator commits and that gets logged."""
    return allocate(method, _active_incident_payload(), _inventory_map())


@app.post("/simulate")
def simulate(
    method: str = Query("optimal", pattern="^(optimal|greedy)$"),
    user: dict = Depends(get_current_user),
):
    # Same active-queue snapshot the read-only previews (/simulate/preview and
    # /incidents/{id}/allocation) use, so nothing disagrees with the committed plan.
    plan = allocate(method, _active_incident_payload(), _inventory_map())

    sid = uuid.uuid4().hex
    simulations().insert_one(
        {"_id": sid, "created_by": user["username"], "created_at": utcnow(), **plan}
    )
    write_audit(
        user["username"],
        "simulate",
        {"simulation_id": sid, "method": method, **plan["summary"]},
    )
    return {"id": sid, **plan}


# --------------------------------------------------------------------------- #
# audit (admin read)
# --------------------------------------------------------------------------- #
@app.get("/audit")
def list_audit(
    limit: int = Query(200, ge=1, le=2000),
    _: dict = Depends(require_admin),
):
    docs = audit_log().find().sort("timestamp", -1).limit(limit)
    return [_clean(d) for d in docs]
