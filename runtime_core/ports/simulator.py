"""Abstract simulator/device adapter boundary for future integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime_core.schemas.commands import Command, ExecutionReceipt, VerificationResult
    from runtime_core.schemas.evidence import Evidence


class SimulatorAdapter(ABC):
    """Execute and verify commands against a simulator or physical adapter."""

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Return the adapter's current observed state."""
        raise NotImplementedError

    @abstractmethod
    def execute_command(self, command: Command) -> ExecutionReceipt:
        """Execute one coordinator-approved command."""
        raise NotImplementedError

    @abstractmethod
    def verify_command(
        self,
        command: Command,
        receipt: ExecutionReceipt,
    ) -> VerificationResult:
        """Verify observed state against a command's expected result."""
        raise NotImplementedError

    @abstractmethod
    def collect_evidence(self, command: Command) -> list[Evidence]:
        """Collect evidence associated with one executed command."""
        raise NotImplementedError

