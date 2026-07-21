"""Deterministic minimum-role selection for critical thunderstorm response."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from runtime_core.schemas.events import EventSeverity
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.world_state import WorldSnapshot


class OrganizationSelectionError(RuntimeError):
    """Base error for unsupported or unsatisfied organization selection."""


class UnsupportedOrganizationEventError(OrganizationSelectionError):
    """Raised when the minimal selector has no deterministic rule."""


class MissingRequiredRoleError(OrganizationSelectionError):
    """Raised when registered roles cannot cover required capabilities."""


class MinimalOrganizationPlan(BaseModel):
    """Frozen recommendation; ModeManager remains the organization writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1)
    target_mode: OperatingMode
    leader_role: str = Field(min_length=1)
    required_capabilities: tuple[str, ...]
    selected_roles: tuple[str, ...]
    suspended_roles: tuple[str, ...]
    reason: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_role_partition(self) -> MinimalOrganizationPlan:
        if len(self.selected_roles) != len(set(self.selected_roles)):
            raise ValueError("selected_roles must not contain duplicates")
        if len(self.suspended_roles) != len(set(self.suspended_roles)):
            raise ValueError("suspended_roles must not contain duplicates")
        if set(self.selected_roles) & set(self.suspended_roles):
            raise ValueError("selected_roles and suspended_roles must not overlap")
        if self.leader_role not in self.selected_roles:
            raise ValueError("leader_role must be selected")
        return self


class MinimalOrganizationSelector:
    """Select the smallest fixed role set that covers incident capabilities."""

    _CAPABILITY_ROLE_PAIRS: tuple[tuple[str, str], ...] = (
        ("command", "incident_commander"),
        ("safety_analysis", "safety"),
        ("equipment_planning", "operations"),
        ("notification", "communication"),
        ("logistics", "logistics"),
    )

    def select(
        self,
        *,
        event_type: str,
        severity: EventSeverity,
        snapshot: WorldSnapshot,
        registered_roles: tuple[str, ...],
        incident_id: Optional[str] = None,
        route_blocked: bool = False,
        base_unavailable: bool = False,
        resource_shortage: bool = False,
    ) -> MinimalOrganizationPlan:
        """Return a recommendation without reading or mutating ModeManager."""
        normalized_event_type = event_type.lower()
        if severity != EventSeverity.CRITICAL or "thunderstorm" not in normalized_event_type:
            raise UnsupportedOrganizationEventError(
                f"unsupported organization event: {event_type}/{severity.value}"
            )
        if len(registered_roles) != len(set(registered_roles)):
            raise OrganizationSelectionError(
                "registered_roles must not contain duplicates"
            )

        capabilities = [
            "command",
            "safety_analysis",
            "equipment_planning",
            "notification",
        ]
        if route_blocked or base_unavailable or resource_shortage:
            capabilities.append("logistics")

        capability_roles = dict(self._CAPABILITY_ROLE_PAIRS)
        selected_roles = tuple(capability_roles[item] for item in capabilities)
        missing = tuple(
            role for role in selected_roles if role not in registered_roles
        )
        if missing:
            raise MissingRequiredRoleError(
                f"registered roles cannot cover selection: {missing}"
            )
        selected_set = set(selected_roles)
        suspended_roles = tuple(
            role for role in registered_roles if role not in selected_set
        )
        logistics_reason = (
            " Logistics was added because routing, base, or resources are constrained."
            if "logistics" in capabilities
            else ""
        )
        return MinimalOrganizationPlan(
            incident_id=(
                incident_id
                or f"{normalized_event_type}:{snapshot.snapshot_id}"
            ),
            target_mode=OperatingMode.EMERGENCY,
            leader_role="incident_commander",
            required_capabilities=tuple(capabilities),
            selected_roles=selected_roles,
            suspended_roles=suspended_roles,
            reason=(
                "Critical thunderstorm requires command, safety analysis, "
                "equipment planning, and notification."
                f"{logistics_reason}"
            ),
            created_at=snapshot.created_at,
        )
