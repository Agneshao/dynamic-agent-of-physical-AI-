"use strict";

const scenario = window.GOLF_RUNTIME_DEMO;
const initialMessages = [
  {
    role: "system",
    kind: "chat",
    sender: "Golf Runtime Agent",
    time: "13:54:00",
    text: `${scenario.steps[0].chat} 等待工作人员下达下一条工作指令。`,
    tags: scenario.steps[0].chatTags
  }
];

const runtime = {
  cursor: scenario.initialCursor,
  authorized: false,
  deferred: false,
  typing: false,
  timer: null,
  replyTimer: null,
  deviceTimers: [],
  commandQueue: Promise.resolve(),
  generation: 0,
  modelConfigured: false,
  isaacConfigured: false,
  isaacConnected: false,
  isaacPollTimer: null,
  mode: scenario.steps[scenario.initialCursor].mode,
  orgVersion: scenario.steps[scenario.initialCursor].orgVersion,
  incidentActive: false,
  worldVersion: scenario.steps[scenario.initialCursor].worldVersion,
  dynamicEvidence: [],
  activeRoutes: {},
  messages: clone(initialMessages),
  devices: clone(scenario.initialDevices),
  hazards: clone(scenario.initialHazards)
};

const $ = (id) => document.getElementById(id);

function init() {
  $("incidentMetric").textContent = scenario.incidentId;
  $("chatForm").addEventListener("submit", submitChat);
  $("resetButton").addEventListener("click", resetDemo);
  document.querySelectorAll("[data-query]").forEach((button) => {
    button.addEventListener("click", () => sendWorkerMessage(button.dataset.query));
  });
  render();
  checkModelStatus();
  checkIsaacStatus();
  runtime.isaacPollTimer = window.setInterval(checkIsaacStatus, 1000);
}

function submitChat(event) {
  event.preventDefault();
  const text = $("chatInput").value.trim();
  if (!text) return;
  $("chatInput").value = "";
  sendWorkerMessage(text);
}

function sendWorkerMessage(text) {
  runtime.messages.push({
    role: "operator",
    kind: "chat",
    sender: "工作人员",
    time: mockTime(),
    text,
    tags: []
  });
  render();
  const generation = runtime.generation;
  runtime.commandQueue = runtime.commandQueue.then(() => {
    if (generation !== runtime.generation) return undefined;
    return requestBackendReply(text, generation);
  });
}

async function checkModelStatus() {
  try {
    const response = await fetch("/api/model-status", { cache: "no-store" });
    if (!response.ok) throw new Error(`model status failed: ${response.status}`);
    const status = await response.json();
    runtime.modelConfigured = Boolean(status.configured);
    $("modelStatus").textContent = runtime.modelConfigured ? `${status.model} · API CONNECTED` : `${status.model} · NOT CONFIGURED`;
    $("modelConnection").classList.toggle("offline", !runtime.modelConfigured);
  } catch (error) {
    runtime.modelConfigured = false;
    $("modelStatus").textContent = "MODEL STATUS UNAVAILABLE";
    $("modelConnection").classList.add("offline");
  }
}

async function checkIsaacStatus() {
  try {
    const response = await fetch("/api/isaac/state", { cache: "no-store" });
    const state = await response.json();
    runtime.isaacConfigured = Boolean(state.configured);
    applyIsaacState(state);
  } catch (error) {
    runtime.isaacConfigured = false;
    runtime.isaacConnected = false;
  }
  render();
}

function applyIsaacState(state) {
  runtime.isaacConnected = Boolean(state.configured && state.connected);
  Object.entries(state.hazards || {}).forEach(([hazardId, observation]) => {
    const hazard = runtime.hazards[hazardId];
    if (!hazard) return;
    hazard.active = Boolean(observation.active);
    hazard.discovered = Boolean(observation.discovered);
    hazard.clearance = String(observation.clearance || hazard.clearance);
  });
  Object.entries(state.entities || {}).forEach(([deviceId, observation]) => {
    const device = runtime.devices[deviceId];
    if (!device) return;
    device.status = String(observation.status || device.status).toUpperCase();
    const zone = String(observation.zone || device.zone);
    const zoneMatch = zone.match(/^zone_([A-D])$/i);
    device.zone = zoneMatch ? `FAIRWAY ${zoneMatch[1].toUpperCase()}` : zone === "maintenance_base" ? "MAINTENANCE" : zone.toUpperCase();
    if (Array.isArray(observation.position) && observation.position.length >= 2) {
      device.physicalX = roundCoordinate(Number(observation.position[0]));
      device.physicalY = roundCoordinate(Number(observation.position[1]));
      device.x = Math.max(0, Math.min(100, Number(observation.position[0]) + 50));
      device.y = Math.max(0, Math.min(100, 50 - Number(observation.position[1])));
    }
  });
}

async function requestBackendReply(text, generation = runtime.generation) {
  setTyping(true);
  let result;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildChatRequest(text))
    });
    if (!response.ok) throw new Error(`chat request failed: ${response.status}`);
    result = await response.json();
  } catch (error) {
    if (generation !== runtime.generation) return;
    runtime.typing = false;
    await handleMockWorkerMessage(text);
    return;
  }
  if (generation !== runtime.generation) return;
  runtime.typing = false;
  runtime.messages.push({
    role: "system",
    kind: "chat",
    sender: "Golf Runtime Agent",
    time: mockTime(),
    text: result.reply,
    tags: [...result.tags, result.model, "STEPFUN"]
  });
  render();
  try {
    await applyModelIntent(text, result.intent);
  } catch (error) {
    runtime.messages.push({
      role: "system",
      kind: "authorization",
      sender: "Runtime Execution Gate",
      time: mockTime(),
      text: `Isaac 真实指令执行失败：${error.message}。Runtime 未使用 mock 伪造成功状态。`,
      tags: ["LIVE COMMAND FAILED", "NO MOCK FALLBACK"]
    });
    render();
  }
}

async function applyModelIntent(text, modelIntent) {
  if (modelIntent === "ANSWER") return false;
  const explicitIntent = inferMockIntent(text);
  if (explicitIntent !== modelIntent) {
    runtime.messages.push({
      role: "system",
      kind: "authorization",
      sender: "Runtime Safety Gate",
      time: mockTime(),
      text: `模型建议 ${modelIntent}，但工作人员原文没有匹配的明确动作指令。建议已阻断，Runtime 状态未改变。`,
      tags: ["MODEL INTENT BLOCKED", "NO STATE MUTATION"]
    });
    render();
    return false;
  }
  return applyRuntimeIntent(text, modelIntent);
}

function buildChatRequest(message) {
  const step = currentStep();
  return {
    message,
    mode: runtime.mode,
    world_version: runtime.worldVersion,
    org_version: runtime.orgVersion,
    incident_id: runtime.incidentActive ? scenario.emergencyIncidentId : scenario.incidentId,
    phase: runtime.incidentActive ? "紧急事件处置" : step.label,
    devices: Object.entries(runtime.devices).map(([deviceId, device]) => ({
      device_id: deviceId,
      device_type: device.type,
      status: device.status,
      zone: device.zone
    })),
    hazards: Object.entries(runtime.hazards).map(([hazardId, hazard]) => ({
      hazard_id: hazardId,
      hazard_type: hazard.type,
      active: hazard.active,
      zone: hazard.zone,
      clearance: hazard.clearance
    }))
  };
}

