"""Sequential execution of one approved and admitted Proposal."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from runtime_core.coordination.proposal_board import ProposalBoard
from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.approval import ApprovalDecision
from runtime_core.schemas.commands import Command, CommandResult, CommandStatus, CommandType
from runtime_core.schemas.proposals import Proposal, ProposalAction, ProposalStatus
from runtime_core.world.state_kernel import WorldStateKernel


class ProposalExecutionError(RuntimeError):
    """Base error for the minimal approved-proposal execution path."""


class ApprovalMismatchError(ProposalExecutionError):
    """Raised when an approval references a different proposal."""


class ProposalNotApprovedError(ProposalExecutionError):
    """Raised when execution is requested without an affirmative decision."""


class ProposalNotExecutableError(ProposalExecutionError):
    """Raised when ProposalBoard no longer considers the proposal accepted."""


_ACTION_TO_COMMAND: dict[str, CommandType] = {
    "hold_position": CommandType.HOLD_POSITION,
    "return_to_base": CommandType.RETURN_TO_BASE,
    "notify_operator": CommandType.NOTIFY_OPERATOR,
}


def execute_approved_proposal(
    *,
    proposal: Proposal,
    approval: ApprovalDecision,
    proposal_board: ProposalBoard,
    mode_manager: ModeManager,
    world_kernel: WorldStateKernel,
    executor: SimpleExecutor,
    incident_id: str,
) -> tuple[CommandResult, ...]:
    """Validate once, then materialize and execute actions one at a time."""
    if approval.proposal_id != proposal.proposal_id:
        raise ApprovalMismatchError("approval proposal_id does not match proposal")
    if not approval.approved:
        raise ProposalNotApprovedError("proposal approval was denied")
    if not incident_id:
        raise ValueError("incident_id must not be empty")

    validation = proposal_board.validate_for_use(proposal.proposal_id)
    if not validation.accepted or validation.status != ProposalStatus.ACCEPTED:
        raise ProposalNotExecutableError(
            f"proposal is not accepted for use: {validation.status.value}"
        )

    execution_org_version = mode_manager.get_current_organization().org_version
    results: list[CommandResult] = []
    for action in proposal.actions:
        organization = mode_manager.get_current_organization()
        if organization.org_version != execution_org_version:
            break
        command = _command_for_action(
            proposal=proposal,
            action=action,
            incident_id=incident_id,
            world_version=world_kernel.get_world_version(),
            org_version=organization.org_version,
        )
        result = executor.execute(command)
        results.append(result)
        if result.status != CommandStatus.VERIFIED:
            break
    return tuple(results)


def _command_for_action(
    *,
    proposal: Proposal,
    action: ProposalAction,
    incident_id: str,
    world_version: int,
    org_version: int,
) -> Command:
    try:
        command_type = _ACTION_TO_COMMAND[action.action_type]
    except KeyError as exc:
        raise ProposalExecutionError(
            f"unsupported proposal action: {action.action_type}"
        ) from exc
    idempotency_key = f"{incident_id}:{command_type.value}:{action.target_id}"
    return Command(
        command_id=uuid5(NAMESPACE_URL, idempotency_key),
        incident_id=incident_id,
        idempotency_key=idempotency_key,
        command_type=command_type,
        target_id=action.target_id,
        parameters=action.parameters,
        source=f"proposal:{proposal.proposal_id}",
        world_version=world_version,
        org_version=org_version,
    )
