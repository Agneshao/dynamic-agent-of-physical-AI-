"""ROS2 topic-to-Event bridge with full Kernel validation and deduplication."""

from __future__ import annotations

from runtime_core.schemas.events import Event, EventSeverity
from runtime_core.schemas.ros2 import Ros2MessageEnvelope, Ros2SensorIngestResult
from runtime_core.schemas.world_state import (
    MachineState,
    PersonState,
    WeatherState,
    ZoneState,
)
from runtime_core.world.state_kernel import WorldStateKernel


class UnsupportedRos2TopicError(RuntimeError):
    """Raised when no deterministic Event mapping exists for a topic."""


class Ros2TopicIdentityError(RuntimeError):
    """Raised when a topic target disagrees with the payload identity."""


class Ros2SensorBridge:
    """Convert subscribed ROS2 messages into authoritative Kernel events."""

    def __init__(self, world_state_kernel: WorldStateKernel) -> None:
        self._world_state_kernel = world_state_kernel

    def ingest(self, envelope: Ros2MessageEnvelope) -> Ros2SensorIngestResult:
        event_type, payload, severity = self._map(envelope)
        previous_version = self._world_state_kernel.get_world_version()
        deduplication_key = (
            f"ros2:{envelope.source_node}:{envelope.topic}:{envelope.sequence}"
        )
        event = Event(
            event_type=event_type,
            source=f"ros2:{envelope.source_node}",
            timestamp=envelope.observed_at,
            payload=payload,
            severity=severity,
            deduplication_key=deduplication_key,
        )
        committed = self._world_state_kernel.apply_event(event)
        return Ros2SensorIngestResult(
            event_id=event.event_id,
            event_type=event_type,
            topic=envelope.topic,
            deduplication_key=deduplication_key,
            previous_world_version=previous_version,
            current_world_version=committed.world_version,
            changed=committed.world_version > previous_version,
        )

    @staticmethod
    def _map(
        envelope: Ros2MessageEnvelope,
    ) -> tuple[str, dict[str, object], EventSeverity]:
        topic = envelope.topic.rstrip("/")
        if topic == "/golf/weather":
            weather = WeatherState.model_validate(envelope.payload)
            severity = (
                EventSeverity.CRITICAL
                if weather.condition.lower() == "thunderstorm"
                and weather.lightning_distance_km is not None
                and weather.lightning_distance_km <= 5.0
                else EventSeverity.INFO
            )
            return "weather.updated", weather.model_dump(mode="python"), severity
        mappings = (
            ("/golf/machines/", "/telemetry", MachineState, "machine.updated", "machine_id"),
            ("/golf/people/", "/telemetry", PersonState, "person.updated", "person_id"),
            ("/golf/zones/", "/state", ZoneState, "zone.updated", "zone_id"),
        )
        for prefix, suffix, model_type, event_type, id_field in mappings:
            if topic.startswith(prefix) and topic.endswith(suffix):
                target_id = topic[len(prefix) : -len(suffix)]
                model = model_type.model_validate(envelope.payload)
                if getattr(model, id_field) != target_id:
                    raise Ros2TopicIdentityError(
                        f"topic target {target_id} does not match {id_field}"
                    )
                return event_type, model.model_dump(mode="python"), EventSeverity.INFO
        raise UnsupportedRos2TopicError(envelope.topic)