function inferMockIntent(text) {
  const normalized = text.toLowerCase();
  if (isMaintenanceClearanceCommand(normalized)) return "CLEAR_MAINTENANCE_HAZARD";
  if (containsAny(normalized, ["解除警报", "解除雷暴", "结束紧急", "恢复日常", "恢复正常", "all clear"])) return "CLEAR_EMERGENCY";
  if (containsAny(normalized, ["确认进入", "进入紧急", "批准切换", "同意切换", "授权进入"])) return "APPROVE_EMERGENCY";
  if (containsAny(normalized, ["暂不切换", "保持 normal", "继续监测", "拒绝切换"])) return "DEFER_EMERGENCY";
  if (containsMowerReference(normalized) && containsAny(normalized, ["回家", "返回", "返航", "回基地", "回维护区"])) return "RETURN_MACHINE_TO_BASE";
  if (containsMowerReference(normalized) && containsAny(normalized, ["前往", "去", "到", "调到", "改到", "移动到"])) return "ASSIGN_MOWING_ZONE";
  if (containsAny(normalized, ["无人机", "drone"]) && containsAny(normalized, ["前往", "飞往", "转到", "改到", "去", "调到"])) return "REDIRECT_INSPECTION";
  if (normalized.includes("巡检") && containsAny(normalized, ["前往", "飞往", "转到", "改到", "去"])) return "REDIRECT_INSPECTION";
  if (containsAny(normalized, ["开始巡检", "开始无人机", "执行巡检", "无人机巡检"])) return "START_INSPECTION";
  if (containsAny(normalized, ["创建维修", "安排维修", "处理维修", "生成维修任务"])) return "CREATE_MAINTENANCE_TASK";
  if (containsAny(normalized, ["模拟雷暴", "注入雷暴", "雷暴告警", "雷暴来了"])) return "INJECT_THUNDERSTORM";
  if (containsAny(normalized, ["评估风险", "判断风险", "安全评估"])) return "ASSESS_RISK";
  if (containsAny(normalized, ["生成紧急组织", "准备紧急组织", "组织建议"])) return "PREPARE_EMERGENCY_ORGANIZATION";
  if (containsAny(normalized, ["请求授权", "提交授权", "询问是否切换"])) return "REQUEST_AUTHORIZATION";
  return "ANSWER";
}

async function applyRuntimeIntent(text, intent) {
  if (intent === "ANSWER") return false;
  if (intent === "START_INSPECTION") return startInspection();
  if (intent === "REDIRECT_INSPECTION") return redirectInspection(text);
  if (intent === "RETURN_MACHINE_TO_BASE") return returnMachineToBase(text);
  if (intent === "ASSIGN_MOWING_ZONE") return assignMowingZone(text);
  if (intent === "CLEAR_MAINTENANCE_HAZARD") return clearMaintenanceHazard();
  if (intent === "CLEAR_EMERGENCY") return clearEmergency();
  const transitions = {
    CREATE_MAINTENANCE_TASK: ["inspection", "daily_proposal"],
    ASSESS_RISK: ["storm_event", "risk"],
    PREPARE_EMERGENCY_ORGANIZATION: ["risk", "recommend"],
    REQUEST_AUTHORIZATION: ["recommend", "approval"]
  };
  if (intent === "INJECT_THUNDERSTORM") {
    const stormIndex = scenario.steps.findIndex((item) => item.id === "storm_event");
    if (runtime.cursor < stormIndex) {
      runtime.incidentActive = true;
      moveToStep("storm_event");
      runPreAuthorizationAssessment();
      if (runtime.isaacConfigured) {
        if (!runtime.isaacConnected) return rejectInstruction("雷暴事件已记录，但 Isaac Bridge 未连接，未启动真实天气和疏散动作。");
        await executeLiveIsaacCommand("activate_thunderstorm", "runtime", null);
      }
      return true;
    }
    return rejectInstruction("雷暴事件已经存在，不能重复注入。");
  }
  if (intent === "APPROVE_EMERGENCY") {
    if (!containsAny(text.toLowerCase(), ["确认", "批准", "同意", "授权", "进入紧急"])) return rejectInstruction("紧急模式授权必须由工作人员使用明确的确认语句。");
    if (prepareEmergencyAuthorization()) return true;
    approveEmergency(false);
    return true;
  }
  if (intent === "DEFER_EMERGENCY") {
    deferEmergency(false);
    return true;
  }
  const transition = transitions[intent];
  if (!transition) return false;
  if (currentStep().id !== transition[0]) return rejectInstruction(`当前阶段为“${currentStep().label}”，不能执行该指令。`);
  moveToStep(transition[1]);
  return true;
}

async function startInspection() {
  if (currentStep().id !== "daily") {
    return rejectInstruction(`当前阶段为“${currentStep().label}”，不能重复开始初始巡检。`);
  }
  if (runtime.isaacConfigured) {
    if (!runtime.isaacConnected) return rejectInstruction("Isaac Bridge 当前未连接，真实巡检未启动。");
    await executeLiveIsaacCommand("start_scenario", "runtime", null);
    await executeLiveIsaacCommand("inspect_zone", "drone_1", "ZONE_C");
    await executeLiveIsaacCommand("declare_irrigation_leak", "runtime", null);
  }
  moveToStep("inspection");
  return true;
}

async function returnMachineToBase(text) {
  const machineId = extractMachineId(text);
  if (!machineId) return rejectInstruction("请指定需要返回的设备，例如“割草机1返回维护区”。");
  const machine = runtime.devices[machineId];
  if (!machine || machine.type !== "MOWER") return rejectInstruction(`未找到可执行返回指令的设备 ${machineId}。`);
  if (machine.status === "PARKED" && machine.zone === "MAINTENANCE") {
    runtime.messages.push({ role: "system", kind: "chat", sender: "Operations Agent", time: mockTime(), text: `${machineId} 已位于 MAINTENANCE，无需重复返回。`, tags: ["COMMAND NO-OP", `WORLD v${runtime.worldVersion}`] });
    render();
    return true;
  }

  if (runtime.isaacConfigured) {
    if (!runtime.isaacConnected) return rejectInstruction("Isaac Bridge 当前未连接，真实返回指令未下发。");
    return executeLiveIsaacCommand("return_to_base", machineId, null);
  }

  const target = { x: machineId === "mower_1" ? 76 : 82, y: 84 };
  return moveDeviceSafely(machineId, target, {
    minimumClearance: 8,
    movingStatus: "RETURNING",
    movingZone: "SERVICE ROAD",
    finalStatus: "PARKED",
    finalZone: "MAINTENANCE",
    acceptedResult: "RETURN COMMAND VERIFIED",
    arrivalResult: "ARRIVAL VERIFIED",
    acceptedText: `${machineId} 已中断当前割草任务，将沿已审查的安全路线返回 MAINTENANCE。`,
    arrivalText: `${machineId} 已到达 MAINTENANCE 并停车，返回任务完成。`
  });
}

async function assignMowingZone(text) {
  if (runtime.mode !== "NORMAL" || runtime.incidentActive) return rejectInstruction("紧急事件期间割草机不能恢复日常割草任务。");
  const machineId = extractMachineId(text);
  const target = extractInspectionTarget(text);
  if (!machineId) return rejectInstruction("请指定割草机编号，例如“割草机1去A区割草”。");
  if (!target) return rejectInstruction("请指定目标区域，例如“割草机1去A区割草”。");
  const machine = runtime.devices[machineId];
  if (!machine || machine.type !== "MOWER") return rejectInstruction(`未找到割草设备 ${machineId}。`);
  const targetZone = `FAIRWAY ${target}`;
  if (machine.status === "MOWING" && machine.zone === targetZone) {
    runtime.messages.push({ role: "system", kind: "chat", sender: "Operations Agent", time: mockTime(), text: `${machineId} 已在 ${targetZone} 割草，无需重复调度。`, tags: ["COMMAND NO-OP", `WORLD v${runtime.worldVersion}`] });
    render();
    return true;
  }

  const coordinates = { A: [20, 40], B: [32, 58], C: [60, 34], D: [69, 68] };
  const [x, y] = coordinates[target];
  const authorityDecision = evaluateMowerMovementAuthority(machineId, targetZone, { x, y });
  if (authorityDecision.outcome === "HOLD_FOR_INSPECTION") {
    return applyMovementAuthorityHold(machineId, targetZone, authorityDecision);
  }
  if (authorityDecision.requiresArbitration) {
    applyMovementAuthorityAllow(machineId, targetZone, authorityDecision);
  }
  if (runtime.isaacConfigured) {
    if (!runtime.isaacConnected) return rejectInstruction("Isaac Bridge 当前未连接，真实移动指令未下发。");
    return executeLiveIsaacCommand("move_to_zone", machineId, `ZONE_${target}`);
  }
  return moveDeviceSafely(machineId, { x, y }, {
    minimumClearance: 8,
    movingStatus: "TRANSITING",
    movingZone: "SERVICE ROAD",
    finalStatus: "MOWING",
    finalZone: targetZone,
    acceptedResult: "MOWING ASSIGNMENT ACCEPTED",
    arrivalResult: "MOWING STARTED",
    acceptedText: `${machineId} 已接受 ${targetZone} 割草任务，正在从 ${machine.zone} 沿安全路线前往目标区域。`,
    arrivalText: `${machineId} 已到达 ${targetZone}，开始执行割草任务。`
  });
}

