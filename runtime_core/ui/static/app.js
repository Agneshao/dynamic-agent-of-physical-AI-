"use strict";

const scenario = window.GOLF_RUNTIME_SCENARIO;
const runtime = {
  cursor: -1,
  selectedSequence: null,
  timer: null
};

const roleLabels = {
  supervisor: "Supervisor",
  incident_commander: "Incident Commander",
  safety: "Safety",
  operations: "Operations",
  maintenance: "Maintenance",
  resource: "Resource",
  communication: "Communication"
};

const roleInitials = {
  supervisor: "SV",
  incident_commander: "IC",
  safety: "SA",
  operations: "OP",
  maintenance: "MT",
  resource: "RS",
  communication: "CM"
};

const normalPositions = {
  supervisor: [50, 20],
  safety: [11, 61],
  operations: [30.5, 61],
  maintenance: [50, 61],
  resource: [69.5, 61],
  communication: [89, 61]
};

const emergencyPositions = {
  incident_commander: [50, 18],
  safety: [24, 55],
  operations: [50, 55],
  communication: [76, 55],
  supervisor: [18, 86],
  maintenance: [50, 86],
  resource: [82, 86]
};

const normalMobilePositions = {
  supervisor: [25, 20],
  safety: [10, 61],
  operations: [29, 61],
  maintenance: [48, 61],
  resource: [67, 61],
  communication: [86, 61]
};

const emergencyMobilePositions = {
  incident_commander: [29, 18],
  safety: [10, 55],
  operations: [29, 55],
  communication: [48, 55],
  supervisor: [62, 86],
  maintenance: [77, 86],
  resource: [90, 86]
};

const $ = (id) => document.getElementById(id);

function init() {
  $("headerIncident").textContent = scenario.id;
  bindControls();
  renderTimeline();
  render();
  window.addEventListener("resize", () => window.requestAnimationFrame(drawReportingLines));
}

function bindControls() {
  $("playButton").addEventListener("click", togglePlayback);
  $("previousButton").addEventListener("click", () => goToStep(runtime.cursor - 1));
  $("nextButton").addEventListener("click", () => goToStep(runtime.cursor + 1));
  $("resetButton").addEventListener("click", resetScenario);
}

function togglePlayback() {
  if (runtime.timer) {
    stopPlayback();
    return;
  }
  if (runtime.cursor >= scenario.steps.length - 1) resetScenario();
  $("playButton").textContent = "Pause Scenario";
  runtime.timer = window.setInterval(() => {
    if (runtime.cursor >= scenario.steps.length - 1) {
      stopPlayback();
      return;
    }
    goToStep(runtime.cursor + 1);
  }, 1050);
}

function stopPlayback() {
  window.clearInterval(runtime.timer);
  runtime.timer = null;
  $("playButton").textContent = "Play Scenario";
}

function resetScenario() {
  stopPlayback();
  runtime.cursor = -1;
  runtime.selectedSequence = null;
  render();
}

function goToStep(index) {
  runtime.cursor = Math.max(-1, Math.min(index, scenario.steps.length - 1));
  runtime.selectedSequence = runtime.cursor >= 0 ? scenario.steps[runtime.cursor].sequence : null;
  render();
  scrollCurrentMessageIntoView();
}

function selectMessage(sequence) {
  runtime.selectedSequence = sequence;
  renderTimeline();
  renderMessageDetail();
}

function render() {
  renderHeader();
  renderProgress();
  renderOrganization();
  renderChangePanel();
  renderTimeline();
  renderMessageDetail();
  renderPhysicalState();
  $("previousButton").disabled = runtime.cursor < 0;
  $("nextButton").disabled = runtime.cursor >= scenario.steps.length - 1;
}

