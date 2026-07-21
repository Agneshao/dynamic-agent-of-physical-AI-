"""Critical-weather tests for exposed-person alert and shelter verification."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime_core.adapters.mock_adapter import MockSimulatorAdapter
from runtime_core.audit.ledger import AuditLedger
from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.policies.emergency_fast_path import EmergencyFastPath
from runtime_core.policies.human_safety_fast_path import HumanSafetyFastPath
from runtime_core.policies.person_safety_monitor import (
    DuplicatePersonSafetySignalError,
    PersonSafetyMonitor,
)
from runtime_core.schemas.commands import CommandStatus, CommandType
from runtime_core.schemas.person_safety import PersonSafetySignal, PersonSafetySignalType
from runtime_core.schemas.world_state import MachineState, PersonState, WorldState
from runtime_core.world.snapshot_manager import SnapshotManager
from runtime_core.world.state_kernel import WorldStateKernel


FIXED_TIME = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)


def make_runtime(tmp_path):
    kernel = WorldStateKernel(
        WorldState(
            people={
                "player_1": PersonState(
                    person_id="player_1",
                    role="player",
                    zone="zone_B",
                    status="active",
                    last_updated_at=FIXED_TIME,
                )
            },
            machines={
                "mower_1": MachineState(
                    machine_id="mower_1",
                    machine_type="mower",
                    zone="zone_B",
                    status="mowing",
                    battery_percent=82,
                    last_updated_at=FIXED_TIME,
                ),
                "mower_2": MachineState(
                    machine_id="mower_2",
                    machine_type="mower",
                    zone="zone_D",
                    status="mowing",
                    battery_percent=76,
                    last_updated_at=FIXED_TIME,
                ),
                "drone_1": MachineState(
                    machine_id="drone_1",
                    machine_type="drone",
                    zone="zone_C",
                    status="patrolling",
                    battery_percent=68,
                    last_updated_at=FIXED_TIME,
                ),
            },
        )
    )
    manager = ModeManager(
        AuditLedger(tmp_path / "audit.jsonl"),
        world_version_provider=kernel.get_world_version,
    )
    adapter = MockSimulatorAdapter(clock=lambda: FIXED_TIME)
    executor = SimpleExecutor(kernel, manager, adapter, clock=lambda: FIXED_TIME)
    return kernel, manager, adapter, executor


def test_exposed_person_keeps_drone_available_and_runs_human_fast_path(tmp_path) -> None:
    kernel, manager, adapter, executor = make_runtime(tmp_path)
    snapshot = SnapshotManager(kernel).create_snapshot()

    equipment_result = EmergencyFastPath(executor, kernel, manager).execute(
        snapshot, incident_id="storm-person-1"
    )
    human_result = HumanSafetyFastPath(executor, kernel, manager).execute(
        snapshot,
        incident_id="storm-person-1",
        shelter_zone="clubhouse",
    )

    assert CommandType.RECALL_DRONE not in tuple(
        command.command_type for command in equipment_result.commands
    )
    assert tuple(command.command_type for command in human_result.commands) == (
        CommandType.ALERT_PERSON,
        CommandType.TRACK_PERSON,
    )
    assert all(
        result.status == CommandStatus.VERIFIED
        for result in human_result.command_results
    )
    state = kernel.get_current_state()
    assert state.people["player_1"].status == "alerted"
    assert state.machines["drone_1"].status == "tracking_person"
    assert adapter.get_state()["people"]["player_1"]["status"] == "alerted"


def test_acknowledgement_and_arrival_are_versioned_kernel_updates(tmp_path) -> None:
    kernel, _, _, _ = make_runtime(tmp_path)
    monitor = PersonSafetyMonitor(kernel)
    initial_version = kernel.get_world_version()
    acknowledged = PersonSafetySignal(
        incident_id="storm-person-1",
        person_id="player_1",
        signal_type=PersonSafetySignalType.ALERT_ACKNOWLEDGED,
        source="player_mobile_app",
        deduplication_key=(
            "storm-person-1:ALERT_ACKNOWLEDGED:player_1"
        ),
        timestamp=FIXED_TIME,
    )
    arrival = PersonSafetySignal(
        incident_id="storm-person-1",
        person_id="player_1",
        signal_type=PersonSafetySignalType.SHELTER_ARRIVAL_VERIFIED,
        source="clubhouse_beacon",
        deduplication_key=(
            "storm-person-1:SHELTER_ARRIVAL_VERIFIED:player_1"
        ),
        shelter_zone="clubhouse",
        timestamp=FIXED_TIME,
    )

    ack_result = monitor.apply(acknowledged)
    arrival_result = monitor.apply(arrival)

    assert ack_result.current_status == "evacuating"
    assert arrival_result.current_status == "safe"
    assert arrival_result.current_zone == "clubhouse"
    assert kernel.get_world_version() == initial_version + 2
    with pytest.raises(DuplicatePersonSafetySignalError):
        monitor.apply(arrival)


def test_noncritical_human_fast_path_does_not_execute(tmp_path) -> None:
    from runtime_core.schemas.events import EventSeverity

    kernel, manager, _, executor = make_runtime(tmp_path)
    snapshot = SnapshotManager(kernel).create_snapshot()

    result = HumanSafetyFastPath(executor, kernel, manager).execute(
        snapshot,
        incident_id="watch-person-1",
        severity=EventSeverity.WARNING,
    )

    assert result.exposed_people == ("player_1",)
    assert result.commands == ()
    assert result.command_results == ()
