"""Protocol boundary for the future DGX model router integration."""

from __future__ import annotations

from typing import Protocol


class ModelRouterPort(Protocol):
    """Structured model completion interface without a network implementation."""

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: type,
        priority: int,
        timeout_seconds: float,
    ) -> object:
        ...

