# Golf Runtime Core 架构说明

## 1. 项目定位

`golf-runtime-core` 是一个面向动态物理环境的多智能体运行时核心。当前实现以高尔夫球场雷暴应急为演示场景，解决以下问题：

- 物理世界状态持续变化时，Agent 的规划结果可能在返回前失效。
- 组织模式变化后，旧组织生成的 Proposal 不能继续执行。
- 安全事件需要绕过慢速规划链，优先执行确定性 Fast Path。
- 外部设备执行成功并不等于 Runtime 已同步成功，两者必须分别验证和记录。
- Proposal、Command、世界版本和组织版本需要可审计、可复核和可幂等执行。

当前项目是 Python 3.9 本地运行时。它提供可选的 StepFun `step-3.7-flash` 模型路由、ROS2 传感/设备传输边界和只读 HTTP 可观测性 UI；测试默认使用离线 fake transport，不依赖网络、ROS2 安装或真实机器人。

## 2. 总体架构

```mermaid
flowchart TB
    EVENT["External Event / Weather Sensor"]
    WORLD["WorldStateKernel\nAuthoritative Physical State"]
    SNAPSHOT["SnapshotManager\nFrozen WorldSnapshot"]
    MODE["ModeManager\nOperatingMode + org_version"]
    FAST["EmergencyFastPath\nDeterministic Safety Policy"]
    NORMAL["NormalOperationsStubPlanner\nNORMAL Agent"]
    EMERGENCY["EmergencyStubPlanner\nEMERGENCY Agent"]
    BOARD["ProposalBoard\nAdmission + Lifecycle"]
    APPROVAL["ApprovalDecision\nHuman Gate"]
    PROPOSAL_EXEC["Proposal Execution\nAction-by-Action Materialization"]
    EXECUTOR["SimpleExecutor\nVersion + Idempotency + Sync"]
    ADAPTER["MockSimulatorAdapter\nExternal Device State"]
    LEDGER["AuditLedger\nAppend-only JSONL"]

    EVENT --> WORLD
    WORLD --> SNAPSHOT
    SNAPSHOT --> FAST
    SNAPSHOT --> NORMAL
    SNAPSHOT --> EMERGENCY
    MODE --> NORMAL
    MODE --> EMERGENCY
    NORMAL --> BOARD
    EMERGENCY --> BOARD
    BOARD --> APPROVAL
    APPROVAL --> PROPOSAL_EXEC
    PROPOSAL_EXEC --> EXECUTOR
    FAST --> EXECUTOR
    EXECUTOR --> ADAPTER
    ADAPTER --> EXECUTOR
    EXECUTOR --> WORLD
    MODE --> LEDGER
    BOARD --> LEDGER
```

## 3. 分层结构

| 层 | 目录 | 主要职责 |
|---|---|---|
| Schema 层 | `runtime_core/schemas` | 定义 frozen 数据契约、状态模型和序列化边界 |
| World 层 | `runtime_core/world` | 管理权威物理状态、世界版本和不可变快照 |
| Organization 层 | `runtime_core/organization` | 管理运行模式、组织版本、角色激活和切换 |
| Coordination 层 | `runtime_core/coordination` | Proposal 准入、去重、版本检查和生命周期失效 |
| Policy 层 | `runtime_core/policies` | 无模型依赖的确定性安全策略 |
| Execution 层 | `runtime_core/execution` | Command 执行、幂等、验证、证据和 Kernel 同步 |
| Adapter 层 | `runtime_core/adapters` | Mock、StepFun 和 ROS2 外部系统边界 |
| Agent 层 | `runtime_core/agents` | 角色约束、生命周期、上下文投影和结构化模型 Handler |
| Orchestration 层 | `runtime_core/orchestration` | 紧急组织内多 Agent 消息编排 |
| Audit 层 | `runtime_core/audit` | 追加式 JSONL 审计记录和校验 |
| Port 层 | `runtime_core/ports` | Planner、模型路由和 Simulator 的抽象接口 |
| Demo 层 | `runtime_core/demo` | Stub Agent 与雷暴端到端编排 |
| Trace/UI 层 | `runtime_core/trace`, `runtime_core/ui` | JSONL 运行轨迹和只读动态 Dashboard |

## 4. 完整目录结构