function renderHeader() {
  const step = currentStep();
  $("headerMode").textContent = step ? step.mode : scenario.initial.mode;
  $("headerWorld").textContent = `v${step ? step.worldVersion : scenario.initial.worldVersion}`;
  $("headerOrg").textContent = `v${step ? step.orgVersion : scenario.initial.orgVersion}`;
  $("headerPhase").textContent = step ? step.phase : scenario.initial.phase;
  $("headerMode").className = step && step.mode === "EMERGENCY" ? "emergency-text" : "";
}

function renderProgress() {
  const completed = runtime.cursor + 1;
  const percent = Math.round((completed / scenario.steps.length) * 100);
  $("stepCounter").textContent = completed === 0 ? "BASELINE" : `STEP ${completed} / ${scenario.steps.length}`;
  $("progressPercent").textContent = `${percent}%`;
  $("progressBar").style.width = `${percent}%`;
}

function renderOrganization() {
  const emergency = isEmergency();
  const organization = emergency ? scenario.organization.emergency : scenario.organization.normal;
  const mobile = window.innerWidth <= 720;
  const positions = emergency
    ? (mobile ? emergencyMobilePositions : emergencyPositions)
    : (mobile ? normalMobilePositions : normalPositions);
  const activeRoles = new Set(organization.roles);
  const allRoles = emergency ? Object.keys(emergencyPositions) : organization.roles;
  const transmitting = transmittingRoles();

  $("fromMode").textContent = "NORMAL";
  $("toMode").textContent = emergency ? "EMERGENCY" : "NORMAL";
  $("orgCaption").textContent = emergency ? "EMERGENCY Minimum Organization · org_version 2" : "NORMAL Organization · org_version 1";
  $("communicationIndicator").textContent = transmitting.label;

  $("agentNodes").innerHTML = allRoles.map((role) => {
    const status = agentStatus(role, emergency, activeRoles);
    const position = positions[role];
    const classes = [
      "agent-node",
      role === organization.leader ? "leader" : "",
      status,
      transmitting.roles.has(role) ? "communicating" : ""
    ].filter(Boolean).join(" ");
    return `<div class="${classes}" data-role="${role}" style="left:${position[0]}%;top:${position[1]}%">
      <span class="node-icon">${roleInitials[role]}</span>
      <span class="node-copy"><strong>${roleLabels[role]}</strong><span>${role === organization.leader ? "LEADER" : status.toUpperCase()}</span></span>
    </div>`;
  }).join("");

  window.requestAnimationFrame(drawReportingLines);
}

function drawReportingLines() {
  const svg = $("reportingLines");
  const network = $("orgNetwork");
  const canvas = $("agentNodes");
  if (!svg || !network || !canvas) return;
  const emergency = isEmergency();
  const organization = emergency ? scenario.organization.emergency : scenario.organization.normal;
  const canvasRect = canvas.getBoundingClientRect();
  const current = currentStep();
  svg.setAttribute("viewBox", `0 0 ${canvasRect.width} ${canvasRect.height}`);
  svg.innerHTML = organization.reports.map(([leader, child]) => {
    const from = network.querySelector(`[data-role="${leader}"]`);
    const to = network.querySelector(`[data-role="${child}"]`);
    if (!from || !to) return "";
    const fromRect = from.getBoundingClientRect();
    const toRect = to.getBoundingClientRect();
    const x1 = fromRect.left + fromRect.width / 2 - canvasRect.left;
    const y1 = fromRect.bottom - canvasRect.top;
    const x2 = toRect.left + toRect.width / 2 - canvasRect.left;
    const y2 = toRect.top - canvasRect.top;
    const midY = y1 + (y2 - y1) * .48;
    const active = current && isAgentPair(current.sender, current.recipient, leader, child);
    return `<path class="reporting-line ${active ? "active-route" : ""}" d="M ${x1} ${y1} V ${midY} H ${x2} V ${y2}"></path>`;
  }).join("");
}

