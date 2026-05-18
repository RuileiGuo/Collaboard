# CollabBoard 安全规范（SECURITY）

## 文档信息

| 项目 | 内容 |
|------|------|
| 文档名称 | CollabBoard 安全规范 |
| 版本 | 1.0 |
| 日期 | 2026-05-18 |
| 适用范围 | CollabBoard 后端（FastAPI/WebSocket）、浏览器客户端、应用层 JSON 协议 |
| 关联文档 | `01_PROTOCOL_SPECIFICATION.md` §9、§12；`00_RESEARCH_PLAN_SUMMARY.md` §8；`02_STATE_MACHINE_DESIGN.md`；`README.md` |

### 文档目的

本文档将 CollabBoard 与**安全、滥用防护、恶意输入**相关的协议条款、实现位置、配置参数及**尚未实现**的扩展能力集中描述，作为：

- 设计与实现的对照基线；
- 测试与安全评审的检查清单；
- 后续启用 `security` 信封与生产加固的规范依据。

**说明**：CollabBoard 当前为可演示的原型系统，默认**不启用**网络层防火墙、身份提供商（IdP）或房间级访问令牌。许多控制依赖**应用层协议**与**单进程内逻辑**；开放公网部署前必须补足本文「未实现」与「部署层建议」章节中的控制。

### 实现状态图例

| 标记 | 含义 |
|------|------|
| **已实现** | 后端或前端代码中已生效，可通过配置或测试验证 |
| **部分实现** | 有规则但不完整，或仅覆盖部分攻击面 |
| **仅 Schema** | 消息结构可校验，业务逻辑不强制执行 |
| **仅设计** | 写在协议/本文中，代码未实现 |
| **未实现** | 明确留作后续工作 |

---

## 1. 信任边界与威胁模型

### 1.1 信任边界

```text
┌─────────────────────────────────────────────────────────────┐
│  不可信：终端用户浏览器、任意 WebSocket 客户端实现            │
└────────────────────────────┬────────────────────────────────┘
                             │ TLS（部署可选）/ WS 明文（开发默认）
┌────────────────────────────▼────────────────────────────────┐
│  半可信：CollabBoard 后端进程（MessageRouter + Handlers）     │
│  - 假定进程与主机未被攻破                                     │
│  - 不假定客户端报文诚实                                       │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│  可信（设计目标）：房间事件历史、成员集合、状态机转移规则        │
└─────────────────────────────────────────────────────────────┘
```

- **客户端不可信**：任何字段均可伪造；安全策略必须在**服务端**强制执行。
- **房间 ID 非机密**：知晓 `room_id` 即可尝试 Join（**未实现**房间令牌时）。
- **User ID / Connection ID**：由客户端自选字符串标识，服务端仅保证**唯一性约束**，不保证与真实身份绑定。

### 1.2 威胁类别（STRIDE 摘要）

| 类别 | 协作白板场景示例 |
|------|------------------|
| **S 仿冒** | 冒充他人 `user_id` 发消息；多开连接占位 |
| **T 篡改** | 修改他人笔划/标注；伪造 `sequence_id` |
| **R 抵赖** | 否认清空、删除操作（无审计签名时难以追责） |
| **I 泄露** | 未授权加入房间窥视 `canvas_history` |
| **D 拒绝服务** | 高频 DRAW、超大 JSON、海量连接占满内存/CPU |
| **E 权限提升** | 非作者 `annotation_delete`；非全员同意 `clear` |

### 1.3 安全目标（非目标）

**目标**

- 拒绝明显非法、超大、超频的协议消息；
- 在已加入房间内，按角色约束协作操作（作者、表决、成员）；
- 降低标注内容进入 DOM 时的脚本注入风险；
- 限制单连接、单房间的资源消耗上界。

**非目标（当前版本）**

- 端到端加密（E2EE）；
- 符合国家等级保护/密评的完整合规套件；
- 抵御大规模分布式 DDoS（需基础设施层）；
- 证明客户端未被篡改（无 attestation）。

---

## 2. 安全架构总览

安全控制分布在下列层次（自外向内）：

