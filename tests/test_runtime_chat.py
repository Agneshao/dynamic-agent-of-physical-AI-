"""Structured model chat service and HTTP boundary tests."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from threading import Thread

import pytest

from runtime_core.schemas.runtime_chat import (
    RuntimeChatDevice,
    RuntimeChatHazard,
    RuntimeChatIntent,
    RuntimeChatReply,
    RuntimeChatRequest,
)
from runtime_core.ui.chat_service import (
    RuntimeChatModelNotConfiguredError,
    RuntimeChatService,
)
from runtime_core.ui.server import create_server


def make_request() -> RuntimeChatRequest:
    return RuntimeChatRequest(
        message="当前人员在哪里？",
        mode="NORMAL",
        world_version=13,
        org_version=1,
        incident_id="WX-0721-A",
        phase="人工授权",
        devices=(
            RuntimeChatDevice(
                device_id="player_1",
                device_type="PERSON",
                status="PLAYING",
                zone="FAIRWAY B",
            ),
        ),
        hazards=(
            RuntimeChatHazard(
                hazard_id="irrigation_leak_c",
                hazard_type="IRRIGATION_LEAK",
                active=True,
                zone="FAIRWAY C",
                clearance="PENDING_MAINTENANCE_INSPECTION",
            ),
        ),
    )


class FakeRouter:
    def __init__(self) -> None:
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return RuntimeChatReply(
            reply="player_1 位于 FAIRWAY B，等待撤离。",
            tags=("PERSON SAFETY",),
            intent=RuntimeChatIntent.ANSWER,
        )


class MisclassifiedRouter:
    def complete(self, **kwargs):
        del kwargs
        return RuntimeChatReply(
            reply="当前运行正常，无活动事故。",
            tags=(),
            intent=RuntimeChatIntent.INJECT_THUNDERSTORM,
        )


class UnderclassifiedRouter:
    def complete(self, **kwargs):
        del kwargs
        return RuntimeChatReply(
            reply="已识别雷暴模拟请求。",
            tags=(),
            intent=RuntimeChatIntent.ANSWER,
        )


def test_chat_service_sends_detached_context_and_requires_typed_output() -> None:
    router = FakeRouter()
    service = RuntimeChatService(router)

    reply = service.reply(make_request())

    assert reply.intent == RuntimeChatIntent.ANSWER
    assert router.calls[0]["output_schema"] is RuntimeChatReply
    prompt = json.loads(router.calls[0]["user_prompt"])
    assert prompt["world_version"] == 13
    assert prompt["devices"][0]["device_id"] == "player_1"
    assert prompt["hazards"][0]["active"] is True
    assert "world_state_kernel" not in prompt


def test_chat_service_uses_configured_local_model_timeout() -> None:
    router = FakeRouter()
    service = RuntimeChatService(router, timeout_seconds=60)

    service.reply(make_request())

    assert router.calls[0]["timeout_seconds"] == 60


def test_chat_service_fails_closed_without_model_router() -> None:
    with pytest.raises(RuntimeChatModelNotConfiguredError):
        RuntimeChatService(None).reply(make_request())


def test_chat_service_blocks_model_write_intent_without_explicit_command() -> None:
    request = make_request().model_copy(
        update={"message": "请汇报当前运行状态"},
    )

    reply = RuntimeChatService(MisclassifiedRouter()).reply(request)

    assert reply.intent == RuntimeChatIntent.ANSWER
    assert "MODEL INTENT BLOCKED" in reply.tags


def test_chat_service_preserves_write_intent_with_explicit_command() -> None:
    request = make_request().model_copy(
        update={"message": "请模拟雷暴告警"},
    )

    reply = RuntimeChatService(MisclassifiedRouter()).reply(request)

    assert reply.intent == RuntimeChatIntent.INJECT_THUNDERSTORM
    assert "MODEL INTENT BLOCKED" not in reply.tags


def test_chat_service_corrects_underclassified_explicit_command() -> None:
    request = make_request().model_copy(
        update={"message": "请模拟雷暴告警"},
    )

    reply = RuntimeChatService(UnderclassifiedRouter()).reply(request)

    assert reply.intent == RuntimeChatIntent.INJECT_THUNDERSTORM
    assert "MODEL INTENT CORRECTED" in reply.tags


def test_chat_service_detects_zone_inspection_redirection() -> None:
    request = make_request().model_copy(
        update={"message": "请让无人机前往 B 区巡检"},
    )

    reply = RuntimeChatService(UnderclassifiedRouter()).reply(request)

    assert reply.intent == RuntimeChatIntent.REDIRECT_INSPECTION
    assert "MODEL INTENT CORRECTED" in reply.tags


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    (
        ("让割草机1中断任务返回维护区", RuntimeChatIntent.RETURN_MACHINE_TO_BASE),
        ("mower_2 立即回家", RuntimeChatIntent.RETURN_MACHINE_TO_BASE),
        ("让割草机1去A区割草", RuntimeChatIntent.ASSIGN_MOWING_ZONE),
        ("M2移动到A区", RuntimeChatIntent.ASSIGN_MOWING_ZONE),
        ("M1返回维护区", RuntimeChatIntent.RETURN_MACHINE_TO_BASE),
        ("割草机2从维护区调到C区执行任务", RuntimeChatIntent.ASSIGN_MOWING_ZONE),
        ("无人机完成C区任务后再去A区", RuntimeChatIntent.REDIRECT_INSPECTION),
        ("解除警报并恢复日常流程", RuntimeChatIntent.CLEAR_EMERGENCY),
        ("我确认C区已经修好漏水", RuntimeChatIntent.CLEAR_MAINTENANCE_HAZARD),
        ("C区已经修复完毕", RuntimeChatIntent.CLEAR_MAINTENANCE_HAZARD),
        ("C區檢修完成", RuntimeChatIntent.CLEAR_MAINTENANCE_HAZARD),
        ("C球道故障已经解除", RuntimeChatIntent.CLEAR_MAINTENANCE_HAZARD),
        ("Zone C valve repaired", RuntimeChatIntent.CLEAR_MAINTENANCE_HAZARD),
    ),
)
def test_chat_service_detects_equipment_and_recovery_commands(
    message,
    expected_intent,
) -> None:
    request = make_request().model_copy(update={"message": message})

    reply = RuntimeChatService(UnderclassifiedRouter()).reply(request)

    assert reply.intent == expected_intent
    assert "MODEL INTENT CORRECTED" in reply.tags


def test_incomplete_c_zone_repair_statement_is_not_a_clearance_command() -> None:
    request = make_request().model_copy(update={"message": "C区需要安排修复"})

    reply = RuntimeChatService(UnderclassifiedRouter()).reply(request)

    assert reply.intent == RuntimeChatIntent.ANSWER


def test_http_chat_endpoint_and_model_status(tmp_path) -> None:
    router = FakeRouter()
    server = create_server(
        port=0,
        audit_path=tmp_path / "chat-server.jsonl",
        model_router=router,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/api/model-status")
        status_response = connection.getresponse()
        status_payload = json.loads(status_response.read())
        assert status_response.status == 200
        assert status_payload == {
            "configured": True,
            "model": "step-3.7-flash",
        }

        body = make_request().model_dump_json().encode("utf-8")
        connection.request(
            "POST",
            "/api/chat",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        chat_response = connection.getresponse()
        chat_payload = json.loads(chat_response.read())
        assert chat_response.status == 200
        assert chat_payload["reply"].startswith("player_1")
        assert chat_payload["source"] == "STEPFUN"
        assert chat_payload["intent"] == "ANSWER"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_chat_endpoint_reports_unconfigured_model(tmp_path) -> None:
    server = create_server(
        port=0,
        audit_path=tmp_path / "unconfigured-chat.jsonl",
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(
            "POST",
            "/api/chat",
            body=make_request().model_dump_json().encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 503
        assert payload["error"] == "MODEL_NOT_CONFIGURED"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
