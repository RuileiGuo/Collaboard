# CollabBoard — 实时协作白板（汇报版 README）

**项目名称**：CollabBoard（协作白板）  
**文档基线**：2026-04-14 设计文档集（`00`～`04` + 快速参考）  
**实现状态**：**可演示版本**（后端 + 前端已联调，2026-05 持续迭代）  
**技术栈**：Python 3 · FastAPI · WebSocket · Vanilla JS · HTML5 Canvas  

> **给老师汇报时怎么用本文档**  
> 按下面 **「§ 一、五分钟口头汇报稿」** 讲即可；需要展开技术细节时，跳到对应章节或打开链接的设计 md。  
> **现场演示** 比念文档更重要，请提前按 **§ 六** 练一遍双设备同房间。

---

## 一、五分钟口头汇报稿（可直接照着说）

### 1. 做什么（30 秒）

CollabBoard 是一个**多人在线协作白板**：多台设备通过 WebSocket 连到同一后端，进入**同一房间**后，可以实时看到彼此的笔画、文字/公式标注，并支持清空表决、删除他人标注需对方同意等协作规则。

### 2. 怎么保证多人不乱（1 分钟）

我采用**事件驱动 + 全局序列号**模型（详见 `01_PROTOCOL_SPECIFICATION.md`）：

- 客户端发 `JOIN` / `DRAW` / `ANNOTATION` 等请求，服务器校验后回复 `ACK` 或 `ERROR`。
- 需要同步给他人的操作，服务器再发 `BROADCAST`，并分配递增的 **`sequence_id`**。
- 各端按 `sequence_id` 顺序重放 `canvas_history`，保证最终画布一致。
- 另有 **`msg_id` 去重**、**JSON Schema 校验**、**令牌桶限流**，以及用户/房间**显式状态机**（`02_STATE_MACHINE_DESIGN.md`）。

### 3. 系统架构（1 分钟）

分层与模块对应 `03_ARCHITECTURE_DESIGN.md`，代码在仓库里已落地：

```text
浏览器 (frontend/*.js)
    │  WebSocket  JSON 消息
    ▼
FastAPI (backend/main.py)  —  /ws/{connection_id}
    │
    ▼
MessageRouter (core/message_router.py)  —  校验 / 去重 / 限流 / 路由
    │
    ├── ConnectionManager   —  连接、房间广播
    ├── RoomManager         —  房间成员、事件历史、快照
    ├── StateManager        —  用户状态机、空闲与恢复
    └── Handlers (backend/handlers/*.py)  —  join / draw / annotation / clear / …
```

### 4. 已实现功能（1.5 分钟）

| 类别 | 能力 |
|------|------|
| 连接与房间 | Join / Leave；`STATE_SYNC` 补事件；断线清理 |
| 绘制 | 画笔/橡皮；笔划广播；`draw_undo` / `draw_redo` |
| 标注 | 文字 / LaTeX 公式；本人删除；**申请删除他人标注 + 对方弹窗表决** |
| 清空 | 多人房间需 `clear_propose` + `clear_vote` 全体同意 |
| 多端对齐 | 画布坐标 **0～1 归一化**（PC 与 iPad 相对位置一致） |
| 会话规则 | **Connection ID** 全服唯一；**同一房间内 User ID、User Name 均不可重复**（名称不区分大小写） |
| 质量保障 | `backend/tests` 自动化测试（当前 **33 passed**） |

### 5. 演示怎么说（1 分钟）

「我启动 `backend/run.bat`，浏览器打开 `http://本机IP:8000/`。两台设备使用**不同的 Connection ID、User ID、User Name**，但 **Room ID 相同**。一台画线，另一台实时出现；一方给另一方标注点『申请删除』，对方同意后面板同步移除。」

### 6. 后续工作（30 秒）

设计文档中的 Phase 4～5：压力测试、持久化存储、鉴权与安全加固、更完善的 E2E。当前以**课程/课题可演示的完整链路**为主，协议与状态机仍按设计文档维护。

---

## 二、项目目录与文档地图

### 2.1 代码目录（实现）

| 路径 | 说明 |
|------|------|
| `backend/main.py` | FastAPI 入口、WebSocket、静态前端 |
| `backend/core/` | 路由、房间、连接、状态机、Schema |
| `backend/handlers/` | 各消息类型处理器（17 个模块文件） |
| `backend/tests/` | 协议 / 处理器 / 集成 / 会话规则测试 |
| `backend/run.bat` | 启动服务（默认 `0.0.0.0:8000`） |
| `frontend/` | ES Module 客户端（Canvas + 标注层 + 协议封装） |
| `docs/BACKEND_QUICKSTART.md` | 安装、运行、测试命令 |

### 2.2 设计文档（理论依据，汇报时作附录）