| 层次 | 机制 | 主要实现位置 |
|------|------|----------------|
| L0 部署/网络 | 绑定地址、防火墙、反向代理、TLS | `config.HOST`；运维配置（**未在代码内强制 TLS**） |
| L1 连接 | Connection ID 唯一、User ID 单连接绑定、WS 关闭 | `backend/main.py`；`connection_manager.py` |
| L2 报文入口 | JSON 解析、大小限制、类型白名单、时间戳 | `message_router.py` |
| L3 模式校验 | JSON Schema Draft-07 | `schemas.py` → `validate_client_message` |
| L4 滥用控制 | 令牌桶限流、msg_id 去重 | `message_router.py`；`room_manager` 事件桶 |
| L5 会话/状态 | 用户状态机、房间成员、超时 | `state_manager.py`；`join_handler.py` |
| L6 业务授权 | Handler 内 `is_user_in_room`、作者校验、表决 | `backend/handlers/*.py` |
| L7 内容安全 | 标注子串黑名单、长度/font 边界 | `schemas.py`；`annotation-layer.js` |
| L8 未来鉴权 | `security` 顶层信封 | **仅 Schema**；见 §8 |

处理顺序（每条 WebSocket 文本消息）：

1. 连接级：首包可绑定 `user_id`，检查全局 User/Connection 占用（`main.py`）。
2. `apply_timeouts` + `restore_room_session`（在线会话恢复，`main.py`）。
3. `MessageRouter.handle_raw`：大小 → JSON → 类型白名单 → 时间戳 → Schema → 限流 → Handler。
4. Handler：状态机 + 房间成员 + 业务规则 → ACK/ERROR + 可选广播。

---

## 3. 传输与连接安全

### 3.1 WebSocket 端点

| 控制项 | 规范 | 实现状态 | 说明 |
|--------|------|----------|------|
| 端点路径 | `GET /ws/{connection_id}` | **已实现** | `main.py` |
| Connection ID 唯一 | 同一 ID 不得重复建连 | **已实现** | 重复则 `CONNECTION_ALREADY_EXISTS` 并 `close(4001)` |
| 监听地址 | 默认 `0.0.0.0:8000` | **已实现** | 局域网可访问；生产应配合防火墙 |
| TLS (wss) | 部署时终止 TLS | **未实现** | 由 Nginx/Caddy 等反向代理承担 |
| 连接数/IP 上限 | 限制单 IP 并发 WS | **未实现** | 易被多连接耗尽 |

### 3.2 连接与用户标识绑定

| 控制项 | 规范 | 实现状态 | 说明 |
|--------|------|----------|------|
| 首条含 `user_id` 的消息绑定 | 将 `user_id` 记入 ConnectionManager | **已实现** | `main.py` 预览 JSON |
| 全局 User ID 单连接 | 同一 `user_id` 不得绑定两个 connection | **已实现** | `get_connection_by_user`；ERROR 后断开 |
| 房间内 User ID 唯一 | 同房间不得两活跃连接同 `user_id` | **已实现** | `join_handler` + `find_user_connection_in_room` |
| 房间内 User Name 唯一 | 显示名不区分大小写唯一 | **已实现** | `room_manager.find_user_id_by_display_name` |
| User ID 真实性 | 与登录账号绑定 | **未实现** | 客户端自报字符串 |

### 3.3 断线与会话

| 控制项 | 规范 | 实现状态 | 说明 |
|--------|------|----------|------|
| 断线清理 | 从房间移除用户、广播 `user_left` | **已实现** | `_cleanup_disconnected_user` |
| 空闲超时 | 无活动转 IDLE/DISCONNECTED | **部分实现** | 在线 WS 不断开时不强制 DISCONNECTED（`apply_timeouts(online_user_ids=…)`） |
| 会话恢复 | DISCONNECTED 但连接仍在时恢复 ACTIVE | **已实现** | `restore_room_session` |
| Join 宽限期 | CONNECTED 后须限时 Join | **已实现** | `USER_JOIN_GRACE_SECONDS`（默认 30s） |

### 3.4 发送超时