```text
golf-runtime-core/
├── ARCHITECTURE.md
├── runtime_core/
│   ├── __init__.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── mock_adapter.py
│   │   ├── ros2_equipment_adapter.py
│   │   ├── ros2_sensor_bridge.py
│   │   └── stepfun_model_router.py
│   ├── agents/
│   │   ├── harness.py
│   │   ├── model_handler.py
│   │   ├── lifecycle.py
│   │   └── role_profile.py
│   ├── audit/
│   │   ├── __init__.py
│   │   └── ledger.py
│   ├── coordination/
│   │   ├── __init__.py
│   │   └── proposal_board.py
│   ├── demo/
│   │   ├── __init__.py
│   │   ├── stub_planners.py
│   │   └── thunderstorm_demo.py
│   ├── errors/
│   │   ├── __init__.py
│   │   └── proposal_errors.py
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── proposal_execution.py
│   │   └── simple_executor.py
│   ├── organization/
│   │   ├── __init__.py
│   │   ├── mode_manager.py
│   │   └── org_transition.py
│   ├── policies/
│   │   ├── __init__.py
│   │   ├── emergency_fast_path.py
│   │   ├── human_safety_fast_path.py
│   │   └── person_safety_monitor.py
│   ├── orchestration/
│   │   └── emergency_team.py
│   ├── ports/
│   │   ├── __init__.py
│   │   ├── model_router.py
│   │   ├── planner.py
│   │   └── simulator.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── approval.py
│   │   ├── audit.py
│   │   ├── commands.py
│   │   ├── events.py
│   │   ├── evidence.py
│   │   ├── organization.py
│   │   ├── proposals.py
│   │   ├── person_safety.py
│   │   ├── ros2.py
│   │   └── world_state.py
│   ├── trace/
│   │   └── exporter.py
│   ├── ui/
│   │   ├── projection.py
│   │   ├── server.py
│   │   └── static/
│   └── world/
│       ├── __init__.py
│       ├── snapshot_manager.py
│       ├── state_kernel.py
│       └── version_manager.py
└── tests/
    ├── test_audit_ledger.py
    ├── test_command_schema.py
    ├── test_emergency_fast_path.py
    ├── test_mock_adapter.py
    ├── test_mode_manager.py
    ├── test_org_transition.py
    ├── test_proposal_board.py
    ├── test_proposal_execution.py
    ├── test_proposal_schema.py
    ├── test_simple_executor.py
    ├── test_snapshots.py
    ├── test_stale_organization_proposal.py
    ├── test_stub_planners.py
    ├── test_thunderstorm_demo.py
    └── test_world_state.py
```

## 5. 状态与版本所有权

系统坚持单一写入者原则，避免同一个版本或状态被多个模块独立修改。

| 权威状态 | 唯一所有者 | 读取者 | 更新规则 |
|---|---|---|---|
| `WorldState` | `WorldStateKernel` | Snapshot、Board、Executor、Policy | 真实变化时 `world_version + 1` |
| `OperatingMode` | `ModeManager` | Planner、Board、Executor | 合法模式变化时 `org_version + 1` |
| Proposal 生命周期 | `ProposalBoard` 中的 `StoredProposal` | 审批、执行编排 | 原始 Proposal 永远保持 `CREATED` |
| 外部模拟设备状态 | `MockSimulatorAdapter` | `SimpleExecutor` | Adapter 执行命令后改变 |
| Command 执行结果 | `SimpleExecutor` | Fast Path、Proposal Execution、Demo | 独立 `CommandResult`，不修改原 Command |
| 审计记录 | `AuditLedger` | Demo、测试、运维读取者 | append-only JSONL |

三个重要版本/状态边界：

```text
WorldStateKernel  owns world_version
ModeManager       owns org_version and OperatingMode
ProposalBoard     owns StoredProposal.current_status
```

## 6. 多智能体组织架构

### 6.1 当前角色全集

```text
supervisor
safety
operations
maintenance
resource
communication
incident_commander
logistics
turf_optimizer
cost_optimizer
daily_scheduler
```

`active_roles` 与 `suspended_roles` 不重叠，二者并集始终等于 `registered_roles`。角色不会在组织切换过程中消失。

### 6.2 模式与活跃角色

| 模式 | 组织负责人 | 当前活跃角色 |
|---|---|---|
| `NORMAL` | `supervisor` | supervisor, safety, operations, maintenance, resource, communication |
| `WATCH` | `supervisor` | supervisor, safety, operations, maintenance, resource, communication |
| `EMERGENCY` | `incident_commander` | incident_commander, safety, operations, logistics, communication |
| `RECOVERY` | `incident_commander` | incident_commander, safety, operations, maintenance, logistics, communication |

