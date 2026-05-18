# CollabBoard：基于 WebSocket 的实时协作白板系统

## 文档信息

| 项目 | 内容 |
|------|------|
| 项目名称 | CollabBoard |
| 文档类型 | 项目总说明（设计基线 + 实现说明） |
| 设计文档完成 | 2026-04-14 |
| 实现联调版本 | 2026-05 |
| 运行环境 | Python 3、FastAPI、WebSocket；浏览器端 HTML5 Canvas |

---

## 摘要

CollabBoard 是一套面向多终端的实时协作白板系统。客户端通过 WebSocket 与中心服务器建立长连接，在逻辑房间（Room）内发送结构化 JSON 消息，完成加入/离开、笔划绘制、标注管理、画布清空等协作操作。服务器对入站消息进行模式校验、幂等去重与速率限制，将需要广播的操作写入房间级事件历史并分配单调递增的 `sequence_id`；各客户端按序重放事件，在局部维护画布与标注状态，从而达到最终一致的多端视图。

系统在 2026 年 4 月完成协议、状态机与分层架构的设计文档（见仓库内 `00`～`04` 系列文件）；同年 5 月完成与 design 对齐的后端服务、浏览器前端及自动化测试，形成可重复演示的端到端原型。

---

## 1. 项目概述

### 1.1 问题定义

多用户同时在数字白板上绘图时，需要解决三类问题：（1）操作如何在网络中可靠传递；（2）各端画布如何保持语义一致；（3）房间与用户的生命周期、权限边界如何界定。本课题以自研应用层协议和显式状态机为核心，在单进程异步后端上实现可验证的协作语义，而非依赖第三方实时协作 SaaS。

### 1.2 建设目标

- 定义统一、可校验的 WebSocket 消息格式及客户端/服务端消息类型集合；
- 采用事件溯源思路维护房间 `canvas_history`，以全局序列号约束广播顺序；
- 对用户连接、入会、活跃、离开、断线等阶段建立有限状态模型，对房间建立独立状态模型；
- 实现绘制、橡皮、撤销/恢复、文字与公式标注、标注删除协商、多人清空表决等业务；
- 支持 PC 与移动浏览器跨分辨率下的相对坐标一致（归一化坐标）；
- 在会话层约束 Connection ID、房间内 User ID 与 User Name 的唯一性；
- 提供单元测试与集成测试，覆盖协议、路由、会话排他及典型协作路径。

### 1.3 技术选型

| 层次 | 技术 |
|------|------|
| 传输 | WebSocket（RFC 6455） |
| 服务端框架 | FastAPI + Uvicorn |
| 并发模型 | asyncio |
| 消息校验 | JSON Schema（Draft-07） |
| 客户端 | 原生 JavaScript（ES Module）、Canvas 2D、无前端框架依赖 |
| 测试 | pytest、httpx TestClient |

---

## 2. 系统架构

### 2.1 逻辑分层

系统分为接入层、路由层、领域管理层与消息处理层。接入层负责 WebSocket 接受、连接注册及出站发送；路由层解析 JSON、执行基础不变量检查、去重、限流并分发至处理器；领域管理层包含连接索引、房间与事件历史、用户/房间状态机；处理层按消息类型实现具体业务。

```
┌─────────────────────────────────────────────────────────┐
│  Browser (frontend/)                                     │
│  app.js · canvas.js · protocol.js · annotation-layer.js  │
└───────────────────────────┬─────────────────────────────┘
                            │ WebSocket /ws/{connection_id}
┌───────────────────────────▼─────────────────────────────┐
│  backend/main.py                                         │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│  MessageRouter (core/message_router.py)                  │
│  解析 · Schema · 去重 · 限流 · 分发                       │
└───────────────────────────┬─────────────────────────────┘
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
 ConnectionManager    RoomManager         StateManager
        │                   │                   │
        └───────────────────┴───────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        ▼                                       ▼
 join / leave / draw / annotation / clear /     …
 state_sync / draw_undo / draw_redo /           (handlers/)
 annotation_delete_* / clear_propose / clear_vote
```