| 参数 | 默认值 | 实现状态 |
|------|--------|----------|
| `WEBSOCKET_SEND_TIMEOUT_SECONDS` | 3 | **已实现** |
| `WEBSOCKET_CLOSE_TIMEOUT_SECONDS` | 2 | **已实现** |
| `WEBSOCKET_READ_TIMEOUT_SECONDS` | 60 | **配置存在**；依赖栈行为 |

---

## 4. 消息信封与输入验证

### 4.1 顶层信封（所有客户端请求）

字段要求见 `01_PROTOCOL_SPECIFICATION.md` §3 与 `CLIENT_MESSAGE_SCHEMA`（`schemas.py`）。

| 字段 | 安全约束 | 实现状态 |
|------|----------|----------|
| `msg_id` | UUID v4 正则 | **已实现** |
| `type` | 枚举白名单（14 种客户端类型） | **已实现**；Router `CLIENT_TYPES` 须与 Schema 同步 |
| `timestamp` | 数值 ≥0；Router 校验 ±容差 | **已实现** |
| `user_id` | 1–100 字符 | **已实现** |
| `room_id` | 1–100 字符 | **已实现** |
| `sequence_id` | 客户端必须为 `null` | **已实现** |
| `payload` | 按 type 的子 Schema | **已实现** |
| `additionalProperties` | 顶层禁止未定义字段 | **已实现** |
| `security` | 可选对象；结构见 §8 | **仅 Schema** |

非法 JSON、非对象、缺字段、类型错误 → `INVALID_MESSAGE`。

### 4.2 消息类型白名单（Router）

`MessageRouter.CLIENT_TYPES` 必须在路由前包含全部合法客户端 `type`，否则返回 `Unknown/invalid message type`（**已实现**）。

当前白名单包括：`join`, `leave`, `draw`, `annotation`, `annotation_delete`, `annotation_delete_request`, `annotation_delete_vote`, `annotation_restore`, `draw_undo`, `draw_redo`, `clear`, `clear_propose`, `clear_vote`, `state_sync`。

### 4.3 载荷边界（按类型）

#### JOIN

| 字段 | 约束 | 实现状态 |
|------|------|----------|
| `metadata.user_name` | 1–100 字符 | **已实现** |
| `metadata` | 允许 `additionalProperties` | **部分实现** | 扩展字段未逐一审查 |

#### DRAW

| 字段 | 约束 | 实现状态 |
|------|------|----------|
| `stroke_id` | UUID | **已实现** |
| `tool` | 枚举：pen, eraser, line, rectangle, circle | **已实现** |
| `color` | `#RRGGBB` | **已实现** |
| `width` | 0.5–50（协议像素语义） | **已实现** |
| `points` | 1–1000 点；每点 x,y, pressure∈[0,1] | **已实现** |
| 坐标范围 | x,y 可为任意 float（含 NaN） | **部分实现** | 前端 clamp 01；服务端未拒绝 NaN/Inf |

#### ANNOTATION

| 字段 | 约束 | 实现状态 |
|------|------|----------|
| `content` | 1–`ANNOTATION_CONTENT_MAX_CHARS`（默认 2000） | **已实现** |
| `font_size` | 8–72 | **已实现** |
| `mode` | text \| formula | **已实现** |
| 危险子串 | 见 §7 | **已实现** |

#### CLEAR / CLEAR_PROPOSE / CLEAR_VOTE

| 控制 | 实现状态 |
|------|----------|
| 裸 `clear` 在多人房拒绝，返回 `CLEAR_REQUIRES_CONSENSUS` | **已实现** |
| 提案 TTL `CLEAR_PROPOSAL_TTL_MS`（默认 120s） | **已实现** |
| 重复同意票 `CLEAR_VOTE_DUPLICATE` | **已实现** |

#### STATE_SYNC

| 字段 | 约束 | 实现状态 |
|------|------|----------|
| `last_received_sequence` | 整数 ≥ -1 | **已实现** |
| 增量拉取 | 仅返回之后事件 | **已实现** |

### 4.4 消息大小