### 6.3 合法模式转换

```mermaid
stateDiagram-v2
    NORMAL --> WATCH
    WATCH --> NORMAL
    NORMAL --> EMERGENCY
    WATCH --> EMERGENCY
    EMERGENCY --> RECOVERY
    RECOVERY --> NORMAL
    RECOVERY --> EMERGENCY
```

非法转换会写拒绝审计并抛出异常。相同模式请求为 no-op，不增加 `org_version`，也不改变 `activated_at` 或 `transition_id`。

### 6.4 已实现 Agent 与角色槽位的区别

当前代码中已实现并可运行的 Agent/决策组件：

| 组件 | 类型 | 使用角色 | 行为 |
|---|---|---|---|
| `NormalOperationsStubPlanner` | 确定性 Stub Agent | operations | 在 NORMAL/WATCH 生成日常割草 Proposal |
| `EmergencyTeamOrchestrator` | 多 Agent 编排 | incident_commander, safety, operations, communication | 通过版本绑定消息生成结构化部门输出和 Proposal |
| `StructuredModelAgentHandler` | 模型 Agent Handler | 任一 RoleProfile | 通过 ModelRouterPort 请求 Pydantic 结构化输出 |
| `EmergencyFastPath` | 确定性安全策略 | 不依赖 Planner | 雷暴时立即暂停设备并冻结任务 |
| `EmergencyModeAuthorizationPolicy` | 紧急模式人工授权策略 | AuditLedger、ModeManager | 授权审计成功后才允许组织切换 |
| `RouteSafetyPolicy` | 设备移动前的确定性路线安全审查 | 人员坐标、起点、目标点、安全距离 | 输出直达、绕行、终点调整或拒绝；不直接修改设备或 WorldState |
| `MovementAuthorityPolicy` | 多 Agent 设备移动冲突裁决 | Operations、Safety、Maintenance 的结构化意见 | Supervisor 发布最终结果；Safety 拥有安全否决，Maintenance 拥有维修放行权 |
| `HumanSafetyFastPath` | 确定性人员安全策略 | 不依赖 Planner | 有暴露人员时告警人员并保留无人机追踪 |
| `PersonSafetyMonitor` | 感知状态处理器 | 不依赖 Planner | 将人员 ACK 和避难所到达验证写回 Kernel |

`safety`、`operations`、`communication` 已有独立结构化输出契约。`StepFunModelRouter` 实现 `ModelRouterPort`，凭证只从 `STEP_API_KEY` 环境变量读取；确定性 Handler 仍是默认 Demo 路径，避免测试依赖外网。

## 7. Agent 控制面与执行面

```mermaid
flowchart LR
    subgraph CONTROL["Control Plane"]
        MM["ModeManager"]
        PB["ProposalBoard"]
        AL["AuditLedger"]
    end

    subgraph AGENTS["Agent Plane"]
        NP["NORMAL Stub Agent"]
        EP["EMERGENCY Stub Agent"]
        FP["Emergency Fast Path"]
    end

    subgraph EXECUTION["Execution Plane"]
        AP["ApprovalDecision"]
        PE["Proposal Action Executor"]
        SE["SimpleExecutor"]
        MA["MockSimulatorAdapter"]
    end

    subgraph STATE["State Plane"]
        WK["WorldStateKernel"]
        SM["SnapshotManager"]
    end

    WK --> SM
    SM --> NP
    SM --> EP
    SM --> FP
    MM --> NP
    MM --> EP
    NP --> PB
    EP --> PB
    PB --> AP
    AP --> PE
    PE --> SE
    FP --> SE
    SE --> MA
    MA --> SE
    SE --> WK
    MM --> AL
    PB --> AL
```

## 8. 核心数据模型

### 8.1 World State

`WorldState` 包含：

- zones
- people
- machines
- tasks
- routes
- weather
- resource reservations
- `new_tasks_frozen`
- `world_version`
- UTC timestamp

`SnapshotManager` 将其转换为深度不可变的 `FrozenWorldState` 和 `WorldSnapshot`。Planner 只能读取 Snapshot，不能修改权威世界。

### 8.2 Proposal

Proposal 是 Agent 对未来动作的建议，不是可执行命令。

