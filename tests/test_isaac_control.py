"""Live Isaac operator boundary tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.client import HTTPConnection
from threading import Thread

import pytest
from pydantic import ValidationError

from runtime_core.schemas.commands import (
    CommandStatus,
    ExecutionReceipt,
    VerificationResult,
)
from runtime_core.schemas.isaac_control import IsaacControlCommandRequest
from runtime_core.schemas.world_state import FrozenMachineState
from runtime_core.ui.server import create_server


NOW = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)


class FakeLiveIsaacAdapter:
    def __init__(self) -> None:
        self.commands = []

    def get_state(self):
        return {
            "connected": True,
            "connection_status": "CONNECTED",
            "entities": {
                "mower_2": {
                    "canonical_id": "mower_2",
                    "isaac_entity_id": "Mower_02",
                    "status": "MOWING",
                    "zone": "zone_A",
                    "position": (-30.0, -25.0, 1.0),
                }
            },
        }

    def execute_command(self, command):
        self.commands.append(command)
        return ExecutionReceipt(
            command_id=command.command_id,
            status=CommandStatus.EXECUTING,
            message="Isaac entity reached ZONE_A",
            observed_machine=FrozenMachineState(
                machine_id="mower_2",
                machine_type="mower",
                zone="zone_A",
                status="mowing",
                battery_percent=76.0,
                last_updated_at=NOW,
            ),
            executed_at=NOW,
        )

    def verify_command(self, command, receipt):
        return VerificationResult(
            command_id=command.command_id,
            status=CommandStatus.VERIFIED,
            message="Isaac observation matches expected command effect",
            observed_machine=receipt.observed_machine,
            verified_at=NOW,
        )


def make_payload():
    return {
        "incident_id": "daily-ops",
        "command_type": "move_to_zone",
        "target_id": "mower_2",
        "target_zone": "A",
        "operator_id": "course_operator_01",
        "confirmed": True,
        "world_version": 11,
        "org_version": 1,
    }


def test_control_request_requires_confirmation_and_valid_zone() -> None:
    request = IsaacControlCommandRequest.model_validate(make_payload())
    assert request.target_zone == "ZONE_A"

    with pytest.raises(ValidationError, match="explicit confirmation"):
        IsaacControlCommandRequest.model_validate(
            {**make_payload(), "confirmed": False}
        )
    with pytest.raises(ValidationError, match="target_zone"):
        IsaacControlCommandRequest.model_validate(
            {**make_payload(), "target_zone": "ZONE_X"}
        )


def test_http_isaac_state_and_command_endpoints(tmp_path) -> None:
    adapter = FakeLiveIsaacAdapter()
    server = create_server(
        port=0,
        audit_path=tmp_path / "isaac-control.jsonl",
        isaac_adapter=adapter,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/api/isaac/state")
        state_response = connection.getresponse()
        state = json.loads(state_response.read())
        assert state_response.status == 200
        assert state["configured"] is True
        assert state["connected"] is True

        connection.request(
            "POST",
            "/api/isaac/command",
            body=json.dumps(make_payload()),
            headers={"Content-Type": "application/json"},
        )
        command_response = connection.getresponse()
        result = json.loads(command_response.read())
        assert command_response.status == 200
        assert result["status"] == "VERIFIED"
        assert result["observed_machine"]["zone"] == "zone_A"
        assert adapter.commands[0].command_type.value == "move_to_zone"
        assert adapter.commands[0].get_parameter("target_zone").value == "ZONE_A"
        assert adapter.commands[0].source == "operator:course_operator_01"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
