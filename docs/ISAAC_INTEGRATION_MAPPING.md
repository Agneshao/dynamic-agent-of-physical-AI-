# Isaac Integration Mapping

This document maps the external Isaac Phase 3E runtime to the Physical AI
multi-agent runtime ownership model. It is intentionally a mapping document
only; it does not define implementation code.

## 1. Source-of-truth table

| State or artifact | Sole owner | Isaac Phase 3E field or source | Mapping rule |
| --- | --- | --- | --- |
| `world_version` | `WorldStateKernel` | Existing Phase 3E scripts currently mutate `world_version` during storm, weather-clear, repair approval, and partial recovery flows. | In the target runtime, only `WorldStateKernel` may increment or publish `world_version`. Isaac and browser clients may only echo an observed/base value. |
| `org_version` | `ModeManager` | Existing Phase 3E scripts use `organization_version`. | Treat `organization_version` as the legacy field name for `org_version`; only `ModeManager` may increment it. |
| `plan_version` | Runtime planning authority, not `WorldStateKernel` | `plan_version` | `plan_version` is its own planning epoch. Do not treat it as `world_version`, do not derive it from `world_version`, and do not allow Isaac/browser code to increment it. The concrete target owner class is not visible in this repository. |
| `OperatingMode` | `ModeManager` | Implied by `organization_mode` values such as `NORMAL`, `EMERGENCY_CELL`, `RECOVERY_CELL`, `NORMAL_REPLANNED`. | `OperatingMode` is the canonical runtime enum/state. Mode changes must go through `ModeManager`. |
| `organization_mode` | `ModeManager` | `organization_mode` | Treat as an Isaac/UI projection of canonical `OperatingMode`, not as an independently writable Isaac field. |
| `scenario_state` | Isaac runtime, projected through `IsaacSimulatorAdapter` into runtime observations | `scenario_state` | Isaac owns raw scenario progression. The runtime should consume it as adapter observations/events and project it into canonical world state where appropriate. |
| `pipeline_gate` | Proposal/recovery workflow owner in the runtime, coordinated with `ProposalBoard` and `ModeManager` | `pipeline_gate` | This is workflow state, not physical world truth. It should be changed by admitted runtime transitions, approvals, receipts, and verification outcomes. |
| Weather observation | External sensor/Isaac source until ingested; canonical observation record owned by `WorldStateKernel` | `visual_weather_state`, operator weather injection workflows | Isaac/browser actions may submit sensor events. Once accepted, the canonical weather observation and resulting `world_version` belong to `WorldStateKernel`. |
| Physical entity state and position | `WorldStateKernel` after adapter ingestion; Isaac is the physical/simulation source for measured positions | Entity positions and statuses | Isaac reports positions/statuses through the adapter. Browser clients must not directly modify device coordinates. |
| Verification result | Runtime verification service through `IsaacSimulatorAdapter` evidence; final workflow result recorded by runtime | `verification_result` | Isaac may provide observations and measured outcomes. The runtime records the canonical `VerificationResult` from adapter evidence. |
| Audit and evidence | Runtime audit/evidence store; `IsaacSimulatorAdapter` collects adapter evidence | Existing Phase 3E `inspection_result`, proposal `evidence`, command/verification result fields | Isaac evidence is input material. Runtime-owned audit records must include operator action, proposal ID, command/action ID, base versions, adapter receipt, and verification evidence. |

## 2. Operator input mapping

| Isaac operator workflow | Runtime input type | Existing Runtime component that should receive it | Mapping |
| --- | --- | --- | --- |
| `INJECT_THUNDERSTORM_DATA` | Sensor `Event` | `WorldStateKernel` event ingestion boundary | Submit a weather sensor event, for example `THUNDERSTORM_EMERGENCY`, with Isaac scenario metadata, observed weather state, entity snapshot, base `world_version`, and action ID. StepFun may classify the intent as advisory, but it must not create commands. |
| `INJECT_WEATHER_CLEAR_DATA` | Sensor `Event` or authorized recovery trigger | `WorldStateKernel` for weather observation, then the recovery workflow/ModeManager boundary for any admitted transition | Submit a weather-clear observation. The runtime should validate that the emergency is active and entity safety conditions are satisfied before allowing recovery progression. |
| `APPROVE_CUT_AND_DRAIN` | `ApprovalDecision` for an admitted proposal | `ProposalBoard` | Apply approval only to an admitted `CUT_AND_DRAIN_ZONE_C` proposal with matching `world_version`, `plan_version`, and `org_version`. Approval admits execution; it does not itself execute physical commands. |
| `APPROVE_PARTIAL_RECOVERY` | `ApprovalDecision` or authorized recovery transition | `ProposalBoard` if represented as a proposal; otherwise the runtime recovery transition boundary coordinated with `ModeManager` | If `PARTIAL_RECOVERY` is modeled as a proposal, route approval through `ProposalBoard`. If it is modeled as a mode transition after successful verification, require an authorized transition that is version-checked and recorded in audit. |

