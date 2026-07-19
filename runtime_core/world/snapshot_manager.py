"""Creation and retrieval of immutable world snapshots."""

from __future__ import annotations

from threading import RLock
from typing import Optional
from uuid import UUID, uuid4

from runtime_core.schemas.world_state import FrozenWorldState, WorldSnapshot, utc_now

from .state_kernel import WorldStateKernel


class SnapshotError(RuntimeError):
    """Base class for snapshot management errors."""


class SnapshotNotFoundError(SnapshotError):
    """Raised when a requested snapshot ID is unknown."""


class SnapshotAlreadyExistsError(SnapshotError):
    """Raised if UUID generation attempts to overwrite snapshot history."""


class NoSnapshotsError(SnapshotError):
    """Raised when latest snapshot is requested before any snapshot exists."""


class SnapshotManager:
    """Build and retain immutable, version-bound snapshots without overwrite."""

    def __init__(self, kernel: WorldStateKernel) -> None:
        self._kernel = kernel
        self._lock = RLock()
        self._snapshots: dict[UUID, WorldSnapshot] = {}
        self._creation_order: list[UUID] = []

    def create_snapshot(self) -> WorldSnapshot:
        """Create a detached immutable snapshot of the current world state."""
        mutable_state = self._kernel.get_current_state()
        frozen_state = FrozenWorldState.from_world_state(mutable_state)
        snapshot = WorldSnapshot(
            snapshot_id=uuid4(),
            world_version=mutable_state.world_version,
            created_at=utc_now(),
            state=frozen_state,
        )
        with self._lock:
            if snapshot.snapshot_id in self._snapshots:
                raise SnapshotAlreadyExistsError(str(snapshot.snapshot_id))
            self._snapshots[snapshot.snapshot_id] = snapshot
            self._creation_order.append(snapshot.snapshot_id)
        return snapshot

    def get_snapshot(self, snapshot_id: UUID | str) -> WorldSnapshot:
        """Return an existing immutable snapshot or raise a clear error."""
        normalized_id = UUID(str(snapshot_id))
        with self._lock:
            try:
                return self._snapshots[normalized_id]
            except KeyError as exc:
                raise SnapshotNotFoundError(str(normalized_id)) from exc

    def get_latest_snapshot(self) -> WorldSnapshot:
        """Return the most recently created snapshot."""
        with self._lock:
            if not self._creation_order:
                raise NoSnapshotsError("no snapshots have been created")
            return self._snapshots[self._creation_order[-1]]

    def list_snapshots(self) -> tuple[WorldSnapshot, ...]:
        """Return snapshot history in creation order."""
        with self._lock:
            return tuple(self._snapshots[item] for item in self._creation_order)

