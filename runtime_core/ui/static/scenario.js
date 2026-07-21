"use strict";

// Replace this object with a normalized runtime_trace.jsonl adapter in production.
window.GOLF_RUNTIME_SCENARIO = {
  id: "thunderstorm-demo-001",
  title: "Thunderstorm Emergency Demo",
  initial: {
    mode: "NORMAL",
    worldVersion: 0,
    orgVersion: 1,
    phase: "BASELINE",
    devices: {
      mower_1: { type: "MOWER", status: "mowing", zone: "zone_B", battery: 82 },
      mower_2: { type: "MOWER", status: "mowing", zone: "zone_D", battery: 76 },
      drone_1: { type: "DRONE", status: "patrolling", zone: "zone_C", battery: 68 }
    },
    newTasksFrozen: false
  },
  final: {
    mode: "EMERGENCY",
    worldVersion: 7,
    orgVersion: 2,
    devices: {
      mower_1: { type: "MOWER", status: "holding", zone: "zone_B", battery: 82 },
      mower_2: { type: "MOWER", status: "idle", zone: "maintenance_base", battery: 76 },
      drone_1: { type: "DRONE", status: "idle", zone: "maintenance_base", battery: 68 }
    },
    newTasksFrozen: true
  },
  organization: {
    normal: {
      leader: "supervisor",
      roles: ["supervisor", "safety", "operations", "maintenance", "resource", "communication"],
      reports: [
        ["supervisor", "safety"],
        ["supervisor", "operations"],
        ["supervisor", "maintenance"],
        ["supervisor", "resource"],
        ["supervisor", "communication"]
      ]
    },
    emergency: {
      leader: "incident_commander",
      roles: ["incident_commander", "safety", "operations", "communication"],
      reports: [
        ["incident_commander", "safety"],
        ["incident_commander", "operations"],
        ["incident_commander", "communication"]
      ],
      activated: ["incident_commander"],
      retained: ["safety", "operations", "communication"],
      suspended: ["supervisor", "maintenance", "resource"],
      trigger: "CRITICAL thunderstorm · lightning distance 2.5 km",
      reason: "Immediate safety response requires a smaller command structure with one accountable incident leader.",
      capabilities: ["command", "safety_analysis", "equipment_planning", "notification"],
      selectedRoles: ["incident_commander", "safety", "operations", "communication"]
    }
  },
  proposalRejection: {
    proposalWorldVersion: 5,
    proposalOrgVersion: 1,
    runtimeWorldVersion: 5,
    runtimeOrgVersion: 2,
    result: "REJECTED",
    code: "STALE_ORGANIZATION_VERSION",
    reason: "World facts are unchanged, but the organization authority changed. A NORMAL-org proposal cannot execute under EMERGENCY org_version 2."
  },
  steps: [
    {
      sequence: 1,
      phase: "THUNDERSTORM DETECTED",
      sender: "WeatherSource",
      recipient: "WorldStateKernel",
      type: "WEATHER_EVENT",
      summary: "Critical thunderstorm telemetry enters the authoritative world state.",
      worldVersion: 1,
      orgVersion: 1,
      mode: "NORMAL",
      payload: { condition: "thunderstorm", lightning_distance_km: 2.5, wind_speed_mps: 18.0 },
      result: "WorldStateKernel validates and commits weather.updated."
    },
    {
      sequence: 2,
      phase: "FAST PATH",
      sender: "WorldStateKernel",
      recipient: "EmergencyFastPath",
      type: "CRITICAL_SNAPSHOT",
      summary: "A versioned snapshot exposes the critical weather state.",
      worldVersion: 1,
      orgVersion: 1,
      mode: "NORMAL",
      payload: { severity: "CRITICAL", snapshot_world_version: 1 },
      result: "EmergencyFastPath accepts the incident-bound snapshot."
    },
    {
      sequence: 3,
      phase: "FAST PATH",
      sender: "EmergencyFastPath",
      recipient: "SimpleExecutor",
      type: "SAFETY_COMMANDS",
      summary: "Pause mowers, freeze new tasks, and recall the drone.",
      worldVersion: 1,
      orgVersion: 1,
      mode: "NORMAL",
      payload: { commands: ["pause mower_1", "pause mower_2", "freeze_new_tasks", "recall drone_1"] },
      result: "Four incident-scoped idempotent commands are submitted."
    },
    {
      sequence: 4,
      phase: "FAST PATH VERIFIED",
      sender: "SimpleExecutor",
      recipient: "WorldStateKernel",
      type: "VERIFIED_STATE_SYNC",
      summary: "Verified adapter effects are synchronized into runtime state.",
      worldVersion: 5,
      orgVersion: 1,
      mode: "NORMAL",
      payload: { mower_1: "paused", mower_2: "paused", drone_1: "maintenance_base", new_tasks_frozen: true },
      result: "Kernel commits four real state changes; world_version advances to 5.",
      statePatch: {
        devices: {
          mower_1: { status: "paused" },
          mower_2: { status: "paused" },
          drone_1: { status: "idle", zone: "maintenance_base" }
        },
        newTasksFrozen: true
      }
    },
    {
      sequence: 5,
      phase: "ORGANIZATION SELECTION",
      sender: "MinimalOrganizationSelector",
      recipient: "ModeManager",
      type: "ORGANIZATION_PLAN",
      summary: "Select the minimum role set required for thunderstorm response.",
      worldVersion: 5,
      orgVersion: 1,
      mode: "NORMAL",
      payload: { capabilities: ["command", "safety_analysis", "equipment_planning", "notification"], selected_roles: ["incident_commander", "safety", "operations", "communication"] },
      result: "A recommendation is produced; only ModeManager may publish it."
    },
    {
      sequence: 6,
      phase: "ORGANIZATION SWITCH",
      sender: "ModeManager",
      recipient: "OrganizationState",
      type: "NORMAL_TO_EMERGENCY",
      summary: "Publish the audited EMERGENCY organization atomically.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { activated: ["incident_commander"], retained: ["safety", "operations", "communication"], suspended: ["supervisor", "maintenance", "resource"] },
      result: "NORMAL → EMERGENCY committed. org_version advances from 1 to 2."
    },
    {
      sequence: 7,
      phase: "VERSION GATE",
      sender: "NormalOperationsAgent",
      recipient: "ProposalBoard",
      type: "OLD_PROPOSAL_SUBMIT",
      summary: "The NORMAL operations agent submits its pre-transition proposal.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { proposal_world_version: 5, proposal_org_version: 1, action: "continue_mowing" },
      result: "ProposalBoard compares the proposal with both runtime versions."
    },
    {
      sequence: 8,
      phase: "OLD PROPOSAL REJECTED",
      sender: "ProposalBoard",
      recipient: "NormalOperationsAgent",
      type: "PROPOSAL_REJECTED",
      summary: "Reject the proposal because its organization authority is stale.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      status: "REJECTED",
      payload: { proposal_world_version: 5, current_world_version: 5, proposal_org_version: 1, current_org_version: 2 },
      result: "STALE_ORGANIZATION_VERSION"
    },
    {
      sequence: 9,
      phase: "MULTI-AGENT PLANNING",
      sender: "IncidentCommander",
      recipient: "Safety",
      type: "TASK_ASSIGNMENT",
      summary: "Assess immediate human and machine exposure.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { objective: "analyze_safety", visible_context: ["people", "machines", "zones", "weather"] },
      result: "Safety agent starts analysis under the EMERGENCY organization binding."
    },
    {
      sequence: 10,
      phase: "MULTI-AGENT PLANNING",
      sender: "Safety",
      recipient: "IncidentCommander",
      type: "SAFETY_REPORT",
      summary: "Zone B is occupied; mower_1 must hold position.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { occupied_zones: ["zone_B"], unsafe_machines: ["mower_1"], required_holds: ["mower_1"], confidence: 0.98 },
      result: "Structured SafetyReport returned; no command is emitted."
    },
    {
      sequence: 11,
      phase: "MULTI-AGENT PLANNING",
      sender: "IncidentCommander",
      recipient: "Operations",
      type: "TASK_ASSIGNMENT",
      summary: "Create bounded equipment actions from safety evidence.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { dependency: "SafetyReport", objective: "equipment_planning" },
      result: "Operations receives the validated safety dependency."
    },
    {
      sequence: 12,
      phase: "MULTI-AGENT PLANNING",
      sender: "Operations",
      recipient: "IncidentCommander",
      type: "OPERATIONS_PLAN",
      summary: "Hold mower_1 and return mower_2 to maintenance base.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { actions: ["hold_position:mower_1", "return_to_base:mower_2"], confidence: 0.96 },
      result: "Structured OperationsPlan returned; execution has not started."
    },
    {
      sequence: 13,
      phase: "MULTI-AGENT PLANNING",
      sender: "IncidentCommander",
      recipient: "Communication",
      type: "TASK_ASSIGNMENT",
      summary: "Prepare the operator notification plan.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { objective: "notify_operator", operator_target: "operator_1" },
      result: "Communication receives incident context without execution privileges."
    },
    {
      sequence: 14,
      phase: "MULTI-AGENT PLANNING",
      sender: "Communication",
      recipient: "IncidentCommander",
      type: "NOTIFICATION_PLAN",
      summary: "Notify operator_1 that emergency posture is active.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { recipients: ["operator_1"], category: "EMERGENCY_RESPONSE" },
      result: "Structured NotificationPlan returned."
    },
    {
      sequence: 15,
      phase: "PROPOSAL COMPOSITION",
      sender: "IncidentCommander",
      recipient: "ProposalBoard",
      type: "EMERGENCY_PROPOSAL",
      summary: "Compose all departmental outputs into one emergency proposal.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { evidence: ["SafetyReport", "OperationsPlan", "NotificationPlan"], actions: ["hold_position", "return_to_base", "notify_operator"] },
      result: "IncidentCommander submits a Proposal, never a Command."
    },
    {
      sequence: 16,
      phase: "PROPOSAL ACCEPTED",
      sender: "ProposalBoard",
      recipient: "IncidentCommander",
      type: "PROPOSAL_ACCEPTED",
      summary: "Accept the emergency proposal against world v5 and org v2.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      status: "ACCEPTED",
      payload: { checked_world_version: 5, checked_org_version: 2, action_count: 3 },
      result: "Proposal lifecycle status becomes ACCEPTED."
    },
    {
      sequence: 17,
      phase: "HUMAN APPROVAL",
      sender: "Operator",
      recipient: "SimpleExecutor",
      type: "APPROVAL_DECISION",
      summary: "Approve the admitted emergency response.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      status: "APPROVED",
      payload: { approved: true, approved_by: "demo_operator" },
      result: "Execution may now materialize version-bound Commands."
    },
    {
      sequence: 18,
      phase: "COMMAND EXECUTION",
      sender: "SimpleExecutor",
      recipient: "MockAdapter",
      type: "EXECUTE_AND_VERIFY",
      summary: "Execute actions through the adapter and collect evidence.",
      worldVersion: 5,
      orgVersion: 2,
      mode: "EMERGENCY",
      payload: { commands: ["hold_position:mower_1", "return_to_base:mower_2", "notify_operator:operator_1"] },
      result: "Adapter execution and verification complete."
    },
    {
      sequence: 19,
      phase: "FINAL STATE SYNC",
      sender: "SimpleExecutor",
      recipient: "WorldStateKernel",
      type: "KERNEL_SYNC",
      summary: "Synchronize verified physical effects into authoritative state.",
      worldVersion: 7,
      orgVersion: 2,
      mode: "EMERGENCY",
      status: "VERIFIED",
      payload: { mower_1: "holding", mower_2: "maintenance_base", drone_1: "maintenance_base", new_tasks_frozen: true },
      result: "Final physical state committed at world_version 7.",
      statePatch: {
        devices: {
          mower_1: { status: "holding" },
          mower_2: { status: "idle", zone: "maintenance_base" }
        },
        newTasksFrozen: true
      }
    }
  ]
};