Agents may observe events, propose intents, or provide StepFun-classified advice, but agents cannot directly produce or execute `Command` objects.

## 3. Execution mapping

The following physical outcomes become runtime `Command` objects and must pass
through the execution chain:

```text
ProposalBoard
-> Approval
-> SimpleExecutor
-> future IsaacSimulatorAdapter
```

Required command-producing flows:

| Runtime result | Physical command target | Notes |
| --- | --- | --- |
| Emergency storm response after admitted runtime transition | Isaac entity routing/safe-state actions for `Player_01`, `Drone_01`, mowers, and maintenance assets | The current Phase 3E script computes emergency routes directly. In the target runtime, physical route/hold commands must be synchronized by `SimpleExecutor`. |
| Weather-clear recovery inspection | Isaac drone inspection route/action for Zone C | The weather-clear observation is an event; the resulting physical inspection dispatch is a command. |
| Approved `CUT_AND_DRAIN_ZONE_C` proposal | Isaac maintenance dispatch and drainage work | `APPROVE_CUT_AND_DRAIN` should approve an admitted proposal; `SimpleExecutor` sends the resulting command to the adapter. |
| Post-repair observation/verification action | Isaac drone observation or sensor verification command | Any physical observation task must be a command when it causes Isaac action. Pure runtime evaluation may remain a verification step. |
| Approved partial recovery actions, if they move devices or change physical tasks | Isaac task/routing changes for post-storm operations | If partial recovery only changes organization/workflow state, it belongs to `ModeManager`/workflow state. If it moves entities or changes physical tasks, it must become commands. |

`SimpleExecutor` remains the only command execution and synchronization boundary. No
agent, browser component, or adapter caller may bypass it.

## 4. Isaac Adapter boundary

Define a future `IsaacSimulatorAdapter` at the Simulator/Adapter boundary.

Responsibilities:

- Send runtime-approved physical commands to Isaac.
- Receive Isaac execution acknowledgements.
- Verify physical outcomes against command preconditions and expected postconditions.
- Collect evidence including Isaac timestamps, entity positions, statuses, weather state, scenario state, raw acknowledgement payloads, and verification measurements.
- Return `ExecutionReceipt` for command completion or failure.
- Return `VerificationResult` for verified physical outcomes.
- Surface adapter health and heartbeat status to the runtime.

Non-responsibilities:

- It must never increment `world_version`.
- It must never increment `org_version` or mutate `OperatingMode`.
- It must never create proposals.
- It must never approve proposals.
- It must never allow Isaac-side `plan_version` to be confused with `world_version`.
- It must never execute commands that did not come through `SimpleExecutor`.

## 5. File protocol

The JSONL/state files exist only between `IsaacSimulatorAdapter` and the Isaac
script. The browser must never write these files directly.

### Files

| File | Direction | Purpose |
| --- | --- | --- |
| Request JSONL | Runtime adapter -> Isaac script | Append-only command request stream. |
| Result JSONL | Isaac script -> runtime adapter | Append-only acknowledgement, progress, receipt, and verification stream. |
| Runtime state JSON | Isaac script -> runtime adapter, optionally adapter-authored health projection | Latest Isaac scenario projection and heartbeat-readable state. |

### Request JSONL

Each line should be one complete JSON object with:

- `action_id`: stable unique ID for deduplication.
- `command_id`: runtime command ID from `SimpleExecutor`.
- `proposal_id`: proposal that authorized the command, when applicable.
- `command_type`: physical action requested of Isaac.
- `base_world_version`, `base_plan_version`, `base_org_version`: versions validated by the runtime before dispatch.
- `issued_at`: adapter timestamp.
- `payload`: command-specific target, route, entity, zone, and expected outcome data.

### Result JSONL

Each line should be one complete JSON object with:

