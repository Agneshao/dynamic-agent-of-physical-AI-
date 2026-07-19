"""Tests for deeply immutable, serializable world snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from runtime_core.schemas.world_state import (
    MachineState,
    PersonState,
    WeatherState,
    WorldSnapshot,
    WorldState,
    ZoneState,
)
from runtime_core.world.snapshot_manager import SnapshotManager, SnapshotNotFoundError
from runtime_core.world.state_kernel import WorldStateKernel


FIXED_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def make_kernel() -> WorldStateKernel:
    state = WorldState(
        timestamp=FIXED_TIME,
        zones={
            "A": ZoneState(zone_id="A", hazards=["wet_grass"]),
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
                zone="A",
                status="WORKING",
                battery_percent=75.0,
                last_updated_at=FIXED_TIME,
            )
        },
        weather=WeatherState(condition="clear", updated_at=FIXED_TIME),
    )
    return WorldStateKernel(state)


def test_create_snapshot_binds_current_world_version() -> None:
    kernel = make_kernel()
    manager = SnapshotManager(kernel)

    snapshot = manager.create_snapshot()

    assert snapshot.world_version == 0
    assert snapshot.state.world_version == 0
    assert manager.get_snapshot(snapshot.snapshot_id) == snapshot
    assert manager.get_latest_snapshot() == snapshot


def test_snapshot_and_nested_models_are_immutable() -> None:
    snapshot = SnapshotManager(make_kernel()).create_snapshot()

    with pytest.raises(ValidationError):
        snapshot.world_version = 9  # type: ignore[misc]
    with pytest.raises(ValidationError):
        snapshot.state.mode = "EMERGENCY"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        snapshot.state.zones[0].hazards += ("flood",)
    with pytest.raises(AttributeError):
        snapshot.state.zones.append(snapshot.state.zones[0])  # type: ignore[attr-defined]


def test_later_world_update_does_not_change_old_snapshot() -> None:
    kernel = make_kernel()
    manager = SnapshotManager(kernel)
    old_snapshot = manager.create_snapshot()

    kernel.update_machine(
        MachineState(
            machine_id="mower_1",
            machine_type="mower",
            zone="A",
            status="PAUSED",
            battery_percent=74.0,
            last_updated_at=FIXED_TIME + timedelta(seconds=1),
        )
    )
    new_snapshot = manager.create_snapshot()

    assert old_snapshot.world_version == 0
    assert old_snapshot.state.get_machine("mower_1").status == "WORKING"  # type: ignore[union-attr]
    assert new_snapshot.world_version == 1
    assert new_snapshot.state.get_machine("mower_1").status == "PAUSED"  # type: ignore[union-attr]


def test_multiple_snapshots_have_unique_ids() -> None:
    manager = SnapshotManager(make_kernel())

    first = manager.create_snapshot()
    second = manager.create_snapshot()

    assert first.snapshot_id != second.snapshot_id
    assert manager.list_snapshots() == (first, second)


def test_missing_snapshot_has_clear_error() -> None:
    manager = SnapshotManager(make_kernel())

    with pytest.raises(SnapshotNotFoundError):
        manager.get_snapshot(uuid4())


def test_snapshot_query_helpers() -> None:
    snapshot = SnapshotManager(make_kernel()).create_snapshot()

    assert snapshot.state.get_zone("A").zone_id == "A"  # type: ignore[union-attr]
    assert snapshot.state.get_machine("mower_1").machine_type == "mower"  # type: ignore[union-attr]
    assert snapshot.state.get_person("player_1").role == "player"  # type: ignore[union-attr]
    assert snapshot.state.get_zone("missing") is None


def test_snapshot_supports_json_mode_dump_and_json_dump() -> None:
    snapshot = SnapshotManager(make_kernel()).create_snapshot()

    json_mode = snapshot.model_dump(mode="json")
    json_text = snapshot.model_dump_json()

    assert json_mode["snapshot_id"] == str(snapshot.snapshot_id)
    assert json.loads(json_text)["world_version"] == snapshot.world_version


def test_snapshot_json_round_trip_preserves_content() -> None:
    snapshot = SnapshotManager(make_kernel()).create_snapshot()

    restored = WorldSnapshot.model_validate_json(snapshot.model_dump_json())

    assert restored == snapshot
    assert restored.state.get_zone("A") == snapshot.state.get_zone("A")