详细模块职责与数据流见 `03_ARCHITECTURE_DESIGN.md`。

### 2.2 核心模块说明

**ConnectionManager**  
维护 `connection_id → WebSocket` 映射、按 `user_id` 反查连接、按 `room_id` 索引同房间连接集合；提供单播 `send` 与房间广播 `broadcast`（支持 `exclude_user_id`）。

**RoomManager**  
管理房间实体：成员集合 `users`、用户元数据 `user_metadata`、单调递增的 `current_sequence`、追加式 `canvas_history`、清空提案与标注删除请求等辅助状态；提供快照 `get_snapshot` 与增量 `get_events_since` 供 `STATE_SYNC` 使用。

**StateManager**  
实现用户八态（INIT、CONNECTED、JOINED、ACTIVE、IDLE、TIMEOUT、LEFT、DISCONNECTED）与房间四态（PENDING_INIT、ACTIVE、IDLE、DESTROYED）的转移规则；`validate_user_action` 在路由前判定当前状态是否允许某类客户端消息；`apply_timeouts` 由后台维护任务周期调用。实现中对「WebSocket 仍在线」的连接豁免因空闲导致的强制断开会话，并在入站消息前尝试 `restore_room_session`，避免连接未断而状态已失效的不一致。

**MessageRouter**  
不依赖具体 Handler 实现以避免循环引用；通过构造注入 Handler 映射表。维护 per-connection 令牌桶与全局 `msg_id` 去重缓存（默认 TTL 300s）。

**Handlers**  
每种客户端 `type` 对应独立模块（共 15 类业务处理器及错误构造工具），负责校验权限、更新房间状态、生成 ACK 与 `BroadcastInstruction` 列表。

### 2.3 仓库目录结构

| 路径 | 职责 |
|------|------|
| `backend/main.py` | 应用入口、WebSocket 端点、静态资源挂载、断线清理 |
| `backend/core/` | models、schemas、message_router、connection_manager、room_manager、state_manager、config |
| `backend/handlers/` | 各消息类型处理器 |
| `backend/tests/` | 协议、管理器、处理器、集成、会话规则测试 |
| `backend/run.bat` | Windows 下启动脚本（默认 `0.0.0.0:8000`） |
| `frontend/` | 协议封装、画布与标注、会话 UI |
| `docs/BACKEND_QUICKSTART.md` | 依赖安装、启动与测试命令 |
| `00_RESEARCH_PLAN_SUMMARY.md` | 研究计划与设计决策总览 |
| `01_PROTOCOL_SPECIFICATION.md` | 协议规范全文 |
| `02_STATE_MACHINE_DESIGN.md` | 状态机设计全文 |
| `03_ARCHITECTURE_DESIGN.md` | 架构设计全文 |
| `04_IMPLEMENTATION_PLAN.md` | 分阶段实现计划 |
| `README_QUICK_REFERENCE.md` | 错误码、配置与流程速查 |

---

## 3. 通信协议与一致性

### 3.1 消息信封

所有客户端请求与服务端响应（含广播）共享下列顶层字段（见 `01_PROTOCOL_SPECIFICATION.md` §3）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `msg_id` | UUID 字符串 | 客户端生成，用于幂等 |
| `type` | 枚举字符串 | 消息类型 |
| `timestamp` | 数值 | 毫秒时间戳，服务端校验容差 |
| `user_id` | 字符串 | 逻辑用户标识 |
| `room_id` | 字符串 | 房间标识 |
| `sequence_id` | 整数或 null | 客户端请求为 null；广播由服务端填写 |
| `payload` | 对象 | 类型相关载荷 |

服务端在路由前调用 `validate_client_message`（`backend/core/schemas.py`），对 `type` 与 `payload` 分别套用 JSON Schema。

