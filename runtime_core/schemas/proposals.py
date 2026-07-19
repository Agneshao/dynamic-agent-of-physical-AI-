"""Immutable schemas for proposal admission and lifecycle storage."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .world_state import utc_now


class ProposalStatus(str, Enum):
    """Proposal lifecycle states."""

    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class ResourceAccessMode(str, Enum):
    """How an action intends to use a claimed resource."""

    SHARED = "SHARED"
    EXCLUSIVE = "EXCLUSIVE"
    BLOCK = "BLOCK"


class ProposalRejectionCode(str, Enum):
    """Stable machine-readable proposal admission outcomes."""

    STALE_WORLD_VERSION = "STALE_WORLD_VERSION"
    STALE_ORGANIZATION_VERSION = "STALE_ORGANIZATION_VERSION"
    EXPIRED_PROPOSAL = "EXPIRED_PROPOSAL"
    INACTIVE_AGENT_ROLE = "INACTIVE_AGENT_ROLE"
    DUPLICATE_PROPOSAL = "DUPLICATE_PROPOSAL"
    INVALID_SCHEMA = "INVALID_SCHEMA"


JsonScalar = Union[str, int, float, bool, None]
ProposalParameterValue = Union[JsonScalar, tuple[JsonScalar, ...]]


def _normalize_aware_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class ProposalParameter(BaseModel):
    """One named, stable JSON-serializable action parameter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    value: ProposalParameterValue

    @field_validator("value")
    @classmethod
    def reject_non_finite_numbers(
        cls, value: ProposalParameterValue
    ) -> ProposalParameterValue:
        values = value if isinstance(value, tuple) else (value,)
        if any(isinstance(item, float) and not math.isfinite(item) for item in values):
            raise ValueError("parameter values must contain only finite numbers")
        return value


class ProposalAction(BaseModel):
    """A typed action proposed for one target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: UUID = Field(default_factory=uuid4)
    action_type: str = Field(min_length=1)
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    parameters: tuple[ProposalParameter, ...] = ()

    @model_validator(mode="after")
    def require_unique_parameter_names(self) -> ProposalAction:
        names = tuple(parameter.name for parameter in self.parameters)
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique within an action")
        return self

    def get_parameter(self, name: str) -> Optional[ProposalParameter]:
        """Return a parameter by name without exposing a mutable container."""
        return next((item for item in self.parameters if item.name == name), None)


class ResourceClaim(BaseModel):
    """A time-bounded claim over a named runtime resource."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    access_mode: ResourceAccessMode
    valid_until: datetime

    @field_validator("valid_until")
    @classmethod
    def require_aware_valid_until(cls, value: datetime) -> datetime:
        return _normalize_aware_datetime(value, "valid_until")


class Proposal(BaseModel):
    """An immutable agent proposal whose embedded status is always CREATED."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID = Field(default_factory=uuid4)
    epoch_id: UUID
    agent_id: str = Field(min_length=1)
    agent_role: str = Field(min_length=1)
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    action_type: str = Field(min_length=1)
    actions: tuple[ProposalAction, ...] = Field(min_length=1)
    resource_claims: tuple[ResourceClaim, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_summary: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    valid_until: datetime
    status: ProposalStatus = ProposalStatus.CREATED

    @field_validator("created_at", "valid_until")
    @classmethod
    def require_aware_timestamps(cls, value: datetime, info) -> datetime:
        return _normalize_aware_datetime(value, info.field_name)

    @field_validator("status")
    @classmethod
    def require_created_status(cls, value: ProposalStatus) -> ProposalStatus:
        if value != ProposalStatus.CREATED:
            raise ValueError("Proposal.status must remain CREATED")
        return value

    @model_validator(mode="after")
    def require_future_expiration(self) -> Proposal:
        if self.valid_until <= self.created_at:
            raise ValueError("valid_until must be later than created_at")
        return self


class ProposalAdmissionResult(BaseModel):
    """Immutable outcome of one proposal admission request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID
    epoch_id: UUID
    accepted: bool
    status: ProposalStatus
    rejection_code: Optional[ProposalRejectionCode] = None
    message: str = Field(min_length=1)
    checked_world_version: int = Field(ge=0)
    checked_org_version: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        return _normalize_aware_datetime(value, "timestamp")

    @model_validator(mode="after")
    def validate_outcome(self) -> ProposalAdmissionResult:
        if self.accepted:
            if self.status != ProposalStatus.ACCEPTED or self.rejection_code is not None:
                raise ValueError("accepted results require ACCEPTED status and no rejection")
        elif self.status != ProposalStatus.REJECTED or self.rejection_code is None:
            raise ValueError("rejected results require REJECTED status and a rejection code")
        return self


class StoredProposal(BaseModel):
    """Board-owned lifecycle state paired with the untouched source proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal: Proposal
    current_status: ProposalStatus
    admission_result: ProposalAdmissionResult

    @model_validator(mode="after")
    def validate_admission_pair(self) -> StoredProposal:
        if self.proposal.proposal_id != self.admission_result.proposal_id:
            raise ValueError("proposal and admission result IDs must match")
        if self.proposal.epoch_id != self.admission_result.epoch_id:
            raise ValueError("proposal and admission result epoch IDs must match")
        if self.current_status != self.admission_result.status:
            raise ValueError("current status must match the admission result")
        if self.current_status not in (ProposalStatus.ACCEPTED, ProposalStatus.REJECTED):
            raise ValueError("newly stored proposals must be accepted or rejected")
        return self