function renderChangePanel() {
  const selectorReached = runtime.cursor >= 4;
  const emergency = isEmergency();
  const config = scenario.organization.emergency;
  $("changeTitle").textContent = selectorReached ? "Minimum emergency organization selected" : "Normal operations organization";
  $("triggerValue").textContent = selectorReached ? config.trigger : "No active incident";
  $("reasonValue").textContent = selectorReached ? config.reason : "Routine golf course operations use functional departments under Supervisor.";
  $("capabilityValue").textContent = selectorReached ? config.capabilities.join(", ") : "supervision, safety, operations, maintenance, resource, communication";
  $("selectedValue").textContent = selectorReached ? config.selectedRoles.map(labelRole).join(", ") : scenario.organization.normal.roles.map(labelRole).join(", ");
  $("activatedRoles").textContent = selectorReached ? config.activated.map(labelRole).join(", ") : "None";
  $("retainedRoles").textContent = selectorReached ? config.retained.map(labelRole).join(", ") : "All normal roles";
  $("suspendedRoles").textContent = selectorReached ? config.suspended.map(labelRole).join(", ") : "None";

  const rejection = scenario.proposalRejection;
  const compared = runtime.cursor >= 6;
  const rejected = runtime.cursor >= 7;
  $("proposalWorld").textContent = rejection.proposalWorldVersion;
  $("proposalOrg").textContent = rejection.proposalOrgVersion;
  $("runtimeWorld").textContent = rejection.runtimeWorldVersion;
  $("runtimeOrg").textContent = rejection.runtimeOrgVersion;
  $("gateResult").textContent = rejected ? rejection.result : compared ? "COMPARING" : "WAITING";
  $("gateReason").textContent = rejected ? `${rejection.code} · ${rejection.reason}` : compared ? "ProposalBoard is comparing both version dimensions." : "The old NORMAL proposal will be checked after organization transition.";
  $("proposalGate").classList.toggle("rejected", rejected);
  if (emergency && !rejected) $("gateResult").textContent = "READY";
}

function renderTimeline() {
  $("messageTimeline").innerHTML = scenario.steps.map((step, index) => {
    const statusClass = step.status === "REJECTED" ? "rejected" : step.status === "ACCEPTED" ? "accepted" : "";
    const classes = [
      "message-row",
      index > runtime.cursor ? "future" : "",
      index === runtime.cursor ? "current" : "",
      statusClass
    ].filter(Boolean).join(" ");
    return `<li class="${classes}">
      <button type="button" data-message-sequence="${step.sequence}">
        <span class="message-seq">${String(step.sequence).padStart(2, "0")}</span>
        <span class="message-route"><span class="route-main"><strong>${escapeHtml(step.sender)}</strong><i>→</i><strong>${escapeHtml(step.recipient)}</strong></span><small>${escapeHtml(step.summary)}</small></span>
        <span class="message-type">${escapeHtml(step.type)}</span>
      </button>
    </li>`;
  }).join("");

  document.querySelectorAll("[data-message-sequence]").forEach((button) => {
    button.addEventListener("click", () => selectMessage(Number(button.dataset.messageSequence)));
  });
}

function renderMessageDetail() {
  const step = scenario.steps.find((item) => item.sequence === runtime.selectedSequence);
  if (!step) {
    $("detailStatus").textContent = "BASELINE";
    $("messageDetail").innerHTML = `<div class="empty-detail">播放场景或选择一条消息查看结构化内容。<br><br>所有消息均绑定 world_version 与 org_version。</div>`;
    return;
  }
  const rejected = step.status === "REJECTED" || step.type === "PROPOSAL_REJECTED";
  $("detailStatus").textContent = step.status || (step.sequence <= runtime.cursor + 1 ? "DELIVERED" : "TRACE PREVIEW");
  $("messageDetail").innerHTML = `
    <div class="detail-route"><div class="detail-agent">${escapeHtml(step.sender)}</div><i>→</i><div class="detail-agent">${escapeHtml(step.recipient)}</div></div>
    <span class="detail-type">${escapeHtml(step.type)}</span>
    <p class="detail-summary">${escapeHtml(step.summary)}</p>
    <div class="detail-versions"><div><span>WORLD_VERSION</span><strong>v${step.worldVersion}</strong></div><div><span>ORG_VERSION</span><strong>v${step.orgVersion}</strong></div></div>
    <div class="payload-box"><span>PAYLOAD SUMMARY</span>${payloadRows(step.payload)}</div>
    <div class="result-box ${rejected ? "rejected" : ""}"><span>RESULT / REASON</span><p>${escapeHtml(step.result)}</p></div>`;
}