```text
Proposal
├── proposal_id / epoch_id
├── agent_id / agent_role
├── world_version / org_version
├── actions: tuple[ProposalAction, ...]
├── resource_claims
├── confidence / rationale_summary
├── created_at / valid_until
└── status = CREATED
```

原始 `Proposal.status` 始终为 `CREATED`。生命周期由 Board 内部的 `StoredProposal.current_status` 管理。

```mermaid
stateDiagram-v2
    CREATED --> ACCEPTED: submit and audit succeed
    CREATED --> REJECTED: admission check fails
    ACCEPTED --> INVALIDATED: world/org/role becomes stale
    ACCEPTED --> EXPIRED: valid_until reached
```

ProposalBoard 的准入检查包括：

1. duplicate proposal ID
2. world version
3. organization version
4. expiration
5. active role

已接受 Proposal 在执行前通过 `validate_for_use()` 显式复核。普通 `get()` 和 list 接口不会隐式改变生命周期。

### 8.3 Command

Command 是绑定当前版本、可以交给 Adapter 的单条执行指令。

```text
Command
├── command_id
├── incident_id
├── idempotency_key
├── command_type / target_id / parameters
├── source
├── world_version / org_version
├── status = CREATED
└── created_at
```

支持的命令：

- `pause_machine`
- `hold_position`
- `return_to_base`
- `recall_drone`
- `freeze_new_tasks`
- `notify_operator`
- `alert_person`
- `track_person`

幂等键固定为：

```text
{incident_id}:{command_type}:{target_id}
```

同一个 incident 的相同动作不会重复执行，新 incident 可以再次向同一设备发送命令。

## 9. 单条 Command 执行链

```mermaid
sequenceDiagram
    participant Caller
    participant Executor as SimpleExecutor
    participant Mode as ModeManager
    participant Adapter as MockSimulatorAdapter
    participant Kernel as WorldStateKernel

    Caller->>Executor: execute(Command)
    Executor->>Kernel: read world_version
    Executor->>Mode: read org_version
    Executor->>Executor: idempotency check
    Executor->>Adapter: execute_command()
    Adapter-->>Executor: ExecutionReceipt
    Executor->>Adapter: verify_command()
    Adapter-->>Executor: VerificationResult
    Executor->>Adapter: collect_evidence()
    Adapter-->>Executor: Evidence[]
    Executor->>Kernel: synchronize verified effect
    Kernel-->>Executor: committed WorldState
    Executor-->>Caller: CommandResult
```

状态边界：

- MockAdapter 模拟外部设备真实状态。
- WorldStateKernel 是 Runtime 的权威状态。
- 只有 SimpleExecutor 可以完成 Adapter 到 Kernel 的同步链。
- Fast Path 和 Planner 不能直接修改 Adapter 内部状态，也不能绕过 Kernel。

如果 Adapter 已执行但 Kernel 同步失败：

- CommandResult 返回 `UNKNOWN`，不返回 `VERIFIED`。
- message 包含 `ADAPTER_EXECUTED_KERNEL_SYNC_FAILED`。
- Evidence 同时保存 Adapter 结果和 Kernel 同步错误。
- 当前版本不执行复杂回滚。

## 10. Proposal 多 Action 执行

`execute_approved_proposal()` 只在执行开始前调用一次 `ProposalBoard.validate_for_use()`。之后逐条物化 Command：

1. 保存执行开始时的 `execution_org_version`。
2. 每条 Action 前读取当前 OrganizationState。
3. 如果 `org_version` 已变化，停止剩余动作。
4. 读取最新 `world_version`。
5. 将当前 Action 转换成一条 Command。
6. 调用 SimpleExecutor。
7. Command 为 `FAILED` 或 `UNKNOWN` 时 fail-stop。

不能预先批量生成所有 Command，因为前一条 Command 可能主动改变 `world_version`。

## 11. 雷暴端到端流程

