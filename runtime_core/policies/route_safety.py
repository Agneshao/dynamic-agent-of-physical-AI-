"""Deterministic person-clearance route planning for mock physical devices."""

from __future__ import annotations

from math import hypot

from runtime_core.schemas.route_safety import (
    RoutePoint,
    RouteSafetyPlan,
    RouteSafetyRequest,
)


class RouteSafetyPolicy:
    """Plan a direct or one-waypoint detour that preserves person clearance."""

    _TARGET_MARGIN = 2.0
    _DETOUR_MARGIN = 6.0

    def plan(self, request: RouteSafetyRequest) -> RouteSafetyPlan:
        target = self._adjust_target(request)
        target_adjusted = target != request.target
        direct_clearance = self._path_clearance(
            (request.start, target),
            request,
        )
        if direct_clearance >= request.minimum_clearance:
            return RouteSafetyPlan(
                device_id=request.device_id,
                safe=True,
                direct=True,
                target_adjusted=target_adjusted,
                requested_target=request.target,
                resolved_target=target,
                waypoints=(target,),
                minimum_clearance=direct_clearance,
                reason="DIRECT_ROUTE_CLEAR",
            )

        candidates = self._detour_candidates(request.start, target, request)
        ranked = sorted(
            (
                (
                    self._path_clearance((request.start, candidate, target), request),
                    candidate,
                )
                for candidate in candidates
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if ranked and ranked[0][0] >= request.minimum_clearance:
            clearance, waypoint = ranked[0]
            return RouteSafetyPlan(
                device_id=request.device_id,
                safe=True,
                direct=False,
                target_adjusted=target_adjusted,
                requested_target=request.target,
                resolved_target=target,
                waypoints=(waypoint, target),
                minimum_clearance=clearance,
                reason="DETOUR_REQUIRED_FOR_PERSON_CLEARANCE",
            )
        return RouteSafetyPlan(
            device_id=request.device_id,
            safe=False,
            direct=False,
            target_adjusted=target_adjusted,
            requested_target=request.target,
            resolved_target=target,
            waypoints=(),
            minimum_clearance=ranked[0][0] if ranked else direct_clearance,
            reason="NO_ROUTE_MEETS_PERSON_CLEARANCE",
        )

    def _adjust_target(self, request: RouteSafetyRequest) -> RoutePoint:
        target = request.target
        required = request.minimum_clearance + self._TARGET_MARGIN
        for person in request.people:
            dx = target.x - person.position.x
            dy = target.y - person.position.y
            distance = hypot(dx, dy)
            if distance >= required:
                continue
            if distance == 0:
                dx, dy, distance = 1.0, 0.0, 1.0
            target = RoutePoint(
                x=_clamp(person.position.x + dx / distance * required),
                y=_clamp(person.position.y + dy / distance * required),
            )
        return target

    def _detour_candidates(
        self,
        start: RoutePoint,
        target: RoutePoint,
        request: RouteSafetyRequest,
    ) -> tuple[RoutePoint, ...]:
        dx = target.x - start.x
        dy = target.y - start.y
        length = hypot(dx, dy) or 1.0
        normal_x, normal_y = -dy / length, dx / length
        offset = request.minimum_clearance + self._DETOUR_MARGIN
        candidates: list[RoutePoint] = []
        diagonal = 2 ** -0.5
        directions = (
            (normal_x, normal_y),
            (-normal_x, -normal_y),
            (1.0, 0.0),
            (-1.0, 0.0),
            (0.0, 1.0),
            (0.0, -1.0),
            (diagonal, diagonal),
            (diagonal, -diagonal),
            (-diagonal, diagonal),
            (-diagonal, -diagonal),
        )
        for person in request.people:
            candidates.extend(
                RoutePoint(
                    x=_clamp(person.position.x + direction_x * offset),
                    y=_clamp(person.position.y + direction_y * offset),
                )
                for direction_x, direction_y in directions
            )
        return tuple(candidates)

    def _path_clearance(
        self,
        points: tuple[RoutePoint, ...],
        request: RouteSafetyRequest,
    ) -> float:
        if not request.people:
            return 100.0
        return min(
            _point_segment_distance(person.position, start, end)
            for start, end in zip(points, points[1:])
            for person in request.people
        )


def _point_segment_distance(point: RoutePoint, start: RoutePoint, end: RoutePoint) -> float:
    dx = end.x - start.x
    dy = end.y - start.y
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return hypot(point.x - start.x, point.y - start.y)
    ratio = ((point.x - start.x) * dx + (point.y - start.y) * dy) / denominator
    ratio = max(0.0, min(1.0, ratio))
    nearest_x = start.x + ratio * dx
    nearest_y = start.y + ratio * dy
    return hypot(point.x - nearest_x, point.y - nearest_y)


def _clamp(value: float) -> float:
    return max(2.0, min(98.0, value))
