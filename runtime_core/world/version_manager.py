"""Version management primitives for runtime-owned state."""

from __future__ import annotations


class VersionConflictError(RuntimeError):
    """Raised when a commit attempts to skip or reuse a world version."""


class VersionManager:
    """Track the committed world version under the kernel's synchronization lock."""

    def __init__(self, initial_world_version: int = 0) -> None:
        if initial_world_version < 0:
            raise ValueError("initial_world_version must be non-negative")
        self._world_version = initial_world_version

    @property
    def world_version(self) -> int:
        """Return the currently committed world version."""
        return self._world_version

    def next_world_version(self) -> int:
        """Return the next candidate version without mutating committed state."""
        return self._world_version + 1

    def commit_world_version(self, version: int) -> None:
        """Commit exactly the next sequential world version."""
        expected = self._world_version + 1
        if version != expected:
            raise VersionConflictError(f"expected world version {expected}, received {version}")
        self._world_version = version

