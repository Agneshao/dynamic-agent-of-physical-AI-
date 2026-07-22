"""Emergency mode human-authorization policy tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from runtime_core.audit.ledger import AuditLedger, AuditLedgerError
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.policies.emergency_mode_authorization import (
    EmergencyModeAuthorizationAuditError,
    EmergencyModeAuthorizationPolicy,
)
from runtime_core.schemas.audit import AuditRecordType
from runtime_core.schemas.mode_authorization import EmergencyModeAuthorizationDecision
from runtime_core.schemas.organization import OperatingMode


def make_policy(tmp_path):
    ledger = AuditLedger(tmp_path / "authorization.jsonl")
    manager = ModeManager(ledger, world_version_provider=lambda: 13)
    policy = EmergencyModeAuthorizationPolicy(
        manager,
        ledger,
        world_version_provider=lambda: 13,
    )
    return policy, manager, ledger


def test_approved_human_authorization_transitions_after_audit(tmp_path) -> None:
    policy, manager, ledger = make_policy(tmp_path)
    decision = EmergencyModeAuthorizationDecision(
        incident_id="storm-1",
        approved=True,
        authorized_by="course_operator_01",
        reason="confirmed thunderstorm emergency response",
    )

    result = policy.apply(decision)

    assert result.decision == decision
    assert result.transition_result is not None
    assert manager.get_current_organization().mode == OperatingMode.EMERGENCY
    assert manager.get_current_organization().org_version == 2
    records = ledger.read_all()
    assert [record.record_type for record in records] == [
        AuditRecordType.EMERGENCY_MODE_AUTHORIZATION_APPROVED,
        AuditRecordType.ORGANIZATION_TRANSITION,
    ]


def test_rejected_authorization_does_not_call_mode_manager(tmp_path) -> None:
    policy, manager, ledger = make_policy(tmp_path)
    decision = EmergencyModeAuthorizationDecision(
        incident_id="storm-1",
        approved=False,
        authorized_by="course_operator_01",
        reason="continue monitoring before organization transition",
    )

    result = policy.apply(decision)

    assert result.transition_result is None
    assert manager.get_current_organization().mode == OperatingMode.NORMAL
    assert manager.get_current_organization().org_version == 1
    assert ledger.read_all()[0].record_type == (
        AuditRecordType.EMERGENCY_MODE_AUTHORIZATION_REJECTED
    )


def test_authorization_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        EmergencyModeAuthorizationDecision(
            incident_id="storm-1",
            approved=True,
            authorized_by="course_operator_01",
            reason="approved",
            timestamp=datetime(2026, 7, 22, 10, 0, 0),
        )


class FailingLedger(AuditLedger):
    def append(self, **kwargs):
        del kwargs
        raise AuditLedgerError("disk unavailable")


def test_authorization_audit_failure_keeps_mode_unchanged(tmp_path) -> None:
    ledger = FailingLedger(tmp_path / "failing.jsonl")
    manager = ModeManager(ledger, world_version_provider=lambda: 13)
    policy = EmergencyModeAuthorizationPolicy(
        manager,
        ledger,
        world_version_provider=lambda: 13,
    )
    decision = EmergencyModeAuthorizationDecision(
        incident_id="storm-1",
        approved=True,
        authorized_by="course_operator_01",
        reason="approved",
    )

    with pytest.raises(EmergencyModeAuthorizationAuditError):
        policy.apply(decision)

    assert manager.get_current_organization().mode == OperatingMode.NORMAL
    assert manager.get_current_organization().org_version == 1
