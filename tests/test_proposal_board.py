"""Tests for proposal admission, auditing, and immutable reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from runtime_core.audit.ledger import AuditLedger, AuditLedgerError
from runtime_core.coordination.proposal_board import ProposalBoard
from runtime_core.errors.proposal_errors import ProposalAuditError
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.audit import AuditRecordType
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.proposals import (
    Proposal,
    ProposalAction,
    ProposalRejectionCode,
    ProposalStatus,
)
from runtime_core.world.state_kernel import WorldStateKernel


def make_runtime(tmp_path):
    kernel = WorldStateKernel()
    ledger = AuditLedger(tmp_path / "audit" / "runtime.jsonl")
    manager = ModeManager(
        ledger, world_version_provider=kernel.get_world_version
    )
    board = ProposalBoard(kernel, manager, ledger)
    return kernel, manager, ledger, board


def make_proposal(
    kernel: WorldStateKernel,
    manager: ModeManager,
    **overrides,
) -> Proposal:
    created_at = datetime.now(timezone.utc)
    data = {
        "proposal_id": uuid4(),
        "epoch_id": uuid4(),
        "agent_id": "operations_agent_1",
        "agent_role": "operations",
        "world_version": kernel.get_world_version(),
        "org_version": manager.get_current_organization().org_version,
        "action_type": "continue_mowing",
        "actions": (
            ProposalAction(
                action_type="continue_mowing",
                target_type="machine",
                target_id="mower_1",
            ),
        ),
        "confidence": 0.85,
        "rationale_summary": "Continue while current constraints remain valid.",
        "created_at": created_at,
        "valid_until": created_at + timedelta(minutes=5),
    }
    data.update(overrides)
    return Proposal.model_validate(data)


def test_current_versions_and_active_role_are_accepted(tmp_path) -> None:
    kernel, manager, ledger, board = make_runtime(tmp_path)
    proposal = make_proposal(kernel, manager)

    result = board.submit(proposal)
    stored = board.get(proposal.proposal_id)

    assert result.accepted is True
    assert result.status == ProposalStatus.ACCEPTED
    assert result.rejection_code is None
    assert proposal.status == ProposalStatus.CREATED
    assert stored is not None
    assert stored.proposal.status == ProposalStatus.CREATED
    assert stored.current_status == ProposalStatus.ACCEPTED
    assert ledger.read_all()[-1].record_type == AuditRecordType.PROPOSAL_ACCEPTED


def test_stale_world_version_is_rejected(tmp_path) -> None:
    kernel, manager, _, board = make_runtime(tmp_path)
    proposal = make_proposal(kernel, manager, world_version=99)

    result = board.submit(proposal)

    assert result.rejection_code == ProposalRejectionCode.STALE_WORLD_VERSION


def test_stale_organization_version_precedes_role_check(tmp_path) -> None:
    kernel, manager, ledger, board = make_runtime(tmp_path)
    proposal = make_proposal(
        kernel,
        manager,
        agent_role="maintenance",
        org_version=1,
    )
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="lightning detected",
        triggered_by="weather_monitor",
    )

    result = board.submit(proposal)

    assert result.rejection_code == ProposalRejectionCode.STALE_ORGANIZATION_VERSION
    record = ledger.read_all()[-1]
    assert record.record_type == AuditRecordType.PROPOSAL_REJECTED
    assert record.payload["rejection_code"] == "STALE_ORGANIZATION_VERSION"


def test_expired_proposal_is_rejected(tmp_path) -> None:
    kernel, manager, _, board = make_runtime(tmp_path)
    created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=created_at,
        valid_until=created_at + timedelta(minutes=1),
    )

    result = board.submit(proposal)

    assert result.rejection_code == ProposalRejectionCode.EXPIRED_PROPOSAL


def test_inactive_role_is_rejected(tmp_path) -> None:
    kernel, manager, _, board = make_runtime(tmp_path)
    proposal = make_proposal(kernel, manager, agent_role="incident_commander")

    result = board.submit(proposal)

    assert result.rejection_code == ProposalRejectionCode.INACTIVE_AGENT_ROLE


def test_duplicate_after_acceptance_is_always_duplicate(tmp_path) -> None:
    kernel, manager, ledger, board = make_runtime(tmp_path)
    proposal = make_proposal(kernel, manager)
    board.submit(proposal)
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="lightning detected",
        triggered_by="weather_monitor",
    )

    result = board.submit(proposal)

    assert result.rejection_code == ProposalRejectionCode.DUPLICATE_PROPOSAL
    assert ledger.read_all()[-1].record_type == AuditRecordType.PROPOSAL_REJECTED


def test_duplicate_after_initial_rejection_is_always_duplicate(tmp_path) -> None:
    kernel, manager, _, board = make_runtime(tmp_path)
    proposal = make_proposal(kernel, manager, world_version=99)
    first = board.submit(proposal)
    second = board.submit(proposal)

    assert first.rejection_code == ProposalRejectionCode.STALE_WORLD_VERSION
    assert second.rejection_code == ProposalRejectionCode.DUPLICATE_PROPOSAL


def test_ledger_failure_does_not_store_or_consume_id(tmp_path, monkeypatch) -> None:
    kernel, manager, ledger, board = make_runtime(tmp_path)
    proposal = make_proposal(kernel, manager)
    original_append = ledger.append

    def fail_append(**kwargs):
        raise AuditLedgerError("disk unavailable")

    monkeypatch.setattr(ledger, "append", fail_append)
    with pytest.raises(ProposalAuditError) as exc_info:
        board.submit(proposal)

    assert exc_info.value.code == "PROPOSAL_AUDIT_APPEND_FAILED"
    assert board.get(proposal.proposal_id) is None

    monkeypatch.setattr(ledger, "append", original_append)
    retry = board.submit(proposal)
    assert retry.accepted is True


def test_public_reads_are_pure_and_do_not_expose_containers(tmp_path) -> None:
    kernel, manager, ledger, board = make_runtime(tmp_path)
    accepted = make_proposal(kernel, manager)
    rejected = make_proposal(kernel, manager, agent_role="incident_commander")
    board.submit(accepted)
    board.submit(rejected)
    count_before = len(ledger.read_all())

    stored = board.get(accepted.proposal_id)
    accepted_items = board.list_accepted()
    rejected_items = board.list_rejected()

    assert stored is not None
    assert isinstance(accepted_items, tuple)
    assert isinstance(rejected_items, tuple)
    assert accepted_items == (accepted,)
    assert len(rejected_items) == 1
    assert len(ledger.read_all()) == count_before
    with pytest.raises(ValidationError):
        stored.current_status = ProposalStatus.REJECTED


def test_lists_can_filter_by_epoch(tmp_path) -> None:
    kernel, manager, _, board = make_runtime(tmp_path)
    selected_epoch = uuid4()
    selected = make_proposal(kernel, manager, epoch_id=selected_epoch)
    other = make_proposal(kernel, manager)
    rejected = make_proposal(
        kernel,
        manager,
        epoch_id=selected_epoch,
        agent_role="incident_commander",
    )
    board.submit(selected)
    board.submit(other)
    board.submit(rejected)

    assert board.list_accepted(selected_epoch) == (selected,)
    assert board.list_rejected(selected_epoch)[0].proposal_id == rejected.proposal_id


def test_audit_payload_contains_admission_context(tmp_path) -> None:
    kernel, manager, ledger, board = make_runtime(tmp_path)
    proposal = make_proposal(kernel, manager)

    board.submit(proposal)
    payload = ledger.read_all()[-1].payload

    assert payload == {
        "proposal_id": str(proposal.proposal_id),
        "epoch_id": str(proposal.epoch_id),
        "agent_id": proposal.agent_id,
        "agent_role": proposal.agent_role,
        "proposal_world_version": proposal.world_version,
        "proposal_org_version": proposal.org_version,
        "current_world_version": kernel.get_world_version(),
        "current_org_version": manager.get_current_organization().org_version,
        "rejection_code": None,
    }


def test_unknown_id_returns_none(tmp_path) -> None:
    _, _, _, board = make_runtime(tmp_path)

    assert board.get(UUID("00000000-0000-0000-0000-000000000001")) is None
