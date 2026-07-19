"""Tests for external state behavior of MockSimulatorAdapter."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from runtime_core.adapters.mock_adapter import MockSimulatorAdapter
from runtime_core.schemas.commands import Command, CommandStatus, CommandType
from runtime_core.schemas.proposals import ProposalParameter


FIXED_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def make_command(
    command_type: CommandType,
    target_id: str,
    *,
    incident_id: str = "storm-1",
    parameters=(),
) -> Command:
    return Command(
        command_id=uuid4(),
        incident_id=incident_id,
        idempotency_key=f"{incident_id}:{command_type.value}:{target_id}",
        command_type=command_type,
        target_id=target_id,
        parameters=parameters,
        source="test",
        world_version=0,
        org_version=1,
        created_at=FIXED_TIME,
    )


def execute_and_verify(adapter: MockSimulatorAdapter, command: Command):
    receipt = adapter.execute_command(command)
    verification = adapter.verify_command(command, receipt)
    return receipt, verification


def test_adapter_supports_machine_and_runtime_commands() -> None:
    adapter = MockSimulatorAdapter(clock=lambda: FIXED_TIME)

    execute_and_verify(
        adapter, make_command(CommandType.PAUSE_MACHINE, "mower_1")
    )
    execute_and_verify(
        adapter, make_command(CommandType.HOLD_POSITION, "mower_2")
    )
    execute_and_verify(
        adapter,
        make_command(CommandType.RETURN_TO_BASE, "mower_2", incident_id="storm-2"),
    )
    execute_and_verify(
        adapter, make_command(CommandType.RECALL_DRONE, "drone_1")
    )
    execute_and_verify(
        adapter, make_command(CommandType.FREEZE_NEW_TASKS, "runtime")
    )
    execute_and_verify(
        adapter,
        make_command(
            CommandType.NOTIFY_OPERATOR,
            "operator",
            parameters=(ProposalParameter(name="message", value="storm warning"),),
        ),
    )

    state = adapter.get_state()
    assert state["machines"]["mower_1"]["status"] == "paused"
    assert state["machines"]["mower_2"]["zone"] == "maintenance_base"
    assert state["machines"]["drone_1"]["zone"] == "maintenance_base"
    assert state["locations"]["zone_B"]["occupied_by_people"] == ("player_1",)
    assert state["locations"]["maintenance_base"]["available"] is True
    assert state["new_tasks_frozen"] is True
    assert state["notifications"] == ("storm warning",)


def test_get_state_does_not_expose_adapter_containers() -> None:
    adapter = MockSimulatorAdapter(clock=lambda: FIXED_TIME)
    state = adapter.get_state()
    state["machines"]["mower_1"]["status"] = "tampered"

    assert adapter.get_state()["machines"]["mower_1"]["status"] == "mowing"


def test_configured_failure_does_not_change_external_state() -> None:
    adapter = MockSimulatorAdapter(
        fail_command_types=(CommandType.PAUSE_MACHINE,),
        clock=lambda: FIXED_TIME,
    )
    command = make_command(CommandType.PAUSE_MACHINE, "mower_1")

    receipt, verification = execute_and_verify(adapter, command)

    assert receipt.status == CommandStatus.FAILED
    assert verification.status == CommandStatus.FAILED
    assert adapter.get_state()["machines"]["mower_1"]["status"] == "mowing"
    assert len(adapter.collect_evidence(command)) == 2


def test_no_response_can_leave_external_effect_uncertain() -> None:
    adapter = MockSimulatorAdapter(
        no_response_command_types=(CommandType.PAUSE_MACHINE,),
        clock=lambda: FIXED_TIME,
    )
    command = make_command(CommandType.PAUSE_MACHINE, "mower_1")

    receipt, verification = execute_and_verify(adapter, command)

    assert receipt.status == CommandStatus.UNKNOWN
    assert verification.status == CommandStatus.UNKNOWN
    assert adapter.get_state()["machines"]["mower_1"]["status"] == "paused"
