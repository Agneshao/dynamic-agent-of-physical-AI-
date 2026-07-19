"""End-to-end tests for explicit accepted-proposal invalidation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from runtime_core.audit.ledger import AuditLedger, AuditLedgerError
from runtime_core.coordination.proposal_board import ProposalBoard
from runtime_core.errors.proposal_errors import ProposalAuditError, ProposalNotFoundError
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.audit import AuditRecordType
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.proposals import (
    Proposal,
    ProposalAction,
    ProposalRejectionCode,
    ProposalStatus,
)
from runtime_core.schemas.world_state import WeatherState
from runtime_core.world.state_kernel import WorldStateKernel


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def make_runtime(tmp_path, *, clock=None):
    kernel = WorldStateKernel()
    ledger = AuditLedger(tmp_path / "audit" / "runtime.jsonl")
    manager = ModeManager(ledger, world_version_provider=kernel.get_world_version)
    board = ProposalBoard(kernel, manager, ledger, clock=clock)
    return kernel, manager, ledger, board


def make_proposal(
    kernel: WorldStateKernel,
    manager: ModeManager,
    *,
    created_at: datetime,
    valid_until: datetime,
    proposal_id: UUID | None = None,
) -> Proposal:
    return Proposal(
        proposal_id=proposal_id or uuid4(),
        epoch_id=uuid4(),
        agent_id="operations_agent_1",
        agent_role="operations",
        world_version=kernel.get_world_version(),
        org_version=manager.get_current_organization().org_version,
        action_type="continue_mowing",
        actions=(
            ProposalAction(
                action_type="continue_mowing",
                target_type="machine",
                target_id="mower_1",
            ),
        ),
        confidence=0.9,
        rationale_summary="Continue while the accepted state remains current.",
        created_at=created_at,
        valid_until=valid_until,
    )


def transition_to_emergency(manager: ModeManager) -> None:
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="lightning threshold reached",
        triggered_by="weather_monitor",
    )


def invalidation_records(ledger: AuditLedger):
    return tuple(
        record
        for record in ledger.read_all()
        if record.record_type == AuditRecordType.PROPOSAL_INVALIDATED
    )


def test_unsubmitted_stale_organization_proposal_is_rejected(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    kernel, manager, ledger, board = make_runtime(tmp_path, clock=lambda: now)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=now,
        valid_until=now + timedelta(minutes=5),
    )
    transition_to_emergency(manager)

    result = board.submit(proposal)

    assert result.status == ProposalStatus.REJECTED
    assert result.rejection_code == ProposalRejectionCode.STALE_ORGANIZATION_VERSION
    assert ledger.read_all()[-1].record_type == AuditRecordType.PROPOSAL_REJECTED


def test_accepted_proposal_is_explicitly_invalidated_after_org_change(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    kernel, manager, ledger, board = make_runtime(tmp_path, clock=lambda: now)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=now,
        valid_until=now + timedelta(minutes=5),
    )
    board.submit(proposal)
    original_world = kernel.get_current_state()
    assert board.list_accepted() == (proposal,)
    transition_to_emergency(manager)
    organization_before_read = manager.get_current_organization()
    record_count_before_read = len(ledger.read_all())

    stored_before = board.get(proposal.proposal_id)

    assert stored_before is not None
    assert stored_before.current_status == ProposalStatus.ACCEPTED
    assert len(ledger.read_all()) == record_count_before_read

    result = board.validate_for_use(proposal.proposal_id)
    stored_after = board.get(proposal.proposal_id)

    assert result.accepted is False
    assert result.status == ProposalStatus.INVALIDATED
    assert result.rejection_code == ProposalRejectionCode.STALE_ORGANIZATION_VERSION
    assert stored_after is not None
    assert stored_after.current_status == ProposalStatus.INVALIDATED
    assert stored_after.proposal == proposal
    assert stored_after.proposal.status == ProposalStatus.CREATED
    assert stored_after.proposal.world_version == proposal.world_version
    assert stored_after.proposal.org_version == proposal.org_version
    assert board.list_accepted() == ()
    assert kernel.get_current_state() == original_world
    assert manager.get_current_organization() == organization_before_read

    records_after_first_validation = invalidation_records(ledger)
    repeated = board.validate_for_use(proposal.proposal_id)

    assert repeated == result
    assert len(records_after_first_validation) == 1
    assert invalidation_records(ledger) == records_after_first_validation
    payload = records_after_first_validation[0].payload
    assert payload["previous_status"] == "ACCEPTED"
    assert payload["new_status"] == "INVALIDATED"
    assert payload["rejection_code"] == "STALE_ORGANIZATION_VERSION"


def test_invalidate_stale_is_idempotent_for_multiple_proposals(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    kernel, manager, ledger, board = make_runtime(tmp_path, clock=lambda: now)
    proposals = tuple(
        make_proposal(
            kernel,
            manager,
            created_at=now,
            valid_until=now + timedelta(minutes=5),
        )
        for _ in range(2)
    )
    for proposal in proposals:
        board.submit(proposal)
    transition_to_emergency(manager)

    first = board.invalidate_stale()
    second = board.invalidate_stale()

    assert first == tuple(proposal.proposal_id for proposal in proposals)
    assert second == ()
    assert board.list_accepted() == ()
    assert len(invalidation_records(ledger)) == 2
    assert all(
        board.get(proposal.proposal_id).current_status == ProposalStatus.INVALIDATED
        for proposal in proposals
    )


def test_invalidation_ledger_failure_keeps_proposal_accepted(
    tmp_path, monkeypatch
) -> None:
    now = datetime.now(timezone.utc)
    kernel, manager, ledger, board = make_runtime(tmp_path, clock=lambda: now)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=now,
        valid_until=now + timedelta(minutes=5),
    )
    board.submit(proposal)
    transition_to_emergency(manager)

    def fail_append(**kwargs):
        raise AuditLedgerError("disk unavailable")

    monkeypatch.setattr(ledger, "append", fail_append)

    with pytest.raises(ProposalAuditError):
        board.validate_for_use(proposal.proposal_id)

    stored = board.get(proposal.proposal_id)
    assert stored is not None
    assert stored.current_status == ProposalStatus.ACCEPTED
    assert stored.proposal == proposal
    assert board.list_accepted() == (proposal,)


def test_world_version_change_invalidates_accepted_proposal(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    kernel, manager, ledger, board = make_runtime(tmp_path, clock=lambda: now)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=now,
        valid_until=now + timedelta(minutes=5),
    )
    board.submit(proposal)
    kernel.update_weather(
        WeatherState(
            condition="rain",
            precipitation_level=0.7,
            updated_at=now + timedelta(seconds=1),
        )
    )

    result = board.validate_for_use(proposal.proposal_id)

    assert kernel.get_world_version() == proposal.world_version + 1
    assert result.status == ProposalStatus.INVALIDATED
    assert result.rejection_code == ProposalRejectionCode.STALE_WORLD_VERSION
    assert invalidation_records(ledger)[0].world_version == kernel.get_world_version()


def test_injected_clock_expires_without_sleep(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    clock = MutableClock(now)
    kernel, manager, ledger, board = make_runtime(tmp_path, clock=clock)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=now,
        valid_until=now + timedelta(minutes=1),
    )
    assert board.submit(proposal).status == ProposalStatus.ACCEPTED
    clock.current = now + timedelta(minutes=2)

    result = board.validate_for_use(proposal.proposal_id)

    assert result.status == ProposalStatus.EXPIRED
    assert result.rejection_code == ProposalRejectionCode.EXPIRED_PROPOSAL
    assert board.get(proposal.proposal_id).current_status == ProposalStatus.EXPIRED
    assert len(invalidation_records(ledger)) == 1


def test_current_accepted_proposal_validation_is_a_pure_read(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    kernel, manager, ledger, board = make_runtime(tmp_path, clock=lambda: now)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=now,
        valid_until=now + timedelta(minutes=5),
    )
    accepted = board.submit(proposal)
    record_count = len(ledger.read_all())

    result = board.validate_for_use(proposal.proposal_id)

    assert result == accepted
    assert board.get(proposal.proposal_id).current_status == ProposalStatus.ACCEPTED
    assert len(ledger.read_all()) == record_count


def test_terminal_rejection_validation_is_idempotent(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    kernel, manager, ledger, board = make_runtime(tmp_path, clock=lambda: now)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=now,
        valid_until=now + timedelta(minutes=5),
    )
    proposal = Proposal.model_validate(
        {**proposal.model_dump(mode="python"), "world_version": 99}
    )
    rejected = board.submit(proposal)
    record_count = len(ledger.read_all())

    result = board.validate_for_use(proposal.proposal_id)

    assert result == rejected
    assert len(ledger.read_all()) == record_count


def test_validate_for_use_rejects_unknown_id(tmp_path) -> None:
    _, _, _, board = make_runtime(tmp_path)

    with pytest.raises(ProposalNotFoundError) as exc_info:
        board.validate_for_use(uuid4())

    assert exc_info.value.code == "PROPOSAL_NOT_FOUND"


def test_clock_must_return_aware_datetime(tmp_path) -> None:
    kernel, manager, _, board = make_runtime(
        tmp_path, clock=lambda: datetime.now()
    )
    now = datetime.now(timezone.utc)
    proposal = make_proposal(
        kernel,
        manager,
        created_at=now,
        valid_until=now + timedelta(minutes=5),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        board.submit(proposal)
