"""Contract tests for ROS2 sensor and equipment integration boundaries."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime_core.adapters.ros2_equipment_adapter import Ros2EquipmentAdapter
from runtime_core.adapters.ros2_sensor_bridge import (
    Ros2SensorBridge,
    Ros2TopicIdentityError,
)
from runtime_core.audit.ledger import AuditLedger
from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.commands import Command, CommandStatus, CommandType
from runtime_core.schemas.proposals import ProposalParameter
from runtime_core.schemas.ros2 import (
    Ros2CommandResponse,
    Ros2MessageEnvelope,
)
from runtime_core.schemas.world_state import (
    FrozenMachineState,
    MachineState,
    PersonState,
    WeatherState,
    WorldState,
)
from runtime_core.world.state_kernel import DuplicateEventError, WorldStateKernel


FIXED_TIME = datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)


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
            people={
                "player_1": PersonState(
                    person_id="player_1",
                    role="player",
                    zone="zone_B",
                    status="active",
                    last_updated_at=FIXED_TIME,
                )
            },
            weather=WeatherState(condition="clear", updated_at=FIXED_TIME),
        )
    )


def test_sensor_bridge_maps_weather_and_machine_topics() -> None:
    kernel = make_kernel()
    bridge = Ros2SensorBridge(kernel)
    weather = Ros2MessageEnvelope(
        topic="/golf/weather",
        source_node="weather_station_1",
        sequence=10,
        observed_at=FIXED_TIME,
        payload=WeatherState(
            condition="thunderstorm",
            lightning_distance_km=2.5,
            wind_speed_mps=18,
            precipitation_level=0.9,
            updated_at=FIXED_TIME,
        ).model_dump(mode="python"),
    )
    machine = Ros2MessageEnvelope(
        topic="/golf/machines/mower_1/telemetry",
        source_node="mower_1_controller",
        sequence=44,
        observed_at=FIXED_TIME,
        payload=MachineState(
            machine_id="mower_1",
            machine_type="mower",
            zone="zone_B",
            status="paused",
            battery_percent=81,
            last_updated_at=FIXED_TIME,
        ).model_dump(mode="python"),
    )

    weather_result = bridge.ingest(weather)
    machine_result = bridge.ingest(machine)

    assert weather_result.event_type == "weather.updated"
    assert weather_result.changed is True
    assert machine_result.event_type == "machine.updated"
    assert kernel.get_current_state().machines["mower_1"].status == "paused"
    with pytest.raises(DuplicateEventError):
        bridge.ingest(machine)


def test_sensor_bridge_rejects_topic_payload_identity_mismatch() -> None:
    bridge = Ros2SensorBridge(make_kernel())
    envelope = Ros2MessageEnvelope(
        topic="/golf/machines/mower_1/telemetry",
        source_node="mower_controller",
        sequence=1,
        observed_at=FIXED_TIME,
        payload=MachineState(
            machine_id="mower_2",
            machine_type="mower",
            zone="zone_D",
            status="mowing",
            battery_percent=70,
            last_updated_at=FIXED_TIME,
        ).model_dump(mode="python"),
    )

    with pytest.raises(Ros2TopicIdentityError):
        bridge.ingest(envelope)


class FakeRos2Transport:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, *, topic, payload, timeout_seconds):
        self.calls.append((topic, payload, timeout_seconds))
        return Ros2CommandResponse(
            accepted=True,
            acknowledged=True,
            message="controller acknowledged and telemetry observed",
            observed_machine=FrozenMachineState(
                machine_id="mower_1",
                machine_type="mower",
                zone="zone_B",
                status="paused",
                battery_percent=82,
                last_updated_at=FIXED_TIME,
            ),
            observed_at=FIXED_TIME,
        )


def test_ros2_equipment_adapter_runs_through_simple_executor(tmp_path) -> None:
    kernel = make_kernel()
    manager = ModeManager(
        AuditLedger(tmp_path / "audit.jsonl"),
        world_version_provider=kernel.get_world_version,
    )
    transport = FakeRos2Transport()
    adapter = Ros2EquipmentAdapter(transport)
    executor = SimpleExecutor(kernel, manager, adapter, clock=lambda: FIXED_TIME)
    command = Command(
        incident_id="storm-ros2-1",
        idempotency_key="storm-ros2-1:pause_machine:mower_1",
        command_type=CommandType.PAUSE_MACHINE,
        target_id="mower_1",
        parameters=(ProposalParameter(name="reason", value="lightning"),),
        source="emergency_fast_path",
        world_version=kernel.get_world_version(),
        org_version=manager.get_current_organization().org_version,
    )

    result = executor.execute(command)

    assert result.status == CommandStatus.VERIFIED
    assert kernel.get_current_state().machines["mower_1"].status == "paused"
    assert transport.calls[0][0] == "/golf/commands/mower_1/pause_machine"
    assert transport.calls[0][1]["idempotency_key"] == command.idempotency_key
    assert len(result.evidence) == 3