| 项 | 规范值 | 实现状态 | 代码 |
|----|--------|----------|------|
| 单条 WS 文本 UTF-8 字节 | ≤ 1 MB | **已实现** | `config.MESSAGE_MAX_BYTES`；`main.py` RouterConfig |
| 文档与 Router 默认值 | 文档写 1MB；Router 类默认 64KB 已被 main 覆盖 | **已实现** | 以 `config` 为准 |

### 4.5 时间戳防重放（弱）

| 控制 | 实现状态 | 说明 |
|------|----------|------|
| 客户端 `timestamp` 与服务器差值 | **已实现** | `TIMESTAMP_TOLERANCE_SECONDS`（默认 30s） |
| 密码学 nonce / 签名防重放 | **未实现** | 见 §8 `security.nonce` |

### 4.6 幂等与重复提交

| 控制 | 规范 | 实现状态 |
|------|------|----------|
| `msg_id` 去重窗口 | 相同 `msg_id` 仅处理一次，重放相同 ACK/ERROR | **已实现** | `DEDUP_WINDOW_SECONDS`（默认 300s） |
| 新 `msg_id` 的重复业务 | 不视为同一请求 | **已实现** | 攻击者可换 UUID 绕过 dedup |

---

## 5. 速率限制与资源耗尽防护

### 5.1 每连接消息速率（令牌桶）

| 参数 | 默认值 | 实现状态 | 行为 |
|------|--------|----------|------|
| `RATE_LIMIT_MESSAGES_PER_SECOND` | 100（容量≈100，补充速率 100/s） | **已实现** | 超限 → `RATE_LIMIT` |
| 适用范围 | 每条通过 Router 的新 `msg_id` | **已实现** | dedup 命中不计入新消耗 |

**限制**：攻击者可使用**多个 Connection ID + 多个 User ID** 线性放大吞吐（无 IP 级聚合限流）。

### 5.2 每房间事件速率

| 参数 | 默认值 | 实现状态 | 行为 |
|------|--------|----------|------|
| `ROOM_RATE_LIMIT_EVENTS_PER_SECOND` | 1000 | **已实现** | `RoomManager.append_event` 抛 `RoomEventRateLimitError` → Router 转 `RATE_LIMIT` |

保护 `canvas_history` 追加与广播风暴；不限制仅失败不落库的尝试（在 append 前已消耗连接桶）。

### 5.3 内存与历史增长

| 风险 | 现状 | 实现状态 |
|------|------|----------|
| `canvas_history` 无界增长 | 房间内事件持续追加 | **未实现** 上限 | 长跑房间内存上涨 |
| 单房间成员数 | 无硬上限 | **未实现** |
| 单进程房间总数 | 无硬上限 | **未实现** |

**建议（仅设计）**：每房间最大事件条数、最大成员数、定期快照归档。

---

## 6. 身份、会话与房间成员安全

### 6.1 用户状态机授权

`StateManager.validate_user_action` 决定当前状态是否允许某 `type`（**已实现**）。

| 状态 | 允许的客户端消息（摘要） |
|------|--------------------------|
| `CONNECTED` | 仅 `join` |
| `JOINED`, `ACTIVE`, `IDLE` | 业务消息 + `leave` + `state_sync` |
| `DISCONNECTED`, `TIMEOUT`, `LEFT` 等 | 仅 `leave`（逃生）或拒绝 |

非法状态 → Handler 前已由 Router 拒绝或 Handler 返回 `UNAUTHORIZED`。

### 6.2 房间成员校验

绝大多数 Handler 首步：`is_user_in_room(room_id, user_id)`（**已实现**）。未加入或已离开 → `ROOM_NOT_FOUND` 或 `UNAUTHORIZED`。

### 6.3 跨房与占位

| 规则 | 实现状态 |
|------|----------|
| 单用户同时仅在一个房间（`find_room_for_user`） | **已实现** |
| 同房间重复 User ID（活跃连接） | **已实现** → `USER_ALREADY_JOINED`，`reason=duplicate_user_id_in_room` |
| 同房间重复 User Name（casefold） | **已实现** → `duplicate_user_name_in_room` |
| 僵尸成员（在房无连接） | **部分实现** | Join 时可能 `leave` 清理同名占位 |

