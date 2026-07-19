"""Mutable runtime state and deeply immutable snapshot schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def _normalize_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class RuntimeModel(BaseModel):
    """Base configuration for mutable runtime schemas."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FrozenRuntimeModel(BaseModel):
    """Base configuration for immutable snapshot schemas."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MachineState(RuntimeModel):
    machine_id: str = Field(min_length=1)
    machine_type: str = Field(min_length=1)
    zone: Optional[str] = None
    status: str = Field(min_length=1)
    battery_percent: float = Field(ge=0.0, le=100.0)
    last_updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("last_updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "last_updated_at")


class PersonState(RuntimeModel):
    person_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    zone: Optional[str] = None
    status: str = Field(min_length=1)
    last_updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("last_updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "last_updated_at")


class ZoneState(RuntimeModel):
    zone_id: str = Field(min_length=1)
    is_open: bool = True
    occupied_by_people: list[str] = Field(default_factory=list)
    active_tasks: list[str] = Field(default_factory=list)
    hazards: list[str] = Field(default_factory=list)


class WeatherState(RuntimeModel):
    condition: str = Field(min_length=1)
    lightning_distance_km: Optional[float] = Field(default=None, ge=0.0)
    wind_speed_mps: float = Field(default=0.0, ge=0.0)
    precipitation_level: float = Field(default=0.0, ge=0.0, le=1.0)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "updated_at")


class TaskState(RuntimeModel):
    task_id: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    zone: Optional[str] = None
    assigned_machine_id: Optional[str] = None
    status: str = Field(min_length=1)
    priority: int = Field(default=0, ge=0)
    started_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("started_at", "updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: Optional[datetime], info: object) -> Optional[datetime]:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "timestamp")
        return _normalize_utc(value, field_name)


class RouteState(RuntimeModel):
    route_id: str = Field(min_length=1)
    machine_id: Optional[str] = None
    zones: list[str] = Field(default_factory=list)
    status: str = Field(min_length=1)
    blocked: bool = False
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "updated_at")


class ResourceReservationState(RuntimeModel):
    reservation_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: Optional[datetime] = None

    @field_validator("created_at", "expires_at")
    @classmethod
    def require_utc_timestamp(cls, value: Optional[datetime], info: object) -> Optional[datetime]:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "timestamp")
        return _normalize_utc(value, field_name)


class WorldState(RuntimeModel):
    """Physical world facts exclusively owned by WorldStateKernel.

    Runtime operating mode is intentionally absent. Organization ModeManager
    is its only authoritative source.
    """

    world_version: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=utc_now)
    zones: dict[str, ZoneState] = Field(default_factory=dict)
    people: dict[str, PersonState] = Field(default_factory=dict)
    machines: dict[str, MachineState] = Field(default_factory=dict)
    tasks: dict[str, TaskState] = Field(default_factory=dict)
    routes: dict[str, RouteState] = Field(default_factory=dict)
    weather: WeatherState = Field(default_factory=lambda: WeatherState(condition="clear"))
    resource_reservations: dict[str, ResourceReservationState] = Field(default_factory=dict)
    new_tasks_frozen: bool = False

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "timestamp")

    @model_validator(mode="after")
    def validate_mapping_keys(self) -> WorldState:
        mappings = (
            ("zones", self.zones, "zone_id"),
            ("people", self.people, "person_id"),
            ("machines", self.machines, "machine_id"),
            ("tasks", self.tasks, "task_id"),
            ("routes", self.routes, "route_id"),
            ("resource_reservations", self.resource_reservations, "reservation_id"),
        )
        for name, values, id_field in mappings:
            for key, item in values.items():
                if key != getattr(item, id_field):
                    raise ValueError(f"{name} key '{key}' does not match {id_field}")
        return self


class FrozenMachineState(FrozenRuntimeModel):
    machine_id: str
    machine_type: str
    zone: Optional[str]
    status: str
    battery_percent: float
    last_updated_at: datetime

    @field_validator("last_updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "last_updated_at")


class FrozenPersonState(FrozenRuntimeModel):
    person_id: str
    role: str
    zone: Optional[str]
    status: str
    last_updated_at: datetime

    @field_validator("last_updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "last_updated_at")


class FrozenZoneState(FrozenRuntimeModel):
    zone_id: str
    is_open: bool
    occupied_by_people: tuple[str, ...]
    active_tasks: tuple[str, ...]
    hazards: tuple[str, ...]


class FrozenWeatherState(FrozenRuntimeModel):
    condition: str
    lightning_distance_km: Optional[float]
    wind_speed_mps: float
    precipitation_level: float
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "updated_at")


class FrozenTaskState(FrozenRuntimeModel):
    task_id: str
    task_type: str
    zone: Optional[str]
    assigned_machine_id: Optional[str]
    status: str
    priority: int
    started_at: Optional[datetime]
    updated_at: datetime

    @field_validator("started_at", "updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: Optional[datetime], info: object) -> Optional[datetime]:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "timestamp")
        return _normalize_utc(value, field_name)


class FrozenRouteState(FrozenRuntimeModel):
    route_id: str
    machine_id: Optional[str]
    zones: tuple[str, ...]
    status: str
    blocked: bool
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "updated_at")


class FrozenResourceReservationState(FrozenRuntimeModel):
    reservation_id: str
    resource_id: str
    resource_type: str
    task_id: str
    status: str
    created_at: datetime
    expires_at: Optional[datetime]

    @field_validator("created_at", "expires_at")
    @classmethod
    def require_utc_timestamp(cls, value: Optional[datetime], info: object) -> Optional[datetime]:
        if value is None:
            return None
        field_name = getattr(info, "field_name", "timestamp")
        return _normalize_utc(value, field_name)


class FrozenWorldState(FrozenRuntimeModel):
    """Immutable physical facts; operating mode is read from ModeManager."""

    world_version: int
    timestamp: datetime
    zones: tuple[FrozenZoneState, ...]
    people: tuple[FrozenPersonState, ...]
    machines: tuple[FrozenMachineState, ...]
    tasks: tuple[FrozenTaskState, ...]
    routes: tuple[FrozenRouteState, ...]
    weather: FrozenWeatherState
    resource_reservations: tuple[FrozenResourceReservationState, ...]
    new_tasks_frozen: bool

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "timestamp")

    @classmethod
    def from_world_state(cls, state: WorldState) -> FrozenWorldState:
        """Create a detached immutable representation of mutable world state."""
        return cls(
            world_version=state.world_version,
            timestamp=state.timestamp,
            zones=tuple(FrozenZoneState(**item.model_dump()) for item in state.zones.values()),
            people=tuple(FrozenPersonState(**item.model_dump()) for item in state.people.values()),
            machines=tuple(FrozenMachineState(**item.model_dump()) for item in state.machines.values()),
            tasks=tuple(FrozenTaskState(**item.model_dump()) for item in state.tasks.values()),
            routes=tuple(FrozenRouteState(**item.model_dump()) for item in state.routes.values()),
            weather=FrozenWeatherState(**state.weather.model_dump()),
            resource_reservations=tuple(
                FrozenResourceReservationState(**item.model_dump())
                for item in state.resource_reservations.values()
            ),
            new_tasks_frozen=state.new_tasks_frozen,
        )

    def get_zone(self, zone_id: str) -> Optional[FrozenZoneState]:
        return next((zone for zone in self.zones if zone.zone_id == zone_id), None)

    def get_machine(self, machine_id: str) -> Optional[FrozenMachineState]:
        return next((machine for machine in self.machines if machine.machine_id == machine_id), None)

    def get_person(self, person_id: str) -> Optional[FrozenPersonState]:
        return next((person for person in self.people if person.person_id == person_id), None)


class WorldSnapshot(FrozenRuntimeModel):
    """Immutable world snapshot bound to one committed world version."""

    snapshot_id: UUID
    world_version: int = Field(ge=0)
    created_at: datetime
    state: FrozenWorldState

    @field_validator("created_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "created_at")

    @model_validator(mode="after")
    def versions_must_match(self) -> WorldSnapshot:
        if self.world_version != self.state.world_version:
            raise ValueError("snapshot world_version must match state world_version")
        return self
