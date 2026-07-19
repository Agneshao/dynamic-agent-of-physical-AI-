"""Errors raised by proposal admission and storage."""


class ProposalBoardError(RuntimeError):
    """Base error raised by the proposal coordination layer."""

    code = "PROPOSAL_BOARD_ERROR"


class ProposalAuditError(ProposalBoardError):
    """Raised when a proposal admission result cannot be durably audited."""

    code = "PROPOSAL_AUDIT_APPEND_FAILED"


class ProposalNotFoundError(ProposalBoardError):
    """Raised when lifecycle validation targets an unknown proposal."""

    code = "PROPOSAL_NOT_FOUND"


class ProposalLifecycleError(ProposalBoardError):
    """Raised when a proposal has an impossible board lifecycle state."""

    code = "INVALID_PROPOSAL_LIFECYCLE"
