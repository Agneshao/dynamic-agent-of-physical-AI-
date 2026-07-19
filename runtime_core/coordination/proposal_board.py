"""Thread-safe proposal admission against current runtime versions."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Optional
from uuid import UUID

from pydantic import JsonValue

from runtime_core.audit.ledger import AuditLedger, AuditLedgerError
from runtime_core.errors.proposal_errors import ProposalAuditError
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.audit import AuditRecordType
from runtime_core.schemas.proposals import (
    Proposal,
    ProposalAdmissionResult,
    ProposalRejectionCode,
    ProposalStatus,
    StoredProposal,
)
from runtime_core.world.state_kernel import WorldStateKernel


class ProposalBoard:
    """Admit and retain immutable proposals with durable admission auditing.

    Admission decisions, ledger append, and in-memory publication are protected
    by one board-local RLock. An ID is marked as seen only after its first
    admission record is appended successfully. This is a single-process
    consistency boundary with a local JSONL ledger, not a distributed
    transaction protocol.
    """

    def __init__(
        self,
        world_state_kernel: WorldStateKernel,
        mode_manager: ModeManager,
        ledger: AuditLedger,
    ) -> None:
        self._lock = RLock()
        self._world_state_kernel = world_state_kernel
        self._mode_manager = mode_manager
        self._ledger = ledger
        self._entries: dict[UUID, StoredProposal] = {}
        self._rejection_history: list[ProposalAdmissionResult] = []
        self._seen_proposal_ids: set[UUID] = set()

    def submit(self, proposal: Proposal) -> ProposalAdmissionResult:
        """Validate, audit, and atomically publish one admission outcome.

        The caller must provide an already validated Proposal. For a previously
        audited proposal_id, duplicate detection takes precedence over all
        state-dependent checks so every later request has a stable result.
        """
        if not isinstance(proposal, Proposal):
            raise TypeError("proposal must be a validated Proposal")

        with self._lock:
            current_world_version = self._world_state_kernel.get_world_version()
            organization = self._mode_manager.get_current_organization()
            timestamp = datetime.now(timezone.utc)
            rejection_code = self._rejection_code_locked(
                proposal=proposal,
                current_world_version=current_world_version,
                current_org_version=organization.org_version,
                active_roles=organization.active_roles,
                timestamp=timestamp,
            )
            result = self._build_result(
                proposal=proposal,
                rejection_code=rejection_code,
                current_world_version=current_world_version,
                current_org_version=organization.org_version,
                timestamp=timestamp,
            )
            self._append_audit_locked(proposal, result)

            if rejection_code == ProposalRejectionCode.DUPLICATE_PROPOSAL:
                self._rejection_history.append(result)
                return self._copy_result(result)

            stored = StoredProposal.model_validate(
                {
                    "proposal": proposal.model_dump(mode="python"),
                    "current_status": result.status,
                    "admission_result": result.model_dump(mode="python"),
                }
            )
            self._entries[proposal.proposal_id] = stored
            if not result.accepted:
                self._rejection_history.append(result)
            self._seen_proposal_ids.add(proposal.proposal_id)
            return self._copy_result(result)

    def get(self, proposal_id: UUID) -> Optional[StoredProposal]:
        """Return a validated frozen copy without changing lifecycle state."""
        with self._lock:
            stored = self._entries.get(proposal_id)
            return None if stored is None else self._copy_stored(stored)

    def list_accepted(
        self, epoch_id: Optional[UUID] = None
    ) -> tuple[Proposal, ...]:
        """Return accepted source proposals, optionally scoped to one epoch."""
        with self._lock:
            return tuple(
                self._copy_proposal(stored.proposal)
                for stored in self._entries.values()
                if stored.current_status == ProposalStatus.ACCEPTED
                and (epoch_id is None or stored.proposal.epoch_id == epoch_id)
            )

    def list_rejected(
        self, epoch_id: Optional[UUID] = None
    ) -> tuple[ProposalAdmissionResult, ...]:
        """Return immutable rejection outcomes, including duplicate requests."""
        with self._lock:
            return tuple(
                self._copy_result(result)
                for result in self._rejection_history
                if epoch_id is None or result.epoch_id == epoch_id
            )

    def _rejection_code_locked(
        self,
        *,
        proposal: Proposal,
        current_world_version: int,
        current_org_version: int,
        active_roles: tuple[str, ...],
        timestamp: datetime,
    ) -> Optional[ProposalRejectionCode]:
        if proposal.proposal_id in self._seen_proposal_ids:
            return ProposalRejectionCode.DUPLICATE_PROPOSAL
        if proposal.world_version != current_world_version:
            return ProposalRejectionCode.STALE_WORLD_VERSION
        if proposal.org_version != current_org_version:
            return ProposalRejectionCode.STALE_ORGANIZATION_VERSION
        if proposal.valid_until <= timestamp:
            return ProposalRejectionCode.EXPIRED_PROPOSAL
        if proposal.agent_role not in active_roles:
            return ProposalRejectionCode.INACTIVE_AGENT_ROLE
        return None

    @staticmethod
    def _build_result(
        *,
        proposal: Proposal,
        rejection_code: Optional[ProposalRejectionCode],
        current_world_version: int,
        current_org_version: int,
        timestamp: datetime,
    ) -> ProposalAdmissionResult:
        accepted = rejection_code is None
        return ProposalAdmissionResult(
            proposal_id=proposal.proposal_id,
            epoch_id=proposal.epoch_id,
            accepted=accepted,
            status=(ProposalStatus.ACCEPTED if accepted else ProposalStatus.REJECTED),
            rejection_code=rejection_code,
            message=(
                "proposal accepted"
                if accepted
                else f"proposal rejected: {rejection_code.value}"
            ),
            checked_world_version=current_world_version,
            checked_org_version=current_org_version,
            timestamp=timestamp,
        )

    def _append_audit_locked(
        self, proposal: Proposal, result: ProposalAdmissionResult
    ) -> None:
        payload: dict[str, JsonValue] = {
            "proposal_id": str(proposal.proposal_id),
            "epoch_id": str(proposal.epoch_id),
            "agent_id": proposal.agent_id,
            "agent_role": proposal.agent_role,
            "proposal_world_version": proposal.world_version,
            "proposal_org_version": proposal.org_version,
            "current_world_version": result.checked_world_version,
            "current_org_version": result.checked_org_version,
            "rejection_code": (
                result.rejection_code.value if result.rejection_code else None
            ),
        }
        try:
            self._ledger.append(
                record_type=(
                    AuditRecordType.PROPOSAL_ACCEPTED
                    if result.accepted
                    else AuditRecordType.PROPOSAL_REJECTED
                ),
                actor="proposal_board",
                world_version=result.checked_world_version,
                org_version=result.checked_org_version,
                payload=payload,
                timestamp=result.timestamp,
            )
        except (AuditLedgerError, OSError, ValueError) as exc:
            raise ProposalAuditError(
                "proposal admission was not published because audit append failed"
            ) from exc

    @staticmethod
    def _copy_proposal(proposal: Proposal) -> Proposal:
        return Proposal.model_validate(proposal.model_dump(mode="python"))

    @staticmethod
    def _copy_result(result: ProposalAdmissionResult) -> ProposalAdmissionResult:
        return ProposalAdmissionResult.model_validate(result.model_dump(mode="python"))

    @staticmethod
    def _copy_stored(stored: StoredProposal) -> StoredProposal:
        return StoredProposal.model_validate(stored.model_dump(mode="python"))
