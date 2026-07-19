"""Tests for approved Proposal action-by-action execution."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from runtime_core.adapters.mock_adapter import MockSimulatorAdapter
from runtime_core.audit.ledger import AuditLedger
from runtime_core.coordination.proposal_board import ProposalBoard
from runtime_core.demo.stub_planners import EmergencyStubPlanner
from runtime_core.execution.proposal_execution import (
    ApprovalMismatchError,
    ProposalNotApprovedError,
    ProposalNotExecutableError,
    execute_approved_proposal,
)
from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.approval import approve_proposal
from runtime_core.schemas.commands import CommandStatus, CommandType
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.proposals import Proposal, ProposalAction, ProposalParameter
from runtime_core.schemas.world_state import MachineState, WorldState
from runtime_core.world.snapshot_manager import SnapshotManager
from runtime_core.world.state_kernel import WorldStateKernel


NOW = datetime.now(timezone.utc)


def make_runtime(tmp_path, *, adapter=None):
    kernel = WorldStateKernel(
        WorldState(
            machines={
                "mower_1": MachineState(
                    machine_id="mower_1",
                    machine_type="mower",
                    zone="zone_B",
                    status="paused",
                    battery_percent=82.0,
                    last_updated_at=NOW,
                ),
                "mower_2": MachineState(
                    machine_id="mower_2",
                    machine_type="mower",
                    zone="zone_D",
                    status="paused",
                    battery_percent=76.0,
                    last_updated_at=NOW,
                ),
                "drone_1": MachineState(
                    machine_id="drone_1",
                    machine_type="drone",
                    zone="maintenance_base",
                    status="idle",
                    battery_percent=68.0,
                    last_updated_at=NOW,
                ),
            },
            new_tasks_frozen=True,
        )
    )
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    manager = ModeManager(ledger, world_version_provider=kernel.get_world_version)
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="storm",
        triggered_by="weather_monitor",
    )
    board = ProposalBoard(kernel, manager, ledger)
    mock = adapter or MockSimulatorAdapter()
    simple = SimpleExecutor(kernel, manager, mock)
    proposal = EmergencyStubPlanner().create_proposal(
        SnapshotManager(kernel).create_snapshot(),
        manager.get_current_organization(),
    )
    assert board.submit(proposal).accepted
    approval = approve_proposal(
        proposal.proposal_id,
        approved=True,
        approved_by="operator",
        reason="approved",
    )
    return kernel, manager, board, mock, simple, proposal, approval


class RecordingExecutor:
    def __init__(self, delegate, *, after_first=None) -> None:
        self.delegate = delegate
        self.commands = []
        self.after_first = after_first

    def execute(self, command):
        self.commands.append(command)
        result = self.delegate.execute(command)
        if len(self.commands) == 1 and self.after_first is not None:
            self.after_first()
        return result


def execute(runtime, *, executor=None, incident_id="storm-1"):
    kernel, manager, board, _, simple, proposal, approval = runtime
    return execute_approved_proposal(
        proposal=proposal,
        approval=approval,
        proposal_board=board,
        mode_manager=manager,
        world_kernel=kernel,
        executor=executor or simple,
        incident_id=incident_id,
    )


def test_approval_decision_is_frozen_and_required(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
    kernel, manager, board, adapter, simple, proposal, _ = runtime
    denied = approve_proposal(
        proposal.proposal_id,
        approved=False,
        approved_by="operator",
        reason="not authorized",
    )

    with pytest.raises(ProposalNotApprovedError):
        execute_approved_proposal(
            proposal=proposal,
            approval=denied,
            proposal_board=board,
            mode_manager=manager,
            world_kernel=kernel,
            executor=simple,
            incident_id="storm-1",
        )
    with pytest.raises(ValidationError):
        denied.approved = True
    assert adapter.get_state()["machines"]["mower_2"]["zone"] == "zone_D"


def test_approval_must_reference_the_same_proposal(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
    kernel, manager, board, _, simple, proposal, _ = runtime
    other_proposal = EmergencyStubPlanner().create_proposal(
        SnapshotManager(kernel).create_snapshot(),
        manager.get_current_organization(),
    )
    wrong = approve_proposal(
        other_proposal.proposal_id,
        approved=True,
        approved_by="operator",
        reason="wrong proposal",
    )

    with pytest.raises(ApprovalMismatchError):
        execute_approved_proposal(
            proposal=proposal,
            approval=wrong,
            proposal_board=board,
            mode_manager=manager,
            world_kernel=kernel,
            executor=simple,
            incident_id="storm-1",
        )


def test_nonaccepted_validate_for_use_result_prevents_execution(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
    kernel, _, _, adapter, _, _, _ = runtime
    kernel.update_new_tasks_frozen(False)

    with pytest.raises(ProposalNotExecutableError):
        execute(runtime)

    assert adapter.get_execution_count("storm-1:hold_position:mower_1") == 0


def test_each_action_uses_latest_world_version(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
    recorder = RecordingExecutor(runtime[4])
    initial_version = runtime[0].get_world_version()

    results = execute(runtime, executor=recorder)

    assert len(results) == 3
    assert all(result.status == CommandStatus.VERIFIED for result in results)
    assert recorder.commands[0].world_version == initial_version
    assert recorder.commands[1].world_version > recorder.commands[0].world_version
    assert recorder.commands[2].world_version > recorder.commands[1].world_version
    assert runtime[0].get_current_state().machines["mower_2"].zone == "maintenance_base"


def test_org_version_change_stops_remaining_actions(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
    manager = runtime[1]

    def transition_after_first() -> None:
        manager.transition(
            OperatingMode.RECOVERY,
            reason="incident phase changed",
            triggered_by="incident_commander",
        )

    recorder = RecordingExecutor(runtime[4], after_first=transition_after_first)

    results = execute(runtime, executor=recorder)

    assert len(results) == 1
    assert len(recorder.commands) == 1
    assert manager.get_current_organization().mode == OperatingMode.RECOVERY
    assert runtime[3].get_state()["machines"]["mower_2"]["zone"] == "zone_D"


@pytest.mark.parametrize(
    "adapter",
    [
        MockSimulatorAdapter(fail_command_types=(CommandType.HOLD_POSITION,)),
        MockSimulatorAdapter(no_response_command_types=(CommandType.HOLD_POSITION,)),
    ],
)
def test_failed_or_unknown_command_stops_remaining_actions(tmp_path, adapter) -> None:
    runtime = make_runtime(tmp_path, adapter=adapter)

    results = execute(runtime)

    assert len(results) == 1
    assert results[0].status in (CommandStatus.FAILED, CommandStatus.UNKNOWN)
    assert adapter.get_execution_count("storm-1:return_to_base:mower_2") == 0


def test_same_incident_reexecution_uses_simple_executor_idempotency(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
    kernel, manager, board, adapter, simple, _, _ = runtime
    snapshot = SnapshotManager(kernel).create_snapshot()
    proposal = Proposal(
        epoch_id=snapshot.snapshot_id,
        agent_id="incident_stub",
        agent_role="incident_commander",
        world_version=snapshot.world_version,
        org_version=manager.get_current_organization().org_version,
        action_type="notify_operator",
        actions=(
            ProposalAction(
                action_type="notify_operator",
                target_type="operator",
                target_id="operator_1",
                parameters=(ProposalParameter(name="message", value="test"),),
            ),
        ),
        confidence=1.0,
        rationale_summary="idempotency test",
        created_at=snapshot.created_at,
        valid_until=snapshot.created_at.replace(year=snapshot.created_at.year + 1),
    )
    board.submit(proposal)
    approval = approve_proposal(
        proposal.proposal_id,
        approved=True,
        approved_by="operator",
        reason="approved",
    )
    kwargs = {
        "proposal": proposal,
        "approval": approval,
        "proposal_board": board,
        "mode_manager": manager,
        "world_kernel": kernel,
        "executor": simple,
        "incident_id": "storm-repeat",
    }

    first = execute_approved_proposal(**kwargs)
    second = execute_approved_proposal(**kwargs)

    assert second == first
    assert adapter.get_state()["notifications"] == ("test",)
    assert adapter.get_execution_count(
        "storm-repeat:notify_operator:operator_1"
    ) == 1