### 3.2 请求—响应与广播

- 客户端操作类消息（如 `join`、`draw`）经 Handler 处理后，向发起连接返回单条 `ack` 或 `error`。
- 需同步至房间内其他成员的操作，额外产生 `broadcast`，其中 `payload.event_type` 描述领域事件（如 `draw`、`annotation_removed`、`user_joined`）。
- 广播写入 `canvas_history` 时分配 `sequence_id`，从 0 起单调递增；清空类事件会截断历史（见 RoomManager.append_event）。

### 3.3 客户端有序重放

前端维护 `lastReceivedSequence` 与待处理广播队列：仅当 `sequence_id === lastReceivedSequence + 1`（或初始同步后的首条 0）时调用 `applyBroadcast`；否则缓冲或丢弃重复序号。加入房间时通过 JOIN 的 `room_state.canvas_history` 全量重放；之后可通过 `state_sync` 拉取 `last_received_sequence` 之后的增量。该机制保证各端在相同事件序列下得到相同笔划与标注可见性结论。

### 3.4 可靠性机制

| 机制 | 实现要点 |
|------|----------|
| 幂等 | Router 层 `msg_id` 去重，重复请求仅回放首次 ACK/ERROR |
| 限流 | 每连接令牌桶；房间级事件速率桶 |
| 时间戳 | 可配置容差（默认 30s），拒绝明显漂移报文 |
| 断线恢复 | `STATE_SYNC`；在线连接会话恢复；周期心跳 `state_sync`（前端 60s） |
| 消息大小 | 默认上限 64KB（RouterConfig） |

### 3.5 已实现客户端消息类型

`join`, `leave`, `draw`, `draw_undo`, `draw_redo`, `annotation`, `annotation_delete`, `annotation_delete_request`, `annotation_delete_vote`, `annotation_restore`, `clear`, `clear_propose`, `clear_vote`, `state_sync`。

主要广播 `event_type` 包括：`draw`, `stroke_undone`, `annotation`, `annotation_removed`, `annotation_delete_requested`, `annotation_delete_rejected`, `user_joined`, `user_left`, `clear`, `clear_propose`, `clear_rejected`, `clear_proposal_cancelled`, `clear_proposal_expired`, `room_idle` 等。完整定义见 `01_PROTOCOL_SPECIFICATION.md`。

### 3.6 错误码

系统定义 `INVALID_MESSAGE`, `ROOM_NOT_FOUND`, `UNAUTHORIZED`, `RATE_LIMIT`, `USER_ALREADY_JOINED`, `CONNECTION_ALREADY_EXISTS` 及清空/标注相关专用码。Handler 与 Router 通过 `ErrorBuilder` 构造统一结构的 `error` 响应。速查表见 `README_QUICK_REFERENCE.md`。

---

## 4. 状态机

### 4.1 用户状态

用户状态机用于约束「在未满足前置状态时拒绝业务消息」。典型路径：WebSocket 建立后 `on_connected` → `CONNECTED`；`join` 成功 → `JOINED`；首次绘制等活动 → `ACTIVE`；长时间无活动可转入 `IDLE`；`leave` 或断线清理 → `LEFT` / `DISCONNECTED`。`TIMEOUT` 为中间态，实现中可紧接 `DISCONNECTED`。

配置项（`backend/config.py`，支持环境变量覆盖）包括：`USER_JOIN_GRACE_SECONDS`、`USER_JOINED_IDLE_SECONDS`、`USER_ACTIVE_IDLE_SECONDS`、`USER_IDLE_TIMEOUT_SECONDS` 等。详见 `02_STATE_MACHINE_DESIGN.md`。

### 4.2 房间状态

