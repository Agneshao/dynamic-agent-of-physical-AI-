"""Audited human authorization policy for emergency organization transitions."""

from __future__ import annotations

from typing import Callable, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from runtime_core.audit.ledger import AuditLedger, AuditLedgerError
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.organization.org_transition import OrganizationTransitionResult
from runtime_core.schemas.audit import AuditRecordType
from runtime_core.schemas.mode_authorization import EmergencyModeAuthorizationDecision


class EmergencyModeAuthorizationResult(BaseModel):
    """Audited policy outcome and optional ModeManager transition result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: EmergencyModeAuthorizationDecision
    authorization_audit_record_id: UUID
    transition_result: Optional[OrganizationTransitionResult] = None

    @model_validator(mode="after")
    def transition_requires_approval(self) -> EmergencyModeAuthorizationResult:
        if not self.decision.approved and self.transition_result is not None:
            raise ValueError("rejected authorization cannot have a transition result")
        if self.decision.approved and self.transition_result is None:
            raise ValueError("approved authorization requires a transition result")
        return self


class EmergencyModeAuthorizationAuditError(RuntimeError):
    """Raised when a human authorization decision cannot be durably audited."""


class EmergencyModeAuthorizationPolicy:
    """Require an audited human decision before asking ModeManager to transition.

    The policy owns authorization validation, while ModeManager remains the only
    writer of OperatingMode and org_version. The authorization audit append must
    succeed before an approved decision is forwarded to ModeManager.
    """

    def __init__(
        self,
        mode_manager: ModeManager,
        ledger: AuditLedger,
        *,
        world_version_provider: Callable[[], int],
    ) -> None:
        self._mode_manager = mode_manager
        self._ledger = ledger
        self._world_version_provider = world_version_provider

    def apply(
        self,
        decision: EmergencyModeAuthorizationDecision,
    ) -> EmergencyModeAuthorizationResult:
        organization = self._mode_manager.get_current_organization()
        record_type = (
            AuditRecordType.EMERGENCY_MODE_AUTHORIZATION_APPROVED
            if decision.approved
            else AuditRecordType.EMERGENCY_MODE_AUTHORIZATION_REJECTED
        )
        try:
            record = self._ledger.append(
                record_type=record_type,
                actor=decision.authorized_by,
                world_version=self._world_version_provider(),
                org_version=organization.org_version,
                payload=decision.model_dump(mode="json"),
                timestamp=decision.timestamp,
            )
        except (AuditLedgerError, OSError, ValueError) as exc:
            raise EmergencyModeAuthorizationAuditError(
                "emergency mode was not requested because authorization audit failed"
            ) from exc

        transition_result = None
        if decision.approved:
            transition_result = self._mode_manager.transition(
                decision.target_mode,
                reason=decision.reason,
                triggered_by=decision.authorized_by,
            )
        return EmergencyModeAuthorizationResult(
            decision=decision,
            authorization_audit_record_id=record.record_id,
            transition_result=transition_result,
        )
