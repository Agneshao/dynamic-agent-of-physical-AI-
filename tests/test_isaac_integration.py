"""Contract tests for the same-host Isaac JSONL bridge."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

import pytest

from runtime_core.adapters.isaac_file_protocol import (
    IsaacFileProtocol,
    IsaacFileProtocolError,
)
from runtime_core.adapters.isaac_simulator_adapter import IsaacSimulatorAdapter
from runtime_core.audit.ledger import AuditLedger
from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.commands import Command, CommandStatus, CommandType
from runtime_core.schemas.isaac import (
    IsaacBridgeResultStatus,
    IsaacBridgeState,
    IsaacCommandResult,
    IsaacEntityObservation,
)
from runtime_core.schemas.proposals import ProposalParameter
from runtime_core.schemas.world_state import MachineState, WeatherState, WorldState
from runtime_core.world.state_kernel import WorldStateKernel


FIXED_TIME = datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc)


def make_command() -> Command:
    return Command(
        incident_id="storm-isaac-1",
        idempotency_key="storm-isaac-1:pause_machine:mower_1",
        command_type=CommandType.PAUSE_MACHINE,
        target_id="mower_1",
        source="test",
        world_version=0,
        org_version=1,
        created_at=FIXED_TIME,
    )


def make_kernel() -> WorldStateKernel:
    return WorldStateKernel(
        WorldState(
            machines={
                "mower_1": MachineState(
                    machine_id="mower_1",
                    machine_type="mower",
                    zone="zone_B",
                    status="mowing",
                    battery_percent=82,
                    last_updated_at=FIXED_TIME,
                )
            },
            weather=WeatherState(condition="clear", updated_at=FIXED_TIME),
        )
    )


def respond_to_first_request(protocol: IsaacFileProtocol) -> threading.Thread:
    def respond() -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            requests = protocol.list_requests()
            if requests:
                request = requests[0]
                protocol.append_result(
                    IsaacCommandResult(
                        action_id=request.action_id,
                        command_id=request.command_id,
                        status=IsaacBridgeResultStatus.SUCCEEDED,
                        message="mower paused and observed",
                        observed_at=FIXED_TIME,
                        observation=IsaacEntityObservation(
                            isaac_entity_id="Mower_01",
                            entity_type="mower",
                            status="PAUSED",
                            zone="ZONE_B",
                            position=(30.0, 35.0, 1.2),
                            battery_percent=81,
                            observed_at=FIXED_TIME,
                        ),
                    )
                )
                return
            time.sleep(0.005)
        raise AssertionError("Runtime request was not written")

    thread = threading.Thread(target=respond, daemon=True)
    thread.start()
    return thread


def test_file_protocol_round_trip_and_invalid_line(tmp_path) -> None:
    protocol = IsaacFileProtocol(tmp_path)
    command = make_command()
    action_id = uuid5(
        NAMESPACE_URL, f"golf-runtime-isaac:{command.idempotency_key}"
    )
    result = IsaacCommandResult(
        action_id=action_id,
        command_id=command.command_id,
        status=IsaacBridgeResultStatus.REJECTED,
        message="rejected for test",
        observed_at=FIXED_TIME,
        error_code="TEST_REJECTION",
    )

    protocol.append_result(result)

    assert protocol.latest_terminal_result(action_id) == result
    protocol.paths.results.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(IsaacFileProtocolError):
        protocol.list_results()


def test_file_protocol_ignores_a_partial_last_line_until_writer_finishes(tmp_path) -> None:
    protocol = IsaacFileProtocol(tmp_path)
    command = make_command()
    action_id = uuid5(
        NAMESPACE_URL, f"golf-runtime-isaac:{command.idempotency_key}"
    )
    result = IsaacCommandResult(
        action_id=action_id,
        command_id=command.command_id,
        status=IsaacBridgeResultStatus.SUCCEEDED,
        message="complete",
        observed_at=FIXED_TIME,
    )
    complete_line = result.model_dump_json() + "\n"
    midpoint = len(complete_line) // 2
    protocol.paths.results.write_text(complete_line[:midpoint], encoding="utf-8")

    assert protocol.list_results() == ()

    with protocol.paths.results.open("a", encoding="utf-8") as handle:
        handle.write(complete_line[midpoint:])
    assert protocol.list_results() == (result,)


def test_isaac_adapter_runs_through_simple_executor_and_normalizes_ids(tmp_path) -> None:
    protocol = IsaacFileProtocol(tmp_path / "bridge")
    responder = respond_to_first_request(protocol)
    kernel = make_kernel()
    manager = ModeManager(
        AuditLedger(tmp_path / "audit.jsonl"),
        world_version_provider=kernel.get_world_version,
    )
    adapter = IsaacSimulatorAdapter(
        protocol.paths.root,
        timeout_seconds=2,
        poll_interval_seconds=0.005,
        clock=lambda: FIXED_TIME,
        protocol=protocol,
    )
    executor = SimpleExecutor(kernel, manager, adapter, clock=lambda: FIXED_TIME)
    command = make_command()

    result = executor.execute(command)
    responder.join(timeout=2)

    assert result.status == CommandStatus.VERIFIED
    assert kernel.get_current_state().machines["mower_1"].status == "paused"
    request = protocol.list_requests()[0]
    assert request.canonical_target_id == "mower_1"
    assert request.isaac_target_id == "mower_01"
    assert len(result.evidence) == 3

    replay = adapter.execute_command(command)
    assert replay.status == CommandStatus.EXECUTING
    assert len(protocol.list_requests()) == 1


def test_adapter_reuses_terminal_result_after_restart_without_duplicate_request(
    tmp_path,
) -> None:
    protocol = IsaacFileProtocol(tmp_path)
    responder = respond_to_first_request(protocol)
    command = make_command()
    first = IsaacSimulatorAdapter(
        tmp_path,
        timeout_seconds=2,
        poll_interval_seconds=0.005,
        clock=lambda: FIXED_TIME,
        protocol=protocol,
    )
    assert first.execute_command(command).status == CommandStatus.EXECUTING
    responder.join(timeout=2)

    restarted = IsaacSimulatorAdapter(
        tmp_path,
        timeout_seconds=0.1,
        poll_interval_seconds=0.005,
        clock=lambda: FIXED_TIME,
        protocol=protocol,
    )
    assert restarted.execute_command(command).status == CommandStatus.EXECUTING
    assert len(protocol.list_requests()) == 1


def test_adapter_timeout_returns_unknown_and_does_not_fake_verification(tmp_path) -> None:
    adapter = IsaacSimulatorAdapter(
        tmp_path,
        timeout_seconds=0.02,
        poll_interval_seconds=0.005,
        clock=lambda: FIXED_TIME,
    )
    command = make_command()

    receipt = adapter.execute_command(command)
    verification = adapter.verify_command(command, receipt)

    assert receipt.status == CommandStatus.UNKNOWN
    assert receipt.message == "ISAAC_BRIDGE_TIMEOUT"
    assert verification.status == CommandStatus.UNKNOWN


def test_adapter_verifies_move_to_zone_result(tmp_path) -> None:
    protocol = IsaacFileProtocol(tmp_path)
    incident_id = "daily-zone-move"
    command = Command(
        incident_id=incident_id,
        idempotency_key=f"{incident_id}:move_to_zone:mower_2",
        command_type=CommandType.MOVE_TO_ZONE,
        target_id="mower_2",
        parameters=(ProposalParameter(name="target_zone", value="ZONE_A"),),
        source="test",
        world_version=0,
        org_version=1,
        created_at=FIXED_TIME,
    )

    def respond() -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            requests = protocol.list_requests()
            if requests:
                request = requests[0]
                protocol.append_result(
                    IsaacCommandResult(
                        action_id=request.action_id,
                        command_id=request.command_id,
                        status=IsaacBridgeResultStatus.SUCCEEDED,
                        message="mower reached ZONE_A",
                        observed_at=FIXED_TIME,
                        observation=IsaacEntityObservation(
                            isaac_entity_id="Mower_02",
                            entity_type="mower",
                            status="MOWING",
                            zone="ZONE_A",
                            position=(-30.0, -25.0, 1.0),
                            observed_at=FIXED_TIME,
                        ),
                    )
                )
                return
            time.sleep(0.005)
        raise AssertionError("Runtime move request was not written")

    responder = threading.Thread(target=respond, daemon=True)
    responder.start()
    adapter = IsaacSimulatorAdapter(
        tmp_path,
        timeout_seconds=2,
        poll_interval_seconds=0.005,
        clock=lambda: FIXED_TIME,
        protocol=protocol,
    )

    receipt = adapter.execute_command(command)
    verification = adapter.verify_command(command, receipt)
    responder.join(timeout=2)

    assert verification.status == CommandStatus.VERIFIED
    assert verification.observed_machine is not None
    assert verification.observed_machine.zone == "zone_A"
    assert verification.observed_machine.status == "mowing"


def test_adapter_reports_missing_fresh_and_stale_heartbeat(tmp_path) -> None:
    protocol = IsaacFileProtocol(tmp_path)
    adapter = IsaacSimulatorAdapter(
        tmp_path,
        heartbeat_timeout_seconds=3,
        clock=lambda: FIXED_TIME,
        protocol=protocol,
    )
    assert adapter.get_state()["connection_status"] == "DISCONNECTED"

    protocol.write_state(
        IsaacBridgeState(
            heartbeat_at=FIXED_TIME - timedelta(seconds=2),
            scenario_state="NORMAL_OPERATION",
            organization_mode="NORMAL",
            observed_plan_version=1,
            pipeline_gate="WAITING_FOR_WEATHER_CLEARANCE",
        )
    )
    assert adapter.get_state()["connection_status"] == "CONNECTED"

    protocol.write_state(
        IsaacBridgeState(
            heartbeat_at=FIXED_TIME - timedelta(seconds=4),
            scenario_state="NORMAL_OPERATION",
            organization_mode="NORMAL",
            observed_plan_version=1,
            pipeline_gate="WAITING_FOR_WEATHER_CLEARANCE",
        )
    )
    assert adapter.get_state()["connection_status"] == "STALE_HEARTBEAT"