### 6.4 房间生命周期

| 控制 | 实现状态 |
|------|----------|
| 最后成员离开 → `room_idle` + TTL | **已实现** |
| `ROOM_IDLE_TTL_SECONDS`（默认 60s）后销毁 | **已实现** |
| `ROOM_PENDING_INIT_TTL_SECONDS`（空房待 Init） | **已实现** |

---

## 7. 业务授权（协作权限模型）

以下为**应用层授权**，不替代身份认证。

### 7.1 绘制与笔划

| 操作 | 授权规则 | 实现状态 |
|------|----------|----------|
| `draw` | 须在房内且状态合法 | **已实现** |
| `draw_undo` | 仅笔划**作者**可撤销 | **已实现** | `stroke_visible_and_author` |
| `draw_redo` | 须在房内；重做可见性规则见 Handler | **已实现** |

### 7.2 标注

| 操作 | 授权规则 | 实现状态 |
|------|----------|----------|
| `annotation` | 房内成员可创建 | **已实现** |
| `annotation_delete` | 仅**创建者**（作者 user_id） | **已实现** |
| `annotation_delete_request` | 非作者且标注可见 | **已实现** |
| `annotation_delete_vote` | 仅**目标作者**；提案未过期 | **已实现** |
| `annotation_restore` | 通常为删除操作者恢复；见 Handler | **已实现** |
| 重复删除申请 | 同学号活跃申请 → `ANNOTATION_DELETE_REQUEST_ACTIVE` | **已实现** |

### 7.3 清空画布

| 场景 | 规则 | 实现状态 |
|------|------|----------|
| 单人房间 | 允许流程见实现（propose/vote 或单人策略） | **已实现** |
| 多人房间 | 禁止裸 `clear`；须 `clear_propose` + 全员 `clear_vote` approve | **已实现** |
| 单方毁损 | 无全员同意不能清空 | **已实现** |

### 7.4 读与同步

| 操作 | 规则 | 实现状态 |
|------|----------|----------|
| `join` 快照 | 返回完整 `canvas_history` | **已实现** | 知 room_id 即可能拉取历史 |
| `state_sync` | 仅房内成员 | **已实现** |

**重要缺口**：无房间密钥时，**知道 `room_id` 即具备读/write 尝试能力**（写仍受状态机与授权约束）。

---

## 8. 内容安全（注入与恶意载荷）

### 8.1 标注文本：服务端黑名单

`assert_annotation_content_safe`（**已实现**），对 `content` 做**小写子串**匹配，命中则 `INVALID_MESSAGE`：

| 禁止片段（当前列表） |
|----------------------|
| `<script` |
| `</script` |
| `javascript:` |
| `onerror=` |
| `onload=` |
| `<iframe` |
| `data:text/html` |

**局限性（部分实现）**：

- 非完整 HTML 净化器；编码绕过、其他事件处理器（`onclick=`）、SVG/MathML 向量可能未覆盖；
- 不防 LaTeX 层面的资源消耗（见下）；
- 历史事件中若含旧版恶意内容，重放时 Schema 可能因「当前规则」与历史不一致——协议建议防御性拒绝（`01` §3.2.4 说明）。

### 8.2 标注渲染：客户端义务

| 要求 | 实现状态 |
|------|----------|
| 文本模式使用 `textContent`，禁止 `innerHTML` 拼接用户内容 | **已实现** | `annotation-layer.js` |
| 公式模式使用 KaTeX，`throwOnError: false` | **已实现** | 失败回退 `textContent` |
| KaTeX 渲染超时 / 沙箱 | **未实现** | 恶意 LaTeX 可能导致 CPU 峰值（前端责任） |
| 容器 `clear()` 使用 `innerHTML=""` 清空自有节点 | **已实现** | 不写入用户字符串 |

### 8.3 其他注入面

