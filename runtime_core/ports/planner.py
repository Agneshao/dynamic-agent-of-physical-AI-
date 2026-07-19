"""Planner integration boundary for future deterministic or model-backed planners."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from runtime_core.schemas.organization import OrganizationState
from runtime_core.schemas.world_state import WorldSnapshot

if TYPE_CHECKING:
    from runtime_core.schemas.proposals import Proposal


class PlanningTask(Protocol):
    """Minimum structural contract accepted by a future planner."""

    task_id: str


class PlannerPort(Protocol):
    """Create a proposal from one immutable snapshot and organization version."""

    def create_proposal(
        self,
        snapshot: WorldSnapshot,
        organization: OrganizationState,
        task: PlanningTask,
    ) -> Proposal:
        ...