- `action_id`: copied from the request.
- `command_id`: copied from the request.
- `status`: `ACKNOWLEDGED`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, `REJECTED`, or `MALFORMED`.
- `isaac_elapsed_time`: Isaac `elapsed_time` at result production.
- `scenario_state`: Isaac scenario state snapshot.
- `entity_positions` and `entity_statuses`: measured physical/simulation state.
- `verification_result`: verification payload when applicable.
- `evidence`: structured evidence collected by Isaac.
- `error`: structured error code/message when applicable.

### Runtime state JSON

The runtime state JSON should be a latest-state projection, not an authority for
runtime-owned versions. It may include:

- `scenario_state`
- `elapsed_time`
- `plan_version` as observed/projection only
- `organization_mode` as observed/projection only
- `pipeline_gate` as observed/projection only
- `visual_weather_state`
- `zone_c_overlay_state`
- `verification_result`
- `entity_positions`
- `entity_statuses`
- adapter `heartbeat`
- adapter/Isaac connection status

### Protocol rules

- Action ID deduplication: Isaac must treat repeated `action_id` values as the same requested action and return the prior terminal result when possible.
- Idempotency: adapter retries must be safe. Replayed requests must not duplicate physical work after an action has been acknowledged or completed.
- Heartbeat: Isaac writes heartbeat information with timestamp, Isaac process state, and latest processed offset/action ID. The adapter marks the connection degraded or disconnected when heartbeat age exceeds the configured threshold.
- Stale version rejection: the adapter rejects requests whose base versions do not match the runtime dispatch snapshot. Isaac may also reject stale request metadata defensively, but runtime-owned version authority remains outside Isaac.
- Malformed input handling: malformed JSONL lines must be written to result JSONL as `MALFORMED` when an `action_id` can be recovered; otherwise Isaac records a structured parser error in its own log and continues processing later lines.
- Disconnected Isaac handling: the adapter returns a failed `ExecutionReceipt` or pending/degraded status according to runtime policy. The browser must display live connection loss and must not silently fall back to mock execution.

## 6. UI migration

The current browser-side mock runtime should become:

- Operator action client: sends operator intent to the runtime API, not to JSONL files.
- Read-only runtime projection: renders `worldVersion`, `orgVersion`, `planVersion`, `OperatingMode`/`organization_mode`, `pipeline_gate`, weather, entities, and verification results from runtime state.
- Live connection indicator: displays adapter/Isaac connection state from heartbeat and runtime health.

In live Isaac mode, `app.js` must not:

- Increment `worldVersion` or `orgVersion`.
- Modify device coordinates itself.
- Change operating mode itself.
- Write request JSONL, result JSONL, or runtime state JSON files directly.
- Silently fall back to Mock mode.

Mock mode should be explicit, visibly labeled, and selected only through an
operator-visible configuration or startup choice.

## 7. Minimal implementation file list

Later implementation should be limited to the following repository files unless
the target multi-agent runtime lives in a different checkout:

Files to add:

- `runtime/adapters/isaac_simulator_adapter.py`
- `runtime/adapters/isaac_file_protocol.py`
- `runtime/schemas/isaac_integration.py`
- `tests/test_isaac_simulator_adapter.py`
- `tests/test_isaac_file_protocol.py`

Files to modify:

- `runtime/world_state_kernel.py`
- `runtime/mode_manager.py`
- `runtime/proposal_board.py`
- `runtime/simple_executor.py`
- `runtime/events.py`
- `runtime/approvals.py`
- `runtime/audit.py`
- `web/app.js`

If the current repository remains the implementation target, these paths are
unresolved because the named multi-agent runtime files and `web/app.js` are not
present in this checkout.

## 8. Unresolved questions

- The concrete target owner of `plan_version` cannot be determined from the provided ownership rules or this repository. It must be a planning authority separate from `WorldStateKernel`.
- The repository inspected here contains Phase 3 Python runtime/prototype files, but does not expose the named target components `WorldStateKernel`, `ModeManager`, `ProposalBoard`, `SimpleExecutor`, `StepFun`, or browser `app.js`.
- The exact `scenario_state` enum values are not visible from the provided field name alone.
- The exact mapping between `pipeline_gate` values and target proposal/workflow states needs the target runtime's state machine.
- It is not yet clear whether `APPROVE_PARTIAL_RECOVERY` should always be a `ProposalBoard` proposal or sometimes a ModeManager-authorized recovery transition.
- The canonical `Evidence`, `ExecutionReceipt`, `VerificationResult`, `Command`, `ApprovalDecision`, and sensor `Event` schemas are not visible in this repository.
- The file names and directory layout for the future web/runtime implementation cannot be verified in this checkout; the minimal file list above uses the names implied by the provided ownership model.
