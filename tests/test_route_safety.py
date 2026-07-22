"""Deterministic route safety and person-clearance tests."""

from runtime_core.policies.route_safety import RouteSafetyPolicy
from runtime_core.schemas.route_safety import (
    RoutePersonObstacle,
    RoutePoint,
    RouteSafetyRequest,
)


def request(*, start, target, person, clearance=8.0):
    return RouteSafetyRequest(
        device_id="mower_1",
        device_type="MOWER",
        start=RoutePoint(x=start[0], y=start[1]),
        target=RoutePoint(x=target[0], y=target[1]),
        people=(
            RoutePersonObstacle(
                person_id="player_1",
                position=RoutePoint(x=person[0], y=person[1]),
            ),
        ),
        minimum_clearance=clearance,
    )


def test_direct_route_is_used_when_person_is_clear() -> None:
    plan = RouteSafetyPolicy().plan(
        request(start=(10, 10), target=(80, 10), person=(40, 40))
    )

    assert plan.safe is True
    assert plan.direct is True
    assert plan.waypoints == (RoutePoint(x=80, y=10),)
    assert plan.minimum_clearance >= 8


def test_detour_is_inserted_when_direct_route_crosses_person() -> None:
    plan = RouteSafetyPolicy().plan(
        request(start=(10, 50), target=(90, 50), person=(50, 50))
    )

    assert plan.safe is True
    assert plan.direct is False
    assert len(plan.waypoints) == 2
    assert plan.minimum_clearance >= 8
    assert plan.reason == "DETOUR_REQUIRED_FOR_PERSON_CLEARANCE"


def test_target_is_shifted_away_from_person() -> None:
    plan = RouteSafetyPolicy().plan(
        request(start=(10, 10), target=(50, 50), person=(50, 50))
    )

    assert plan.safe is True
    assert plan.target_adjusted is True
    assert plan.resolved_target != plan.requested_target
    assert plan.minimum_clearance >= 8


def test_no_people_uses_direct_route() -> None:
    plan = RouteSafetyPolicy().plan(
        RouteSafetyRequest(
            device_id="drone_1",
            device_type="DRONE",
            start=RoutePoint(x=10, y=10),
            target=RoutePoint(x=90, y=90),
            people=(),
            minimum_clearance=10,
        )
    )

    assert plan.safe is True
    assert plan.direct is True
    assert plan.minimum_clearance == 100


def test_mower_can_leave_nearby_player_via_safe_detour_after_clearance() -> None:
    plan = RouteSafetyPolicy().plan(
        request(start=(28, 57), target=(60, 34), person=(35, 52))
    )

    assert plan.safe is True
    assert plan.direct is False
    assert len(plan.waypoints) == 2
    assert plan.minimum_clearance >= 8
