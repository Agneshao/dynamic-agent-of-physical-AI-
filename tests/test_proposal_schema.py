"""Tests for immutable and JSON-safe proposal schemas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from runtime_core.schemas.proposals import (
    Proposal,
    ProposalAction,
    ProposalParameter,
    ProposalStatus,
    ResourceAccessMode,
    ResourceClaim,
)


def make_proposal(**overrides) -> Proposal:
    created_at = datetime.now(timezone.utc)
    data = {
        "epoch_id": uuid4(),
        "agent_id": "operations_agent_1",
        "agent_role": "operations",
        "world_version": 0,
        "org_version": 1,
        "action_type": "continue_mowing",
        "actions": (
            ProposalAction(
                action_type="continue_mowing",
                target_type="machine",
                target_id="mower_1",
                parameters=(ProposalParameter(name="zone_id", value="B"),),
            ),
        ),
        "resource_claims": (
            ResourceClaim(
                resource_type="zone",
                resource_id="B",
                access_mode=ResourceAccessMode.EXCLUSIVE,
                valid_until=created_at + timedelta(minutes=10),
            ),
        ),
        "confidence": 0.9,
        "rationale_summary": "Conditions remain inside the operating envelope.",
        "created_at": created_at,
        "valid_until": created_at + timedelta(minutes=5),
    }
    data.update(overrides)
    return Proposal.model_validate(data)


def test_valid_proposal_is_frozen_and_json_serializable() -> None:
    proposal = make_proposal()

    assert proposal.status == ProposalStatus.CREATED
    assert isinstance(proposal.actions, tuple)
    assert isinstance(proposal.resource_claims, tuple)
    assert Proposal.model_validate_json(proposal.model_dump_json()) == proposal
    with pytest.raises(ValidationError):
        proposal.confidence = 0.1


@pytest.mark.parametrize("field_name", ["created_at", "valid_until"])
def test_proposal_rejects_naive_datetime(field_name: str) -> None:
    with pytest.raises(ValidationError):
        make_proposal(**{field_name: datetime.now()})


def test_resource_claim_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        ResourceClaim(
            resource_type="zone",
            resource_id="B",
            access_mode=ResourceAccessMode.SHARED,
            valid_until=datetime.now(),
        )


def test_valid_until_must_follow_created_at() -> None:
    created_at = datetime.now(timezone.utc)

    with pytest.raises(ValidationError):
        make_proposal(created_at=created_at, valid_until=created_at)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_in_unit_interval(confidence: float) -> None:
    with pytest.raises(ValidationError):
        make_proposal(confidence=confidence)


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_proposal(callback="unsafe")


def test_proposal_status_cannot_be_pretransitioned() -> None:
    with pytest.raises(ValidationError):
        make_proposal(status=ProposalStatus.ACCEPTED)


def test_action_requires_unique_parameter_names() -> None:
    with pytest.raises(ValidationError):
        ProposalAction(
            action_type="set_speed",
            target_type="machine",
            target_id="mower_1",
            parameters=(
                ProposalParameter(name="speed", value=1.0),
                ProposalParameter(name="speed", value=2.0),
            ),
        )


@pytest.mark.parametrize("value", [{"nested": "mapping"}, float("inf"), float("nan")])
def test_parameter_rejects_unstable_or_unbounded_values(value) -> None:
    with pytest.raises(ValidationError):
        ProposalParameter(name="unsafe", value=value)


def test_action_parameter_collection_is_a_tuple() -> None:
    action = ProposalAction(
        action_type="set_speed",
        target_type="machine",
        target_id="mower_1",
        parameters=[{"name": "speed", "value": 1.5}],
    )

    assert isinstance(action.parameters, tuple)
    assert action.get_parameter("speed") == action.parameters[0]
    assert action.get_parameter("missing") is None


def test_proposal_contains_data_only() -> None:
    proposal = make_proposal()

    assert not hasattr(proposal, "execute")
    assert not hasattr(proposal, "callback")
    assert not hasattr(proposal, "adapter")