| 面 | 风险 | 实现状态 |
|----|------|----------|
| `user_name` / `user_id` 显示在 UI | DOM 文本若用 `textContent` 则低 | **已实现**（成员 chip、Diagnostics） |
| `event_log` / Diagnostics | 若拼接未转义 HTML | **部分实现** | 主要为 `textContent` |
| JSON 深度炸弹 | 极大嵌套 JSON | **部分实现** | 依赖解析器与 1MB 上限 |
| 原型污染 | `payload` 对象键 | **低** | Python 侧按 dict 访问，非 `eval` |

### 8.4 笔划坐标

- 协议允许归一化坐标；服务端不验证 [0,1] 范围（**部分实现**）。
- 前端 `clamp01` 限制显示；越界笔划可能影响体验但不构成服务端 RCE。

---

## 9. Security Envelope（扩展鉴权协议）

规范全文：`01_PROTOCOL_SPECIFICATION.md` §12。  
结构校验：`CLIENT_MESSAGE_SCHEMA.properties.security`（**仅 Schema**）。

### 9.1 建议字段语义

```json
{
  "security": {
    "session_id": "sess-001",
    "auth_token": "optional-room-or-bearer-token",
    "nonce": "nonce-12345678",
    "signature": "optional-hmac-or-signature",
    "issued_at": 1712889600000,
    "device_id": "ipad-alice",
    "capabilities": ["join", "draw", "annotation"],
    "risk_context": {
      "source": "web",
      "trust_level": "baseline"
    }
  }
}
```

| 字段 | 设计用途 | 实现状态 |
|------|----------|----------|
| `session_id` | 登录态/协作会话标识 | **未实现** |
| `auth_token` | 房间或用户令牌 | **未实现** |
| `nonce` | 单次请求随机数，防重放 | **未实现** |
| `signature` | 对关键字段 HMAC/签名，防篡改 | **未实现** |
| `issued_at` | 请求时效窗口 | **未实现** |
| `device_id` | 设备审计、并发会话 | **未实现** |
| `capabilities` | 服务端签发能力集合 | **未实现** |
| `risk_context` | 风控扩展 | **未实现** |

### 9.2 启用后的建议流程（仅设计）

1. **Join**：校验 `auth_token` 或房间邀请码；绑定 `session_id`；签发房间内 `capabilities`。
2. **后续每条消息**：校验 `nonce` 未使用（服务端 nonce 存储）；校验 `signature` 覆盖 `msg_id|type|timestamp|user_id|room_id|payload_hash`；校验 `issued_at` 在窗口内。
3. **失败错误码（建议新增）**：`AUTH_REQUIRED`、`INVALID_TOKEN`、`INVALID_SIGNATURE`、`NONCE_REPLAY`、`CAPABILITY_DENIED`（**均未实现**）。

### 9.3 与现有 `timestamp` + `msg_id` dedup 的关系

| 机制 | 防重放强度 |
|------|------------|
| `timestamp` ±30s | 弱；窗口内可无限新 `msg_id` |
| `msg_id` dedup 300s | 中；仅防重复同一 ID |
| `security.nonce` + 签名 | 强（设计目标） |

---

## 10. 广播与序列完整性

| 控制 | 实现状态 | 说明 |
|------|----------|------|
| 服务端分配 `sequence_id` | **已实现** | 客户端不得自带有效 sequence |
| 有序重放 | **已实现**（客户端） | 乱序缓冲/丢弃 |
| 伪造他人 `user_id` 发 draw | **部分实现** | 服务端以连接绑定 user 为准；消息体 `user_id` 应与连接一致（Handler 使用 message 内字段，**须在实现中保持一致**） |
| `SEQUENCE_CONFLICT` | **仅设计/少量** | 主要用于客户端检测 |

---

## 11. 错误码与安全语义