```mermaid
sequenceDiagram
    participant Weather
    participant World as WorldStateKernel
    participant Fast as EmergencyFastPath
    participant Normal as NORMAL Agent
    participant Mode as ModeManager
    participant Board as ProposalBoard
    participant Emergency as EMERGENCY Agent
    participant Human as ApprovalDecision
    participant Exec as SimpleExecutor
    participant Device as MockAdapter

    Weather->>World: thunderstorm event
    World->>Fast: latest snapshot
    Fast->>Exec: pause mowers / freeze tasks
    Fast->>Exec: alert exposed person / track with drone
    Exec->>Device: execute and verify
    Exec->>World: synchronize effects
    World->>Normal: snapshot W + org_version 1
    Normal-->>Board: delayed Proposal not submitted yet
    Mode->>Mode: NORMAL to EMERGENCY
    Note over Mode: org_version 1 to 2
    Normal->>Board: submit Proposal W / org_version 1
    Board-->>Normal: STALE_ORGANIZATION_VERSION
    World->>Emergency: snapshot W + org_version 2
    Emergency->>Board: emergency Proposal
    Board-->>Emergency: ACCEPTED
    Board->>Board: validate_for_use = ACCEPTED
    Human->>Exec: approve Proposal
    Exec->>Device: hold / return / notify
    Exec->>World: synchronize final state
```

关键时序保证：NORMAL Proposal 在 Fast Path 完成后创建；组织切换后、旧 Proposal 提交前不再修改 WorldState。因此：

```text
proposal.world_version == current.world_version
proposal.org_version   != current.org_version
```

拒绝原因稳定为 `STALE_ORGANIZATION_VERSION`，而不是 `STALE_WORLD_VERSION`。

## 12. 雷暴 Demo 最终状态

自动批准时：

| 对象 | 最终状态 |
|---|---|
| mower_1 | `holding`，保持在 zone_B |
| mower_2 | `idle`，位于 maintenance_base |
| drone_1 | `tracking_person`，保留在 zone_C |
| player_1 | `alerted`，等待 ACK 或到达验证 |
| new tasks | frozen |
| organization | EMERGENCY / org_version 2 |

拒绝人工审批时：

- Emergency Proposal 仍然可以被接受。
- 不执行后续 hold/return/notify Actions。
- mower_1 和 mower_2 保持 Fast Path 产生的 paused 状态。
- drone_1 继续执行人员追踪，不因后续 Proposal 被拒而返航。
- 系统仍处于 EMERGENCY，且新任务保持冻结。

## 13. 审计架构

AuditLedger 是带 checksum 的 append-only JSONL 文件。当前记录类型包括：

- `ORGANIZATION_TRANSITION`
- `ORGANIZATION_TRANSITION_REJECTED`
- `ORGANIZATION_TRANSITION_NO_OP`
- `PROPOSAL_ACCEPTED`
- `PROPOSAL_REJECTED`
- `PROPOSAL_INVALIDATED`

组织切换与 Proposal 生命周期都采用“先写 Ledger，后发布内存状态”的顺序。Ledger 失败时：

- 组织状态不切换。
- Proposal 不接受、不拒绝、不失效。
- proposal ID 不会因失败审计而被占用。

这是单进程内存状态与本地 JSONL Ledger 的一致性边界，不声称是分布式事务。

## 14. 关键安全不变量

1. WorldState 只能由 WorldStateKernel 提交。
2. OperatingMode 和 org_version 只能由 ModeManager 分配。
3. 原始 Proposal 和 Command 都是 frozen，状态变化保存在独立结果模型。
4. 所有关键 datetime 必须 timezone-aware，并规范化到 UTC。
5. 非法更新、重复事件、no-op 都不能错误增加 world_version。
6. Ledger append 失败不能发布对应组织或 Proposal 状态。
7. 旧 world/org version 的 Command 不能到达 Adapter。
8. 同 incident 的同逻辑 Command 只执行一次。
9. Adapter 已执行但 Kernel 同步失败时必须返回 UNKNOWN。
10. 公开读取接口不返回内部可变容器引用。

## 15. 测试结构

当前测试覆盖：

- WorldState 原子更新、版本规则、事件去重
- Frozen Snapshot 深度不可变和 JSON 往返
- 模式转换矩阵、角色不变量和 Ledger 失败边界
- Proposal Schema、准入、重复 ID 和显式失效
- Command/Evidence Schema 和 UTC 规则
- MockAdapter 命令、失败与无回传
- SimpleExecutor 版本检查、幂等和同步失败
- Emergency Fast Path 最终安全状态
- Stub Planner 模式约束和版本绑定
- Approval、逐 Action 最新版本执行和 fail-stop
- 雷暴 Demo 自动批准与拒绝路径
- StepFun 严格 JSON Schema 输出与 AgentHarness 接线
- 人员告警、无人机追踪、ACK 和避难到达验证
- ROS2 Sensor Bridge、Equipment Adapter 和 Kernel 同步
- runtime_trace.jsonl 导出、HTTP 服务和 UI 投影

