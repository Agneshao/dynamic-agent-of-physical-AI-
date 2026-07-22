"""Immutable route-safety contracts for physical device movement."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoutePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)


class RoutePersonObstacle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    person_id: str = Field(min_length=1, max_length=128)
    position: RoutePoint


class RouteSafetyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    device_id: str = Field(min_length=1, max_length=128)
    device_type: str = Field(min_length=1, max_length=64)
    start: RoutePoint
    target: RoutePoint
    people: tuple[RoutePersonObstacle, ...] = ()
    minimum_clearance: float = Field(gt=0.0, le=50.0)

    @model_validator(mode="after")
    def unique_people(self) -> RouteSafetyRequest:
        ids = tuple(person.person_id for person in self.people)
        if len(ids) != len(set(ids)):
            raise ValueError("person_id values must be unique")
        return self


class RouteSafetyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    device_id: str
    safe: bool
    direct: bool
    target_adjusted: bool
    requested_target: RoutePoint
    resolved_target: RoutePoint
    waypoints: tuple[RoutePoint, ...]
    minimum_clearance: float = Field(ge=0.0)
    reason: str = Field(min_length=1)
