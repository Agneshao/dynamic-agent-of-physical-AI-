"""Errors raised by proposal admission and storage."""


class ProposalBoardError(RuntimeError):
    """Base error raised by the proposal coordination layer."""

    code = "PROPOSAL_BOARD_ERROR"


class ProposalAuditError(ProposalBoardError):
    """Raised when a proposal admission result cannot be durably audited."""

    code = "PROPOSAL_AUDIT_APPEND_FAILED"
