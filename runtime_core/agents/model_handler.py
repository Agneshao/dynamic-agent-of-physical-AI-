"""Adapter from version-bound AgentHarness calls to a structured model router."""

from __future__ import annotations

import json
from typing import Type

from pydantic import BaseModel

from runtime_core.ports.model_router import ModelRouterPort
from runtime_core.schemas.agent_messages import AgentMessage
from runtime_core.schemas.agent_outputs import AgentContextView


class StructuredModelAgentHandler:
    """Serialize frozen agent inputs and request one typed model output."""

    def __init__(
        self,
        *,
        model_router: ModelRouterPort,
        system_prompt: str,
        output_schema: Type[BaseModel],
        priority: int = 0,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not system_prompt:
            raise ValueError("system_prompt must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._model_router = model_router
        self._system_prompt = system_prompt
        self._output_schema = output_schema
        self._priority = priority
        self._timeout_seconds = timeout_seconds

    def __call__(
        self,
        message: AgentMessage,
        context: AgentContextView,
        dependencies: tuple[object, ...],
    ) -> object:
        dependency_payloads = []
        for dependency in dependencies:
            if not isinstance(dependency, BaseModel):
                raise TypeError("model dependencies must be Pydantic models")
            dependency_payloads.append(
                {
                    "type": type(dependency).__name__,
                    "value": dependency.model_dump(mode="json"),
                }
            )
        user_prompt = json.dumps(
            {
                "message": message.model_dump(mode="json"),
                "context": context.model_dump(mode="json"),
                "dependencies": dependency_payloads,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return self._model_router.complete(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            output_schema=self._output_schema,
            priority=self._priority,
            timeout_seconds=self._timeout_seconds,
        )