async function executeLiveIsaacCommand(commandType, targetId, targetZone) {
  runtime.messages.push({
    role: "system",
    kind: "event",
    sender: "Runtime Execution Gate",
    time: mockTime(),
    text: `${commandType} 已提交到真实 Isaac Bridge，等待物理状态验证。`,
    tags: ["LIVE ISAAC COMMAND", targetId]
  });
  render();
  const response = await fetch("/api/isaac/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      incident_id: runtime.incidentActive ? scenario.emergencyIncidentId : scenario.incidentId,
      command_type: commandType,
      target_id: targetId,
      target_zone: targetZone,
      operator_id: "course_operator_01",
      confirmed: true,
      world_version: runtime.worldVersion,
      org_version: runtime.orgVersion
    })
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || result.error || `HTTP ${response.status}`);
  if (result.status !== "VERIFIED") throw new Error(result.message || `verification ${result.status}`);
  applyIsaacState(result.state || {});
  runtime.worldVersion += 1;
  const machine = result.observed_machine;
  const detail = machine ? `${machine.machine_id} ${machine.status} / ${machine.zone}` : targetId;
  addDynamicEvidence("ISAAC COMMAND VERIFIED", "isaac_simulator_adapter", `${detail} · command ${result.command_id}`);
  runtime.messages.push({
    role: "system",
    kind: "event",
    sender: "Runtime Execution Gate",
    time: mockTime(),
    text: `Isaac 已回传并验证：${detail}。`,
    tags: ["VERIFIED", "LIVE ISAAC", `WORLD v${runtime.worldVersion}`]
  });
  render();
  return true;
}

function evaluateMowerMovementAuthority(machineId, targetZone, requestedTarget) {
  const hazard = runtime.hazards.irrigation_leak_c;
  const route = planSafeRoute(machineId, requestedTarget, 8);
  const points = [route.start, ...route.waypoints];
  const targetAffected = targetZone === hazard.zone || pointDistance(requestedTarget, hazard) <= hazard.radius;
  const routeAffected = hazard.active && (targetAffected || pathIntersectsHazard(points, hazard));
  return {
    outcome: routeAffected ? "HOLD_FOR_INSPECTION" : "ALLOW",
    requiresArbitration: hazard.active,
    finalAuthority: "Supervisor",
    winningRule: routeAffected ? "SAFETY_VETO > MAINTENANCE_CLEARANCE > OPERATIONS_CONTINUITY" : "NO_ACTIVE_ROUTE_HAZARD",
    hazard,
    targetZone,
    routeAffected
  };
}

function applyMovementAuthorityHold(machineId, targetZone, decision) {
  const machine = runtime.devices[machineId];
  runtime.messages.push(
    { role: "system", kind: "chat", sender: "Operations Agent", time: mockTime(), text: `提议继续执行：将 ${machineId} 从 ${machine.zone} 调往 ${targetZone}，保持割草进度。`, tags: ["PROPOSAL", "CONTINUE_MOWING"] },
    { role: "system", kind: "authorization", sender: "Safety Agent", time: mockTime(), text: `安全否决：新路线进入 C 区漏水影响范围。要求停止本次转区，不中断设备在当前安全区域的原任务。`, tags: ["SAFETY VETO", "REJECT_NEW_ROUTE"] },
    { role: "system", kind: "chat", sender: "Maintenance Agent", time: mockTime(), text: "维修判断：灌溉管线必须先隔离并现场检查；在 MAINTENANCE CLEARANCE 产生前，不允许设备进入影响范围。", tags: ["INSPECTION REQUIRED", "CLEARANCE PENDING"] },
    { role: "system", kind: "authorization", sender: "Supervisor", time: mockTime(), text: `最终裁决：REJECT_NEW_ASSIGNMENT_KEEP_CURRENT_TASK。Supervisor 拥有最终发布权，规则要求 ${decision.winningRule}；因此拒绝进入 C 区，${machineId} 继续当前安全任务，等待 Maintenance 放行。`, tags: ["FINAL AUTHORITY", "ASSIGNMENT REJECTED", "CURRENT TASK PRESERVED"] }
  );
  addDynamicEvidence("AGENT CONFLICT ARBITRATED", "movement_authority_policy", `${machineId} ${machine.zone} → ${targetZone} · ${decision.winningRule}`);
  addDynamicEvidence("CURRENT TASK PRESERVED", runtime.isaacConnected ? "isaac_simulator_adapter" : "mock_isaac_adapter", `${machineId} remains ${machine.status} in ${machine.zone}; rejected command was not dispatched`);
  render();
  return true;
}

function applyMovementAuthorityAllow(machineId, targetZone, decision) {
  const machine = runtime.devices[machineId];
  runtime.messages.push(
    { role: "system", kind: "chat", sender: "Operations Agent", time: mockTime(), text: `运营建议：将 ${machineId} 从 ${machine.zone} 调往 ${targetZone}，继续割草任务。`, tags: ["PROPOSAL", "OPERATIONS CONTINUITY"] },
    { role: "system", kind: "authorization", sender: "Safety Agent", time: mockTime(), text: "安全审查：C 区仍为限制区，但该目标和审查路线未进入漏水影响范围，可附带路线约束放行。", tags: ["SAFETY REVIEW", "ROUTE CONSTRAINED"] },
    { role: "system", kind: "chat", sender: "Maintenance Agent", time: mockTime(), text: "维修判断：C 区继续等待现场检查；不反对设备在其他安全区域作业。", tags: ["C ZONE RESTRICTED", "INSPECTION PENDING"] },
    { role: "system", kind: "authorization", sender: "Supervisor", time: mockTime(), text: `最终裁决：ALLOW_WITH_ROUTE_CONSTRAINTS。Supervisor 依据 ${decision.winningRule} 批准本次转区，同时保持 C 区禁入。`, tags: ["FINAL AUTHORITY", "APPROVED", "RULE APPLIED"] }
  );
  addDynamicEvidence("AGENT CONFLICT ARBITRATED", "movement_authority_policy", `${machineId} ${machine.zone} → ${targetZone} · ALLOW_WITH_ROUTE_CONSTRAINTS`);
  render();
}

function pathIntersectsHazard(points, hazard) {
  if (!hazard.active || points.length < 2) return false;
  const center = { x: hazard.x, y: hazard.y };
  return points.slice(0, -1).some((start, index) => pointSegmentDistance(center, start, points[index + 1]) <= hazard.radius);
}

