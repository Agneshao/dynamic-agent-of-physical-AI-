"""Frozen contracts for the operator-to-runtime model chat boundary."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .organization import OperatingMode


class RuntimeChatIntent(str, Enum):
    ANSWER = "ANSWER"
    START_INSPECTION = "START_INSPECTION"
    REDIRECT_INSPECTION = "REDIRECT_INSPECTION"
    RETURN_MACHINE_TO_BASE = "RETURN_MACHINE_TO_BASE"
    ASSIGN_MOWING_ZONE = "ASSIGN_MOWING_ZONE"
    CREATE_MAINTENANCE_TASK = "CREATE_MAINTENANCE_TASK"
    CLEAR_MAINTENANCE_HAZARD = "CLEAR_MAINTENANCE_HAZARD"
    INJECT_THUNDERSTORM = "INJECT_THUNDERSTORM"
    ASSESS_RISK = "ASSESS_RISK"
    PREPARE_EMERGENCY_ORGANIZATION = "PREPARE_EMERGENCY_ORGANIZATION"
    REQUEST_AUTHORIZATION = "REQUEST_AUTHORIZATION"
    APPROVE_EMERGENCY = "APPROVE_EMERGENCY"
    DEFER_EMERGENCY = "DEFER_EMERGENCY"
    CLEAR_EMERGENCY = "CLEAR_EMERGENCY"


class RuntimeChatDevice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    device_id: str = Field(min_length=1, max_length=128)
    device_type: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=128)
    zone: Optional[str] = Field(default=None, max_length=128)


class RuntimeChatHazard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hazard_id: str = Field(min_length=1, max_length=128)
    hazard_type: str = Field(min_length=1, max_length=128)
    active: bool
    zone: str = Field(min_length=1, max_length=128)
    clearance: str = Field(min_length=1, max_length=128)


class RuntimeChatRequest(BaseModel):
    """Detached read-only context submitted by the operator UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1, max_length=2000)
    mode: OperatingMode
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    incident_id: str = Field(min_length=1, max_length=128)
    phase: str = Field(min_length=1, max_length=128)
    devices: tuple[RuntimeChatDevice, ...] = ()
    hazards: tuple[RuntimeChatHazard, ...] = ()

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be blank")
        return stripped

    @model_validator(mode="after")
    def unique_device_ids(self) -> RuntimeChatRequest:
        ids = tuple(device.device_id for device in self.devices)
        if len(ids) != len(set(ids)):
            raise ValueError("device_id values must be unique")
        hazard_ids = tuple(hazard.hazard_id for hazard in self.hazards)
        if len(hazard_ids) != len(set(hazard_ids)):
            raise ValueError("hazard_id values must be unique")
        return self


class RuntimeChatReply(BaseModel):
    """Structured model output without execution or state-write capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reply: str = Field(min_length=1, max_length=3000)
    tags: tuple[str, ...] = Field(default=(), max_length=6)
    intent: RuntimeChatIntent = RuntimeChatIntent.ANSWER

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not tag or len(tag) > 64 for tag in value):
            raise ValueError("tags must contain non-empty values up to 64 characters")
        if len(value) != len(set(value)):
            raise ValueError("tags must be unique")
        return value
