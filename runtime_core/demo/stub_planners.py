"""Deterministic local planners used by the thunderstorm demo."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional
from uuid import uuid4

from runtime_core.ports.planner import PlanningTask
from runtime_core.schemas.organization import OperatingMode, OrganizationState
from runtime_core.schemas.proposals import Proposal, ProposalAction, ProposalParameter
from runtime_core.schemas.world_state import WorldSnapshot


class StubPlannerModeError(RuntimeError):
    """Raised when a stub planner is used under an incompatible mode."""


class NormalOperationsStubPlanner:
    """Produce one deterministic NORMAL/WATCH mowing proposal."""

    def create_proposal(
        self,
        snapshot: WorldSnapshot,
        organization: OrganizationState,
        task: Optional[PlanningTask] = None,
    ) -> Proposal:
        del task
        if organization.mode not in (OperatingMode.NORMAL, OperatingMode.WATCH):
            raise StubPlannerModeError(
                "NormalOperationsStubPlanner requires NORMAL or WATCH mode"
            )
        if "operations" not in organization.active_roles:
            raise StubPlannerModeError("operations role must be active")
        return Proposal(
            epoch_id=uuid4(),
            agent_id="normal_operations_stub",
            agent_role="operations",
            world_version=snapshot.world_version,
            org_version=organization.org_version,
            action_type="continue_mowing",
            actions=(
                ProposalAction(
                    action_type="continue_mowing",
                    target_type="machine",
                    target_id="mower_1",
                    parameters=(
                        ProposalParameter(name="zone", value="zone_B"),
                    ),
                ),
            ),
            confidence=0.8,
            rationale_summary="Resume the current mowing assignment in zone_B.",
            created_at=snapshot.created_at,
            valid_until=snapshot.created_at + timedelta(minutes=10),
        )


class EmergencyStubPlanner:
    """Produce a deterministic three-action EMERGENCY response proposal."""

    def create_proposal(
        self,
        snapshot: WorldSnapshot,
        organization: OrganizationState,
        task: Optional[PlanningTask] = None,
    ) -> Proposal:
        del task
        if organization.mode != OperatingMode.EMERGENCY:
            raise StubPlannerModeError(
                "EmergencyStubPlanner requires EMERGENCY mode"
            )
        if "incident_commander" not in organization.active_roles:
            raise StubPlannerModeError("incident_commander role must be active")
        return Proposal(
            epoch_id=uuid4(),
            agent_id="emergency_incident_stub",
            agent_role="incident_commander",
            world_version=snapshot.world_version,
            org_version=organization.org_version,
            action_type="emergency_response",
            actions=(
                ProposalAction(
                    action_type="hold_position",
                    target_type="machine",
                    target_id="mower_1",
                ),
                ProposalAction(
                    action_type="return_to_base",
                    target_type="machine",
                    target_id="mower_2",
                ),
                ProposalAction(
                    action_type="notify_operator",
                    target_type="operator",
                    target_id="operator_1",
                    parameters=(
                        ProposalParameter(
                            name="message",
                            value="Thunderstorm response is active.",
                        ),
                    ),
                ),
            ),
            confidence=0.95,
            rationale_summary="Hold exposed equipment and return assets to safety.",
            created_at=snapshot.created_at,
            valid_until=snapshot.created_at + timedelta(minutes=10),
        )