async function clearMaintenanceHazard() {
  const hazard = runtime.hazards.irrigation_leak_c;
  if (!hazard.discovered) return rejectInstruction("当前没有已发现的 C 区灌溉故障，无法签发维修放行。");
  if (!hazard.active) {
    runtime.messages.push({ role: "system", kind: "chat", sender: "Maintenance Agent", time: mockTime(), text: "C 区灌溉故障已经解除，当前放行状态为 MAINTENANCE_VERIFIED。", tags: ["CLEARANCE NO-OP", `WORLD v${runtime.worldVersion}`] });
    render();
    return true;
  }

  if (runtime.isaacConfigured) {
    if (!runtime.isaacConnected) return rejectInstruction("Isaac Bridge 当前未连接，C 区维修放行未同步。");
    await executeLiveIsaacCommand("clear_irrigation_leak", "runtime", null);
  }

  const resumedMachines = Object.entries(runtime.devices)
    .filter(([, device]) => device.type === "MOWER" && device.status === "HOLDING" && device.zone !== hazard.zone)
    .map(([deviceId, device]) => {
      device.status = "MOWING";
      return deviceId;
    });
  Object.assign(hazard, {
    active: false,
    clearance: "MAINTENANCE_VERIFIED",
    clearedAt: mockTime()
  });
  runtime.worldVersion += 1;
  runtime.messages.push(
    { role: "system", kind: "chat", sender: "Maintenance Agent", time: mockTime(), text: "维修确认已验证：C 区阀门已修复，压力测试通过，漏水影响范围已关闭。", tags: ["REPAIR VERIFIED", "MAINTENANCE CLEARANCE"] },
    { role: "system", kind: "chat", sender: "Safety Agent", time: mockTime(), text: "已读取 Maintenance 放行证据，解除 C 区设备进入否决。人员避让和路线净空规则继续有效。", tags: ["SAFETY VETO RELEASED", "ROUTE CHECK REQUIRED"] },
    { role: "system", kind: "authorization", sender: "Supervisor", time: mockTime(), text: `C 区重新开放。${resumedMachines.length ? `${resumedMachines.join("、")} 恢复原安全区域任务；` : ""}此前被拒绝的跨区指令不会自动重放，需要重新下达。`, tags: ["ZONE C REOPENED", "CLEARANCE PUBLISHED", `WORLD v${runtime.worldVersion}`] }
  );
  addDynamicEvidence("MAINTENANCE CLEARANCE VERIFIED", "maintenance_agent/pressure_test", `irrigation_leak_c repaired · C-zone reopened · kernel sync W${runtime.worldVersion}`);
  render();
  return true;
}

function extractMachineId(text) {
  const normalized = text.toLowerCase();
  const match = normalized.match(/(?:割草机|除草机|mower[_\s-]*)([12])/) || normalized.match(/(?:^|[^a-z0-9])m0?([12])(?=$|[^a-z0-9])/);
  return match ? `mower_${match[1]}` : null;
}

function clearEmergency() {
  if (runtime.mode !== "EMERGENCY" || !runtime.incidentActive) return rejectInstruction("当前没有需要解除的紧急警报。");
  window.clearInterval(runtime.timer);
  runtime.deviceTimers.forEach((timer) => window.clearTimeout(timer));
  runtime.deviceTimers = [];
  runtime.timer = null;
  runtime.mode = "RECOVERY";
  runtime.orgVersion += 1;
  runtime.messages.push({ role: "system", kind: "authorization", sender: "Recovery Policy", time: "14:22:15", text: `解除警报已验证。ModeManager 执行 EMERGENCY → RECOVERY，org v${runtime.orgVersion}。`, tags: ["ALL CLEAR VERIFIED", "RECOVERY"] });

  runtime.devices = clone(scenario.initialDevices);
  runtime.worldVersion += 1;
  runtime.cursor = scenario.initialCursor;
  runtime.mode = "NORMAL";
  runtime.orgVersion += 1;
  runtime.incidentActive = false;
  runtime.authorized = false;
  runtime.deferred = false;
  addDynamicEvidence("DAILY OPERATIONS RESUMED", "recovery_policy/mode_manager", `NORMAL org v${runtime.orgVersion} · equipment tasks resumed · kernel sync W${runtime.worldVersion}`, "14:22:16.000");
  runtime.messages.push({ role: "system", kind: "event", sender: "Golf Runtime Agent", time: "14:22:16", text: `警报解除，组织已恢复 NORMAL / org v${runtime.orgVersion}。割草机恢复日常任务，无人机恢复例行巡检，当前无活动事故。`, tags: ["NORMAL RESTORED", "DAILY OPS RESUMED", `WORLD v${runtime.worldVersion}`] });
  render();
  return true;
}

function addDynamicEvidence(result, source, detail, clock = currentStep().clock) {
  runtime.dynamicEvidence.push({
    clock,
    evidence: { source, result, detail }
  });
}

function runPreAuthorizationAssessment() {
  window.clearInterval(runtime.timer);
  const assessmentSteps = ["risk", "recommend", scenario.approvalStepId];
  let assessmentCursor = 0;
  runtime.timer = window.setInterval(() => {
    if (assessmentCursor >= assessmentSteps.length) {
      window.clearInterval(runtime.timer);
      runtime.timer = null;
      return;
    }
    moveToStep(assessmentSteps[assessmentCursor]);
    assessmentCursor += 1;
  }, 720);
}

async function redirectInspection(text) {
  const stormIndex = scenario.steps.findIndex((item) => item.id === "storm_event");
  if (runtime.cursor >= stormIndex) return rejectInstruction("紧急事件期间无人机由 Safety Agent 调度，不能执行日常巡检重定向。");
  const target = extractInspectionTarget(text);
  if (!target) return rejectInstruction("请在巡检指令中指定区域，例如“前往 B 区巡检”。");
  const drone = runtime.devices.drone_1;
  const targetZone = `FAIRWAY ${target}`;
  if (drone.zone === targetZone && drone.status === "INSPECTING") {
    runtime.messages.push({ role: "system", kind: "chat", sender: "Golf Runtime Agent", time: mockTime(), text: `drone_1 已在 ${targetZone} 执行巡检，无需重复下发。`, tags: ["COMMAND NO-OP", `WORLD v${runtime.worldVersion}`] });
    render();
    return true;
  }
  if (runtime.isaacConfigured) {
    if (!runtime.isaacConnected) return rejectInstruction("Isaac Bridge 当前未连接，真实巡检转区指令未下发。");
    return executeLiveIsaacCommand("inspect_zone", "drone_1", `ZONE_${target}`);
  }
  const coordinates = { A: [18, 38], B: [34, 50], C: [56, 39], D: [69, 68] };
  const [x, y] = coordinates[target] || [50, 50];
  return moveDeviceSafely("drone_1", { x, y }, {
    minimumClearance: 10,
    movingStatus: "TRANSITING",
    movingZone: "AIR CORRIDOR",
    finalStatus: "INSPECTING",
    finalZone: targetZone,
    acceptedResult: "INSPECTION REDIRECT ACCEPTED",
    arrivalResult: "COMMAND VERIFIED",
    acceptedText: `drone_1 已接受 ${targetZone} 巡检任务，正在沿人员避让航线飞往目标区域。`,
    arrivalText: `drone_1 已到达 ${targetZone} 并开始巡检。`
  });
}

function moveDeviceSafely(deviceId, requestedTarget, options) {
  const device = runtime.devices[deviceId];
  const plan = planSafeRoute(deviceId, requestedTarget, options.minimumClearance);
  if (!plan.safe) {
    addDynamicEvidence("ROUTE REJECTED", "route_safety_policy", `${deviceId} · ${plan.reason} · clearance ${plan.minimumClearance.toFixed(1)} < ${options.minimumClearance}`);
    return rejectInstruction(`${deviceId} 的移动指令已拒绝：当前路线无法与人员保持 ${options.minimumClearance} 个单位的安全距离。`);
  }

  runtime.activeRoutes[deviceId] = { ...plan, status: "ACTIVE" };
  const routeType = plan.direct ? "DIRECT" : "DETOUR";
  const adjustment = plan.targetAdjusted ? ` · target adjusted to COURSE(${formatCoordinate(plan.resolvedTarget.x)},${formatCoordinate(plan.resolvedTarget.y)})` : "";
  addDynamicEvidence("ROUTE SAFETY VERIFIED", "route_safety_policy", `${deviceId} · ${routeType} · clearance ${plan.minimumClearance.toFixed(1)} >= ${options.minimumClearance}${adjustment}`);
  runtime.messages.push({
    role: "system",
    kind: "event",
    sender: "Route Safety Policy",
    time: mockTime(),
    text: routeSafetyMessage(deviceId, plan, options.minimumClearance),
    tags: ["ROUTE VERIFIED", routeType, `CLEARANCE ${options.minimumClearance}`]
  });

  Object.assign(device, { status: options.movingStatus, zone: options.movingZone });
  runtime.worldVersion += 1;
  addDynamicEvidence(options.acceptedResult, "operations/simple_executor", `${deviceId} command accepted after route verification · kernel sync W${runtime.worldVersion}`);
  runtime.messages.push({ role: "system", kind: "event", sender: "Operations Agent", time: mockTime(), text: options.acceptedText, tags: ["TASK ASSIGNED", "SAFE ROUTE", `WORLD v${runtime.worldVersion}`] });
  render();

  return executeRoute(deviceId, plan, options);
}