房间在首个成员加入时由 `PENDING_INIT` 进入 `ACTIVE`；最后成员离开后进入 `IDLE` 并启动空闲 TTL，到期可销毁（`DESTROYED`）。成员再次加入时从 `IDLE` 回到 `ACTIVE`。房间状态与用户状态正交，由 RoomManager 与 Leave/Join 逻辑协同维护。

---

## 5. 功能实现说明

### 5.1 房间与会话

- **加入**：`JoinHandler` 校验 StateManager、跨房占用、房间内 User ID / User Name 唯一（名称比较前 `strip` 且 `casefold`）、Connection 层同房间占用；成功后写入成员集、广播 `user_joined`、返回含 `active_users` 与 `canvas_history` 的快照。
- **离开**：`LeaveHandler` 更新状态机、移出成员、广播 `user_left`；若房间为空则广播 `room_idle`。
- **排他规则**  
  - `connection_id`：全局唯一，重复连接在 accept 阶段关闭。  
  - `user_id`：同一时刻仅允许处于一个房间；同一房间内不可两名成员使用相同 `user_id`。  
  - `user_name`：同一房间内显示名不可重复（不区分大小写）。  
- **断线**：`main.py` 的 `finally` 块调用 `_cleanup_disconnected_user`，同步 `on_leave` 与 `room_manager.leave`。

### 5.2 绘制与坐标

- 笔划以 `stroke_id` 标识，点列中 `x`,`y` 为相对画布的 **[0,1] 归一化坐标**；线宽 `width` 仍为协议规定的像素语义值，不参与归一化。
- 前端在本地屏幕尺寸下换算绘制，使不同分辨率设备上相对位置一致。
- 支持 `draw_undo` / `draw_redo`（广播 `stroke_undone` 或重新 `draw`）。

### 5.3 标注

- `annotation` 支持 `text` 与 `formula` 模式；内容长度与字号受 `config` 约束；禁止危险子串（Schema 层）。
- 作者可 `annotation_delete`；他人须 `annotation_delete_request`，作者在有效期内 `annotation_delete_vote`（`approve` / `reject`）；通过后广播 `annotation_removed`。
- `annotation_restore` 可在删除后由原作者恢复（重放 `annotation` 事件）。

### 5.4 清空画布

- 单成员房间可直接 `clear`。
- 多成员须 `clear_propose`，各成员 `clear_vote`；全部同意后方广播 `clear` 并清空 `canvas_history` 中的笔划事件（标注策略见协议 § 清空与标注关系）。

### 5.5 前端行为概要

- 模块划分：`protocol.js`（组包）、`state.js`（会话状态）、`canvas.js`（笔划）、`annotation-layer.js`（标注 DOM）、`board-coords.js`（坐标变换）、`app.js`（WebSocket 与 UI 逻辑）。
- Join 成功后锁定身份输入；Leave 清空事件日志与本地撤销栈；Diagnostics 显示房间与成员摘要。
- 成员列表由 `active_users` 与 `user_joined` / `user_left` 维护；历史重放时从 `canvas_history` 重建成员与标注。

---

## 6. 测试与验证

测试目录：`backend/tests/`。

| 测试模块 | 覆盖范围 |
|----------|----------|
| `test_protocol.py` | JSON Schema、非法 UUID、标注内容约束等 |
| `test_state_manager.py` | 用户状态转移、空闲超时、在线豁免 |
| `test_handlers.py` | Join/Draw 路由、去重、标注删除请求路由 |
| `test_session_logic.py` | 跨房拒绝、Connection/User 重复、房间内 User Name 重复 |
| `test_integration.py` | WebSocket 双客户端 Join、绘制、标注删除权限 |
| `test_managers.py` | ConnectionManager 广播与索引 |

执行命令：

```powershell
cd d:\Vscode_python\Collaboard
python -m pytest backend\tests -q
```

当前自动化测试结果：33 passed，1 skipped（以仓库内最后一次 pytest 为准）。

---

## 7. 部署与运行

### 7.1 依赖安装