| 文件 | 一句话用途 | 汇报时何时翻 |
|------|------------|--------------|
| [`00_RESEARCH_PLAN_SUMMARY.md`](00_RESEARCH_PLAN_SUMMARY.md) | 目标、原则、序列与清理策略总览 | 被问「为什么这样设计」 |
| [`01_PROTOCOL_SPECIFICATION.md`](01_PROTOCOL_SPECIFICATION.md) | 消息格式、类型、广播事件、错误码 | 被问「协议字段/流程」 |
| [`02_STATE_MACHINE_DESIGN.md`](02_STATE_MACHINE_DESIGN.md) | 用户 8 态、房间 4 态、超时 | 被问「状态与空闲」 |
| [`03_ARCHITECTURE_DESIGN.md`](03_ARCHITECTURE_DESIGN.md) | 分层架构、管理器职责、数据流 | 被问「模块划分」 |
| [`04_IMPLEMENTATION_PLAN.md`](04_IMPLEMENTATION_PLAN.md) | 分阶段计划与检查清单 | 被问「计划 vs 进度」 |
| [`README_QUICK_REFERENCE.md`](README_QUICK_REFERENCE.md) | 错误码、配置、流程速查 | 答辩临场查表 |
| [`frontend/README.md`](frontend/README.md) | 前端运行方式 | 只跑前端时的说明 |

**推荐阅读顺序（自学/写报告）**：`00` → `01` → `02` → `03` → `04` → 本 README → `README_QUICK_REFERENCE`。

---

## 三、设计与实现对照（Phase 进度）

依据 `04_IMPLEMENTATION_PLAN.md`，当前进度概括如下（**✅ 已实现 / 🟡 部分 / ⬜ 未做**）：

### Phase 1 — 基础设施 ✅

- FastAPI + WebSocket `/ws/{connection_id}`
- `MessageRouter`：JSON 解析、Schema、`msg_id` 去重、限流
- `ConnectionManager` / `RoomManager` / `StateManager`
- `GET /health`，根路径托管前端

### Phase 2 — 业务逻辑 ✅

- Join / Leave / Draw / Clear / StateSync
- Draw undo/redo、标注 CRUD、标注删除申请与投票
- Clear propose/vote、房间事件历史与快照
- 用户/房间状态机 + 维护循环（在线连接不因空闲误踢）

### Phase 3 — 前端 ✅

- WebSocket 会话、Join/Leave 状态机、事件有序队列
- Canvas 绘制与归一化坐标、标注层、乐观绘制回滚
- 清空/删除标注/离开小结等模态框、Diagnostics 与成员列表

### Phase 4～5 — 测试与生产化 🟡 / ⬜

- ✅ 单元与集成测试（`pytest backend/tests`）
- ⬜ 大规模压测、持久化 DB、完整 E2E 浏览器自动化
- ⬜ 生产部署文档、监控与鉴权体系

---

## 四、核心机制（汇报用精简版）

### 4.1 统一消息壳（与 `01` 一致）

```json
{
  "msg_id": "uuid",
  "type": "join | leave | draw | annotation | … | ack | error | broadcast",
  "timestamp": 1730000000000,
  "user_id": "user-pc",
  "room_id": "room-1",
  "sequence_id": null,
  "payload": { }
}
```

- 客户端请求：`sequence_id` 为 `null`。
- 服务器广播：携带递增的 `sequence_id`，写入房间 `canvas_history`。

### 4.2 状态机（与 `02` 一致）

**用户**：`CONNECTED` → `JOINED` → `ACTIVE` ↔ `IDLE` → `LEFT` / `DISCONNECTED`  
**房间**：`PENDING_INIT` → `ACTIVE` ↔ `IDLE` → `DESTROYED`

实现上：**WebSocket 仍连接时**不会因空闲直接把用户标为不可用；断线后会话可自动恢复或提示重新 Join。

### 4.3 协作规则（实现中的业务约束）

| 规则 | 说明 |
|------|------|
| Connection ID | 全局唯一，重复则拒绝连接 |
| User ID | 同一 **Room** 内不可两人共用；且单用户不能同时在两个房间 |
| User Name | 同一 **Room** 内不可重复（**不区分大小写**） |
| 清空画布 | 多人在场时需所有人表决同意 |
| 删他人标注 | 需 `annotation_delete_request` + 作者 `annotation_delete_vote` |

### 4.4 主要客户端消息类型（实现）

`join`, `leave`, `draw`, `draw_undo`, `draw_redo`, `annotation`, `annotation_delete`, `annotation_delete_request`, `annotation_delete_vote`, `annotation_restore`, `clear`, `clear_propose`, `clear_vote`, `state_sync`

广播事件示例：`draw`, `stroke_undone`, `annotation`, `annotation_removed`, `annotation_delete_requested`, `user_joined`, `user_left`, `clear`, …

