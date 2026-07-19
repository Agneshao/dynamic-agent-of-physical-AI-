"""Tests for deterministic mode-bound demo planners."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from runtime_core.audit.ledger import AuditLedger
from runtime_core.demo.stub_planners import (
    EmergencyStubPlanner,
    NormalOperationsStubPlanner,
    StubPlannerModeError,
)
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.proposals import ProposalStatus
from runtime_core.schemas.world_state import MachineState, WorldState
from runtime_core.world.snapshot_manager import SnapshotManager
from runtime_core.world.state_kernel import WorldStateKernel


FIXED_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def make_context(tmp_path):
    kernel = WorldStateKernel(
        WorldState(
            world_version=7,
            machines={
                "mower_1": MachineState(
                    machine_id="mower_1",
                    machine_type="mower",
                    zone="zone_B",
                    status="mowing",
                    battery_percent=80.0,
                    last_updated_at=FIXED_TIME,
                )
            },
        )
    )
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    manager = ModeManager(ledger, world_version_provider=kernel.get_world_version)
    snapshot = SnapshotManager(kernel).create_snapshot()
    return snapshot, manager


def test_normal_planner_binds_input_versions_without_mutation(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)
    organization = manager.get_current_organization()
    snapshot_before = snapshot.model_dump(mode="python")
    organization_before = organization.model_dump(mode="python")

    proposal = NormalOperationsStubPlanner().create_proposal(
        snapshot, organization
    )

    assert proposal.world_version == snapshot.world_version
    assert proposal.org_version == organization.org_version
    assert proposal.agent_role == "operations"
    assert proposal.action_type == "continue_mowing"
    assert proposal.actions[0].target_id == "mower_1"
    assert proposal.actions[0].get_parameter("zone").value == "zone_B"
    assert snapshot.model_dump(mode="python") == snapshot_before
    assert organization.model_dump(mode="python") == organization_before
    with pytest.raises(ValidationError):
        proposal.status = ProposalStatus.ACCEPTED


def test_normal_planner_rejects_emergency_mode(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="storm",
        triggered_by="weather_monitor",
    )

    with pytest.raises(StubPlannerModeError):
        NormalOperationsStubPlanner().create_proposal(
            snapshot, manager.get_current_organization()
        )


def test_emergency_planner_binds_versions_and_actions(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="storm",
        triggered_by="weather_monitor",
    )
    organization = manager.get_current_organization()

    proposal = EmergencyStubPlanner().create_proposal(snapshot, organization)

    assert proposal.world_version == snapshot.world_version
    assert proposal.org_version == organization.org_version
    assert proposal.agent_role == "incident_commander"
    assert tuple(action.action_type for action in proposal.actions) == (
        "hold_position",
        "return_to_base",
        "notify_operator",
    )


def test_emergency_planner_rejects_normal_mode(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)

    with pytest.raises(StubPlannerModeError):
        EmergencyStubPlanner().create_proposal(
            snapshot, manager.get_current_organization()
        )
