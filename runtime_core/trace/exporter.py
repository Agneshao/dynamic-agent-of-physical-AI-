"""Export completed runtime results as newline-delimited JSON."""

from __future__ import annotations

import json
from typing import Any

from runtime_core.demo.thunderstorm_demo import ThunderstormDemoResult
from runtime_core.schemas.commands import CommandType
from runtime_core.ui.projection import ObservabilityEvent, build_observability_view


TRACE_SCHEMA_VERSION = "1.0"


def build_runtime_trace(result: ThunderstormDemoResult) -> tuple[dict[str, Any], ...]:
    """Build a detached trace containing one scenario record and ordered events."""
    view = build_observability_view(result)
    normal_roles = result.initial_organization.active_roles
    emergency_roles = result.final_organization.active_roles
    normal_set = set(normal_roles)
    emergency_set = set(emergency_roles)
    metadata = {
        "record_type": "scenario",
        "schema_version": TRACE_SCHEMA_VERSION,
        "scenario": {
            "id": view.incident_id,
            "title": "Thunderstorm Emergency Demo",
            "generatedAt": view.generated_at.isoformat(),
            "initial": _runtime_state(result.initial_world_state, view.initial_mode, view.initial_org_version),
            "final": _runtime_state(result.final_world_state, view.final_mode, view.final_org_version),
            "organization": {
                "normal": {
                    "leader": "supervisor",
                    "roles": list(normal_roles),
                    "reports": [["supervisor", role] for role in normal_roles if role != "supervisor"],
                },
                "emergency": {
                    "leader": "incident_commander",
                    "roles": list(emergency_roles),
                    "reports": [["incident_commander", role] for role in emergency_roles if role != "incident_commander"],
                    "activated": sorted(emergency_set - normal_set),
                    "retained": sorted(emergency_set & normal_set),
                    "suspended": sorted(normal_set - emergency_set),
                    "trigger": "CRITICAL thunderstorm; lightning distance 2.5 km",
                    "reason": result.organization_plan.reason,
                    "capabilities": list(result.organization_plan.required_capabilities),
                    "selectedRoles": list(emergency_roles),
                },
            },
            "proposalRejection": {
                "proposalWorldVersion": result.normal_proposal.world_version,
                "proposalOrgVersion": result.normal_proposal.org_version,
                "runtimeWorldVersion": result.stale_proposal_result.checked_world_version,
                "runtimeOrgVersion": result.stale_proposal_result.checked_org_version,
                "result": result.stale_proposal_result.status.value,
                "code": result.stale_proposal_result.rejection_code.value,
                "reason": result.stale_proposal_result.message,
            },
        },
    }
    records = [metadata]
    records.extend(_event_record(event) for event in view.events)
    return tuple(records)


def dump_runtime_trace_jsonl(result: ThunderstormDemoResult) -> bytes:
    """Serialize a completed scenario as UTF-8 JSONL suitable for streaming."""
    lines = (
        json.dumps(record, separators=(",", ":"), ensure_ascii=True)
        for record in build_runtime_trace(result)
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _runtime_state(world: Any, mode: str, org_version: int) -> dict[str, Any]:
    return {
        "mode": mode,
        "worldVersion": world.world_version,
        "orgVersion": org_version,
        "phase": "BASELINE" if mode == "NORMAL" else "COMPLETE",
        "devices": {
            machine.machine_id: {
                "type": machine.machine_type.upper(),
                "status": machine.status,
                "zone": machine.zone,
                "battery": machine.battery_percent,
            }
            for machine in world.machines
        },
        "people": {
            person.person_id: {
                "role": person.role,
                "status": person.status,
                "zone": person.zone,
            }
            for person in world.people
        },
        "newTasksFrozen": world.new_tasks_frozen,
    }


def _event_record(event: ObservabilityEvent) -> dict[str, Any]:
    facts = {fact.name: fact.value for fact in event.facts}
    return {
        "record_type": "event",
        "schema_version": TRACE_SCHEMA_VERSION,
        "event": {
            "sequence": event.sequence,
            "phase": event.title.upper(),
            "sender": event.sender or "runtime",
            "recipient": event.recipient or "runtime_observer",
            "type": event.kind,
            "summary": event.summary,
            "worldVersion": event.world_version,
            "orgVersion": event.org_version,
            "mode": "EMERGENCY" if event.org_version > 1 else "NORMAL",
            "status": event.status,
            "payload": facts,
            "result": event.summary,
            "timestamp": event.timestamp.isoformat(),
            "statePatch": _state_patch(facts),
        },
    }


def _state_patch(facts: dict[str, Any]) -> dict[str, Any]:
    command_type = facts.get("command_type") or facts.get("action_type")
    target_id = facts.get("target_id")
    if command_type == CommandType.FREEZE_NEW_TASKS.value:
        return {"newTasksFrozen": True}
    if command_type == CommandType.ALERT_PERSON.value and target_id:
        return {"people": {target_id: {"status": "alerted"}}}
    machine_patch = {
        CommandType.PAUSE_MACHINE.value: {"status": "paused"},
        CommandType.TRACK_PERSON.value: {"status": "tracking_person"},
        CommandType.HOLD_POSITION.value: {"status": "holding"},
        CommandType.RETURN_TO_BASE.value: {"status": "idle", "zone": "maintenance_base"},
        CommandType.RECALL_DRONE.value: {"status": "idle", "zone": "maintenance_base"},
    }.get(command_type)
    if target_id and machine_patch:
        return {"devices": {target_id: machine_patch}}
    return {}
