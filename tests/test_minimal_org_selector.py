"""Tests for deterministic minimum-capability organization selection."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from runtime_core.audit.ledger import AuditLedger
from runtime_core.organization.minimal_org_selector import (
    MinimalOrganizationPlan,
    MinimalOrganizationSelector,
    MissingRequiredRoleError,
)
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.events import EventSeverity
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.world_state import WeatherState, WorldState
from runtime_core.world.snapshot_manager import SnapshotManager
from runtime_core.world.state_kernel import WorldStateKernel


FIXED_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def make_context(tmp_path):
    kernel = WorldStateKernel(
        WorldState(
            weather=WeatherState(
                condition="thunderstorm", updated_at=FIXED_TIME
            )
        )
    )
    manager = ModeManager(
        AuditLedger(tmp_path / "audit.jsonl"),
        world_version_provider=kernel.get_world_version,
    )
    snapshot = SnapshotManager(kernel).create_snapshot()
    return snapshot, manager


def select(snapshot, registered_roles, **overrides):
    data = {
        "event_type": "weather.thunderstorm",
        "severity": EventSeverity.CRITICAL,
        "snapshot": snapshot,
        "registered_roles": registered_roles,
        "incident_id": "storm-1",
    }
    data.update(overrides)
    return MinimalOrganizationSelector().select(**data)


def test_basic_thunderstorm_selects_exactly_four_roles(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)
    registered = manager.get_current_organization().registered_roles

    plan = select(snapshot, registered)

    assert plan.target_mode == OperatingMode.EMERGENCY
    assert plan.leader_role == "incident_commander"
    assert plan.selected_roles == (
        "incident_commander",
        "safety",
        "operations",
        "communication",
    )
    assert "logistics" not in plan.selected_roles
    assert "maintenance" not in plan.selected_roles
    assert "resource" not in plan.selected_roles
    assert "cost_optimizer" not in plan.selected_roles


@pytest.mark.parametrize(
    "constraint",
    ["route_blocked", "base_unavailable", "resource_shortage"],
)
def test_explicit_constraint_adds_logistics(tmp_path, constraint: str) -> None:
    snapshot, manager = make_context(tmp_path)

    plan = select(
        snapshot,
        manager.get_current_organization().registered_roles,
        **{constraint: True},
    )

    assert plan.selected_roles[-1] == "logistics"
    assert plan.required_capabilities[-1] == "logistics"


def test_selected_roles_cover_every_required_capability(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)
    plan = select(snapshot, manager.get_current_organization().registered_roles)
    capability_roles = {
        "command": "incident_commander",
        "safety_analysis": "safety",
        "equipment_planning": "operations",
        "notification": "communication",
        "logistics": "logistics",
    }

    assert all(
        capability_roles[capability] in plan.selected_roles
        for capability in plan.required_capabilities
    )


def test_selector_does_not_modify_mode_manager_or_organization(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)
    before = manager.get_current_organization()

    plan = select(snapshot, before.registered_roles)

    assert manager.get_current_organization() == before
    assert manager.get_current_organization().mode == OperatingMode.NORMAL
    assert plan.target_mode == OperatingMode.EMERGENCY


def test_plan_is_frozen_and_json_round_trips(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)
    plan = select(snapshot, manager.get_current_organization().registered_roles)

    assert MinimalOrganizationPlan.model_validate_json(plan.model_dump_json()) == plan
    assert isinstance(plan.selected_roles, tuple)
    assert isinstance(plan.suspended_roles, tuple)
    with pytest.raises(ValidationError):
        plan.target_mode = OperatingMode.NORMAL


def test_missing_required_role_is_rejected(tmp_path) -> None:
    snapshot, manager = make_context(tmp_path)
    registered = tuple(
        role
        for role in manager.get_current_organization().registered_roles
        if role != "communication"
    )

    with pytest.raises(MissingRequiredRoleError):
        select(snapshot, registered)