```powershell
cd d:\Vscode_python\Collaboard
python -m pip install -r backend\requirements.txt
```

### 7.2 启动服务

```powershell
backend\run.bat
```

默认监听 `0.0.0.0:8000`。浏览器访问 `http://127.0.0.1:8000/`；局域网内其他设备须使用主机局域网 IP，且 Server URL 配置为 `ws://<主机IP>:8000/ws`（前端可自动补全协议前缀）。

仅本地回环访问时可设置环境变量 `COLLABOARD_HOST=127.0.0.1`。详见 `docs/BACKEND_QUICKSTART.md`。

### 7.3 多端联调参数示例

| 字段 | 设备 A | 设备 B |
|------|--------|--------|
| Connection ID | `conn-a` | `conn-b` |
| User ID | `user-a` | `user-b` |
| User Name | `A` | `B` |
| Room ID | 相同，如 `room-1` | 相同 |

### 7.4 健康检查

`GET /health` 返回 `{"status":"ok"}`。

---

## 8. 设计文档与实现阶段对照

2026-04-14 完成的五份设计文档构成实现的规范基线。`04_IMPLEMENTATION_PLAN.md` 将工作划分为五个 Phase；截至 2026-05 的实现情况如下。

| 阶段 | 计划内容 | 实现情况 |
|------|----------|----------|
| Phase 1 | FastAPI/WebSocket、Schema、三管理器、Router 框架 | 已完成 |
| Phase 2 | Join/Leave/Draw/Clear/StateSync、状态机、历史与清理 | 已完成；并扩展 undo/redo、标注与表决类消息 |
| Phase 3 | 前端连接、Canvas、有序重放、基础 UI | 已完成；含归一化坐标与协作模态 |
| Phase 4 | 单元/集成测试 | 已完成基础集；大规模压测与 E2E 未开展 |
| Phase 5 | 部署、监控、安全加固 | 未系统化完成；保留为后续工作 |

设计阶段交付物（协议完整定义、状态机、架构分层、实现路线图、约 3350 行设计正文）均保留在仓库中；代码实现以设计为准，局部行为（如在线空闲策略、房间内名称唯一）在实现阶段根据联调结果增补，协议层通过 `reason` 字段区分 `duplicate_user_id_in_room` 与 `duplicate_user_name_in_room` 等错误语义。

---

## 9. 后续工作

- 持久化：将 `canvas_history` 与房间元数据落盘或接入数据库，支持进程重启恢复；
- 安全：鉴权、`security` 信封字段的完整校验与密钥管理；
- 性能：大规模房间与高频绘制下的压测与水平扩展方案；
- 运维：结构化日志、指标采集、配置外置；
- 前端：自动化 E2E（Playwright 等）覆盖双端协作路径；
- 文档：保持 `01`～`04` 与代码变更同步修订。

---

## 10. 版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-04-14 | 完成研究计划、协议、状态机、架构、实现计划及快速参考文档 |
| 2.0 | 2026-05-18 | 完成后端与前端联调、协作规则与测试集；本 README 作为项目总说明定稿 |

---

## 参考文献与延伸阅读（仓库内）

1. `00_RESEARCH_PLAN_SUMMARY.md` — 设计目标、原则与交互序列总览  
2. `01_PROTOCOL_SPECIFICATION.md` — 消息与事件规范  
3. `02_STATE_MACHINE_DESIGN.md` — 用户与房间状态机  
4. `03_ARCHITECTURE_DESIGN.md` — 模块划分与数据流  
5. `04_IMPLEMENTATION_PLAN.md` — 分阶段计划与检查清单  
6. `README_QUICK_REFERENCE.md` — 实现期速查  
7. `docs/BACKEND_QUICKSTART.md` — 运行与测试说明  
8. `frontend/README.md` — 前端模块与启动方式  

外部标准：WebSocket（RFC 6455）、JSON Schema（https://json-schema.org/）、FastAPI 官方文档。
