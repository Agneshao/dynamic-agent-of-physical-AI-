"""Tests for immutable command and evidence schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from runtime_core.schemas.commands import (
    Command,
    CommandResult,
    CommandStatus,
    CommandType,
)
from runtime_core.schemas.evidence import Evidence, EvidenceFact, EvidenceKind
from runtime_core.schemas.proposals import ProposalParameter


def make_command(**overrides) -> Command:
    data = {
        "incident_id": "storm-1",
        "idempotency_key": "storm-1:pause_machine:mower_1",
        "command_type": CommandType.PAUSE_MACHINE,
        "target_id": "mower_1",
        "parameters": (ProposalParameter(name="reason", value="lightning"),),
        "source": "emergency_fast_path",
        "world_version": 3,
        "org_version": 1,
    }
    data.update(overrides)
    return Command.model_validate(data)


def test_command_is_frozen_and_json_round_trips() -> None:
    command = make_command()

    assert command.status == CommandStatus.CREATED
    assert isinstance(command.parameters, tuple)
    assert Command.model_validate_json(command.model_dump_json()) == command
    with pytest.raises(ValidationError):
        command.status = CommandStatus.APPROVED


def test_idempotency_key_must_bind_incident_action_and_target() -> None:
    with pytest.raises(ValidationError, match="idempotency_key"):
        make_command(idempotency_key="global:pause_machine:mower_1")


def test_command_rejects_naive_datetime_and_noncreated_status() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        make_command(created_at=datetime.now())
    with pytest.raises(ValidationError, match="must remain CREATED"):
        make_command(status=CommandStatus.APPROVED)


def test_command_parameter_names_are_unique() -> None:
    duplicate_parameters = (
        ProposalParameter(name="reason", value="lightning"),
        ProposalParameter(name="reason", value="storm"),
    )

    with pytest.raises(ValidationError, match="names must be unique"):
        make_command(parameters=duplicate_parameters)


def test_evidence_and_command_result_are_frozen_and_serializable() -> None:
    command_id = uuid4()
    evidence = Evidence(
        command_id=command_id,
        kind=EvidenceKind.KERNEL_SYNC,
        source="simple_executor",
        facts=(EvidenceFact(name="world_version", value=4),),
    )
    result = CommandResult(
        command_id=command_id,
        status=CommandStatus.VERIFIED,
        message="synchronized",
        evidence=(evidence,),
        executed_at=datetime.now(timezone.utc),
    )

    assert CommandResult.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        evidence.source = "changed"
    with pytest.raises(ValidationError):
        result.status = CommandStatus.FAILED
