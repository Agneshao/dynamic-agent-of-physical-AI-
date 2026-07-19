"""Tests for deterministic, versioned world state mutation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from runtime_core.schemas.events import Event
from runtime_core.schemas.world_state import (
    MachineState,
    PersonState,
    TaskState,
    WeatherState,
    WorldState,
    ZoneState,
)
from runtime_core.world.state_kernel import (
    DuplicateEventError,
    MachineNotFoundError,
    WorldStateKernel,
)


FIXED_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def make_initial_state() -> WorldState:
    return WorldState(
        world_version=0,
        timestamp=FIXED_TIME,
        zones={
            "A": ZoneState(zone_id="A"),
            "B": ZoneState(zone_id="B", occupied_by_people=["player_1"]),
        },
        people={
            "player_1": PersonState(
                person_id="player_1",
                role="player",
                zone="B",
                status="ACTIVE",
                last_updated_at=FIXED_TIME,
            )
        },
        machines={
            "mower_1": MachineState(
                machine_id="mower_1",
                machine_type="mower",
                zone="B",
                status="WORKING",
                battery_percent=82.0,
                last_updated_at=FIXED_TIME,
            )
        },
        tasks={
            "task_1": TaskState(
                task_id="task_1",
                task_type="mowing",
                zone="B",
                assigned_machine_id="mower_1",
                status="ACTIVE",
                updated_at=FIXED_TIME,
            )
        },
        weather=WeatherState(condition="clear", updated_at=FIXED_TIME),
    )


def test_initial_world_version() -> None:
    kernel = WorldStateKernel(make_initial_state())

    assert kernel.get_world_version() == 0
    assert kernel.get_current_state().world_version == 0


def test_successful_update_increments_world_version_once() -> None:
    kernel = WorldStateKernel(make_initial_state())
    updated = MachineState(
        machine_id="mower_1",
        machine_type="mower",
        zone="B",
        status="PAUSED",
        battery_percent=81.5,
        last_updated_at=FIXED_TIME + timedelta(seconds=1),
    )

    result = kernel.update_machine(updated)

    assert result.world_version == 1
    assert kernel.get_world_version() == 1
    assert result.machines["mower_1"].status == "PAUSED"


def test_invalid_update_does_not_increment_version() -> None:
    kernel = WorldStateKernel(make_initial_state())
    unknown = MachineState(
        machine_id="missing_mower",
        machine_type="mower",
        zone="A",
        status="IDLE",
        battery_percent=100.0,
        last_updated_at=FIXED_TIME,
    )

    with pytest.raises(MachineNotFoundError):
        kernel.update_machine(unknown)

    assert kernel.get_world_version() == 0


def test_same_value_noop_update_does_not_increment_version() -> None:
    kernel = WorldStateKernel(make_initial_state())
    same_machine = kernel.get_current_state().machines["mower_1"]

    result = kernel.update_machine(same_machine)

    assert result.world_version == 0
    assert kernel.get_world_version() == 0


def test_returned_state_can_be_modified_without_mutating_kernel() -> None:
    kernel = WorldStateKernel(make_initial_state())
    returned = kernel.get_current_state()

    returned.machines["mower_1"].status = "BROKEN"
    returned.zones["B"].hazards.append("local-only-change")

    current = kernel.get_current_state()
    assert current.machines["mower_1"].status == "WORKING"
    assert current.zones["B"].hazards == []


def test_concurrent_updates_produce_unique_sequential_versions() -> None:
    kernel = WorldStateKernel(make_initial_state())

    def update(index: int) -> int:
        result = kernel.update_machine(
            MachineState(
                machine_id="mower_1",
                machine_type="mower",
                zone="B",
                status=f"CONCURRENT_{index}",
                battery_percent=80.0,
                last_updated_at=FIXED_TIME + timedelta(seconds=index + 1),
            )
        )
        return result.world_version

    with ThreadPoolExecutor(max_workers=8) as executor:
        versions = list(executor.map(update, range(20)))

    assert sorted(versions) == list(range(1, 21))
    assert kernel.get_world_version() == 20


def test_supported_event_is_applied_and_duplicate_is_rejected() -> None:
    kernel = WorldStateKernel(make_initial_state())
    event = Event(
        event_type="machine.updated",
        timestamp=FIXED_TIME,
        source="mock_sensor",
        deduplication_key="machine-update-1",
        payload={
            "machine_id": "mower_1",
            "machine_type": "mower",
            "zone": "B",
            "status": "PAUSED",
            "battery_percent": 79.0,
            "last_updated_at": FIXED_TIME,
        },
    )

    result = kernel.apply_event(event)

    assert result.world_version == 1
    assert result.machines["mower_1"].status == "PAUSED"
    with pytest.raises(DuplicateEventError):
        kernel.apply_event(event)
    assert kernel.get_world_version() == 1


def test_failed_event_does_not_consume_deduplication_key() -> None:
    kernel = WorldStateKernel(make_initial_state())
    failed_event = Event(
        event_type="machine.updated",
        timestamp=FIXED_TIME,
        source="mock_sensor",
        deduplication_key="reusable-after-failure",
        payload={
            "machine_id": "unknown",
            "machine_type": "mower",
            "zone": "A",
            "status": "PAUSED",
            "battery_percent": 50.0,
            "last_updated_at": FIXED_TIME,
        },
    )

    with pytest.raises(MachineNotFoundError):
        kernel.apply_event(failed_event)

    corrected_event = Event(
        event_type="machine.updated",
        timestamp=FIXED_TIME,
        source="mock_sensor",
        deduplication_key="reusable-after-failure",
        payload={
            "machine_id": "mower_1",
            "machine_type": "mower",
            "zone": "B",
            "status": "PAUSED",
            "battery_percent": 50.0,
            "last_updated_at": FIXED_TIME,
        },
    )
    result = kernel.apply_event(corrected_event)

    assert result.world_version == 1
    assert result.machines["mower_1"].status == "PAUSED"


def test_aware_timestamps_are_normalized_to_utc() -> None:
    china_time = datetime(2026, 7, 20, 16, 0, tzinfo=timezone(timedelta(hours=8)))

    machine = MachineState(
        machine_id="mower_2",
        machine_type="mower",
        zone="D",
        status="IDLE",
        battery_percent=100.0,
        last_updated_at=china_time,
    )

    assert machine.last_updated_at.tzinfo == timezone.utc
    assert machine.last_updated_at.hour == 8


@pytest.mark.parametrize(
    "factory",
    [
        lambda naive: Event(
            event_type="weather.updated",
            timestamp=naive,
            source="weather_sensor",
            payload={},
            deduplication_key="naive-event",
        ),
        lambda naive: MachineState(
            machine_id="mower_2",
            machine_type="mower",
            zone="D",
            status="IDLE",
            battery_percent=100.0,
            last_updated_at=naive,
        ),
        lambda naive: WorldState(timestamp=naive),
    ],
)
def test_naive_timestamps_are_rejected(factory: object) -> None:
    naive = datetime(2026, 7, 20, 8, 0)

    with pytest.raises(ValidationError):
        factory(naive)  # type: ignore[operator]

