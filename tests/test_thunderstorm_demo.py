"""End-to-end tests for the pure-local thunderstorm demo."""

from __future__ import annotations

from runtime_core.demo.thunderstorm_demo import _print_result, run_thunderstorm_demo
from runtime_core.schemas.audit import AuditRecordType
from runtime_core.schemas.commands import CommandStatus, CommandType
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.proposals import ProposalRejectionCode, ProposalStatus


def test_auto_approved_thunderstorm_demo(tmp_path) -> None:
    result = run_thunderstorm_demo(
        auto_approve=True,
        audit_path=tmp_path / "approved.jsonl",
    )

    assert result.initial_mode == OperatingMode.NORMAL
    assert result.initial_org_version == 1
    assert result.final_mode == OperatingMode.EMERGENCY
    assert result.final_org_version == 2
    assert result.mode_authorization.decision.approved is True
    assert result.mode_authorization.decision.authorization_method == "HUMAN_OPERATOR"
    assert result.mode_authorization.transition_result is not None
    assert tuple(command.command_type for command in result.fast_path_commands) == (
        CommandType.PAUSE_MACHINE,
        CommandType.PAUSE_MACHINE,
        CommandType.FREEZE_NEW_TASKS,
    )
    assert tuple(
        command.command_type for command in result.human_safety_commands
    ) == (CommandType.ALERT_PERSON, CommandType.TRACK_PERSON)
    assert all(item.status == CommandStatus.VERIFIED for item in result.fast_path_results)
    assert result.normal_proposal.world_version == result.stale_submission_world_version
    assert result.normal_proposal.org_version == 1
    assert result.stale_proposal_result.status == ProposalStatus.REJECTED
    assert (
        result.stale_proposal_result.rejection_code
        == ProposalRejectionCode.STALE_ORGANIZATION_VERSION
    )
    assert result.emergency_proposal_result.status == ProposalStatus.ACCEPTED
    assert result.emergency_validation_result.status == ProposalStatus.ACCEPTED
    assert result.approval_decision.approved is True
    assert len(result.command_results) == 3
    assert result.final_world_state.get_machine("mower_1").status == "holding"
    assert (
        result.final_world_state.get_machine("mower_2").zone
        == "maintenance_base"
    )
    assert result.final_world_state.get_machine("drone_1").zone == "zone_C"
    assert (
        result.final_world_state.get_machine("drone_1").status
        == "tracking_person"
    )
    assert result.final_world_state.get_person("player_1").status == "alerted"
    assert result.final_world_state.new_tasks_frozen is True
    assert result.final_world_version > result.initial_world_version
    record_types = {record.record_type for record in result.audit_records}
    assert AuditRecordType.ORGANIZATION_TRANSITION in record_types
    assert AuditRecordType.EMERGENCY_MODE_AUTHORIZATION_APPROVED in record_types
    assert AuditRecordType.PROPOSAL_REJECTED in record_types
    assert AuditRecordType.PROPOSAL_ACCEPTED in record_types
    assert result.audit_log_path.exists()


def test_rejected_approval_keeps_fast_path_safe_state(tmp_path) -> None:
    result = run_thunderstorm_demo(
        auto_approve=False,
        audit_path=tmp_path / "rejected.jsonl",
    )

    assert result.final_mode == OperatingMode.EMERGENCY
    assert result.final_org_version == 2
    assert result.emergency_proposal_result.status == ProposalStatus.ACCEPTED
    assert result.approval_decision.approved is False
    assert result.command_results == ()
    assert result.final_world_state.get_machine("mower_1").status == "paused"
    assert result.final_world_state.get_machine("mower_2").status == "paused"
    assert result.final_world_state.get_machine("mower_2").zone == "zone_D"
    assert result.final_world_state.get_machine("drone_1").zone == "zone_C"
    assert (
        result.final_world_state.get_machine("drone_1").status
        == "tracking_person"
    )
    assert result.final_world_state.get_person("player_1").status == "alerted"
    assert result.final_world_state.new_tasks_frozen is True


def test_cli_summary_contains_required_markers(tmp_path, capsys) -> None:
    result = run_thunderstorm_demo(
        audit_path=tmp_path / "output.jsonl"
    )

    _print_result(result)
    output = capsys.readouterr().out

    assert "OLD PROPOSAL REJECTED: STALE_ORGANIZATION_VERSION" in output
    assert "ORGANIZATION SWITCHED: org_version 1 -> 2" in output
    assert "mower_1 status: holding" in output
    assert "mower_2 location: maintenance_base" in output
    assert "drone_1 location: zone_C" in output
    assert "drone_1 status: tracking_person" in output
    assert "player_1 status: alerted" in output
    assert "new_tasks_frozen: True" in output