完整测试命令：

```bash
cd /Users/zhiqihao/Documents/DGX/golf-runtime-core
python3 -m pytest -q
```

当前基线为 `145 passed`。

## 16. 运行 Demo

自动批准：

```bash
python3 -m runtime_core.demo.thunderstorm_demo
```

拒绝后续动作：

```bash
python3 -m runtime_core.demo.thunderstorm_demo --reject
```

CLI 会明确输出：

```text
ORGANIZATION SWITCHED: org_version 1 -> 2
OLD PROPOSAL REJECTED: STALE_ORGANIZATION_VERSION
EMERGENCY PROPOSAL ACCEPTED
HUMAN APPROVAL: APPROVED or REJECTED
```

### 16.1 运行 Dashboard

```bash
python3 -m runtime_core.ui.server --port 8765
```

当前交互演示由 `scenario.js` 中的 Mock Isaac telemetry、设备状态和 evidence 驱动，并明确显示 `MOCK CONNECTED` / `MOCK INPUT`。页面以 WeChat 风格的运行时通讯入口和实时 Mock Isaac 世界为核心，不显示线性阶段列表；状态变化通过 Agent 消息、地图坐标、设备 telemetry 和执行 Evidence 呈现。工作人员可查询世界、人员和设备状态，并通过聊天文本或消息内授权卡确认组织切换。服务仍提供 `/runtime_trace.jsonl`，后续可通过标准化 adapter 替换 mock 数据和通讯 transport，而不改变 WorldStateKernel、ModeManager、ProposalBoard 或 SimpleExecutor 的职责。

### 16.2 启用 StepFun Agent Handler

设置 `STEP_API_KEY` 后，UI Server 会创建 `StepFunModelRouter`。工作人员消息通过 `/api/chat` 提交只读的 mode、双版本号、阶段和设备摘要，并要求模型返回 `RuntimeChatReply` 结构化结果；`/api/model-status` 暴露不含凭证的配置状态。未配置或模型请求失败时 UI 明确显示 `MOCK FALLBACK`。API key 不进入 schema、日志、trace 或仓库；模型没有 Kernel、ModeManager、ProposalBoard 或 Executor 写权限，明确授权仍由确定性逻辑处理。

UI 场景在人工授权前采用指令驱动，不使用定时自动播放。StepFun 负责基于只读现场上下文生成自然语言回复；确定性命令解析器从工作人员原文生成受控 `RuntimeChatIntent`，并且对控制意图拥有最终权威。模型误报写意图时记录 `MODEL INTENT BLOCKED`，模型漏报明确命令时记录 `MODEL INTENT CORRECTED`。前端随后依据当前 Runtime 状态校验允许的转换；重复、无目标或缺少明确授权的控制指令不会改变版本或设备状态。人工确认紧急模式后，组织提交、Agent 协作、Proposal 准入和 Mock Isaac 执行结果通过消息与 Evidence 呈现。

紧急授权是高层复合指令：活动雷暴已经进入 Runtime 后，工作人员可以直接授权“进入紧急状态”。UI 会先补齐风险判断、最小紧急组织建议和授权记录，再提交组织切换；它不会要求工作人员手工逐步推进 05、06、07。没有活动紧急事件时，同一授权请求会被拒绝。

Mock 雷暴信号进入后，确定性 Safety Policy 会自动完成风险判断和最小组织建议，并停在人工授权门。此时不会切换 OperatingMode，也不会发布新的 OrganizationState；工作人员通过 Policy 授权卡批准后，才进入授权审计和 `ModeManager` 组织切换。

日常巡检支持带目标区域的设备指令，例如“前往 B 区巡检”。该指令被解析为 `REDIRECT_INSPECTION`，由演示中的 Mock Adapter 更新无人机位置并验证，再增加 UI Runtime 的 `world_version`、写入动态 Evidence；它不会切换组织模式，也不会绕过紧急事件期间 Safety Agent 对无人机的调度权。

割草机“返回/回家”指令被解析为 `RETURN_MACHINE_TO_BASE`，产生中断作业、返回途中和到达维护区的可观测状态，并实时更新地图坐标、telemetry、Evidence 和 `world_version`。全部安全目标到达指定位置后，位置复核停止。工作人员发出“解除警报/恢复日常”时，恢复策略驱动 `EMERGENCY → RECOVERY → NORMAL`，关闭 incident 并恢复日常设备任务。

