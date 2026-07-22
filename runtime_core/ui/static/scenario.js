"use strict";

// Mock Isaac signals and runtime decisions. This object can later be replaced
// by a normalized runtime_trace.jsonl + Isaac telemetry adapter.
window.GOLF_RUNTIME_DEMO = {
  incidentId: "NO ACTIVE INCIDENT",
  emergencyIncidentId: "WX-0721-A",
  initialCursor: 0,
  approvalStepId: "approval",
  roles: {
    normal: ["supervisor", "safety", "operations", "maintenance", "resource", "communication"],
    emergency: ["incident_commander", "safety", "operations", "communication"]
  },
  roleLabels: {
    supervisor: "Supervisor",
    incident_commander: "Incident Commander",
    safety: "Safety",
    operations: "Operations",
    maintenance: "Maintenance",
    resource: "Resource",
    communication: "Communication"
  },
  initialDevices: {
    mower_1: { type: "MOWER", status: "MOWING", zone: "FAIRWAY B", battery: 82, x: 28, y: 57 },
    mower_2: { type: "MOWER", status: "MOWING", zone: "FAIRWAY D", battery: 76, x: 69, y: 68 },
    drone_1: { type: "DRONE", status: "PATROL", zone: "ZONE C", battery: 68, x: 62, y: 30 },
    player_1: { type: "PERSON", status: "PLAYING", zone: "FAIRWAY B", battery: null, x: 35, y: 52 }
  },
  initialHazards: {
    irrigation_leak_c: {
      type: "IRRIGATION_LEAK",
      active: false,
      discovered: false,
      zone: "FAIRWAY C",
      x: 56,
      y: 39,
      radius: 12,
      clearance: "PENDING_MAINTENANCE_INSPECTION"
    }
  },
  steps: [
    {
      id: "daily", label: "日常运营", mode: "NORMAL", worldVersion: 10, orgVersion: 1,
      title: "早班任务正常运行", detail: "两台割草机作业，无人机执行例行巡检。",
      route: "DailyScheduler → Operations", clock: "13:54:00.000", lightningKm: 42.0,
      chat: "早班运行检查完成：两台割草机正在计划区域作业，无人机开始第 3 轮例行巡检，当前没有活动事故。",
      chatTags: ["DAILY OPS", "ALL SYSTEMS NORMAL"],
      evidence: { source: "daily_scheduler", result: "SHIFT ACTIVE", detail: "3 machines online · no incident" }
    },
    {
      id: "inspection", label: "无人机巡检", mode: "NORMAL", worldVersion: 11, orgVersion: 1,
      title: "发现灌溉阀异常", detail: "drone_1 在 Zone C / COURSE(56,39) 发现漏水维修点。",
      route: "drone_1 → WorldStateKernel", clock: "13:56:18.240", lightningKm: 39.5,
      statePatch: { drone_1: { status: "INSPECTING", x: 56, y: 39 } },
      chat: "巡检告示：drone_1 在 ZONE C、COURSE(56,39) 发现灌溉阀渗漏；图像、坐标与置信度已实时上报。未发现人员安全风险。",
      chatTags: ["MAINTENANCE POINT", "ZONE C", "POS 56,39"],
      evidence: { source: "drone_1_vision", result: "ANOMALY FOUND", detail: "irrigation valve leak · COURSE(56,39) · confidence 0.94" }
    },
    {
      id: "daily_proposal", label: "日常协作", mode: "NORMAL", worldVersion: 12, orgVersion: 1,
      title: "维修任务已排入队列", detail: "Maintenance 接受低风险维修 Proposal。",
      route: "Operations → Maintenance → ProposalBoard", clock: "13:56:19.100", lightningKm: 39.5,
      statePatch: { drone_1: { status: "PATROL", x: 62, y: 30 } },
      chat: "Maintenance Agent 已接收巡检证据，维修任务 maintenance-204 排入 15:30 队列，日常割草任务继续。",
      chatTags: ["PROPOSAL ACCEPTED", "NORMAL ORG"],
      evidence: { source: "proposal_board", result: "MAINTENANCE QUEUED", detail: "task maintenance-204 · org v1" }
    },
    {
      id: "storm_event", label: "天气事件", mode: "NORMAL", worldVersion: 13, orgVersion: 1,
      title: "强雷暴预警进入 Runtime", detail: "雷暴预计 8 分钟后进入球场。",
      route: "WeatherSource → WorldStateKernel", clock: "14:22:08.000", lightningKm: 6.8,
      chat: "紧急告示：气象源报告强雷暴预计 8 分钟后进入球场。Fairway B 仍有 1 名人员，两台割草机正在作业。",
      chatTags: ["NEW INCIDENT", "ETA 8 MIN", "PERSON EXPOSED"],
      evidence: { source: "weather_station_03", result: "WEATHER W13", detail: "wind 14.7 m/s · lightning 6.8 km" }
    },
    {
      id: "risk", label: "风险判断", mode: "NORMAL", worldVersion: 13, orgVersion: 1,
      title: "安全风险达到 CRITICAL", detail: "人员暴露与运行设备需要立即处理。",
      route: "Safety Agent → Incident Predictor", clock: "14:22:08.180", lightningKm: 6.8,
      chat: "Safety Agent 判断风险为 CRITICAL：人员需撤离，割草机需暂停，无人机应保留用于人员追踪。",
      chatTags: ["RISK CRITICAL", "FAST PATH READY"],
      evidence: { source: "safety_agent", result: "RISK CRITICAL", detail: "person exposure · equipment active" }
    },
    {
      id: "recommend", label: "组织建议", mode: "NORMAL", worldVersion: 13, orgVersion: 1,
      title: "最小紧急组织已生成", detail: "等待工作人员确认控制面切换。",
      route: "OrganizationSelector → ModeManager", clock: "14:22:08.320", lightningKm: 6.8,
      chat: "建议切换到最小紧急组织：激活 Incident Commander，保留 Safety、Operations、Communication，暂停其余日常角色。",
      chatTags: ["PLAN READY", "4 ACTIVE ROLES"],
      evidence: { source: "organization_selector", result: "PLAN READY", detail: "4 active roles · 3 suspended" }
    },
    {
      id: "approval", label: "人工授权", mode: "NORMAL", worldVersion: 13, orgVersion: 1,
      title: "等待工作人员决策", detail: "ModeManager 尚未发布新 OrganizationState。",
      route: "Golf Runtime Agent → course_operator_01", clock: "14:22:08.420", lightningKm: 6.8,
      chat: "组织建议和执行范围已准备完成。请确认是否进入紧急模式。",
      chatTags: ["HUMAN AUTH REQUIRED", "NO MUTATION YET"],
      evidence: { source: "approval_gate", result: "WAITING", detail: "no control-plane mutation" }
    },
    {
      id: "reconfigure", label: "组织重构", mode: "EMERGENCY", worldVersion: 13, orgVersion: 2,
      title: "授权审计并切换组织", detail: "人工授权 Policy 审计成功后，ModeManager 发布 org v2。",
      route: "Operator → AuthorizationPolicy → AuditLedger → ModeManager", clock: "14:22:09.060", lightningKm: 6.4,
      chat: "人工授权已由 EmergencyModeAuthorizationPolicy 验证并写入 AuditLedger。ModeManager 已将组织从 NORMAL 原子切换为 EMERGENCY / org v2。",
      chatTags: ["HUMAN AUTH AUDITED", "POLICY PASSED", "ORG v2"],
      evidence: { source: "emergency_mode_authorization_policy", result: "AUTHORIZATION COMMITTED", detail: "course_operator_01 · HUMAN_OPERATOR · org transition allowed" }
    },
    {
      id: "location_sweep", label: "位置排查", mode: "EMERGENCY", worldVersion: 13, orgVersion: 2,
      title: "确认人员与设备初始位置", detail: "Safety 与 Operations 并行核对现场目标。",
      route: "Incident Commander → Safety / Operations → Sensor Bridge", clock: "14:22:09.420", lightningKm: 6.2,
      chat: "首轮位置排查：player_1 位于 FAIRWAY B；mower_1 位于 FAIRWAY B；mower_2 位于 FAIRWAY D；drone_1 位于 ZONE C。人员尚未进入避险点。",
      chatTags: ["POSITION REPORT 01", "1 PERSON EXPOSED", "2 MOWERS ACTIVE"],
      evidence: { source: "safety_operations_position_check", result: "POSITIONS CONFIRMED", detail: "player_1:B · mower_1:B · mower_2:D · drone_1:C" }
    },
    {
      id: "collaboration", label: "Agent 会商", mode: "EMERGENCY", worldVersion: 13, orgVersion: 2,
      title: "生成紧急处置方案", detail: "Safety、Operations、Communication 汇总位置证据。",
      route: "Safety / Operations / Communication → Incident Commander", clock: "14:22:09.740", lightningKm: 6.1,
      chat: "多 Agent 会商完成：立即通知 player_1 撤离；mower_1、mower_2 分别返回休息泊位；drone_1 先定位人员，再沿疏散路线护送至休息区。",
      chatTags: ["3 AGENT REPORTS", "PLAN READY", "BOUND W13/O2"],
      evidence: { source: "agent_harness", result: "3 REPORTS", detail: "human evacuation · mower safety · communication plan" }
    },
    {
      id: "proposal", label: "紧急 Proposal", mode: "EMERGENCY", worldVersion: 13, orgVersion: 2,
      title: "处置 Proposal 通过版本门", detail: "人员告警、设备控制与持续追踪获得准入。",
      route: "Incident Commander → ProposalBoard", clock: "14:22:10.260", lightningKm: 5.7,
      chat: "ProposalBoard 已接受 emergency-response-01：版本绑定 world v13 / org v2，允许下发人员告警、设备停止与持续位置核验指令。",
      chatTags: ["PROPOSAL ACCEPTED", "VERSION MATCH", "EXECUTION READY"],
      evidence: { source: "proposal_board", result: "ACCEPTED", detail: "world v13 · org v2 · continuous verification required" }
    },
    {
      id: "intervention", label: "紧急干预", mode: "EMERGENCY", worldVersion: 17, orgVersion: 2,
      title: "人员撤离与设备安全动作", detail: "SimpleExecutor 执行并逐项验证四项动作。",
      route: "Incident Commander → SimpleExecutor ↔ IsaacSimulatorAdapter", clock: "14:22:11.160", lightningKm: 5.5,
      statePatch: {
        mower_1: { status: "RETURNING", zone: "SERVICE ROAD" },
        mower_2: { status: "RETURNING", zone: "SERVICE ROAD", x: 74, y: 74 },
        drone_1: { status: "LOCATING PERSON", x: 39, y: 43 },
        player_1: { status: "EVACUATING", x: 44, y: 46 }
      },
      chat: "首轮干预已验证：player_1 开始撤离；两台割草机正沿 SERVICE ROAD 返回休息泊位；drone_1 正在定位人员。",
      chatTags: ["4 COMMANDS VERIFIED", "WORLD v17", "RECHECK REQUIRED"],
      evidence: { source: "simple_executor/isaac_adapter", result: "INTERVENTION VERIFIED", detail: "person evacuating · both mowers returning · drone locating person" }
    },
    {
      id: "position_recheck", label: "位置复核", mode: "EMERGENCY", worldVersion: 18, orgVersion: 2,
      title: "干预过程中再次确认位置", detail: "Sensor Bridge 回传人员与割草机最新位置。",
      route: "Sensor Bridge → Safety / Operations → Incident Commander", clock: "14:22:12.020", lightningKm: 5.3,
      statePatch: {
        mower_1: { status: "RETURNING", zone: "SERVICE ROAD", x: 76, y: 78 },
        mower_2: { status: "RETURNING", zone: "SERVICE ROAD", x: 78, y: 78 },
        drone_1: { status: "TRACKING PERSON", zone: "FAIRWAY B", x: 43, y: 45 },
        player_1: { status: "EVACUATING", zone: "EVACUATION ROUTE", x: 50, y: 51 }
      },
      chat: "位置复核 02：player_1 已进入 EVACUATION ROUTE；两台割草机位于 SERVICE ROAD；drone_1 已确认人员位置并保持跟随。",
      chatTags: ["POSITION REPORT 02", "PERSON MOVING", "MOWERS CONFIRMED"],
      evidence: { source: "sensor_bridge_position_recheck", result: "POSITIONS UPDATED", detail: "player route · both mowers returning · drone tracking" }
    },
    {
      id: "shelter_verified", label: "到达确认", mode: "EMERGENCY", worldVersion: 19, orgVersion: 2,
      title: "人员到达避险点并确认设备状态", detail: "Safety 完成人员闭环，Operations 完成设备复核。",
      route: "Drone / Equipment Telemetry → Safety / Operations → Incident Commander", clock: "14:22:12.880", lightningKm: 5.2,
      statePatch: {
        mower_1: { status: "PARKED", zone: "MAINTENANCE", x: 76, y: 82 },
        mower_2: { status: "PARKED", zone: "MAINTENANCE", x: 82, y: 82 },
        drone_1: { status: "OVERWATCH", zone: "CLUBHOUSE", x: 49, y: 48 },
        player_1: { status: "SHELTERED", zone: "CLUBHOUSE", x: 57, y: 55 }
      },
      chat: "位置确认 03：player_1 已到达休息区，状态 SHELTERED；两台割草机已停入各自休息泊位；drone_1 跟随到达后转为避险点监视。",
      chatTags: ["SHELTER VERIFIED", "MOWERS SAFE", "WORLD v19"],
      evidence: { source: "safety_operations_final_check", result: "SAFETY CLOSED LOOP", detail: "person sheltered · both mowers parked · drone overwatch" }
    }
  ]
};
