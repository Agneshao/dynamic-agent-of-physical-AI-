"""Immutable contracts for multi-agent mower movement arbitration."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MovementRecommendation(str, Enum):
    CONTINUE_MOWING = "CONTINUE_MOWING"
    STOP_MACHINE = "STOP_MACHINE"
    INSPECT_HAZARD = "INSPECT_HAZARD"


class MovementDecisionOutcome(str, Enum):
    ALLOW = "ALLOW"
    HOLD_FOR_INSPECTION = "HOLD_FOR_INSPECTION"


class AgentMovementPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1, max_length=64)
    recommendation: MovementRecommendation
    reason: str = Field(min_length=1, max_length=512)
    has_veto: bool = False


class MovementAuthorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    device_id: str = Field(min_length=1, max_length=128)
    origin_zone: str = Field(min_length=1, max_length=128)
    target_zone: str = Field(min_length=1, max_length=128)
    hazard_id: str = Field(min_length=1, max_length=128)
    hazard_active: bool
    route_affected: bool


class MovementAuthorityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    device_id: str
    outcome: MovementDecisionOutcome
    final_authority: str
    positions: tuple[AgentMovementPosition, ...]
    winning_rule: str
    reason: str

    @model_validator(mode="after")
    def unique_roles(self) -> MovementAuthorityDecision:
        roles = tuple(position.role for position in self.positions)
        if len(roles) != len(set(roles)):
            raise ValueError("agent movement position roles must be unique")
        return self
