"""Deterministic handlers for the minimal emergency organization."""

from __future__ import annotations

from datetime import timedelta
from typing import Type, TypeVar
from uuid import uuid4

from runtime_core.schemas.agent_messages import AgentMessage
from runtime_core.schemas.agent_outputs import (
    AgentContextView,
    NotificationPlan,
    OperationsPlan,
    SafetyReport,
)
from runtime_core.schemas.proposals import Proposal, ProposalAction, ProposalParameter


def safety_handler(
    message: AgentMessage,
    context: AgentContextView,
    dependencies: tuple[object, ...],
) -> SafetyReport:
    """Identify occupied zones and exposed machines from projected context."""
    del dependencies
    people = context.people or ()
    machines = context.machines or ()
    occupied_zones = tuple(
        dict.fromkeys(person.zone for person in people if person.zone is not None)
    )
    unsafe_machines = tuple(
        machine.machine_id
        for machine in machines
        if machine.zone in occupied_zones or machine.status in ("mowing", "paused")
    )
    required_holds = tuple(
        machine.machine_id for machine in machines if machine.zone in occupied_zones
    )
    return SafetyReport(
        incident_id=message.incident_id,
        world_version=context.world_version,
        org_version=context.org_version,
        occupied_zones=occupied_zones,
        unsafe_machines=unsafe_machines,
        required_holds=required_holds,
        risk_summary=(
            "Lightning is near an occupied work zone; exposed equipment must remain controlled."
        ),
        confidence=0.98,
    )


def operations_handler(
    message: AgentMessage,
    context: AgentContextView,
    dependencies: tuple[object, ...],
) -> OperationsPlan:
    """Turn a safety report into bounded equipment actions."""
    safety = _require_dependency(dependencies, SafetyReport)
    machine_ids = {machine.machine_id for machine in context.machines or ()}
    actions = []
    if "mower_1" in safety.required_holds and "mower_1" in machine_ids:
        actions.append(
            ProposalAction(
                action_type="hold_position",
                target_type="machine",
                target_id="mower_1",
            )
        )
    if "mower_2" in machine_ids:
        actions.append(
            ProposalAction(
                action_type="return_to_base",
                target_type="machine",
                target_id="mower_2",
            )
        )
    return OperationsPlan(
        incident_id=message.incident_id,
        world_version=context.world_version,
        org_version=context.org_version,
        recommended_actions=tuple(actions),
        operational_summary=(
            "Hold the occupied-zone mower and return the remote mower to base."
        ),
        confidence=0.96,
    )


def communication_handler(
    message: AgentMessage,
    context: AgentContextView,
    dependencies: tuple[object, ...],
) -> NotificationPlan:
    """Prepare the operator notification without dispatching it."""
    del dependencies
    recipient = context.operator_target or "operator_1"
    return NotificationPlan(
        incident_id=message.incident_id,
        world_version=context.world_version,
        org_version=context.org_version,
        recipients=(recipient,),
        message_category="EMERGENCY_RESPONSE",
        notification_summary=(
            "Thunderstorm response is active; equipment has entered its safe posture."
        ),
    )


def incident_commander_handler(
    message: AgentMessage,
    context: AgentContextView,
    dependencies: tuple[object, ...],
) -> Proposal:
    """Compose departmental outputs into a Proposal, never a Command."""
    safety = _require_dependency(dependencies, SafetyReport)
    operations = _require_dependency(dependencies, OperationsPlan)
    notification = _require_dependency(dependencies, NotificationPlan)
    notify_actions = tuple(
        ProposalAction(
            action_type="notify_operator",
            target_type="operator",
            target_id=recipient,
            parameters=(
                ProposalParameter(
                    name="message",
                    value="Thunderstorm response is active.",
                ),
            ),
        )
        for recipient in notification.recipients
    )
    return Proposal(
        epoch_id=uuid4(),
        agent_id="emergency_incident_commander",
        agent_role="incident_commander",
        world_version=context.world_version,
        org_version=context.org_version,
        action_type="emergency_response",
        actions=operations.recommended_actions + notify_actions,
        confidence=min(safety.confidence, operations.confidence),
        rationale_summary=(
            "Departmental evidence supports holding exposed equipment, returning safe assets, "
            "and notifying the operator."
        ),
        created_at=message.created_at,
        valid_until=message.created_at + timedelta(minutes=10),
    )


DependencyT = TypeVar("DependencyT")


def _require_dependency(
    dependencies: tuple[object, ...],
    expected_type: Type[DependencyT],
) -> DependencyT:
    for dependency in dependencies:
        if isinstance(dependency, expected_type):
            return dependency
    raise ValueError(f"missing required dependency: {expected_type.__name__}")