更全列表见 `01_PROTOCOL_SPECIFICATION.md` 与 `README_QUICK_REFERENCE.md`。

---

## 五、快速启动（演示前必做）

### 5.1 安装依赖

```powershell
cd d:\Vscode_python\Collaboard
python -m pip install -r backend\requirements.txt
```

### 5.2 启动服务

```powershell
backend\run.bat
```

- 本机访问：`http://127.0.0.1:8000/`
- 局域网（如 iPad）：`http://<电脑局域网IP>:8000/`（**不要用 127.0.0.1**）

### 5.3 运行测试（可向老师展示）

```powershell
python -m pytest backend\tests -q
```

### 5.4 前端注意

- 必须通过后端打开页面（或自填 `ws://IP:8000/ws`），不要直接双击本地 HTML。
- 改完前端后建议 **Ctrl+F5** 硬刷新。

---

## 六、现场演示脚本（约 3～5 分钟）

### 6.1 环境准备

| 设备 | Connection ID | User ID | User Name | Room ID |
|------|---------------|---------|-----------|---------|
| PC | `conn-pc` | `user-pc` | `PC` | `demo-1` |
| 手机/平板 | `conn-ipad` | `user-ipad` | `iPad` | `demo-1` |

Server URL：PC 可用自动检测；iPad 填 `ws://<PC的IP>:8000/ws` 或 `http://<IP>:8000`（会自动补全）。

### 6.2 演示步骤

1. 两台设备依次 **Join**，指出 Diagnostics：**当前成员 2 人**。
2. PC 画几条线 → iPad 同步出现（强调 **sequence 有序重放**）。
3. iPad 放一个文字标注 → PC 可见。
4. PC 点击**对方标注** →「向对方申请删除」→ iPad 弹窗 **同意** → 两端标注消失。
5. （可选）PC 发起 **清空表决** → iPad 同意/拒绝。
6. （可选）终端运行 `pytest`，说明有回归测试。

### 6.3 常见问题（答辩备用）

| 现象 | 原因 | 处理 |
|------|------|------|
| `USER_ALREADY_JOINED` | 同房间 User ID/Name 重复，或用户已在别房 | 换 ID/Name 或先 Leave |
| `CONNECTION_ALREADY_EXISTS` | Connection ID 重复 | 换 `conn-xxx` |
| `UNAUTHORIZED` | 会话状态过期 | 刷新后重新 Join；已做在线保活与自动恢复 |
| 两端笔画位置不一致 | 旧房间数据或缓存 | 新 Room ID + 硬刷新 |
| iPad 连不上 | 用了 127.0.0.1 | 改成电脑局域网 IP |

---

## 七、设计亮点（对应 `00` 与实现）

1. **协议先行**：设计与代码均以 `01` 为准，Schema 校验防止脏消息。  
2. **显式状态机**：用户/房间生命周期清晰，非法操作返回明确 `ERROR`。  
3. **最终一致**：`sequence_id` + 有序队列，而非简单「转发最后一次坐标」。  
4. **协作治理**：清空与删他人标注带表决，避免一人清屏/删注破坏他人。  
5. **多端可用**：归一化坐标 + 成员/诊断信息，面向 PC + 平板演示。  
6. **可测**：处理器、协议、会话排他、集成流程均有 pytest 覆盖。

---

## 八、版本记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-04-14 | 完成设计文档集（`00`～`04`、快速参考） |
| **2.0** | **2026-05-18** | **实现可演示版本**：前后端联调、标注删除流程、房间内 ID/Name 唯一、空闲会话修复、本 README 改为汇报版 |

---

## 九、附录：给老师的问题 → 去哪份文档

| 问题 | 文档 |
|------|------|
| 整体目标和原则？ | `00_RESEARCH_PLAN_SUMMARY.md` |
| 某条消息 JSON 长什么样？ | `01_PROTOCOL_SPECIFICATION.md` |
| 用户什么时候会变成 IDLE？ | `02_STATE_MACHINE_DESIGN.md` |
| 有几个管理器、各干什么？ | `03_ARCHITECTURE_DESIGN.md` |
| 原计划分几阶段？ | `04_IMPLEMENTATION_PLAN.md` |
| 错误码 `RATE_LIMIT` 什么意思？ | `README_QUICK_REFERENCE.md` |
| 怎么跑起来？ | `docs/BACKEND_QUICKSTART.md`、本文 § 五 |

---

**汇报建议**：用 **§ 一** 当口稿，用 **§ 六** 做演示，设计细节以 **§ 二、§ 四** 和 `00`～`04` 为备查；不要逐页朗读 md，突出「协议 + 状态机 + 可运行系统 + 测试」四条线即可。