function executeRoute(deviceId, plan, options) {
  const generation = runtime.generation;
  const device = runtime.devices[deviceId];
  let waypointIndex = 0;
  return new Promise((resolve) => {
    const moveNext = () => {
      if (generation !== runtime.generation) {
        resolve(false);
        return;
      }
      const waypoint = plan.waypoints[waypointIndex];
      if (!waypoint) {
        Object.assign(device, { status: options.finalStatus, zone: options.finalZone });
        runtime.activeRoutes[deviceId].status = "COMPLETED";
        runtime.worldVersion += 1;
        addDynamicEvidence(options.arrivalResult, "equipment_position_sensor", `${deviceId} arrived ${options.finalZone} COURSE(${formatCoordinate(device.x)},${formatCoordinate(device.y)}) · kernel sync W${runtime.worldVersion}`);
        runtime.messages.push({ role: "system", kind: "event", sender: "Operations Agent", time: mockTime(), text: `${options.arrivalText} 坐标 COURSE(${formatCoordinate(device.x)},${formatCoordinate(device.y)})。`, tags: ["ARRIVAL VERIFIED", options.finalStatus, `WORLD v${runtime.worldVersion}`] });
        render();
        resolve(true);
        return;
      }

      const liveClearance = segmentClearance({ x: device.x, y: device.y }, waypoint, peopleObstacles());
      if (liveClearance + 0.001 < options.minimumClearance) {
        device.status = "HOLDING";
        runtime.activeRoutes[deviceId].status = "BLOCKED";
        runtime.worldVersion += 1;
        addDynamicEvidence("ROUTE RECHECK FAILED", "route_safety_policy", `${deviceId} held before leg ${waypointIndex + 1} · live clearance ${liveClearance.toFixed(1)}`);
        runtime.messages.push({ role: "system", kind: "authorization", sender: "Route Safety Policy", time: mockTime(), text: `${deviceId} 移动已暂停：第 ${waypointIndex + 1} 段复核发现人员距离不足，设备保持 HOLDING。`, tags: ["MOVEMENT BLOCKED", "PERSON CLEARANCE", `WORLD v${runtime.worldVersion}`] });
        render();
        resolve(false);
        return;
      }

      const timer = window.setTimeout(() => {
        Object.assign(device, { x: roundCoordinate(waypoint.x), y: roundCoordinate(waypoint.y) });
        runtime.worldVersion += 1;
        addDynamicEvidence("ROUTE LEG VERIFIED", "mock_isaac_position_sensor", `${deviceId} leg ${waypointIndex + 1}/${plan.waypoints.length} reached COURSE(${formatCoordinate(device.x)},${formatCoordinate(device.y)}) · kernel sync W${runtime.worldVersion}`);
        waypointIndex += 1;
        render();
        moveNext();
      }, 850);
      runtime.deviceTimers.push(timer);
    };
    moveNext();
  });
}

function planSafeRoute(deviceId, requestedTarget, minimumClearance) {
  const device = runtime.devices[deviceId];
  const start = { x: Number(device.x), y: Number(device.y) };
  const people = peopleObstacles();
  const resolvedTarget = adjustTargetForPeople(requestedTarget, people, minimumClearance + 2);
  const targetAdjusted = pointDistance(requestedTarget, resolvedTarget) > 0.001;
  const directClearance = pathClearance([start, resolvedTarget], people);
  if (directClearance >= minimumClearance) {
    return { safe: true, direct: true, targetAdjusted, start, requestedTarget, resolvedTarget, waypoints: [resolvedTarget], minimumClearance: directClearance, reason: "DIRECT_ROUTE_CLEAR" };
  }

  const dx = resolvedTarget.x - start.x;
  const dy = resolvedTarget.y - start.y;
  const length = Math.hypot(dx, dy) || 1;
  const normal = { x: -dy / length, y: dx / length };
  const diagonal = Math.SQRT1_2;
  const directions = [
    normal, { x: -normal.x, y: -normal.y },
    { x: 1, y: 0 }, { x: -1, y: 0 }, { x: 0, y: 1 }, { x: 0, y: -1 },
    { x: diagonal, y: diagonal }, { x: diagonal, y: -diagonal },
    { x: -diagonal, y: diagonal }, { x: -diagonal, y: -diagonal }
  ];
  const candidates = people.flatMap((person) => directions.map((direction) => ({
    x: clampCoordinate(person.x + direction.x * (minimumClearance + 6)),
    y: clampCoordinate(person.y + direction.y * (minimumClearance + 6))
  })));
  const ranked = candidates.map((waypoint) => ({ waypoint, clearance: pathClearance([start, waypoint, resolvedTarget], people) })).sort((left, right) => right.clearance - left.clearance);
  if (ranked.length && ranked[0].clearance >= minimumClearance) {
    return { safe: true, direct: false, targetAdjusted, start, requestedTarget, resolvedTarget, waypoints: [ranked[0].waypoint, resolvedTarget], minimumClearance: ranked[0].clearance, reason: "DETOUR_REQUIRED_FOR_PERSON_CLEARANCE" };
  }
  return { safe: false, direct: false, targetAdjusted, start, requestedTarget, resolvedTarget, waypoints: [], minimumClearance: ranked.length ? ranked[0].clearance : directClearance, reason: "NO_ROUTE_MEETS_PERSON_CLEARANCE" };
}

function adjustTargetForPeople(requestedTarget, people, requiredClearance) {
  return people.reduce((target, person) => {
    let dx = target.x - person.x;
    let dy = target.y - person.y;
    let distance = Math.hypot(dx, dy);
    if (distance >= requiredClearance) return target;
    if (distance === 0) { dx = 1; dy = 0; distance = 1; }
    return {
      x: clampCoordinate(person.x + (dx / distance) * requiredClearance),
      y: clampCoordinate(person.y + (dy / distance) * requiredClearance)
    };
  }, { x: requestedTarget.x, y: requestedTarget.y });
}

function routeSafetyMessage(deviceId, plan, minimumClearance) {
  const personIds = peopleObstacles().map((person) => person.id).join("、") || "无人员目标";
  const route = plan.direct
    ? "直达路线安全"
    : `直线路径过于接近人员，已加入绕行点 COURSE(${formatCoordinate(plan.waypoints[0].x)},${formatCoordinate(plan.waypoints[0].y)})`;
  const target = plan.targetAdjusted ? `；原终点离人员过近，安全终点调整为 COURSE(${formatCoordinate(plan.resolvedTarget.x)},${formatCoordinate(plan.resolvedTarget.y)})` : "";
  return `${deviceId} 路线审查通过：${route}；已检查 ${personIds}，规划最近距离 ${plan.minimumClearance.toFixed(1)}，要求至少 ${minimumClearance}${target}。`;
}

function peopleObstacles() {
  return Object.entries(runtime.devices)
    .filter(([, device]) => device.type === "PERSON")
    .map(([id, device]) => ({ id, x: Number(device.x), y: Number(device.y) }));
}

function pathClearance(points, people) {
  if (!people.length) return 100;
  let clearance = 100;
  for (let index = 0; index < points.length - 1; index += 1) {
    clearance = Math.min(clearance, segmentClearance(points[index], points[index + 1], people));
  }
  return clearance;
}

function segmentClearance(start, end, people) {
  if (!people.length) return 100;
  return Math.min(...people.map((person) => pointSegmentDistance(person, start, end)));
}

function pointSegmentDistance(point, start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const denominator = dx * dx + dy * dy;
  if (denominator === 0) return pointDistance(point, start);
  const ratio = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / denominator));
  return Math.hypot(point.x - (start.x + ratio * dx), point.y - (start.y + ratio * dy));
}

