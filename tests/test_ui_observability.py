"""Read-only projection and HTTP tests for the standalone observability UI."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from threading import Thread

from runtime_core.demo.thunderstorm_demo import run_thunderstorm_demo
from runtime_core.ui.projection import ObservabilityLayer, ObservabilityView, build_observability_view
from runtime_core.ui.server import create_server


def test_projection_is_frozen_json_safe_and_round_trips(tmp_path) -> None:
    result = run_thunderstorm_demo(audit_path=tmp_path / "projection.jsonl")
    view = build_observability_view(result)

    payload = view.model_dump_json()
    reloaded = ObservabilityView.model_validate_json(payload)
    assert reloaded == view
    assert len(view.interactions) == 7
    assert set(event.layer for event in view.events) == set(ObservabilityLayer)
    assert view.final_world_version > view.initial_world_version
    assert view.machine_changes[0].initial_status == "mowing"
    assert view.machine_changes[0].final_status == "holding"


def test_projection_is_detached_from_runtime_service_owners(tmp_path) -> None:
    result = run_thunderstorm_demo(audit_path=tmp_path / "detached.jsonl")
    payload = build_observability_view(result).model_dump(mode="json")
    json.dumps(payload)

    assert not {
        "world_state_kernel",
        "mode_manager",
        "proposal_board",
        "simple_executor",
        "adapter",
    } & set(payload)


def test_http_server_exposes_scenario_and_static_assets(tmp_path) -> None:
    server = create_server(
        port=0,
        audit_path=tmp_path / "server.jsonl",
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/api/scenario")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["incident_id"] == "thunderstorm-demo-001"
        assert len(payload["interactions"]) == 7

        connection.request("GET", "/")
        page = connection.getresponse()
        body = page.read().decode("utf-8")
        assert page.status == 200
        assert "Golf Course Runtime" in body

        connection.request("GET", "/scenario.js")
        scenario_response = connection.getresponse()
        scenario_body = scenario_response.read().decode("utf-8")
        assert scenario_response.status == 200
        assert "GOLF_RUNTIME_SCENARIO" in scenario_body

        connection.request("POST", "/api/scenario")
        write_response = connection.getresponse()
        write_response.read()
        assert write_response.status == 501
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
