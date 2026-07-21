"""Logical agent lifecycle states."""

from enum import Enum


class AgentLifecycleStatus(str, Enum):
    """Whether a version-bound logical harness may process messages."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
