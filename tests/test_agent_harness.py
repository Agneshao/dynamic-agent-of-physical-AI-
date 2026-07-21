"""Tests for version-bound synchronous logical AgentHarness behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from runtime_core.agents.harness import (
    AgentForbiddenOutputError,
    AgentHarness,
    AgentMessageTypeNotAllowedError,
    AgentRecipientMismatchError,
    AgentRoleInactiveError,
    AgentSuspendedError,
    StaleAgentMessageOrganizationVersionError,
    StaleAgentMessageWorldVersionError,
    StaleAgentOrganizationVersionError,
)
from runtime_core.agents.lifecycle import AgentLifecycleStatus
from runtime_core.agents.role_profile import emergency_role_profiles
from runtime_core.audit.ledger import AuditLedger
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.agent_messages import (
    AgentMessage,
    AgentMessageType,
    AgentPayloadField,
)
from runtime_core.schemas.agent_outputs import SafetyReport
from runtime_core.schemas.commands import Command, CommandType
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.world_state import (
    MachineState,
    PersonState,
    WeatherState,
    WorldState,
    ZoneState,
)
from runtime_core.world.snapshot_manager import SnapshotManager
from runtime_core.world.state_kernel import WorldStateKernel


FIXED_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def make_context(tmp_path):
    kernel = WorldStateKernel(
        WorldState(
            zones={
                "zone_B": ZoneState(
                    zone_id="zone_B", occupied_by_people=["player_1"]
                )
            },
            people={
                "player_1": PersonState(
                    person_id="player_1",
                    role="player",
                    zone="zone_B",
                    status="active",
                    last_updated_at=FIXED_TIME,
                )
            },
            machines={
                "mower_1": MachineState(
                    machine_id="mower_1",
                    machine_type="mower",
                    zone="zone_B",
                    status="paused",
                    battery_percent=82.0,
                    last_updated_at=FIXED_TIME,
                )
            },
            weather=WeatherState(
                condition="thunderstorm", updated_at=FIXED_TIME
            ),
            new_tasks_frozen=True,
        )
    )
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    manager = ModeManager(ledger, world_version_provider=kernel.get_world_version)
    normal_organization = manager.get_current_organization()
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="storm",
        triggered_by="weather_monitor",
    )
    organization = manager.get_current_organization()
    snapshot = SnapshotManager(kernel).create_snapshot()
    return snapshot, normal_organization, organization


def profile_for(role: str):
    return next(item for item in emergency_role_profiles() if item.role == role)


def make_message(snapshot, organization, **overrides) -> AgentMessage:
    data = {
        "correlation_id": uuid4(),
        "incident_id": "storm-1",
        "message_type": AgentMessageType.TASK_ASSIGNMENT,
        "sender_role": "incident_commander",
        "recipient_role": "safety",
        "world_version": snapshot.world_version,
        "org_version": organization.org_version,
        "objective": "assess thunderstorm safety",
        "payload": (
            AgentPayloadField(name="operator_target", value="operator_1"),
        ),
        "created_at": FIXED_TIME,
    }
    data.update(overrides)
    return AgentMessage.model_validate(data)


def safety_handler(message, context, dependencies):
    assert dependencies == ()
    occupied_zones = tuple(
        zone.zone_id for zone in context.zones if zone.occupied_by_people
    )
    return SafetyReport(
        incident_id=message.incident_id,
        world_version=message.world_version,
        org_version=message.org_version,
        occupied_zones=occupied_zones,
        unsafe_machines=("mower_1",),
        required_holds=("mower_1",),
        risk_summary="zone_B is occupied during a thunderstorm",
        confidence=1.0,
    )


def make_harness(organization, **overrides) -> AgentHarness:
    data = {
        "role_profile": profile_for("safety"),
        "lifecycle_status": AgentLifecycleStatus.ACTIVE,
        "bound_org_version": organization.org_version,
        "agent_id": "safety-agent",
        "handler": safety_handler,
    }
    data.update(overrides)
    return AgentHarness(**data)


def test_active_harness_processes_structured_message(tmp_path) -> None:
    snapshot, _, organization = make_context(tmp_path)
    harness = make_harness(organization)
    message = make_message(snapshot, organization)

    result = harness.handle(
        message=message,
        snapshot=snapshot,
        organization=organization,
    )

    assert isinstance(result, SafetyReport)
    assert result.occupied_zones == ("zone_B",)
    assert result.world_version == snapshot.world_version
    assert result.org_version == organization.org_version


def test_suspended_harness_rejects_before_handler(tmp_path) -> None:
    snapshot, _, organization = make_context(tmp_path)
    harness = make_harness(
        organization, lifecycle_status=AgentLifecycleStatus.SUSPENDED
    )

    with pytest.raises(AgentSuspendedError) as exc_info:
        harness.handle(
            message=make_message(snapshot, organization),
            snapshot=snapshot,
            organization=organization,
        )

    assert exc_info.value.code == "AGENT_SUSPENDED"


def test_old_org_version_harness_is_stale(tmp_path) -> None:
    snapshot, normal_organization, emergency_organization = make_context(tmp_path)
    harness = make_harness(
        emergency_organization,
        bound_org_version=normal_organization.org_version,
    )

    with pytest.raises(StaleAgentOrganizationVersionError) as exc_info:
        harness.handle(
            message=make_message(snapshot, emergency_organization),
            snapshot=snapshot,
            organization=emergency_organization,
        )

    assert exc_info.value.code == "STALE_AGENT_ORGANIZATION_VERSION"


def test_inactive_role_is_rejected(tmp_path) -> None:
    snapshot, normal_organization, _ = make_context(tmp_path)
    harness = AgentHarness(
        role_profile=profile_for("incident_commander"),
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        bound_org_version=normal_organization.org_version,
        agent_id="incident-agent",
        handler=safety_handler,
    )
    message = make_message(
        snapshot,
        normal_organization,
        recipient_role="incident_commander",
        message_type=AgentMessageType.SAFETY_REPORT,
    )

    with pytest.raises(AgentRoleInactiveError) as exc_info:
        harness.handle(
            message=message,
            snapshot=snapshot,
            organization=normal_organization,
        )

    assert exc_info.value.code == "AGENT_ROLE_INACTIVE"


def test_wrong_recipient_is_rejected(tmp_path) -> None:
    snapshot, _, organization = make_context(tmp_path)
    harness = make_harness(organization)

    with pytest.raises(AgentRecipientMismatchError):
        harness.handle(
            message=make_message(
                snapshot, organization, recipient_role="operations"
            ),
            snapshot=snapshot,
            organization=organization,
        )


def test_stale_message_versions_are_rejected(tmp_path) -> None:
    snapshot, _, organization = make_context(tmp_path)
    harness = make_harness(organization)

    with pytest.raises(StaleAgentMessageWorldVersionError):
        harness.handle(
            message=make_message(snapshot, organization, world_version=99),
            snapshot=snapshot,
            organization=organization,
        )
    with pytest.raises(StaleAgentMessageOrganizationVersionError):
        harness.handle(
            message=make_message(snapshot, organization, org_version=99),
            snapshot=snapshot,
            organization=organization,
        )


def test_disallowed_message_type_is_rejected(tmp_path) -> None:
    snapshot, _, organization = make_context(tmp_path)

    with pytest.raises(AgentMessageTypeNotAllowedError):
        make_harness(organization).handle(
            message=make_message(
                snapshot,
                organization,
                message_type=AgentMessageType.ACKNOWLEDGEMENT,
            ),
            snapshot=snapshot,
            organization=organization,
        )


def test_handler_receives_projected_context_without_mutating_inputs(tmp_path) -> None:
    snapshot, _, organization = make_context(tmp_path)
    snapshot_before = snapshot.model_dump(mode="python")
    organization_before = organization.model_dump(mode="python")
    captured = []

    def capture_handler(message, context, dependencies):
        captured.append(context)
        return safety_handler(message, context, dependencies)

    harness = make_harness(organization, handler=capture_handler)
    harness.handle(
        message=make_message(snapshot, organization),
        snapshot=snapshot,
        organization=organization,
    )

    context = captured[0]
    assert context.people is not None
    assert context.machines is not None
    assert context.tasks is None
    assert context.current_mode is None
    assert context.operator_target is None
    assert snapshot.model_dump(mode="python") == snapshot_before
    assert organization.model_dump(mode="python") == organization_before


def test_handler_cannot_return_command(tmp_path) -> None:
    snapshot, _, organization = make_context(tmp_path)

    def command_handler(message, context, dependencies):
        return Command(
            incident_id=message.incident_id,
            idempotency_key=f"{message.incident_id}:pause_machine:mower_1",
            command_type=CommandType.PAUSE_MACHINE,
            target_id="mower_1",
            source="forbidden-agent",
            world_version=message.world_version,
            org_version=message.org_version,
        )

    with pytest.raises(AgentForbiddenOutputError):
        make_harness(organization, handler=command_handler).handle(
            message=make_message(snapshot, organization),
            snapshot=snapshot,
            organization=organization,
        )


def test_agent_message_and_role_profiles_are_frozen_json_data(tmp_path) -> None:
    snapshot, _, organization = make_context(tmp_path)
    message = make_message(snapshot, organization)
    profile = profile_for("safety")

    assert AgentMessage.model_validate_json(message.model_dump_json()) == message
    assert len(emergency_role_profiles()) == 4
    with pytest.raises(ValidationError):
        message.objective = "changed"
    with pytest.raises(ValidationError):
        profile.role = "changed"
