"""
models.py
---------
Pydantic request/response schemas.

Report models are source-shaped and use `extra="forbid"`, so the difference
between sources is structural, not cosmetic: `CitizenReport` has no reporter
name / phone / handle field to send at all -- posting one is a 422, not a
silently-dropped value.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from resource_rules import INCIDENT_TYPES, RESOURCE_TYPES
from severity_rules import SEVERITY_WEIGHTS

SourceType = Literal["social_media", "ground_team", "citizen_reports"]
STRUCTURAL_FLAGS = tuple(SEVERITY_WEIGHTS)


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


# --------------------------------------------------------------------------- #
# reports - one model per source, discriminated on `source_type`
# --------------------------------------------------------------------------- #
class _ReportBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    location: str | None = None
    occurred_at: dt.datetime | None = None


class SocialMediaReport(_ReportBase):
    source_type: Literal["social_media"] = "social_media"
    platform: str | None = None
    handle: str | None = None
    url: str | None = None


class GroundTeamReport(_ReportBase):
    source_type: Literal["ground_team"] = "ground_team"
    team_id: str | None = None
    unit: str | None = None
    verified: bool = False


class CitizenReport(_ReportBase):
    source_type: Literal["citizen_reports"] = "citizen_reports"
    # No reporter identity fields by design (name / phone / email / handle).


ManualReportRequest = Annotated[
    Union[SocialMediaReport, GroundTeamReport, CitizenReport],
    Field(discriminator="source_type"),
]

# columns an /ingest CSV may carry, per source (besides text/location/occurred_at)
INGEST_EXTRA_COLUMNS: dict[str, set[str]] = {
    "social_media": {"platform", "handle", "url"},
    "ground_team": {"team_id", "unit", "verified"},
    "citizen_reports": set(),
}


class PasteReportsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: SourceType
    text: str = Field(min_length=1)
    location: str | None = None


# --------------------------------------------------------------------------- #
# incidents
# --------------------------------------------------------------------------- #
class ConfidenceInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    num_sources: int | None = Field(default=None, ge=0)
    ground_confirmed: bool | None = None
    agreement_ratio: float | None = Field(default=None, ge=0, le=1)
    recency_minutes: int | None = Field(default=None, ge=0)


class IncidentManualRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_type: str
    location: str | None = None
    flags: dict[str, bool] = Field(default_factory=dict)
    confidence: ConfidenceInputs | None = None
    notes: str | None = None

    @field_validator("incident_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in INCIDENT_TYPES:
            raise ValueError(f"unknown incident_type {v!r}; expected one of {list(INCIDENT_TYPES)}")
        return v

    @field_validator("flags")
    @classmethod
    def _known_flags(cls, v: dict[str, bool]) -> dict[str, bool]:
        unknown = set(v) - set(STRUCTURAL_FLAGS)
        if unknown:
            raise ValueError(
                f"unknown severity flag(s) {sorted(unknown)}; allowed: {list(STRUCTURAL_FLAGS)}"
            )
        return v


# --------------------------------------------------------------------------- #
# resources
# --------------------------------------------------------------------------- #
class ResourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_type: str
    label: str | None = None
    quantity: int = Field(ge=0)

    @field_validator("resource_type")
    @classmethod
    def _known_resource(cls, v: str) -> str:
        if v not in RESOURCE_TYPES:
            raise ValueError(f"unknown resource_type {v!r}; expected one of {list(RESOURCE_TYPES)}")
        return v


class ResourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    quantity: int | None = Field(default=None, ge=0)


# --------------------------------------------------------------------------- #
# generic responses
# --------------------------------------------------------------------------- #
class CreatedResponse(BaseModel):
    id: str
    created: int = 1
    detail: dict[str, Any] | None = None
