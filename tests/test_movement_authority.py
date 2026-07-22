"""Tests for deterministic multi-agent mower movement authority."""

from runtime_core.policies.movement_authority import MovementAuthorityPolicy
from runtime_core.schemas.movement_authority import (
    MovementAuthorityDecision,
    MovementAuthorityRequest,
    MovementDecisionOutcome,
    MovementRecommendation,
)


def request(*, hazard_active: bool = True, route_affected: bool = True) -> MovementAuthorityRequest:
    return MovementAuthorityRequest(
        device_id="mower_1",
        origin_zone="FAIRWAY B",
        target_zone="FAIRWAY C",
        hazard_id="irrigation_leak_c",
        hazard_active=hazard_active,
        route_affected=route_affected,
    )


def test_active_route_hazard_activates_safety_veto_and_maintenance_hold() -> None:
    decision = MovementAuthorityPolicy().decide(request())

    assert decision.outcome == MovementDecisionOutcome.HOLD_FOR_INSPECTION
    assert decision.final_authority == "supervisor"
    assert decision.positions[0].recommendation == MovementRecommendation.CONTINUE_MOWING
    assert decision.positions[1].recommendation == MovementRecommendation.STOP_MACHINE
    assert decision.positions[1].has_veto is True
    assert decision.positions[2].recommendation == MovementRecommendation.INSPECT_HAZARD
    assert decision.winning_rule.startswith("SAFETY_VETO")


def test_unaffected_route_is_allowed_by_supervisor() -> None:
    decision = MovementAuthorityPolicy().decide(request(route_affected=False))

    assert decision.outcome == MovementDecisionOutcome.ALLOW
    assert decision.final_authority == "supervisor"
    assert decision.winning_rule == "NO_ACTIVE_ROUTE_HAZARD"


def test_inactive_hazard_does_not_block_route() -> None:
    decision = MovementAuthorityPolicy().decide(request(hazard_active=False))

    assert decision.outcome == MovementDecisionOutcome.ALLOW


def test_decision_is_json_safe_and_round_trips() -> None:
    decision = MovementAuthorityPolicy().decide(request())

    reloaded = MovementAuthorityDecision.model_validate_json(decision.model_dump_json())
    assert reloaded == decision
