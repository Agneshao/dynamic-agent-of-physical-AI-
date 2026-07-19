"""Pure-local end-to-end thunderstorm response demonstration."""

from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

from runtime_core.adapters.mock_adapter import MockSimulatorAdapter
from runtime_core.audit.ledger import AuditLedger
from runtime_core.coordination.proposal_board import ProposalBoard
from runtime_core.demo.stub_planners import (
    EmergencyStubPlanner,
    NormalOperationsStubPlanner,
)
from runtime_core.execution.proposal_execution import execute_approved_proposal
from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.policies.emergency_fast_path import EmergencyFastPath
from runtime_core.schemas.approval import ApprovalDecision, approve_proposal
from runtime_core.schemas.audit import AuditRecord
from runtime_core.schemas.commands import Command, CommandResult
from runtime_core.schemas.events import Event, EventSeverity
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.proposals import Proposal, ProposalAdmissionResult
from runtime_core.schemas.world_state import (
    FrozenWorldState,
    MachineState,
    PersonState,
    WeatherState,
    WorldState,
    ZoneState,
)
from runtime_core.world.snapshot_manager import SnapshotManager
from runtime_core.world.state_kernel import WorldStateKernel


class ThunderstormDemoResult(BaseModel):
    """Immutable summary of one complete local thunderstorm scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_world_version: int
    final_world_version: int
    initial_org_version: int
    final_org_version: int
    initial_mode: OperatingMode
    final_mode: OperatingMode
    fast_path_commands: tuple[Command, ...]
    fast_path_results: tuple[CommandResult, ...]
    normal_proposal: Proposal
    stale_submission_world_version: int
    stale_proposal_result: ProposalAdmissionResult
    emergency_proposal: Proposal
    emergency_proposal_result: ProposalAdmissionResult
    emergency_validation_result: ProposalAdmissionResult
    approval_decision: ApprovalDecision
    command_results: tuple[CommandResult, ...]
    final_world_state: FrozenWorldState
    audit_records: tuple[AuditRecord, ...]
    audit_log_path: Path


def run_thunderstorm_demo(
    *,
    auto_approve: bool = True,
    audit_path: Optional[Path] = None,
) -> ThunderstormDemoResult:
    """Run the deterministic scenario without network or model dependencies."""
    timestamp = datetime.now(timezone.utc)
    incident_id = "thunderstorm-demo-001"
    resolved_audit_path = audit_path or (
        Path(tempfile.mkdtemp(prefix="golf-runtime-demo-")) / "audit.jsonl"
    )
    world_kernel = WorldStateKernel(_initial_world_state(timestamp))
    snapshot_manager = SnapshotManager(world_kernel)
    ledger = AuditLedger(resolved_audit_path)
    mode_manager = ModeManager(
        ledger, world_version_provider=world_kernel.get_world_version
    )
    proposal_board = ProposalBoard(world_kernel, mode_manager, ledger)
    adapter = MockSimulatorAdapter()
    executor = SimpleExecutor(world_kernel, mode_manager, adapter)
    fast_path = EmergencyFastPath(executor, world_kernel, mode_manager)

    initial_world_version = world_kernel.get_world_version()
    initial_organization = mode_manager.get_current_organization()

    thunderstorm = Event(
        event_type="weather.updated",
        source="mock_weather_station",
        severity=EventSeverity.CRITICAL,
        deduplication_key=f"{incident_id}:weather",
        payload=WeatherState(
            condition="thunderstorm",
            lightning_distance_km=2.5,
            wind_speed_mps=18.0,
            precipitation_level=0.9,
            updated_at=timestamp,
        ).model_dump(mode="python"),
    )
    world_kernel.apply_event(thunderstorm)

    fast_path_snapshot = snapshot_manager.create_snapshot()
    fast_path_result = fast_path.execute(
        fast_path_snapshot,
        incident_id=incident_id,
        severity=thunderstorm.severity,
    )

    normal_snapshot = snapshot_manager.create_snapshot()
    normal_proposal = NormalOperationsStubPlanner().create_proposal(
        normal_snapshot,
        mode_manager.get_current_organization(),
    )

    mode_manager.transition(
        OperatingMode.EMERGENCY,
        reason="thunderstorm safety threshold reached",
        triggered_by="mock_weather_station",
    )
    stale_submission_world_version = world_kernel.get_world_version()
    if normal_proposal.world_version != stale_submission_world_version:
        raise RuntimeError("demo invariant failed: world changed before stale submission")
    stale_result = proposal_board.submit(normal_proposal)

    emergency_snapshot = snapshot_manager.create_snapshot()
    emergency_organization = mode_manager.get_current_organization()
    emergency_proposal = EmergencyStubPlanner().create_proposal(
        emergency_snapshot,
        emergency_organization,
    )
    emergency_result = proposal_board.submit(emergency_proposal)
    emergency_validation = proposal_board.validate_for_use(
        emergency_proposal.proposal_id
    )

    approval = approve_proposal(
        emergency_proposal.proposal_id,
        approved=auto_approve,
        approved_by="demo_operator",
        reason=(
            "approved deterministic emergency response"
            if auto_approve
            else "operator rejected follow-up movement"
        ),
    )
    command_results: tuple[CommandResult, ...] = ()
    if approval.approved:
        command_results = execute_approved_proposal(
            proposal=emergency_proposal,
            approval=approval,
            proposal_board=proposal_board,
            mode_manager=mode_manager,
            world_kernel=world_kernel,
            executor=executor,
            incident_id=incident_id,
        )

    final_state = FrozenWorldState.from_world_state(
        world_kernel.get_current_state()
    )
    final_organization = mode_manager.get_current_organization()
    return ThunderstormDemoResult(
        initial_world_version=initial_world_version,
        final_world_version=world_kernel.get_world_version(),
        initial_org_version=initial_organization.org_version,
        final_org_version=final_organization.org_version,
        initial_mode=initial_organization.mode,
        final_mode=final_organization.mode,
        fast_path_commands=fast_path_result.commands,
        fast_path_results=fast_path_result.command_results,
        normal_proposal=normal_proposal,
        stale_submission_world_version=stale_submission_world_version,
        stale_proposal_result=stale_result,
        emergency_proposal=emergency_proposal,
        emergency_proposal_result=emergency_result,
        emergency_validation_result=emergency_validation,
        approval_decision=approval,
        command_results=command_results,
        final_world_state=final_state,
        audit_records=ledger.read_all(),
        audit_log_path=resolved_audit_path,
    )


def _initial_world_state(timestamp: datetime) -> WorldState:
    return WorldState(
        timestamp=timestamp,
        zones={
            "zone_A": ZoneState(zone_id="zone_A"),
            "zone_B": ZoneState(
                zone_id="zone_B", occupied_by_people=["player_1"]
            ),
            "zone_C": ZoneState(zone_id="zone_C"),
            "zone_D": ZoneState(zone_id="zone_D"),
            "maintenance_base": ZoneState(zone_id="maintenance_base"),
        },
        people={
            "player_1": PersonState(
                person_id="player_1",
                role="player",
                zone="zone_B",
                status="active",
                last_updated_at=timestamp,
            )
        },
        machines={
            "mower_1": MachineState(
                machine_id="mower_1",
                machine_type="mower",
                zone="zone_B",
                status="mowing",
                battery_percent=82.0,
                last_updated_at=timestamp,
            ),
            "mower_2": MachineState(
                machine_id="mower_2",
                machine_type="mower",
                zone="zone_D",
                status="mowing",
                battery_percent=76.0,
                last_updated_at=timestamp,
            ),
            "drone_1": MachineState(
                machine_id="drone_1",
                machine_type="drone",
                zone="zone_C",
                status="patrolling",
                battery_percent=68.0,
                last_updated_at=timestamp,
            ),
        },
        weather=WeatherState(condition="clear", updated_at=timestamp),
        new_tasks_frozen=False,
    )


def _print_result(result: ThunderstormDemoResult) -> None:
    print("INITIAL STATE")
    print("THUNDERSTORM DETECTED")
    print("FAST PATH EXECUTED")
    print("NORMAL PROPOSAL CREATED")
    print(
        "ORGANIZATION SWITCHED: "
        f"org_version {result.initial_org_version} -> {result.final_org_version}"
    )
    print(
        "OLD PROPOSAL REJECTED: "
        f"{result.stale_proposal_result.rejection_code.value}"
    )
    print("EMERGENCY PROPOSAL ACCEPTED")
    print(
        "HUMAN APPROVAL: "
        f"{'APPROVED' if result.approval_decision.approved else 'REJECTED'}"
    )
    print("COMMANDS EXECUTED" if result.command_results else "COMMANDS SKIPPED")
    print("FINAL STATE")
    mower_1 = result.final_world_state.get_machine("mower_1")
    mower_2 = result.final_world_state.get_machine("mower_2")
    drone_1 = result.final_world_state.get_machine("drone_1")
    print(f"mower_1 status: {mower_1.status}")
    print(f"mower_2 location: {mower_2.zone}")
    print(f"drone_1 location: {drone_1.zone}")
    print(f"new_tasks_frozen: {result.final_world_state.new_tasks_frozen}")
    print(
        "world_version: "
        f"{result.initial_world_version} -> {result.final_world_version}"
    )
    print(
        "org_version: "
        f"{result.initial_org_version} -> {result.final_org_version}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local thunderstorm demo")
    parser.add_argument(
        "--reject",
        action="store_true",
        help="reject the emergency proposal instead of auto-approving it",
    )
    args = parser.parse_args()
    _print_result(run_thunderstorm_demo(auto_approve=not args.reject))


if __name__ == "__main__":
    main()
