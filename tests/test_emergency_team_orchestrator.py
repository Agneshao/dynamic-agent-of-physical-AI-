"""Tests for real structured messages in the synchronous emergency team."""

from __future__ import annotations

from runtime_core.demo.thunderstorm_demo import run_thunderstorm_demo
from runtime_core.schemas.agent_messages import AgentMessageType


def test_emergency_team_produces_version_bound_interactions(tmp_path) -> None:
    result = run_thunderstorm_demo(audit_path=tmp_path / "team.jsonl")

    team = result.emergency_team_result
    assert team is not None
    assert len(team.interactions) == 7
    assert tuple(item.sequence for item in team.interactions) == tuple(range(1, 8))
    assert all(
        item.world_version == result.emergency_proposal.world_version
        for item in team.interactions
    )
    assert all(
        item.org_version == result.final_org_version for item in team.interactions
    )
    assert team.interactions[-1].message_type == AgentMessageType.FINAL_PROPOSAL
    assert team.interactions[-1].recipient_role == "proposal_board"


def test_department_outputs_compose_proposal_without_commands(tmp_path) -> None:
    result = run_thunderstorm_demo(audit_path=tmp_path / "proposal.jsonl")

    team = result.emergency_team_result
    assert team is not None
    assert team.proposal == result.emergency_proposal
    assert tuple(action.action_type for action in team.proposal.actions) == (
        "hold_position",
        "return_to_base",
        "notify_operator",
    )
    assert team.safety_report.required_holds == ("mower_1",)
    assert team.operations_plan.recommended_actions == team.proposal.actions[:2]


def test_demo_retains_explicit_stub_fallback(tmp_path) -> None:
    result = run_thunderstorm_demo(
        audit_path=tmp_path / "fallback.jsonl",
        use_agent_harness=False,
    )

    assert result.emergency_team_result is None
    assert result.emergency_proposal.agent_id == "emergency_incident_stub"
