"""Validated operator requests for the live Isaac control HTTP boundary."""

from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .commands import CommandStatus, CommandType
from .world_state import FrozenMachineState, FrozenPersonState


_CONTROL_COMMANDS = {
    CommandType.PAUSE_MACHINE,
    CommandType.HOLD_POSITION,
    CommandType.RETURN_TO_BASE,
    CommandType.MOVE_TO_ZONE,
    CommandType.RECALL_DRONE,
    CommandType.ACTIVATE_THUNDERSTORM,
    CommandType.RESET_SCENARIO,
    CommandType.START_SCENARIO,
    CommandType.INSPECT_ZONE,
    CommandType.DECLARE_IRRIGATION_LEAK,
    CommandType.CLEAR_IRRIGATION_LEAK,
}
_CONTROL_TARGETS = {"mower_1", "mower_2", "drone_1", "runtime"}
_MOWING_ZONES = {"ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D"}


class IsaacControlCommandRequest(BaseModel):
    """One explicit, human-confirmed command submitted by the operator UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    incident_id: str = Field(min_length=1, max_length=128)
    command_type: CommandType
    target_id: str = Field(min_length=1, max_length=128)
    target_zone: Optional[str] = Field(default=None, max_length=32)
    operator_id: str = Field(min_length=1, max_length=128)
    confirmed: bool
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)

    @field_validator("target_zone")
    @classmethod
    def normalize_target_zone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().upper().replace(" ", "_")
        if len(normalized) == 1:
            normalized = "ZONE_" + normalized
        if normalized not in _MOWING_ZONES:
            raise ValueError("target_zone must be ZONE_A, ZONE_B, ZONE_C, or ZONE_D")
        return normalized

    @model_validator(mode="after")
    def validate_control_scope(self) -> "IsaacControlCommandRequest":
        if not self.confirmed:
            raise ValueError("live Isaac commands require explicit confirmation")
        if self.command_type not in _CONTROL_COMMANDS:
            raise ValueError("command_type is not enabled for the operator UI")
        if self.target_id not in _CONTROL_TARGETS:
            raise ValueError("target_id is not enabled for the operator UI")
        if self.command_type in {
            CommandType.ACTIVATE_THUNDERSTORM,
            CommandType.RESET_SCENARIO,
            CommandType.START_SCENARIO,
            CommandType.DECLARE_IRRIGATION_LEAK,
            CommandType.CLEAR_IRRIGATION_LEAK,
        }:
            if self.target_id != "runtime":
                raise ValueError(f"{self.command_type.value} must target runtime")
        if self.command_type in {CommandType.MOVE_TO_ZONE, CommandType.INSPECT_ZONE}:
            if self.command_type == CommandType.MOVE_TO_ZONE and not self.target_id.startswith("mower_"):
                raise ValueError("move_to_zone currently supports mower targets only")
            if self.command_type == CommandType.INSPECT_ZONE and self.target_id != "drone_1":
                raise ValueError("inspect_zone requires drone_1")
            if self.target_zone is None:
                raise ValueError(f"{self.command_type.value} requires target_zone")
        elif self.target_zone is not None:
            raise ValueError("target_zone is only valid for zone movement commands")
        return self


class IsaacControlCommandResponse(BaseModel):
    """Terminal Runtime verification plus the latest detached Isaac state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    command_id: UUID
    status: CommandStatus
    message: str = Field(min_length=1)
    observed_machine: Optional[FrozenMachineState] = None
    observed_person: Optional[FrozenPersonState] = None
    state: dict[str, object]
