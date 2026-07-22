"""Offline contract tests for StepFun structured model routing."""

from __future__ import annotations

import json

import pytest

from runtime_core.adapters.stepfun_model_router import (
    StepFunConfigurationError,
    StepFunModelRouter,
    StepFunRouterConfig,
    StepFunStructuredOutputError,
)
from runtime_core.agents.model_handler import StructuredModelAgentHandler
from runtime_core.schemas.agent_outputs import SafetyReport


def safety_payload() -> dict[str, object]:
    return {
        "incident_id": "storm-1",
        "world_version": 5,
        "org_version": 2,
        "occupied_zones": ["zone_B"],
        "unsafe_machines": ["mower_1"],
        "required_holds": ["mower_1"],
        "risk_summary": "person exposed to lightning",
        "confidence": 0.98,
    }


def test_router_requests_json_schema_and_validates_output(monkeypatch) -> None:
    captured = {}

    def transport(endpoint, payload, api_key, timeout_seconds):
        captured.update(
            endpoint=endpoint,
            payload=payload,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(safety_payload())},
                }
            ]
        }

    monkeypatch.setenv("STEP_API_KEY", "test-only-key")
    router = StepFunModelRouter(transport=transport)
    result = router.complete(
        system_prompt="safety policy",
        user_prompt="version-bound context",
        output_schema=SafetyReport,
        priority=10,
        timeout_seconds=12.0,
    )

    assert isinstance(result, SafetyReport)
    assert result.required_holds == ("mower_1",)
    assert captured["api_key"] == "test-only-key"
    assert captured["timeout_seconds"] == 12.0
    assert captured["endpoint"].endswith("/v1/chat/completions")
    response_format = captured["payload"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert captured["payload"]["max_tokens"] == 2048


def test_router_requires_environment_key(monkeypatch) -> None:
    monkeypatch.delenv("STEP_API_KEY", raising=False)
    router = StepFunModelRouter(transport=lambda *args: {})

    with pytest.raises(StepFunConfigurationError, match="STEP_API_KEY"):
        router.complete(
            system_prompt="system",
            user_prompt="user",
            output_schema=SafetyReport,
            priority=0,
            timeout_seconds=1,
        )


def test_router_rejects_truncated_or_invalid_output(monkeypatch) -> None:
    monkeypatch.setenv("STEP_API_KEY", "test-only-key")
    truncated = StepFunModelRouter(
        transport=lambda *args: {
            "choices": [
                {"finish_reason": "length", "message": {"content": "{}"}}
            ]
        }
    )
    invalid = StepFunModelRouter(
        transport=lambda *args: {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "{}"}}
            ]
        }
    )

    kwargs = dict(
        system_prompt="system",
        user_prompt="user",
        output_schema=SafetyReport,
        priority=0,
        timeout_seconds=1,
    )
    with pytest.raises(StepFunStructuredOutputError, match="length"):
        truncated.complete(**kwargs)
    with pytest.raises(StepFunStructuredOutputError, match="validation"):
        invalid.complete(**kwargs)


def test_router_config_enforces_safe_completion_budget() -> None:
    with pytest.raises(ValueError, match="at least 256"):
        StepFunRouterConfig(max_tokens=32)


def test_router_config_allows_only_local_plain_http() -> None:
    assert StepFunRouterConfig(base_url="http://127.0.0.1:8080/v1").base_url
    assert StepFunRouterConfig(base_url="http://localhost:8080/v1").base_url
    with pytest.raises(ValueError, match="localhost HTTP"):
        StepFunRouterConfig(base_url="http://model.internal:8080/v1")


def test_local_router_uses_prompt_schema_without_llama_grammar(monkeypatch) -> None:
    captured = {}

    def transport(endpoint, payload, api_key, timeout_seconds):
        del endpoint, api_key, timeout_seconds
        captured.update(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(safety_payload())},
                }
            ]
        }

    monkeypatch.setenv("STEP_API_KEY", "local")
    router = StepFunModelRouter(
        StepFunRouterConfig(base_url="http://127.0.0.1:8080/v1"),
        transport=transport,
    )

    result = router.complete(
        system_prompt="Return a safety report.",
        user_prompt="local context",
        output_schema=SafetyReport,
        priority=0,
        timeout_seconds=60,
    )

    assert isinstance(result, SafetyReport)
    assert "response_format" not in captured
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}
    assert "JSON Schema" in captured["messages"][0]["content"]


def test_structured_handler_sends_only_serializable_frozen_inputs() -> None:
    class FakeRouter:
        def complete(self, **kwargs):
            data = json.loads(kwargs["user_prompt"])
            assert data["message"]["world_version"] == 5
            assert data["context"]["org_version"] == 2
            assert data["dependencies"] == []
            return SafetyReport.model_validate(safety_payload())

    handler = StructuredModelAgentHandler(
        model_router=FakeRouter(),
        system_prompt="Apply explicit safety policy.",
        output_schema=SafetyReport,
    )
    assert handler._output_schema is SafetyReport