| `error_code` | 典型安全含义 | 实现状态 |
|--------------|--------------|----------|
| `INVALID_MESSAGE` | Schema/时间戳/危险内容/未知 type | **已实现** |
| `UNAUTHORIZED` | 状态机不允许、非作者、非表决人 | **已实现** |
| `RATE_LIMIT` | 连接或房间过载 | **已实现** |
| `USER_ALREADY_JOINED` | 占位/跨房/重复 ID 或 Name | **已实现** |
| `CONNECTION_ALREADY_EXISTS` | 连接 ID 冲突 | **已实现** |
| `ROOM_NOT_FOUND` | 房间不存在或用户不在房 | **已实现** |
| `CLEAR_REQUIRES_CONSENSUS` | 禁止未表决清空 | **已实现** |
| `CLEAR_PROPOSAL_ACTIVE` | 防提案堆叠滥用 | **已实现** |
| `ANNOTATION_DELETE_REQUEST_ACTIVE` | 防删除申请刷屏 | **已实现** |
| `INTERNAL_ERROR` | 未预期异常；应隐藏细节 | **部分实现** | 可能含 `details` |

客户端建议：对 `RATE_LIMIT` 指数退避；对 `UNAUTHORIZED` 尝试 `state_sync` 或重新 Join（**前端已实现部分**）。

---

## 12. 配置参数一览（安全相关）

环境变量前缀示例：`COLLABOARD_*`（见 `backend/config.py`）。

| 参数 | 默认值 | 安全用途 |
|------|--------|----------|
| `MESSAGE_MAX_BYTES` | 1048576 | 单条消息上界 |
| `TIMESTAMP_TOLERANCE_SECONDS` | 30 | 时钟漂移容忍 |
| `DEDUP_WINDOW_SECONDS` | 300 | 幂等窗口 |
| `RATE_LIMIT_MESSAGES_PER_SECOND` | 100 | 每连接吞吐 |
| `ROOM_RATE_LIMIT_EVENTS_PER_SECOND` | 1000 | 每房间事件吞吐 |
| `USER_JOIN_GRACE_SECONDS` | 30 | 占连接不 Join |
| `USER_JOINED_IDLE_SECONDS` | 600 | 入会未活动→IDLE |
| `USER_ACTIVE_IDLE_SECONDS` | 1800 | 活动后空闲→IDLE |
| `USER_IDLE_TIMEOUT_SECONDS` | 1800 | IDLE→断开 |
| `ROOM_IDLE_TTL_SECONDS` | 60 | 空房销毁 |
| `CLEAR_PROPOSAL_TTL_MS` | 120000 | 表决悬挂上界 |
| `ANNOTATION_CONTENT_MAX_CHARS` | 2000 | 标注长度 |
| `ANNOTATION_FONT_SIZE_MIN/MAX` | 8 / 72 | 字号边界 |
| `WEBSOCKET_*_TIMEOUT_SECONDS` | 见 config | 发送/关闭阻塞 |

---

## 13. 威胁—控制对照矩阵

| 威胁 | 控制措施 | 状态 | 残余风险 |
|------|----------|------|----------|
| 超大 JSON 占带宽/内存 | 1MB 上限 | 已实现 | 多连接并行 |
| 高频消息洪泛 | 连接+房间限流 | 已实现 | 多账号分布式 |
| 重复 POST 同一操作 | msg_id dedup | 已实现 | 换 msg_id 重试 |
| 时钟漂移攻击 | timestamp 容差 | 已实现 | 30s 窗口内仍有效 |
| 未知消息类型 | Router 白名单 | 已实现 | 需与 Schema 同步维护 |
| XSS 经标注注入 | 子串黑名单+textContent | 部分 | 绕过变种、LaTeX CPU |
| 非作者删标注 | 作者校验+申请表决 | 已实现 | — |
| 单方清空画布 | clear 表决 | 已实现 | 单人房策略需知悉 |
| 冒充 user_id（双连接） | 全局单连接+房内唯一 | 已实现 | 无账号体系 |
| 未授权进房窥视 | — | 未实现 | 知 room_id 即可 Join |
| 重放已签名请求（未来） | security.nonce | 未实现 | — |
| WS 连接耗尽 | — | 未实现 | 需网关限连 |
| canvas_history 撑爆内存 | — | 未实现 | 长跑房间 |
| 中间人窃听 | TLS | 未实现 | 开发环境明文 WS |

---

## 14. 测试与验证