function pointDistance(left, right) { return Math.hypot(left.x - right.x, left.y - right.y); }
function clampCoordinate(value) { return Math.max(2, Math.min(98, value)); }
function roundCoordinate(value) { return Math.round(value * 10) / 10; }
function formatCoordinate(value) { return Number.isInteger(value) ? String(value) : value.toFixed(1); }

function extractInspectionTarget(text) {
  const normalized = text.toUpperCase();
  const namedZones = Array.from(normalized.matchAll(/(?:ZONE|FAIRWAY|球道)\s*([A-H])/g));
  const chineseZones = Array.from(normalized.matchAll(/([A-H])\s*(?:区|區)/g));
  const matches = [...namedZones, ...chineseZones].sort((left, right) => left.index - right.index);
  return matches.length ? matches[matches.length - 1][1] : null;
}

function prepareEmergencyAuthorization() {
  const stormIndex = scenario.steps.findIndex((item) => item.id === "storm_event");
  const approvalIndex = scenario.steps.findIndex((item) => item.id === scenario.approvalStepId);
  if (runtime.cursor < stormIndex) {
    rejectInstruction("当前没有活动紧急事件，不能进入紧急模式。");
    return true;
  }
  if (runtime.cursor >= approvalIndex) return false;
  ["risk", "recommend", scenario.approvalStepId].forEach((stepId) => {
    const stepIndex = scenario.steps.findIndex((item) => item.id === stepId);
    if (runtime.cursor < stepIndex) moveToStep(stepId);
  });
  approveEmergency(false);
  return true;
}

function moveToStep(stepId) {
  const targetIndex = scenario.steps.findIndex((item) => item.id === stepId);
  if (targetIndex < 0) return;
  runtime.cursor = targetIndex;
  const step = currentStep();
  runtime.mode = step.mode;
  runtime.orgVersion = Math.max(runtime.orgVersion, step.orgVersion);
  runtime.worldVersion = Math.max(runtime.worldVersion, step.worldVersion);
  if (step.statePatch && !runtime.isaacConnected) Object.entries(step.statePatch).forEach(([id, patch]) => Object.assign(runtime.devices[id], patch));
  synchronizeHazards(step.id);
  runtime.messages.push({ role: "system", kind: step.id === "storm_event" ? "event" : "chat", sender: "Golf Runtime Agent", time: step.clock.slice(0, 8), text: step.chat || `${step.title}。`, tags: [...(step.chatTags || []), "INSTRUCTION APPLIED"] });
  render();
}

function rejectInstruction(message) {
  runtime.messages.push({ role: "system", kind: "chat", sender: "Golf Runtime Agent", time: mockTime(), text: message, tags: ["INSTRUCTION REJECTED"] });
  render();
  return true;
}

function handleMockWorkerMessage(text) {
  const inferredIntent = inferMockIntent(text);
  if (inferredIntent !== "ANSWER") {
    return applyRuntimeIntent(text, inferredIntent);
  }
  const normalized = text.toLowerCase();
  if (containsAny(normalized, ["当前状态", "现在情况", "发生了什么", "现场情况"])) {
    queueAgentReply(runtimeStatusReply(), [runtime.mode, `WORLD v${runtime.worldVersion}`, `ORG v${runtime.orgVersion}`]);
    return;
  }
  if (containsAny(normalized, ["人员", "球员", "人在哪里", "撤离"])) {
    const person = runtime.devices.player_1;
    const safetyContext = runtime.authorized ? `无人机状态为 ${runtime.devices.drone_1.status}。` : runtime.incidentActive ? "雷暴到达前需要完成撤离。" : "当前没有人员安全告警。";
    queueAgentReply(`player_1 当前位于 ${person.zone}，坐标 COURSE(${person.x},${person.y})，状态为 ${person.status}。${safetyContext}`, ["PERSON SAFETY", person.status]);
    return;
  }
  if (containsAny(normalized, ["设备", "割草机", "无人机", "机器"])) {
    queueAgentReply(deviceStatusReply(), ["ISAAC MOCK", `WORLD v${runtime.worldVersion}`]);
    return;
  }
  if (containsAny(normalized, ["为什么", "原因", "风险", "雷暴"])) {
    queueAgentReply("风险由三项证据共同触发：雷电距离 6.8 km、预计 8 分钟到达、Fairway B 存在人员和运行设备。建议使用最小紧急组织减少指挥链路。", ["EVIDENCE BASED", "RISK CRITICAL"]);
    return;
  }
  if (containsAny(normalized, ["组织", "agent", "proposal"])) {
    queueAgentReply(runtime.authorized
      ? "当前 EMERGENCY 组织由 Incident Commander 负责，Safety、Operations、Communication 保持激活；Proposal 已绑定最新 world/org 版本。"
      : `当前为 ${runtime.mode} / org v${runtime.orgVersion}，日常组织由 Supervisor 负责。`, ["ORGANIZATION", `ORG v${runtime.orgVersion}`]);
    return;
  }
  queueAgentReply("收到。我可以查询当前状态、人员位置、设备状态、风险原因和 Agent 组织，也可以在你明确授权后进入紧急模式。", ["RUNTIME ASSISTANT"]);
}

function approveEmergency(recordOperator = true) {
  if (runtime.authorized) return;
  if (currentStep().id !== scenario.approvalStepId) {
    runtime.messages.push({ role: "system", kind: "chat", sender: "Golf Runtime Agent", time: mockTime(), text: "当前没有待授权的组织切换。日常巡检和事件评估仍在进行。", tags: ["NO PENDING AUTH"] });
    render();
    return;
  }
  runtime.authorized = true;
  runtime.deferred = false;
  if (recordOperator) addOperatorDecision("确认进入紧急模式。", "HUMAN APPROVED");
  runtime.messages.push({
    role: "system",
    kind: "authorization",
    sender: "Golf Runtime Agent",
    time: "14:22:09",
    text: "授权身份 course_operator_01 已验证。EmergencyModeAuthorizationPolicy 正在写入授权审计，成功后才允许 ModeManager 切换组织。",
    tags: ["HUMAN AUTHORITY VERIFIED", "POLICY AUDIT", "ORG TRANSITION PENDING"]
  });
  runRemainingSteps();
}

function deferEmergency(recordOperator = true) {
  if (runtime.authorized || runtime.deferred) return;
  if (currentStep().id !== scenario.approvalStepId) {
    runtime.messages.push({ role: "system", kind: "chat", sender: "Golf Runtime Agent", time: mockTime(), text: "当前没有待处理的组织切换请求。", tags: ["NO PENDING AUTH"] });
    render();
    return;
  }
  runtime.deferred = true;
  if (recordOperator) addOperatorDecision("暂不切换，保持 NORMAL 并持续监测。", "DEFERRED");
  runtime.messages.push({
    role: "system",
    kind: "authorization",
    sender: "Golf Runtime Agent",
    time: "14:22:09",
    text: "已保留 NORMAL 组织。系统不会下发设备动作；风险监测继续运行。你仍可在聊天中输入“确认进入紧急模式”改变决定。",
    tags: ["NO STATE MUTATION", "WATCHING"]
  });
  render();
}

function addOperatorDecision(text, tag) {
  runtime.messages.push({ role: "operator", kind: "decision", sender: "工作人员", time: mockTime(), text, tags: [tag] });
}

function queueAgentReply(text, tags) {
  setTyping(true);
  window.clearTimeout(runtime.replyTimer);
  runtime.replyTimer = window.setTimeout(() => {
    runtime.typing = false;
    runtime.messages.push({ role: "system", kind: "chat", sender: "Golf Runtime Agent", time: mockTime(), text, tags: [...tags, "MOCK FALLBACK"] });
    render();
  }, 460);
}

function setTyping(value) {
  runtime.typing = value;
  renderConversation();
}

