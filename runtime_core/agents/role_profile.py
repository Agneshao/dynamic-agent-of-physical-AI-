"""Immutable role configuration for the minimal emergency agent team."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_core.schemas.agent_messages import AgentMessageType
from runtime_core.schemas.organization import OperatingMode


class RoleProfile(BaseModel):
    """Declarative context and message contract for one logical role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    leader_role: Optional[str] = None
    allowed_modes: tuple[OperatingMode, ...]
    visible_context_fields: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    allowed_input_types: tuple[AgentMessageType, ...]
    allowed_output_types: tuple[AgentMessageType, ...]

    @model_validator(mode="after")
    def require_unique_configuration_values(self) -> RoleProfile:
        fields = (
            self.allowed_modes,
            self.visible_context_fields,
            self.allowed_actions,
            self.allowed_input_types,
            self.allowed_output_types,
        )
        if any(len(items) != len(set(items)) for items in fields):
            raise ValueError("RoleProfile tuple fields must not contain duplicates")
        return self


def emergency_role_profiles() -> tuple[RoleProfile, ...]:
    """Build the four immutable profiles used by the emergency team."""
    return (
        RoleProfile(
            role="incident_commander",
            display_name="Incident Commander",
            leader_role=None,
            allowed_modes=(OperatingMode.EMERGENCY,),
            visible_context_fields=(
                "machines",
                "zones",
                "weather",
                "new_tasks_frozen",
                "incident",
                "current_mode",
            ),
            allowed_actions=(
                "assign_safety_analysis",
                "assign_equipment_planning",
                "assign_notification",
                "create_emergency_proposal",
            ),
            allowed_input_types=(
                AgentMessageType.SAFETY_REPORT,
                AgentMessageType.OPERATIONS_PLAN,
                AgentMessageType.NOTIFICATION_PLAN,
            ),
            allowed_output_types=(
                AgentMessageType.TASK_ASSIGNMENT,
                AgentMessageType.FINAL_PROPOSAL,
            ),
        ),
        RoleProfile(
            role="safety",
            display_name="Safety Department",
            leader_role="incident_commander",
            allowed_modes=(OperatingMode.EMERGENCY,),
            visible_context_fields=(
                "people",
                "machines",
                "zones",
                "routes",
                "weather",
                "new_tasks_frozen",
            ),
            allowed_actions=("analyze_safety",),
            allowed_input_types=(AgentMessageType.TASK_ASSIGNMENT,),
            allowed_output_types=(AgentMessageType.SAFETY_REPORT,),
        ),
        RoleProfile(
            role="operations",
            display_name="Operations Department",
            leader_role="incident_commander",
            allowed_modes=(OperatingMode.EMERGENCY,),
            visible_context_fields=(
                "machines",
                "tasks",
                "routes",
                "zones",
                "new_tasks_frozen",
            ),
            allowed_actions=("hold_position", "return_to_base"),
            allowed_input_types=(AgentMessageType.TASK_ASSIGNMENT,),
            allowed_output_types=(AgentMessageType.OPERATIONS_PLAN,),
        ),
        RoleProfile(
            role="communication",
            display_name="Communication Department",
            leader_role="incident_commander",
            allowed_modes=(OperatingMode.EMERGENCY,),
            visible_context_fields=(
                "incident",
                "people",
                "operator_target",
                "current_mode",
            ),
            allowed_actions=("notify_operator",),
            allowed_input_types=(AgentMessageType.TASK_ASSIGNMENT,),
            allowed_output_types=(AgentMessageType.NOTIFICATION_PLAN,),
        ),
    )
