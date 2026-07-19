"""Tests for authoritative and atomic operating mode transitions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from runtime_core.audit.ledger import AuditLedger, AuditLedgerError
from runtime_core.organization.mode_manager import (
    InvalidModeTransitionError,
    ModeManager,
    OrganizationTransitionAuditError,
)
from runtime_core.organization.org_transition import TransitionStatus
from runtime_core.schemas.audit import AuditRecordType
from runtime_core.schemas.organization import OperatingMode


def make_manager(tmp_path) -> tuple[ModeManager, AuditLedger]:
    ledger = AuditLedger(tmp_path / "audit" / "runtime.jsonl")
    return ModeManager(ledger, world_version_provider=lambda: 7), ledger


def test_initial_mode_and_version_are_explicit(tmp_path) -> None:
    manager, _ = make_manager(tmp_path)

    organization = manager.get_current_organization()

    assert organization.mode == OperatingMode.NORMAL
    assert organization.org_version == 1


def test_normal_to_watch_then_emergency(tmp_path) -> None:
    manager, _ = make_manager(tmp_path)

    watch = manager.transition(
        OperatingMode.WATCH,
        reason="weather risk rising",
        triggered_by="weather_monitor",
    )
    emergency = manager.transition(
        OperatingMode.EMERGENCY,
        reason="lightning threshold reached",
        triggered_by="weather_monitor",
    )

    assert watch.organization.org_version == 2
    assert watch.organization.mode == OperatingMode.WATCH
    assert emergency.organization.org_version == 3
    assert emergency.organization.mode == OperatingMode.EMERGENCY


def test_watch_can_return_to_normal(tmp_path) -> None:
    manager, _ = make_manager(tmp_path)
    manager.transition(
        OperatingMode.WATCH,
        reason="weather risk rising",
        triggered_by="weather_monitor",
    )

    result = manager.transition(
        OperatingMode.NORMAL,
        reason="weather risk cleared",
        triggered_by="weather_monitor",
    )

    assert result.organization.mode == OperatingMode.NORMAL
    assert result.organization.org_version == 3


def test_direct_normal_to_emergency(tmp_path) -> None:
    manager, _ = make_manager(tmp_path)

    result = manager.transition(
        OperatingMode.EMERGENCY,
        reason="collision emergency",
        triggered_by="safety_policy",
    )

    assert result.status == TransitionStatus.APPLIED
    assert result.organization.org_version == 2


def test_emergency_recovery_normal_sequence(tmp_path) -> None:
    manager, _ = make_manager(tmp_path)

    manager.transition(
        OperatingMode.EMERGENCY,
        reason="lightning threshold reached",
        triggered_by="weather_monitor",
    )
    recovery = manager.transition(
        OperatingMode.RECOVERY,
        reason="storm cleared",
        triggered_by="incident_commander",
    )
    normal = manager.transition(
        OperatingMode.NORMAL,
        reason="course inspection completed",
        triggered_by="incident_commander",
    )

    assert recovery.organization.mode == OperatingMode.RECOVERY
    assert normal.organization.mode == OperatingMode.NORMAL
    assert normal.organization.org_version == 4


def test_recovery_can_return_to_emergency(tmp_path) -> None:
    manager, _ = make_manager(tmp_path)
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="first storm cell",
        triggered_by="weather_monitor",
    )
    manager.transition(
        OperatingMode.RECOVERY,
        reason="first cell cleared",
        triggered_by="incident_commander",
    )

    result = manager.transition(
        OperatingMode.EMERGENCY,
        reason="second storm cell",
        triggered_by="weather_monitor",
    )

    assert result.organization.mode == OperatingMode.EMERGENCY
    assert result.organization.org_version == 4


def test_illegal_transition_does_not_modify_organization(tmp_path) -> None:
    manager, ledger = make_manager(tmp_path)
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="storm detected",
        triggered_by="weather_monitor",
    )
    before = manager.get_current_organization()

    with pytest.raises(InvalidModeTransitionError) as exc_info:
        manager.transition(
            OperatingMode.NORMAL,
            reason="unsafe direct reset",
            triggered_by="operator",
        )

    assert exc_info.value.code == "INVALID_MODE_TRANSITION"
    assert manager.get_current_organization() == before
    assert ledger.read_all()[-1].record_type == AuditRecordType.ORGANIZATION_TRANSITION_REJECTED


def test_noop_only_records_request_and_keeps_state_unchanged(tmp_path) -> None:
    manager, ledger = make_manager(tmp_path)
    before = manager.get_current_organization()

    result = manager.transition(
        OperatingMode.NORMAL,
        reason="confirm current mode",
        triggered_by="operator",
    )

    after = manager.get_current_organization()
    assert result.status == TransitionStatus.NO_OP_TRANSITION
    assert result.transition is None
    assert after == before
    assert after.org_version == before.org_version
    assert after.activated_at == before.activated_at
    assert after.transition_id == before.transition_id
    records = ledger.read_all()
    assert len(records) == 1
    assert records[0].record_type == AuditRecordType.ORGANIZATION_TRANSITION_NO_OP
    assert "transition_id" not in records[0].payload


def test_ledger_failure_prevents_state_publication(tmp_path, monkeypatch) -> None:
    manager, ledger = make_manager(tmp_path)
    before = manager.get_current_organization()

    def fail_append(**kwargs):
        raise AuditLedgerError("disk unavailable")

    monkeypatch.setattr(ledger, "append", fail_append)

    with pytest.raises(OrganizationTransitionAuditError) as exc_info:
        manager.transition(
            OperatingMode.WATCH,
            reason="weather risk rising",
            triggered_by="weather_monitor",
        )

    assert exc_info.value.code == "ORGANIZATION_AUDIT_APPEND_FAILED"
    assert manager.get_current_organization() == before


def test_concurrent_requests_do_not_duplicate_org_versions(tmp_path) -> None:
    manager, _ = make_manager(tmp_path)

    def request_emergency(index: int):
        return manager.transition(
            OperatingMode.EMERGENCY,
            reason=f"concurrent emergency request {index}",
            triggered_by="weather_monitor",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(request_emergency, range(20)))

    applied_versions = [
        result.organization.org_version
        for result in results
        if result.status == TransitionStatus.APPLIED
    ]
    assert applied_versions == [2]
    assert manager.get_current_organization().org_version == 2