function runRemainingSteps() {
  if (runtime.isaacConfigured && runtime.isaacConnected) {
    runLiveEmergencySteps();
    return;
  }
  window.clearInterval(runtime.timer);
  advanceStep();
  runtime.timer = window.setInterval(() => {
    if (runtime.cursor >= scenario.steps.length - 1) {
      window.clearInterval(runtime.timer);
      runtime.timer = null;
      runtime.messages.push({
        role: "system",
        kind: "event",
        sender: "Golf Runtime Agent",
        time: "14:22:13",
        text: "紧急处置闭环已完成：人员到达避险点，两台割草机位置已确认。所有目标已到达指定位置，停止周期位置复核，等待解除警报。",
        tags: ["SAFETY CLOSED LOOP", "POSITION MONITOR STOPPED", "WORLD v19"]
      });
      render();
      return;
    }
    advanceStep();
  }, 920);
}

function runLiveEmergencySteps() {
  window.clearInterval(runtime.timer);
  runtime.timer = window.setInterval(() => {
    if (currentStep().id !== "position_recheck") {
      advanceStep();
      return;
    }
    if (!liveEmergencySafetyClosedLoop()) return;
    window.clearInterval(runtime.timer);
    runtime.timer = null;
    moveToStep("shelter_verified");
    runtime.messages.push({
      role: "system",
      kind: "event",
      sender: "Golf Runtime Agent",
      time: mockTime(),
      text: "Isaac 实时位置已验证：人员到达避险点，两台割草机分别停入休息泊位，无人机完成跟随并转为监视。",
      tags: ["LIVE SAFETY CLOSED LOOP", "ISAAC POSITIONS VERIFIED", `WORLD v${runtime.worldVersion}`]
    });
    render();
  }, 1000);
}

function liveEmergencySafetyClosedLoop() {
  const mower1 = runtime.devices.mower_1?.status || "";
  const mower2 = runtime.devices.mower_2?.status || "";
  const drone = runtime.devices.drone_1?.status || "";
  const player = runtime.devices.player_1?.status || "";
  return mower1.includes("PARKED_AT_MOWER_BAY_01")
    && mower2.includes("PARKED_AT_MOWER_BAY_02")
    && drone.includes("OVERWATCH_AT_")
    && player.includes("SHELTERED_AT_");
}

function advanceStep() {
  runtime.cursor = Math.min(runtime.cursor + 1, scenario.steps.length - 1);
  const step = currentStep();
  runtime.mode = step.mode;
  runtime.orgVersion = Math.max(runtime.orgVersion, step.orgVersion);
  runtime.worldVersion = Math.max(runtime.worldVersion, step.worldVersion);
  if (step.statePatch && !runtime.isaacConnected) Object.entries(step.statePatch).forEach(([id, patch]) => Object.assign(runtime.devices[id], patch));
  synchronizeHazards(step.id);
  if (step.chat) runtime.messages.push({ role: "system", kind: step.id === "storm_event" ? "event" : "chat", sender: "Golf Runtime Agent", time: step.clock.slice(0, 8), text: step.chat, tags: step.chatTags || [] });
  render();
}

async function resetDemo() {
  if (runtime.isaacConfigured && runtime.isaacConnected) {
    try {
      await executeLiveIsaacCommand("reset_scenario", "runtime", null);
    } catch (error) {
      return rejectInstruction(`Isaac 重置失败：${error.message}`);
    }
  }
  window.clearInterval(runtime.timer);
  window.clearTimeout(runtime.replyTimer);
  runtime.deviceTimers.forEach((timer) => window.clearTimeout(timer));
  runtime.timer = null;
  runtime.replyTimer = null;
  runtime.deviceTimers = [];
  runtime.generation += 1;
  runtime.commandQueue = Promise.resolve();
  runtime.cursor = scenario.initialCursor;
  runtime.authorized = false;
  runtime.deferred = false;
  runtime.typing = false;
  runtime.mode = scenario.steps[scenario.initialCursor].mode;
  runtime.orgVersion = scenario.steps[scenario.initialCursor].orgVersion;
  runtime.incidentActive = false;
  runtime.worldVersion = scenario.steps[scenario.initialCursor].worldVersion;
  runtime.dynamicEvidence = [];
  runtime.activeRoutes = {};
  runtime.messages = clone(initialMessages);
  runtime.devices = clone(scenario.initialDevices);
  runtime.hazards = clone(scenario.initialHazards);
  $("chatInput").value = "";
  render();
}

function render() {
  const step = currentStep();
  $("incidentMetric").textContent = runtime.incidentActive ? scenario.emergencyIncidentId : scenario.incidentId;
  $("modeMetric").textContent = runtime.mode;
  $("modeMetric").style.color = runtime.mode === "EMERGENCY" ? "var(--danger)" : "var(--text)";
  $("worldMetric").textContent = `v${runtime.worldVersion}`;
  $("orgMetric").textContent = `v${runtime.orgVersion}`;
  $("simClock").textContent = step.clock;
  $("stormDistance").textContent = `LIGHTNING ${step.lightningKm.toFixed(1)} KM`;
  $("telemetryVersion").textContent = `WORLD v${runtime.worldVersion}`;
  const awaitingApproval = step.id === scenario.approvalStepId && !runtime.authorized && !runtime.deferred;
  $("conversationState").textContent = runtime.authorized ? (runtime.cursor === scenario.steps.length - 1 ? "等待解除警报" : "响应执行中") : runtime.deferred ? "持续监测" : awaitingApproval ? "等待授权" : "等待指令";
  $("conversationState").className = `status-tag ${runtime.authorized ? "active" : awaitingApproval ? "waiting" : ""}`;
  updateLiveNotice();
  renderConversation();
  renderCourseMap();
  renderTelemetry();
  renderEvidence();
}

function updateLiveNotice() {
  const step = currentStep();
  const maintenanceHazard = runtime.hazards.irrigation_leak_c;
  $("noticeTime").textContent = step.clock.slice(0, 8);
  $("noticeLabel").textContent = runtime.incidentActive ? "LIVE INCIDENT" : maintenanceHazard.active ? "LIVE MAINTENANCE ALERT" : "LIVE OPERATIONS";
  const routineNotice = maintenanceHazard.active
    ? "C 区灌溉阀漏水 · 等待 Maintenance 放行"
    : maintenanceHazard.discovered
      ? "C 区维修已验证 · 区域警报解除"
      : step.id === "daily" ? "日常任务正常 · 无活动事故" : step.id === "inspection" ? `无人机正在 ${runtime.devices.drone_1.zone} 巡检` : step.id === "daily_proposal" ? "维修任务已排队 · 日常作业继续" : "强雷暴预计 8 分钟后到达 · 1 人暴露";
  $("liveNotice").textContent = runtime.authorized
    ? runtime.cursor === scenario.steps.length - 1 ? "人员与设备已到位 · 等待解除警报" : `紧急响应执行中 · ${step.label}`
    : runtime.deferred ? "组织切换已暂缓 · 风险监测持续运行" : routineNotice;
}

