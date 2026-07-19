"""Thread-safe owner of the authoritative runtime operating mode."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Callable
from uuid import UUID, uuid4

from pydantic import JsonValue

from runtime_core.audit.ledger import AuditLedger, AuditLedgerError
from runtime_core.schemas.audit import AuditRecord, AuditRecordType
from runtime_core.schemas.organization import OperatingMode, OrganizationState

from .org_transition import (
    OrganizationTransition,
    OrganizationTransitionResult,
    TransitionStatus,
)


REGISTERED_ROLES: tuple[str, ...] = (
    "supervisor",
    "safety",
    "operations",
    "maintenance",
    "resource",
    "communication",
    "incident_commander",
    "logistics",
    "turf_optimizer",
    "cost_optimizer",
    "daily_scheduler",
)

LEGAL_TRANSITIONS: frozenset[tuple[OperatingMode, OperatingMode]] = frozenset(
    {
        (OperatingMode.NORMAL, OperatingMode.WATCH),
        (OperatingMode.WATCH, OperatingMode.NORMAL),
        (OperatingMode.WATCH, OperatingMode.EMERGENCY),
        (OperatingMode.NORMAL, OperatingMode.EMERGENCY),
        (OperatingMode.EMERGENCY, OperatingMode.RECOVERY),
        (OperatingMode.RECOVERY, OperatingMode.NORMAL),
        (OperatingMode.RECOVERY, OperatingMode.EMERGENCY),
    }
)


class OrganizationControlError(RuntimeError):
    """Base error for organization control-plane failures."""

    code = "ORGANIZATION_CONTROL_ERROR"


class InvalidModeTransitionError(OrganizationControlError):
    """Raised when a requested transition is not in the legal matrix."""

    code = "INVALID_MODE_TRANSITION"

    def __init__(self, from_mode: OperatingMode, to_mode: OperatingMode) -> None:
        self.from_mode = from_mode
        self.to_mode = to_mode
        super().__init__(f"invalid mode transition: {from_mode.value} -> {to_mode.value}")


class OrganizationTransitionAuditError(OrganizationControlError):
    """Raised when the ledger cannot durably record a transition request."""

    code = "ORGANIZATION_AUDIT_APPEND_FAILED"


class ModeManager:
    """Own and atomically publish OrganizationState transitions.

    A successful transition requires both a validated candidate organization
    and a successful append to the local JSONL ledger. Both steps run under one
    ModeManager RLock, and the new in-memory state is published only after the
    append succeeds. This is a single-process consistency boundary between
    memory and a local file; it is not a distributed transaction protocol.
    """

    def __init__(
        self,
        ledger: AuditLedger,
        *,
        world_version_provider: Callable[[], int] | None = None,
    ) -> None:
        self._lock = RLock()
        self._ledger = ledger
        self._world_version_provider = world_version_provider or (lambda: 0)
        self._state = self._build_organization(
            mode=OperatingMode.NORMAL,
            org_version=1,
            transition_id=uuid4(),
            reason="runtime_initialized",
            activated_at=datetime.now(timezone.utc),
        )

    def get_current_organization(self) -> OrganizationState:
        """Return a fully validated copy, never the internal state object."""
        with self._lock:
            return self._copy_state_locked()

    def transition(
        self,
        target_mode: OperatingMode,
        *,
        reason: str,
        triggered_by: str,
    ) -> OrganizationTransitionResult:
        """Validate, audit, and atomically publish one mode transition."""
        with self._lock:
            current = self._state
            if target_mode == current.mode:
                record = self._append_audit_locked(
                    record_type=AuditRecordType.ORGANIZATION_TRANSITION_NO_OP,
                    actor=triggered_by,
                    org_version=current.org_version,
                    payload={
                        "requested_mode": target_mode.value,
                        "current_mode": current.mode.value,
                        "reason": reason,
                        "outcome": TransitionStatus.NO_OP_TRANSITION.value,
                    },
                )
                return OrganizationTransitionResult(
                    status=TransitionStatus.NO_OP_TRANSITION,
                    organization=self._copy_state_locked(),
                    transition=None,
                    audit_record_id=record.record_id,
                )

            if (current.mode, target_mode) not in LEGAL_TRANSITIONS:
                self._append_audit_locked(
                    record_type=AuditRecordType.ORGANIZATION_TRANSITION_REJECTED,
                    actor=triggered_by,
                    org_version=current.org_version,
                    payload={
                        "from_mode": current.mode.value,
                        "requested_mode": target_mode.value,
                        "reason": reason,
                        "error_code": InvalidModeTransitionError.code,
                    },
                )
                raise InvalidModeTransitionError(current.mode, target_mode)

            transition_time = datetime.now(timezone.utc)
            transition_id = uuid4()
            candidate = self._build_organization(
                mode=target_mode,
                org_version=current.org_version + 1,
                transition_id=transition_id,
                reason=reason,
                activated_at=transition_time,
            )
            current_active = set(current.active_roles)
            candidate_active = set(candidate.active_roles)
            transition = OrganizationTransition(
                transition_id=transition_id,
                from_mode=current.mode,
                to_mode=target_mode,
                from_org_version=current.org_version,
                to_org_version=candidate.org_version,
                activated_roles=tuple(
                    role for role in REGISTERED_ROLES if role in candidate_active - current_active
                ),
                suspended_roles=tuple(
                    role for role in REGISTERED_ROLES if role in current_active - candidate_active
                ),
                triggered_by=triggered_by,
                reason=reason,
                timestamp=transition_time,
            )
            record = self._append_audit_locked(
                record_type=AuditRecordType.ORGANIZATION_TRANSITION,
                actor=triggered_by,
                org_version=candidate.org_version,
                payload=transition.model_dump(mode="json"),
            )

            self._state = candidate
            return OrganizationTransitionResult(
                status=TransitionStatus.APPLIED,
                organization=self._copy_state_locked(),
                transition=transition,
                audit_record_id=record.record_id,
            )

    def _append_audit_locked(
        self,
        *,
        record_type: AuditRecordType,
        actor: str,
        org_version: int,
        payload: dict[str, JsonValue],
    ) -> AuditRecord:
        try:
            return self._ledger.append(
                record_type=record_type,
                actor=actor,
                world_version=self._world_version_provider(),
                org_version=org_version,
                payload=payload,
            )
        except (AuditLedgerError, OSError, ValueError) as exc:
            raise OrganizationTransitionAuditError(
                "organization transition was not published because audit append failed"
            ) from exc

    def _copy_state_locked(self) -> OrganizationState:
        return OrganizationState.model_validate(self._state.model_dump(mode="python"))

    @staticmethod
    def _build_organization(
        *,
        mode: OperatingMode,
        org_version: int,
        transition_id: UUID,
        reason: str,
        activated_at: datetime,
    ) -> OrganizationState:
        active_roles = _active_roles_for_mode(mode)
        active_set = set(active_roles)
        suspended_roles = tuple(
            role for role in REGISTERED_ROLES if role not in active_set
        )
        permission_profile = {
            role: ("read_world_snapshot",) if role in active_set else ()
            for role in REGISTERED_ROLES
        }
        return OrganizationState.model_validate(
            {
                "org_version": org_version,
                "mode": mode,
                "registered_roles": REGISTERED_ROLES,
                "active_roles": active_roles,
                "suspended_roles": suspended_roles,
                "reporting_graph": _reporting_graph_for_mode(mode),
                "permission_profile": permission_profile,
                "activated_at": activated_at,
                "transition_id": transition_id,
                "reason": reason,
            }
        )


def _active_roles_for_mode(mode: OperatingMode) -> tuple[str, ...]:
    if mode in (OperatingMode.NORMAL, OperatingMode.WATCH):
        return (
            "supervisor",
            "safety",
            "operations",
            "maintenance",
            "resource",
            "communication",
        )
    if mode == OperatingMode.EMERGENCY:
        return (
            "incident_commander",
            "safety",
            "operations",
            "logistics",
            "communication",
        )
    return (
        "incident_commander",
        "safety",
        "operations",
        "maintenance",
        "logistics",
        "communication",
    )


def _reporting_graph_for_mode(mode: OperatingMode) -> dict[str, tuple[str, ...]]:
    if mode in (OperatingMode.NORMAL, OperatingMode.WATCH):
        return {
            "supervisor": (
                "safety",
                "operations",
                "maintenance",
                "resource",
                "communication",
            )
        }
    if mode == OperatingMode.EMERGENCY:
        return {
            "incident_commander": (
                "safety",
                "operations",
                "logistics",
                "communication",
            )
        }
    return {
        "incident_commander": (
            "safety",
            "operations",
            "maintenance",
            "logistics",
            "communication",
        )
    }