| 测试资产 | 覆盖的安全点 | 位置 |
|----------|--------------|------|
| `test_protocol.py` | Schema、UUID、标注 `<script>` 拒绝 | `backend/tests/` |
| `test_handlers.py` | 限流、路由、删除申请 | 同上 |
| `test_session_logic.py` | 重复 Connection/User ID/Name | 同上 |
| `test_integration.py` | 双端 Join、非作者删标注拒绝 | 同上 |
| `test_state_manager.py` | 超时、在线豁免 | 同上 |
| `test_managers.py` | 房间事件限流 | 同上 |

**缺失的测试类型（建议）**：模糊测试 payload、恶意 LaTeX、并发 Join 竞态、security 信封启用后的签名向量。

---

## 15. 部署层安全建议（代码外）

以下不在当前仓库实现，公网部署**建议**至少满足：

1. **TLS 终止**：仅暴露 `wss://`，禁止明文 `ws://` 跨公网。
2. **反向代理限流**：按 IP 限制新建连接与 HTTP/WS 速率。
3. **防火墙**：仅开放必要端口；管理面隔离。
4. **资源上限**：进程 `ulimit`、容器 memory limit、单实例房间数监控。
5. **日志与审计**：记录 Join/Leave/Clear/删除表决；不记录完整 payload 中的敏感正文（若未来有）。
6. **房间邀请机制**：房间 UUID、一次性 token，替代可猜测 `room_id`。
7. **身份提供商**：OAuth2/OIDC 签发 `auth_token`，与 §9 信封对接。

---

## 16. 后续工作路线图（安全）

| 优先级 | 项 | 类型 |
|--------|-----|------|
| P0 | 房间级 `auth_token` 或邀请码 | 鉴权 |
| P0 | 启用 `security` 信封：Join 验 token + 全局 nonce | 防重放/篡改 |
| P1 | IP / 连接数限流 | 防 DoS |
| P1 | `canvas_history` 条数上限与归档 | 防内存耗尽 |
| P1 | DRAW 坐标拒绝 NaN/Inf；可选 clamp [0,1] | 输入硬化 |
| P2 | 标注 HTML 净化（allowlist）替代纯子串 | 内容安全 |
| P2 | KaTeX 渲染超时与长度配额（前端） | 防 CPU |
| P2 | 安全相关错误码：`AUTH_REQUIRED` 等 | 协议 |
| P3 | 渗透测试与 fuzz WebSocket 帧 | 验证 |

---

## 17. 文档与代码同步维护

| 变更类型 | 应更新文档 |
|----------|------------|
| 新增客户端 `type` | `01` §3、`schemas.py`、`message_router.CLIENT_TYPES`、本文 §4.2 |
| 新增错误码 | `models.ErrorCode`、`README_QUICK_REFERENCE.md`、本文 §11 |
| 调整限流/大小 | `config.py`、本文 §5、§12 |
| 启用 security | `01` §12、本文 §9、Handler 验签逻辑 |
| 标注黑名单变更 | `schemas.py`、本文 §8.1 |

---

## 18. 参考文献

1. `01_PROTOCOL_SPECIFICATION.md` — §9 安全约束、§12 Security Envelope  
2. `00_RESEARCH_PLAN_SUMMARY.md` — §8 安全性和验证  
3. `02_STATE_MACHINE_DESIGN.md` — 用户/房间状态与超时  
4. `03_ARCHITECTURE_DESIGN.md` — 模块职责边界  
5. `04_IMPLEMENTATION_PLAN.md` — §4.5 安全性检查  
6. `README_QUICK_REFERENCE.md` — 错误码与限流速查  
7. `backend/core/schemas.py` — Schema 与 `assert_annotation_content_safe`  
8. `backend/core/message_router.py` — 入口校验与限流  
9. `backend/config.py` — 安全相关运行时配置  
10. OWASP — XSS Prevention Cheat Sheet（标注渲染参考）  
11. RFC 6455 — The WebSocket Protocol  

---

**文档维护**：安全相关实现变更时，应同步修订本文「实现状态」列与 §13 威胁矩阵，避免规范与代码漂移。
