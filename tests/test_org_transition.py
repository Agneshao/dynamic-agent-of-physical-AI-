"""Tests for organization role partitioning and transition records."""

from __future__ import annotations

from datetime import timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from runtime_core.audit.ledger import AuditLedger
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.organization import OperatingMode, OrganizationState
from runtime_core.schemas.world_state import WorldState


def test_operating_mode_has_one_authoritative_schema_source() -> None:
    assert "mode" not in WorldState.model_fields
    assert OrganizationState.model_fields["org_version"].is_required()
    assert {item.value for item in OperatingMode} == {
        "NORMAL",
        "WATCH",
        "EMERGENCY",
        "RECOVERY",
    }


def test_emergency_roles_and_transition_delta(tmp_path) -> None:
    manager = ModeManager(AuditLedger(tmp_path / "audit.jsonl"))

    result = manager.transition(
        OperatingMode.EMERGENCY,
        reason="lightning red threshold",
        triggered_by="weather_monitor",
    )
    organization = result.organization
    transition = result.transition

    assert "incident_commander" in organization.active_roles
    assert "supervisor" not in organization.active_roles
    assert "supervisor" in organization.suspended_roles
    assert "turf_optimizer" in organization.suspended_roles
    assert "cost_optimizer" in organization.suspended_roles
    assert "daily_scheduler" in organization.suspended_roles
    assert transition is not None
    assert transition.from_org_version == 1
    assert transition.to_org_version == 2
    assert "incident_commander" in transition.activated_roles
    assert "supervisor" in transition.suspended_roles
    assert transition.timestamp.tzinfo == timezone.utc


def test_roles_always_partition_registered_roles(tmp_path) -> None:
    manager = ModeManager(AuditLedger(tmp_path / "audit.jsonl"))

    for mode in (
        OperatingMode.NORMAL,
        OperatingMode.WATCH,
        OperatingMode.EMERGENCY,
        OperatingMode.RECOVERY,
    ):
        current = manager.get_current_organization()
        if current.mode != mode:
            manager.transition(
                mode,
                reason=f"move to {mode.value}",
                triggered_by="test",
            )
        organization = manager.get_current_organization()
        active = set(organization.active_roles)
        suspended = set(organization.suspended_roles)
        assert not active & suspended
        assert active | suspended == set(organization.registered_roles)


def test_invalid_role_partition_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrganizationState(
            org_version=1,
            mode=OperatingMode.NORMAL,
            registered_roles=("supervisor", "safety"),
            active_roles=("supervisor",),
            suspended_roles=("supervisor",),
            activated_at="2026-07-20T08:00:00Z",
            transition_id=uuid4(),
            reason="invalid overlap",
        )


def test_returned_organization_does_not_expose_internal_state(tmp_path) -> None:
    manager = ModeManager(AuditLedger(tmp_path / "audit.jsonl"))
    returned = manager.get_current_organization()

    returned.permission_profile["supervisor"] = ("mutated",)

    current = manager.get_current_organization()
    assert current.permission_profile["supervisor"] == ("read_world_snapshot",)