function renderPhysicalState() {
  const currentState = stateAtCursor();
  const deviceCards = Object.entries(scenario.initial.devices).map(([id, initial]) => {
    const current = currentState.devices[id];
    return `<article class="device-card">
      <header><strong>${id}</strong><span>${initial.type}</span></header>
      <div class="device-delta"><span>${initial.status}</span><i>→</i><span class="current">${current.status}</span></div>
      <div class="device-delta"><span>${initial.zone}</span><i>→</i><span class="current">${current.zone}</span></div>
      <div class="battery-track"><i style="width:${current.battery}%"></i></div>
    </article>`;
  }).join("");
  $("deviceStateGrid").innerHTML = `${deviceCards}
    <article class="runtime-state-card"><span>NEW_TASKS_FROZEN</span><strong>${String(currentState.newTasksFrozen).toUpperCase()}</strong></article>
    <article class="runtime-state-card"><span>CURRENT MODE</span><strong>${currentState.mode}</strong></article>
    <article class="runtime-state-card"><span>CURRENT ORG_VERSION</span><strong>v${currentState.orgVersion}</strong></article>`;
}

function stateAtCursor() {
  const state = {
    mode: scenario.initial.mode,
    orgVersion: scenario.initial.orgVersion,
    newTasksFrozen: scenario.initial.newTasksFrozen,
    devices: JSON.parse(JSON.stringify(scenario.initial.devices))
  };
  scenario.steps.slice(0, runtime.cursor + 1).forEach((step) => {
    state.mode = step.mode;
    state.orgVersion = step.orgVersion;
    if (!step.statePatch) return;
    if (typeof step.statePatch.newTasksFrozen === "boolean") state.newTasksFrozen = step.statePatch.newTasksFrozen;
    Object.entries(step.statePatch.devices || {}).forEach(([id, patch]) => Object.assign(state.devices[id], patch));
  });
  return state;
}

function transmittingRoles() {
  const step = currentStep();
  if (!step) return { roles: new Set(), label: "No active transmission" };
  const roles = new Set([normalizeRole(step.sender), normalizeRole(step.recipient)].filter((role) => roleLabels[role]));
  return { roles, label: `${step.sender} → ${step.recipient}` };
}

function agentStatus(role, emergency, activeRoles) {
  if (!emergency) return "retained";
  if (!activeRoles.has(role)) return "suspended";
  if (scenario.organization.emergency.activated.includes(role)) return "activated";
  return "retained";
}

function isAgentPair(sender, recipient, roleA, roleB) {
  const normalized = [normalizeRole(sender), normalizeRole(recipient)];
  return normalized.includes(roleA) && normalized.includes(roleB);
}

function normalizeRole(value) {
  return String(value).replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase();
}

function labelRole(role) { return roleLabels[role] || role; }
function currentStep() { return runtime.cursor >= 0 ? scenario.steps[runtime.cursor] : null; }
function isEmergency() { return Boolean(currentStep() && currentStep().mode === "EMERGENCY"); }

function payloadRows(payload) {
  return Object.entries(payload).map(([key, value]) => `<div class="payload-row"><code>${escapeHtml(key)}</code><strong>${escapeHtml(formatValue(value))}</strong></div>`).join("");
}

function formatValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function scrollCurrentMessageIntoView() {
  const row = document.querySelector(".message-row.current");
  if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  }[character]));
}

init();
