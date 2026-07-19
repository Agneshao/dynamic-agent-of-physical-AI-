"""Tests for versioned single-command execution and kernel synchronization."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from runtime_core.adapters.mock_adapter import MockSimulatorAdapter
from runtime_core.audit.ledger import AuditLedger
from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.commands import Command, CommandStatus, CommandType
from runtime_core.schemas.evidence import EvidenceKind
from runtime_core.schemas.organization import OperatingMode
from runtime_core.schemas.world_state import MachineState, WorldState
from runtime_core.world.state_kernel import WorldStateKernel


FIXED_TIME = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def make_world_state() -> WorldState:
    return WorldState(
        machines={
            "mower_1": MachineState(
                machine_id="mower_1",
                machine_type="mower",
                zone="zone_B",
                status="mowing",
                battery_percent=82.0,
                last_updated_at=FIXED_TIME,
            ),
            "mower_2": MachineState(
                machine_id="mower_2",
                machine_type="mower",
                zone="zone_D",
                status="mowing",
                battery_percent=76.0,
                last_updated_at=FIXED_TIME,
            ),
            "drone_1": MachineState(
                machine_id="drone_1",
                machine_type="drone",
                zone="zone_C",
                status="patrolling",
                battery_percent=68.0,
                last_updated_at=FIXED_TIME,
            ),
        }
    )


def make_runtime(tmp_path, *, adapter=None):
    kernel = WorldStateKernel(make_world_state())
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    manager = ModeManager(ledger, world_version_provider=kernel.get_world_version)
    mock = adapter or MockSimulatorAdapter(clock=lambda: FIXED_TIME)
    executor = SimpleExecutor(kernel, manager, mock, clock=lambda: FIXED_TIME)
    return kernel, manager, mock, executor


def make_command(
    kernel: WorldStateKernel,
    manager: ModeManager,
    *,
    incident_id: str = "storm-1",
    command_type: CommandType = CommandType.PAUSE_MACHINE,
    target_id: str = "mower_1",
    world_version=None,
    org_version=None,
) -> Command:
    return Command(
        command_id=uuid4(),
        incident_id=incident_id,
        idempotency_key=f"{incident_id}:{command_type.value}:{target_id}",
        command_type=command_type,
        target_id=target_id,
        source="test",
        world_version=(
            kernel.get_world_version() if world_version is None else world_version
        ),
        org_version=(
            manager.get_current_organization().org_version
            if org_version is None
            else org_version
        ),
        created_at=FIXED_TIME,
    )


def test_verified_machine_effect_is_written_to_kernel(tmp_path) -> None:
    kernel, manager, adapter, executor = make_runtime(tmp_path)
    before = kernel.get_world_version()
    command = make_command(kernel, manager)

    result = executor.execute(command)

    assert result.status == CommandStatus.VERIFIED
    assert kernel.get_current_state().machines["mower_1"].status == "paused"
    assert kernel.get_world_version() > before
    assert adapter.get_state()["machines"]["mower_1"]["status"] == "paused"
    assert result.evidence[-1].kind == EvidenceKind.KERNEL_SYNC


def test_stale_world_command_never_reaches_adapter(tmp_path) -> None:
    kernel, manager, adapter, executor = make_runtime(tmp_path)
    command = make_command(kernel, manager, world_version=99)

    result = executor.execute(command)

    assert result.status == CommandStatus.FAILED
    assert result.message == "STALE_WORLD_VERSION"
    assert adapter.get_execution_count(command.idempotency_key) == 0


def test_stale_organization_command_never_reaches_adapter(tmp_path) -> None:
    kernel, manager, adapter, executor = make_runtime(tmp_path)
    old_org_version = manager.get_current_organization().org_version
    manager.transition(
        OperatingMode.EMERGENCY,
        reason="storm",
        triggered_by="weather_monitor",
    )
    command = make_command(kernel, manager, org_version=old_org_version)

    result = executor.execute(command)

    assert result.status == CommandStatus.FAILED
    assert result.message == "STALE_ORGANIZATION_VERSION"
    assert adapter.get_execution_count(command.idempotency_key) == 0


def test_same_incident_action_is_idempotent_but_new_incident_executes(tmp_path) -> None:
    kernel, manager, adapter, executor = make_runtime(tmp_path)
    first = make_command(kernel, manager)
    first_result = executor.execute(first)
    version_after_first = kernel.get_world_version()
    repeated = make_command(kernel, manager)

    repeated_result = executor.execute(repeated)
    new_incident = make_command(kernel, manager, incident_id="storm-2")
    new_result = executor.execute(new_incident)

    assert repeated_result == first_result
    assert adapter.get_execution_count(first.idempotency_key) == 1
    assert adapter.get_execution_count(new_incident.idempotency_key) == 1
    assert new_result.status == CommandStatus.VERIFIED
    assert kernel.get_world_version() == version_after_first


def test_no_response_is_unknown_and_not_synchronized(tmp_path) -> None:
    adapter = MockSimulatorAdapter(
        no_response_command_types=(CommandType.PAUSE_MACHINE,),
        clock=lambda: FIXED_TIME,
    )
    kernel, manager, adapter, executor = make_runtime(tmp_path, adapter=adapter)
    command = make_command(kernel, manager)

    result = executor.execute(command)

    assert result.status == CommandStatus.UNKNOWN
    assert adapter.get_state()["machines"]["mower_1"]["status"] == "paused"
    assert kernel.get_current_state().machines["mower_1"].status == "mowing"


def test_adapter_success_with_kernel_sync_failure_is_unknown(
    tmp_path, monkeypatch
) -> None:
    kernel, manager, adapter, executor = make_runtime(tmp_path)
    command = make_command(kernel, manager)

    def fail_sync(machine):
        raise RuntimeError("kernel storage unavailable")

    monkeypatch.setattr(kernel, "update_machine", fail_sync)

    result = executor.execute(command)

    assert result.status == CommandStatus.UNKNOWN
    assert "ADAPTER_EXECUTED_KERNEL_SYNC_FAILED" in result.message
    assert adapter.get_state()["machines"]["mower_1"]["status"] == "paused"
    assert kernel.get_current_state().machines["mower_1"].status == "mowing"
    assert result.evidence[-1].kind == EvidenceKind.KERNEL_SYNC_FAILED
    assert any(
        fact.name == "kernel_sync_error" for fact in result.evidence[-1].facts
    )


def test_freeze_new_tasks_synchronizes_runtime_flag(tmp_path) -> None:
    kernel, manager, _, executor = make_runtime(tmp_path)
    command = make_command(
        kernel,
        manager,
        command_type=CommandType.FREEZE_NEW_TASKS,
        target_id="runtime",
    )

    result = executor.execute(command)

    assert result.status == CommandStatus.VERIFIED
    assert kernel.get_current_state().new_tasks_frozen is True
