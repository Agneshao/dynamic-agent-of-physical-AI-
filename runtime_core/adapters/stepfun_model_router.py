"""StepFun OpenAI-compatible implementation of the model-router port."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable, Optional, Type
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError


class StepFunModelRouterError(RuntimeError):
    """Base error for model transport and structured-output failures."""


class StepFunConfigurationError(StepFunModelRouterError):
    """Raised when the router has no usable API key or endpoint configuration."""


class StepFunRequestError(StepFunModelRouterError):
    """Raised when StepFun rejects or cannot complete a request."""


class StepFunStructuredOutputError(StepFunModelRouterError):
    """Raised when a successful response cannot validate as the requested model."""


JsonTransport = Callable[[str, dict[str, object], str, float], dict[str, object]]


@dataclass(frozen=True)
class StepFunRouterConfig:
    """Immutable model and endpoint configuration without credentials."""

    model: str = "step-3.7-flash"
    base_url: str = "https://api.stepfun.com/v1"
    api_key_env: str = "STEP_API_KEY"
    max_tokens: int = 2048
    reasoning_effort: str = "low"
    temperature: float = 0.0

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model must not be empty")
        secure_remote = self.base_url.startswith("https://")
        local_http = self.base_url.startswith(
            ("http://127.0.0.1", "http://localhost")
        )
        if not secure_remote and not local_http:
            raise ValueError(
                "base_url must use HTTPS or localhost HTTP"
            )
        if self.max_tokens < 256:
            raise ValueError("max_tokens must be at least 256")
        if self.reasoning_effort not in ("low", "medium", "high"):
            raise ValueError("unsupported reasoning_effort")


class StepFunModelRouter:
    """Request strict Pydantic outputs from StepFun without exposing the API key."""

    def __init__(
        self,
        config: Optional[StepFunRouterConfig] = None,
        *,
        transport: Optional[JsonTransport] = None,
    ) -> None:
        self.config = config or StepFunRouterConfig()
        self._transport = transport or _urllib_json_transport

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: type,
        priority: int,
        timeout_seconds: float,
    ) -> object:
        """Return one fully validated structured model, never raw model text."""
        del priority
        if not system_prompt or not user_prompt:
            raise ValueError("system_prompt and user_prompt must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not isinstance(output_schema, type) or not issubclass(output_schema, BaseModel):
            raise TypeError("output_schema must be a Pydantic BaseModel type")
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise StepFunConfigurationError(
                f"missing API key environment variable: {self.config.api_key_env}"
            )

        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "reasoning_effort": self.config.reasoning_effort,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_schema.__name__,
                    "strict": True,
                    "schema": output_schema.model_json_schema(),
                },
            },
        }
        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        response = self._transport(endpoint, payload, api_key, timeout_seconds)
        try:
            choices = response["choices"]
            choice = choices[0]  # type: ignore[index]
            finish_reason = choice.get("finish_reason")  # type: ignore[union-attr]
            content = choice["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise StepFunStructuredOutputError(
                "StepFun response did not contain a completion message"
            ) from exc
        if finish_reason != "stop":
            raise StepFunStructuredOutputError(
                f"StepFun completion did not finish normally: {finish_reason}"
            )
        try:
            parsed = json.loads(content)
            return output_schema.model_validate(parsed)
        except (json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise StepFunStructuredOutputError(
                f"StepFun output failed {output_schema.__name__} validation"
            ) from exc


def _urllib_json_transport(
    endpoint: str,
    payload: dict[str, object],
    api_key: str,
    timeout_seconds: float,
) -> dict[str, object]:
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = json.load(response)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(raw)
        except json.JSONDecodeError:
            details = {"message": "non-JSON error response"}
        raise StepFunRequestError(
            f"StepFun request failed with HTTP {exc.code}: {details}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise StepFunRequestError(
            f"StepFun request transport failed: {type(exc).__name__}"
        ) from exc
    if not isinstance(body, dict):
        raise StepFunRequestError("StepFun response body must be a JSON object")
    return body