工作人员连续下达的聊天命令进入单一串行队列，前一条模型调用和 Runtime 动作完成后才处理下一条。无人机区域指派选择原文中最后一个目标区域，因此“完成 C 区后再去 A 区”会转派到 A；`ASSIGN_MOWING_ZONE` 支持将位于 Maintenance 的割草机重新派往指定 Fairway，并经过 `TRANSITING → MOWING` 的 Adapter 验证链。

所有无人机和割草机移动在 Adapter 执行前都经过 `RouteSafetyPolicy`。Policy 使用设备起点、目标点和最新人员坐标检查线段净空；无人机默认保持 10 个场地坐标单位，割草机保持 8 个单位。目标点过近时先在目标区域内调整安全终点，直线路径不安全时生成绕行点，仍无法满足净空则拒绝命令。演示执行器按 waypoint 逐段移动，每段出发前重新读取人员位置；复核失败时设备进入 `HOLDING`，不会写入虚假的到达状态。路线结论、每段位置 ACK 和 Kernel 版本同步均写入 Evidence。

C 区灌溉故障被发现后，割草机跨区指令先进入 `MovementAuthorityPolicy`。Operations 可以提出继续割草，Safety 可以基于湿滑和地面稳定性风险行使停机否决，Maintenance 负责判断是否已经完成隔离与检查。Supervisor 是最终结果的唯一发布者，但其规则顺序为 `SAFETY_VETO > MAINTENANCE_CLEARANCE > OPERATIONS_CONTINUITY`，不能覆盖未解除的安全否决或伪造维修放行。受影响路线返回 `HOLD_FOR_INSPECTION`，随后只有 SimpleExecutor 执行停机并把验证结果同步到 Kernel。

工作人员明确确认 C 区维修完成时，命令被确定性识别为 `CLEAR_MAINTENANCE_HAZARD`，不会与雷暴 `CLEAR_EMERGENCY` 混用。Maintenance 先提交修复和压力测试证据，Safety 据此解除区域否决，Supervisor 发布 C 区重新开放；危险状态和安全区域内被暂停设备的恢复在一次世界状态提交中使 `world_version + 1`。被拒绝的旧跨区命令不会自动重放，工作人员必须重新下达，新的移动仍需经过人员净空和路线检查。

维修放行识别采用受控组合语义，不依赖单一固定句子：区域必须明确为 C 区、C 球道、Zone C 或 Fairway C，同时必须出现修好、修复完成、检修完毕、故障解除等完成式表达。“需要修复”之类计划表达不会触发放行。Mock Isaac 地图为每个设备保留稳定 DOM 节点，只更新位置和状态，因此雷暴撤离的 `EVACUATING → SHELTERED`、返回的 `RETURNING → PARKED` 和无人机跟踪过程会产生连续位置变化，而不会因重建节点丢失动画。

同一个 Router 也可注入 `StructuredModelAgentHandler`，再由对应 `AgentHarness` 使用。模型输出必须完整通过目标 Pydantic schema 才能返回调用者。

### 16.3 ROS2 接入

`Ros2SensorBridge` 将 `/golf/weather`、设备 telemetry、人员 telemetry 和区域状态映射为 Kernel Event。`Ros2EquipmentAdapter` 依赖注入的 `Ros2CommandTransportPort` 发布命令并接收 ACK/观测；只有 `SimpleExecutor` 能把已验证观测同步到 WorldStateKernel。

## 17. 当前未实现的边界

以下能力仍是未来扩展，不属于当前代码现状：

- DGX/vLLM 模型服务连接
- Isaac Sim 连接
- 具体 `rclpy` Node/Action Client 部署（当前通过注入式 ROS2 transport port 接入）
- 人员身份认证、手机/穿戴设备 ACK transport 和真实避难所定位源
- CapabilityRegistry
- PolicyVersionProvider
- 复杂 PlanComposer 和 ConflictResolver
- 多级人工审批
- 分布式事务和恢复协议
- 动态组织搜索算法
- `MinimalOrganizationSelector` 推荐四角色，但 ModeManager 当前 EMERGENCY 配置还包含 logistics；需要统一配置来源

这些扩展应通过现有 Port、Proposal、Command 和版本所有权边界接入，而不绕过 WorldStateKernel、ModeManager、ProposalBoard 或 SimpleExecutor。