function renderConversation() {
  const messages = runtime.messages.map((message) => `
    <div class="message ${message.role} ${message.kind || ""}">
      <div class="message-meta"><span>${escapeHtml(message.sender)}</span><time>${message.time}</time></div>
      <div class="message-body">${escapeHtml(message.text)}
        ${message.tags.length ? `<div class="message-tags">${message.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
      </div>
    </div>`).join("");
  const authorization = currentStep().id === scenario.approvalStepId && !runtime.authorized && !runtime.deferred ? `
    <div class="message system authorization-message">
      <div class="message-meta"><span>Golf Runtime Agent</span><time>需要回复</time></div>
      <div class="message-body">是否授权进入紧急模式？
        <div class="authorization-card"><strong>Policy 控制的组织切换授权</strong><p>EmergencyModeAuthorizationPolicy 将记录人工身份和决定；审计成功后才允许 ModeManager 激活 Incident Commander。</p>
          <div class="authorization-actions"><button id="approveButton" class="primary" type="button">进入紧急模式</button><button id="deferButton" type="button">暂不切换</button></div>
        </div>
      </div>
    </div>` : "";
  const typing = runtime.typing ? `<div class="message system typing"><div class="message-meta"><span>Golf Runtime Agent</span><time>正在输入</time></div><div class="message-body">正在读取 Runtime 状态</div></div>` : "";
  $("conversation").innerHTML = messages + authorization + typing;
  $("approveButton")?.addEventListener("click", () => approveEmergency(true));
  $("deferButton")?.addEventListener("click", () => deferEmergency(true));
  $("conversation").scrollTop = $("conversation").scrollHeight;
}

function renderCourseMap() {
  const routePlans = Object.entries(runtime.activeRoutes);
  const maximumClearance = routePlans.reduce((value, [deviceId]) => Math.max(value, deviceId.startsWith("drone") ? 10 : 8), 8);
  const courseMap = $("courseMap");
  if (!courseMap.dataset.initialized) {
    courseMap.innerHTML = '<div class="storm-front" hidden></div><div class="fairway a"></div><div class="fairway b"></div><div class="fairway c"></div><div class="maintenance-base">MAINTENANCE</div><svg class="route-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="设备安全路线"></svg><div class="hazard-layer"></div><div class="device-layer"></div><div class="sim-watermark">ISAAC SIGNALS: MOCK INPUT</div>';
    courseMap.dataset.initialized = "true";
  }
  courseMap.querySelector(".sim-watermark").textContent = runtime.isaacConnected ? "ISAAC SIGNALS: LIVE BRIDGE" : runtime.isaacConfigured ? "ISAAC SIGNALS: BRIDGE DISCONNECTED" : "ISAAC SIGNALS: MOCK INPUT";
  courseMap.querySelector(".storm-front").hidden = !runtime.incidentActive;
  courseMap.querySelector(".route-overlay").innerHTML = `
    ${peopleObstacles().map((person) => `<circle class="person-clearance" cx="${person.x}" cy="${person.y}" r="${maximumClearance}"></circle>`).join("")}
    ${routePlans.map(([deviceId, plan]) => `<polyline class="planned-route ${plan.status.toLowerCase()} ${plan.direct ? "direct" : "detour"}" points="${[plan.start, ...plan.waypoints].map((point) => `${point.x},${point.y}`).join(" ")}"></polyline>`).join("")}`;
  courseMap.querySelector(".hazard-layer").innerHTML = Object.entries(runtime.hazards).filter(([, hazard]) => hazard.discovered).map(([id, hazard]) => `<div class="map-hazard ${hazard.active ? "active" : "cleared"}" style="left:${hazard.x}%;top:${hazard.y}%"><span>${hazard.active ? "LEAK" : "REPAIRED"}</span><b>${escapeHtml(id)}<br>${escapeHtml(hazard.clearance)}</b></div>`).join("");

  const deviceLayer = courseMap.querySelector(".device-layer");
  const activeDeviceIds = new Set(Object.keys(runtime.devices));
  Array.from(deviceLayer.children).forEach((element) => {
    if (!activeDeviceIds.has(element.dataset.deviceId)) element.remove();
  });
  Object.entries(runtime.devices).forEach(([id, device]) => {
    const isPerson = device.type === "PERSON";
    const tracking = device.status.includes("TRACKING");
    let element = Array.from(deviceLayer.children).find((candidate) => candidate.dataset.deviceId === id);
    const isNew = !element;
    if (isNew) {
      element = document.createElement("div");
      element.dataset.deviceId = id;
      deviceLayer.appendChild(element);
    }
    element.className = `map-object ${isPerson ? "person" : ""} ${tracking ? "tracking" : ""}`;
    element.innerHTML = `${isPerson ? "P1" : id.startsWith("drone") ? "D1" : id.endsWith("1") ? "M1" : "M2"}<span class="object-label">${escapeHtml(id)} / ${escapeHtml(device.status)}<br>POS ${device.x},${device.y}</span>`;
    const updatePosition = () => {
      element.style.left = `${device.x}%`;
      element.style.top = `${device.y}%`;
    };
    if (isNew) updatePosition(); else window.requestAnimationFrame(updatePosition);
  });
}

function synchronizeHazards(stepId) {
  if (stepId !== "inspection" && stepId !== "daily_proposal") return;
  Object.assign(runtime.hazards.irrigation_leak_c, {
    active: true,
    discovered: true,
    clearance: "PENDING_MAINTENANCE_INSPECTION"
  });
}

function renderTelemetry() {
  $("deviceTelemetry").innerHTML = Object.entries(runtime.devices).map(([id, device]) => `<div class="device-row"><div><strong>${escapeHtml(id)}</strong><span>${escapeHtml(device.type)} · ${escapeHtml(device.zone)}<br>COURSE POS ${device.physicalX ?? device.x},${device.physicalY ?? device.y}</span>${device.battery === null ? "" : `<div class="battery"><i style="width:${device.battery}%"></i></div>`}</div><span class="device-status">${escapeHtml(device.status)}</span></div>`).join("");
}

function renderEvidence() {
  const records = [...scenario.steps.slice(0, runtime.cursor + 1), ...runtime.dynamicEvidence]
    .sort((left, right) => left.clock.localeCompare(right.clock));
  $("evidenceCount").textContent = `${records.length} RECORDS`;
  $("evidenceStream").innerHTML = records.slice().reverse().map((step) => `<li class="evidence-item"><time>${step.clock.slice(0, 8)}</time><div><strong>${escapeHtml(step.evidence.result)}</strong><span>${escapeHtml(step.evidence.source)}<br>${escapeHtml(step.evidence.detail)}</span></div></li>`).join("");
}

function runtimeStatusReply() {
  const step = currentStep();
  if (runtime.authorized) return `当前为 ${runtime.mode}，world v${runtime.worldVersion}，org v${runtime.orgVersion}。${runtime.cursor === scenario.steps.length - 1 ? "人员和设备均已到达指定安全位置，等待解除警报。" : `正在处理：${step.label}。`}`;
  if (step.id === scenario.approvalStepId) return `当前为 NORMAL，world v${runtime.worldVersion}，org v${runtime.orgVersion}。雷暴风险为 CRITICAL，ModeManager 正在等待 Policy 人工授权。`;
  return `当前为 ${runtime.mode}，world v${runtime.worldVersion}，org v${runtime.orgVersion}。${runtime.incidentActive ? "雷暴事件正在评估中。" : "日常任务正在运行。"}`;
}

function deviceStatusReply() {
  const source = runtime.isaacConnected ? "真实 Isaac Bridge telemetry" : "Mock Isaac telemetry";
  return Object.entries(runtime.devices).map(([id, device]) => `${id}: ${device.status} / ${device.zone} / COURSE(${device.x},${device.y})`).join("；") + `。以上数据来自${source}。`;
}

function containsAny(text, candidates) { return candidates.some((candidate) => text.includes(candidate)); }
function containsMowerReference(text) { return containsAny(text, ["割草机", "除草机", "mower"]) || /(?:^|[^a-z0-9])m0?[12](?=$|[^a-z0-9])/.test(text); }
function isMaintenanceClearanceCommand(text) {
  const compact = text.toLowerCase().replaceAll(" ", "").replaceAll("區", "区").replaceAll("檢", "检").replaceAll("復", "复").replaceAll("維", "维");
  const zoneC = containsAny(compact, ["c区", "c球道", "zonec", "fairwayc"]);
  const completed = containsAny(compact, ["修好", "已修复", "已经修复", "修复完", "修复完成", "修复完毕", "修复好了", "修理好了", "维修好了", "完成修复", "已处理", "处理完成", "已经处理好", "恢复使用", "修完", "维修完", "处理完", "检修完", "已经正常", "恢复正常", "故障解除", "故障已解除", "故障已经解除", "已解除故障", "问题解决", "漏水解决", "repaired", "fixed", "repaircomplete", "cleared"]);
  return zoneC && completed;
}
function mockTime() { return currentStep().clock.slice(0, 8); }
function currentStep() { return scenario.steps[runtime.cursor]; }
function clone(value) { return JSON.parse(JSON.stringify(value)); }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character])); }

init();
