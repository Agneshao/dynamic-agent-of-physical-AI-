"""Tests for deterministic incident-scoped emergency commands."""

from __future__ import annotations

from datetime import datetime, timezone

from runtime_core.adapters.mock_adapter import MockSimulatorAdapter
from runtime_core.audit.ledger import AuditLedger
from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.policies.emergency_fast_path import EmergencyFastPath
from runtime_core.schemas.commands import CommandStatus, CommandType
from runtime_core.schemas.events import EventSeverity
from runtime_core.schemas.world_state import MachineState, WorldState
from runtime_core.world.snapshot_manager import SnapshotManager
from runtime_core.world.state_kernel import WorldStateKernel


FIXED_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def make_fast_path(tmp_path):
    state = WorldState(
        machines={
            "mower_1": MachineState(
                machine_id="mower_1",
                machine_type="mower",
                zone="zone_B",
                status="mowing",
                battery_percent=82.0,
                last_updated_at=FIXED_TIME,
            ),
            "mower_2": MachineState(
                machine_id="mower_2",
                machine_type="mower",
                zone="zone_D",
                status="mowing",
                battery_percent=76.0,
                last_updated_at=FIXED_TIME,
            ),
            "drone_1": MachineState(
                machine_id="drone_1",
                machine_type="drone",
                zone="zone_C",
                status="patrolling",
                battery_percent=68.0,
                last_updated_at=FIXED_TIME,
            ),
        }
    )
    kernel = WorldStateKernel(state)
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    manager = ModeManager(ledger, world_version_provider=kernel.get_world_version)
    adapter = MockSimulatorAdapter(clock=lambda: FIXED_TIME)
    executor = SimpleExecutor(kernel, manager, adapter, clock=lambda: FIXED_TIME)
    policy = EmergencyFastPath(executor, kernel, manager)
    return kernel, manager, adapter, policy


def test_critical_fast_path_reaches_expected_safe_state(tmp_path) -> None:
    kernel, _, adapter, policy = make_fast_path(tmp_path)
    initial_version = kernel.get_world_version()
    snapshot = SnapshotManager(kernel).create_snapshot()

    result = policy.execute(snapshot, incident_id="storm-1")
    final = kernel.get_current_state()

    assert tuple(command.command_type for command in result.commands) == (
        CommandType.PAUSE_MACHINE,
        CommandType.PAUSE_MACHINE,
        CommandType.FREEZE_NEW_TASKS,
        CommandType.RECALL_DRONE,
    )
    assert all(item.status == CommandStatus.VERIFIED for item in result.command_results)
    assert final.machines["mower_1"].status == "paused"
    assert final.machines["mower_1"].zone == "zone_B"
    assert final.machines["mower_2"].status == "paused"
    assert final.machines["mower_2"].zone == "zone_D"
    assert final.machines["drone_1"].status == "idle"
    assert final.machines["drone_1"].zone == "maintenance_base"
    assert final.new_tasks_frozen is True
    assert kernel.get_world_version() > initial_version
    assert adapter.get_state()["new_tasks_frozen"] is True


def test_same_incident_is_idempotent_and_new_incident_can_execute(tmp_path) -> None:
    kernel, _, adapter, policy = make_fast_path(tmp_path)
    snapshot = SnapshotManager(kernel).create_snapshot()
    first = policy.execute(snapshot, incident_id="storm-1")
    version_after_first = kernel.get_world_version()

    repeated = policy.execute(snapshot, incident_id="storm-1")
    new_incident = policy.execute(snapshot, incident_id="storm-2")

    assert repeated.command_results == first.command_results
    assert kernel.get_world_version() == version_after_first
    for command in first.commands:
        assert adapter.get_execution_count(command.idempotency_key) == 1
    for command in new_incident.commands:
        assert adapter.get_execution_count(command.idempotency_key) == 1


def test_noncritical_weather_does_not_execute_commands(tmp_path) -> None:
    kernel, _, adapter, policy = make_fast_path(tmp_path)
    snapshot = SnapshotManager(kernel).create_snapshot()

    result = policy.execute(
        snapshot,
        incident_id="watch-1",
        severity=EventSeverity.WARNING,
    )

    assert result.commands == ()
    assert result.command_results == ()
    assert kernel.get_world_version() == snapshot.world_version
    assert adapter.get_state()["machines"]["mower_1"]["status"] == "mowing"
