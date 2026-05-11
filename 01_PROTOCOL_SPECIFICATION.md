# CollabBoard - 协议规范 (Protocol Specification)

**文档版本**: 1.3  
**日期**: 2026-05-07  
**状态**: 与当前实现对齐（含撤销/恢复绘制与离开小结等客户端行为说明）

---

## 1. 概述 (Overview)

CollabBoard 采用 **WebSocket + 事件驱动** 架构，所有用户操作转换为规范化的事件消息，由服务器赋予全局序列号，然后广播给所有客户端。

### 核心原则
- **协议一致性**: 所有消息遵循统一的 JSON Schema
- **顺序性**: 服务器保证事件的全局顺序
- **最终一致性**: 所有客户端通过重放有序事件达到一致状态
- **容错性**: 每个客户端请求必须获得 ACK 或 ERROR 响应

---

## 2. 基础消息格式 (Base Message Format)

所有从客户端发送到服务器的消息必须遵循此格式：

```json
{
  "msg_id": "uuid-v4",
  "type": "join | leave | draw | draw_undo | draw_redo | annotation | annotation_delete | annotation_restore | clear | clear_propose | clear_vote | ack | error | state_sync | broadcast",
  "timestamp": 1712889600000,
  "user_id": "user_abc123",
  "room_id": "room_xyz789",
  "sequence_id": null,
  "payload": {}
}
```

### 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `msg_id` | UUID | ✓ | 消息唯一标识，用于去重和 ACK 匹配 |
| `type` | string | ✓ | 消息类型（见下文） |
| `timestamp` | number | ✓ | 客户端时间戳（毫秒级 unix timestamp） |
| `user_id` | string | ✓ | 发送者用户 ID |
| `room_id` | string | ✓ | 房间 ID |
| `sequence_id` | number \| null | ✗ | 服务器赋予的全局序列号（客户端请求时为 null） |
| `payload` | object | ✓ | 消息负载，根据消息类型而定 |

---

## 3. 消息类型定义 (Message Types)

### 3.1 JOIN - 加入房间

**客户端请求**:
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440001",
  "type": "join",
  "timestamp": 1712889600000,
  "user_id": "user_alice",
  "room_id": "room_design1",
  "sequence_id": null,
  "payload": {
    "client_version": "1.0.0",
    "metadata": {
      "user_name": "Alice",
      "client_type": "web"
    }
  }
}
```

**服务器 ACK 响应**:
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440001",
  "type": "ack",
  "timestamp": 1712889601000,
  "user_id": "server",
  "room_id": "room_design1",
  "sequence_id": 0,
  "payload": {
    "status": "ok",
    "reason": "joined",
    "room_state": {
      "room_id": "room_design1",
      "user_count": 2,
      "canvas_history": [
        { "user_id": "user_bob", "type": "draw", "sequence_id": 0, "payload": {...} }
      ]
    }
  }
}
```

**服务器广播消息** (其他客户端收到):
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440001",
  "type": "broadcast",
  "timestamp": 1712889601000,
  "user_id": "user_alice",
  "room_id": "room_design1",
  "sequence_id": 1,
  "payload": {
    "event_type": "user_joined",
    "user_id": "user_alice",
    "user_name": "Alice",
    "room_user_count": 2
  }
}
```

---

### 3.2 DRAW - 绘制操作

**客户端请求**:
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440002",
  "type": "draw",
  "timestamp": 1712889602000,
  "user_id": "user_alice",
  "room_id": "room_design1",
  "sequence_id": null,
  "payload": {
    "stroke_id": "stroke_uuid_001",
    "tool": "pen",
    "color": "#FF0000",
    "width": 2,
    "points": [
      {"x": 100, "y": 150, "pressure": 1.0},
      {"x": 102, "y": 152, "pressure": 1.0},
      {"x": 105, "y": 155, "pressure": 0.9}
    ]
  }
}
```

**服务器 ACK**:
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440002",
  "type": "ack",
  "timestamp": 1712889602500,
  "user_id": "server",
  "room_id": "room_design1",
  "sequence_id": 2,
  "payload": {
    "status": "ok",
    "stroke_id": "stroke_uuid_001",
    "server_sequence": 2
  }
}
```

**服务器广播** (包含服务器赋予的序列号):
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440002",
  "type": "broadcast",
  "timestamp": 1712889602500,
  "user_id": "user_alice",
  "room_id": "room_design1",
  "sequence_id": 2,
  "payload": {
    "event_type": "draw",
    "stroke_id": "stroke_uuid_001",
    "tool": "pen",
    "color": "#FF0000",
    "width": 2,
    "points": [
      {"x": 100, "y": 150, "pressure": 1.0},
      {"x": 102, "y": 152, "pressure": 1.0},
      {"x": 105, "y": 155, "pressure": 0.9}
    ]
  }
}
```

---

### 3.2.1 ANNOTATION - 文字 / 公式标注

在画布坐标 `(x, y)` 放置一段纯文本或 LaTeX 源码（由客户端用 KaTeX/MathJax 等安全渲染）。

**客户端请求 `payload`**:

| 字段 | 说明 |
|------|------|
| `annotation_id` | UUID |
| `mode` | `text` \| `formula` |
| `content` | 字符串，长度 ≤ 2000（配置项） |
| `x`, `y` | 画布 CSS 像素坐标 |
| `font_size` | 8–72 |
| `color` | `#RRGGBB` |

**广播 `event_type`: `annotation`**：消息顶层 `user_id` 为创建者；`payload` 内含 `user_id`、`user_name` 及上述字段。事件 **append** 到 `canvas_history`，参与全局 `sequence_id` 流。

**客户端重放**：按 `sequence_id` 顺序处理；对每条 `annotation`，若该 `annotation_id` 当前为「可见」则渲染（详见 **§3.2.2** 可见性规则）。

---

### 3.2.2 ANNOTATION_DELETE - 删除单条文字 / 公式标注

删除 **某一条** 标注（不清空笔迹、不截断 `canvas_history`）。仅 **该标注的创建者**（见下）可删除；其他人发送本消息将得到 **`UNAUTHORIZED`**。

**创建者判定（服务器）**：在 `canvas_history` 中按时间顺序扫描同一 `annotation_id` 的相关事件，**最后一条**决定状态：

- 若为 `event_type: annotation` → 标注**可见**，创建者为该条广播消息 **顶层** `user_id`（与 `payload.user_id` 一致）。
- 若为 `event_type: annotation_removed` → 标注**不可见**（已删除或从未存在）。

同一 `annotation_id` 可被再次 `annotation` 添加（新一次生命周期）；删除只影响当前可见实例。

**客户端请求**：

```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440030",
  "type": "annotation_delete",
  "timestamp": 1712889603000,
  "user_id": "user_alice",
  "room_id": "room_design1",
  "sequence_id": null,
  "payload": {
    "annotation_id": "550e8400-e29b-41d4-a716-446655440031"
  }
}
```

**`payload` 字段**：

| 字段 | 说明 |
|------|------|
| `annotation_id` | UUID，与创建时 `annotation` 请求中的 `annotation_id` 相同 |

**成功时服务器 ACK**（`sequence_id` 为处理完成后房间当前序号）：

```json
{
  "type": "ack",
  "user_id": "server",
  "room_id": "room_design1",
  "sequence_id": 12,
  "payload": {
    "status": "ok",
    "annotation_id": "550e8400-e29b-41d4-a716-446655440031",
    "server_sequence": 12
  }
}
```

**广播 `event_type`: `annotation_removed`**（append 到 `canvas_history`，**不**触发与 `clear` 等价的「清空历史」行为）：

```json
{
  "type": "broadcast",
  "user_id": "user_alice",
  "room_id": "room_design1",
  "sequence_id": 12,
  "payload": {
    "event_type": "annotation_removed",
    "annotation_id": "550e8400-e29b-41d4-a716-446655440031",
    "user_id": "user_alice",
    "user_name": "Alice"
  }
}
```

**错误**：

| 条件 | `error_code` |
|------|----------------|
| 发送者不是该可见标注的创建者 | `UNAUTHORIZED` |
| 标注不存在、或已被删除（当前不可见） | `ANNOTATION_NOT_FOUND` |
| 用户不在房间内等 | `ROOM_NOT_FOUND` / `UNAUTHORIZED`（与既有规则一致） |

**客户端重放**：收到 `annotation_removed` 时，移除本地 UI 中对应 `annotation_id` 的覆盖层；`STATE_SYNC` / `canvas_history` 全量重放时，须按序应用 `annotation` 与 `annotation_removed`（与服务器可见性规则一致）。

**成功 ACK** 建议带 `op: "annotation_delete"` 以便客户端维护「可撤销」栈（实现可选）。

---

### 3.2.3 DRAW_UNDO - 撤销本人一笔绘制（含橡皮）

画布上的每一笔（`tool: pen | eraser | …`）对应一条 `draw` 事件与唯一 `stroke_id`。`draw_undo` 将 **该笔** 从协作重放结果中移除（**不**修改历史数组中已有事件，而是 **append** 一条补偿事件）。

**笔迹可见性（服务器）**：对同一 `stroke_id` 顺序扫描 `canvas_history`，最后一条 `draw` 与 `stroke_undone` 择一生效：

- 最后为 `event_type: draw` 且 `stroke_id` 匹配 → 笔迹**存在**。
- 最后为 `event_type: stroke_undone` 且 `stroke_id` 匹配 → 笔迹**已撤销**。

仅 **该笔 `draw` 的顶层 `user_id`（作者）** 可发送 `draw_undo`；他人 → `UNAUTHORIZED`；已撤销或不存在 → `STROKE_NOT_FOUND`。

**客户端请求 `payload`**：`{ "stroke_id": "<uuid>" }`

**广播 `event_type`: `stroke_undone`**：`payload` 含 `stroke_id`、`user_id`、`user_name`。

**成功 ACK**：含 `op: "draw_undo"`、`stroke_id`、`server_sequence`。

**客户端重放**：与 `draw` 一并按序应用；见 **§6.2** 笔迹列表推导。

---

### 3.2.4 ANNOTATION_RESTORE - 恢复刚删除的标注

当某 `annotation_id` 的当前状态为「已 `annotation_removed`」，且 **发出该删除的用户** 请求恢复时，服务器从历史上最近一次 **`annotation`** 广播中取出字段，**再次 append 一条 `event_type: annotation` 广播**（内容、坐标等与删除前一致）。其他客户端无需新增渲染分支。

**条件不满足**（标注仍可见、从未存在、或删除者不是请求者）→ `ANNOTATION_NOT_FOUND`。

**客户端请求 `payload`**：`{ "annotation_id": "<uuid>" }`

**成功 ACK**：含 `op: "annotation_restore"`、`annotation_id`、`server_sequence`。

**说明**：若历史中的 `content` 违反当前安全子串规则，服务器可返回 `INVALID_MESSAGE`（防御性）。

---

### 3.2.5 DRAW_REDO - 恢复被 draw_undo 撤掉的笔迹

当某 `stroke_id` 的 **最后一条** 相关事件为 `stroke_undone`，且该笔原始 `draw` 的作者是请求者时，服务器在历史中找到对应的 `draw` 载荷，**再 append 一条 `event_type: draw` 广播**（与 **§3.2** 相同结构，`stroke_id` 不变）。若当前笔迹已处于可见状态（最后事件为 `draw`）或找不到可恢复的 `draw` → `STROKE_NOT_FOUND`。

**客户端请求 `payload`**：`{ "stroke_id": "<uuid>" }`（与 `draw_undo` 相同）

**成功 ACK**：含 `op: "draw_redo"`、`stroke_id`、`server_sequence`。

**与标注侧的「恢复」**：删除标注后的「撤销」用 `annotation_restore`（§3.2.4）；若用户希望 **再次删除** 刚恢复的标注，可再次发送 `annotation_delete`（协作语义上等价于对删除操作的 redo，由客户端快捷键/双栈实现，无单独 `annotation_redo` 消息）。

---

### 3.3 CLEAR - 直接清空（已弃用为独立操作）

为降低误删与恶意清屏风险，**客户端发送的 `type: "clear"` 不再执行清空**。服务器返回 **`ERROR`**，`error_code: CLEAR_REQUIRES_CONSENSUS`，详见下文 **`clear_propose` / `clear_vote`**。

历史上成功清空后的广播示例仍如下（表决通过后与此一致，并带 `consensus: true` 等字段）:

```json
{
  "type": "broadcast",
  "sequence_id": 3,
  "payload": {
    "event_type": "clear",
    "clear_type": "full",
    "user_id": "user_alice",
    "user_name": "Alice",
    "consensus": true,
    "proposal_id": "uuid"
  }
}
```

---

### 3.3.1 CLEAR_PROPOSE - 发起清空表决

- 发起者在 **`required_voters`（表决创建时房间内全体成员）** 中默认视为已投 **同意**。
- 若当时房间内仅有发起人一人，则 **立即执行清空**（与单人房间一致），并广播 `clear`。
- 否则写入内存态 `ClearProposalState`，并广播 `event_type: clear_propose`（含 `proposal_id`、`proposer_name`、`required_voters`、`expires_ms`、可选 `message`）。
- 同一房间 **同时仅允许一个** 待决提案；否则 `CLEAR_PROPOSAL_ACTIVE`。

**`payload`**（均可选扩展）: `{ "message": "string ≤500" }` 或 `{}`。

---

### 3.3.2 CLEAR_VOTE - 对清空表决投票

**`payload`**:

```json
{
  "proposal_id": "uuid",
  "vote": "approve | reject"
}
```

- 任一 **`reject`**：广播 `clear_rejected`，提案作废。
- 当 **`required_voters` ⊆ 已同意集合** 时：广播最终 **`clear`**，并清空画布历史。
- 重复同意：`CLEAR_VOTE_DUPLICATE`；提案不存在或过期：`CLEAR_PROPOSAL_NOT_FOUND`。
- 发起人离开：广播 `clear_proposal_cancelled`；其他成员离开：从 `required_voters` 中剔除后再判断可否达成全体同意。

维护循环会按 `CLEAR_PROPOSAL_TTL_MS` 广播 `clear_proposal_expired` 并清除内存态。

---

### 3.4 LEAVE - 离开房间

**客户端请求**:
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440004",
  "type": "leave",
  "timestamp": 1712889604000,
  "user_id": "user_alice",
  "room_id": "room_design1",
  "sequence_id": null,
  "payload": {
    "reason": "manual",
    "message": "User closed browser"
  }
}
```

**说明**: 
- `reason` 可以是: `manual | disconnect | timeout | error`
- 服务器会推送 ACK，然后广播 `user_left` 事件
- 如果这是房间的最后一个用户，触发清理策略

**服务器 ACK**:
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440004",
  "type": "ack",
  "timestamp": 1712889604500,
  "user_id": "server",
  "room_id": "room_design1",
  "sequence_id": 4,
  "payload": {
    "status": "ok",
    "room_user_count": 1
  }
}
```

**服务器广播** (其他用户收到):
```json
{
  "type": "broadcast",
  "sequence_id": 4,
  "payload": {
    "event_type": "user_left",
    "user_id": "user_alice",
    "reason": "manual",
    "remaining_users": 1,
    "room_cleanup_started": false
  }
}
```

当房间变为空（`remaining_users == 0`）时的广播：
```json
{
  "type": "broadcast",
  "sequence_id": 5,
  "payload": {
    "event_type": "room_idle",
    "room_id": "room_design1",
    "ttl_seconds": 60,
    "message": "Room will be destroyed in 60 seconds if no user rejoins"
  }
}
```

---

### 3.5 STATE_SYNC - 状态同步（重连支持）

用于客户端重连时同步完整的房间状态。

**客户端请求**:
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440005",
  "type": "state_sync",
  "timestamp": 1712889605000,
  "user_id": "user_alice",
  "room_id": "room_design1",
  "sequence_id": null,
  "payload": {
    "last_received_sequence": 4
  }
}
```

**服务器响应**:
```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440005",
  "type": "ack",
  "timestamp": 1712889605500,
  "user_id": "server",
  "room_id": "room_design1",
  "sequence_id": null,
  "payload": {
    "status": "ok",
    "room_state": {
      "room_id": "room_design1",
      "current_sequence": 10,
      "canvas_events": [
        { "sequence_id": 5, "type": "broadcast", "payload": {...} },
        { "sequence_id": 6, "type": "broadcast", "payload": {...} },
        ...
      ],
      "active_users": ["user_bob", "user_charlie"]
    }
  }
}
```

---

### 3.6 ACK - 成功响应

**格式**:
```json
{
  "msg_id": "request_msg_id",
  "type": "ack",
  "timestamp": 1712889610000,
  "user_id": "server",
  "room_id": "room_design1",
  "sequence_id": 10,
  "payload": {
    "status": "ok",
    "reason": "描述",
    "server_sequence": 10
  }
}
```

---

### 3.7 ERROR - 错误响应

**格式**:
```json
{
  "msg_id": "request_msg_id",
  "type": "error",
  "timestamp": 1712889610000,
  "user_id": "server",
  "room_id": "room_design1",
  "sequence_id": null,
  "payload": {
    "status": "fail",
    "error_code": "ROOM_NOT_FOUND | INVALID_MESSAGE | UNAUTHORIZED | RATE_LIMIT | ANNOTATION_NOT_FOUND | ...",
    "message": "详细错误信息",
    "details": {}
  }
}
```

**常见错误码**:

| 错误码 | HTTP等效 | 说明 |
|--------|---------|------|
| `ROOM_NOT_FOUND` | 404 | 房间不存在 |
| `INVALID_MESSAGE` | 400 | 消息格式错误 |
| `UNAUTHORIZED` | 403 | 无权限访问房间 |
| `RATE_LIMIT` | 429 | 速率限制 |
| `USER_ALREADY_JOINED` | 409 | 用户已加入 |
| `SEQUENCE_CONFLICT` | 409 | 序列号冲突 |
| `INTERNAL_ERROR` | 500 | 服务器错误 |
| `ANNOTATION_NOT_FOUND` | 404 | 标注不存在或已删除（当前不可见） |
| `STROKE_NOT_FOUND` | 404 | 笔迹不存在或已撤销 |

---

### 3.8 BROADCAST - 广播事件

服务器推送给所有连接的客户端的事件（包括发起者）。

**格式**:
```json
{
  "type": "broadcast",
  "timestamp": 1712889610000,
  "user_id": "user_bob",
  "room_id": "room_design1",
  "sequence_id": 10,
  "payload": {
    "event_type": "draw | stroke_undone | annotation | annotation_removed | clear | clear_propose | clear_rejected | clear_proposal_cancelled | clear_proposal_expired | user_joined | user_left | room_idle | room_destroyed",
    ...
  }
}
```

---

## 4. JSON Schema 验证

### 4.1 客户端请求 Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "msg_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    },
    "type": {
      "type": "string",
      "enum": ["join", "leave", "draw", "draw_undo", "draw_redo", "annotation", "annotation_delete", "annotation_restore", "clear", "clear_propose", "clear_vote", "state_sync"]
    },
    "timestamp": {
      "type": "number",
      "minimum": 0
    },
    "user_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "room_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "sequence_id": {
      "type": null
    },
    "payload": {
      "type": "object"
    }
  },
  "required": ["msg_id", "type", "timestamp", "user_id", "room_id", "payload"],
  "additionalProperties": false
}
```

### 4.2 DRAW Payload Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "stroke_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    },
    "tool": {
      "type": "string",
      "enum": ["pen", "eraser", "line", "rectangle", "circle"]
    },
    "color": {
      "type": "string",
      "pattern": "^#[0-9A-Fa-f]{6}$"
    },
    "width": {
      "type": "number",
      "minimum": 0.5,
      "maximum": 50
    },
    "points": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "x": { "type": "number" },
          "y": { "type": "number" },
          "pressure": { "type": "number", "minimum": 0, "maximum": 1 }
        },
        "required": ["x", "y", "pressure"]
      },
      "minItems": 1
    }
  },
  "required": ["stroke_id", "tool", "color", "width", "points"],
  "additionalProperties": false
}
```

### 4.3 ANNOTATION Payload Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "annotation_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    },
    "mode": { "type": "string", "enum": ["text", "formula"] },
    "content": { "type": "string" },
    "x": { "type": "number" },
    "y": { "type": "number" },
    "font_size": { "type": "number", "minimum": 8, "maximum": 72 },
    "color": { "type": "string", "pattern": "^#[0-9A-Fa-f]{6}$" }
  },
  "required": ["annotation_id", "mode", "content", "x", "y", "font_size", "color"],
  "additionalProperties": false
}
```

另：服务器对 `content` 做危险子串校验（见 **§9.4**），与 Schema 并行。

### 4.4 ANNOTATION_DELETE Payload Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "annotation_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    }
  },
  "required": ["annotation_id"],
  "additionalProperties": false
}
```

### 4.5 DRAW_UNDO / DRAW_REDO Payload Schema

```json
{
  "type": "object",
  "properties": {
    "stroke_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    }
  },
  "required": ["stroke_id"],
  "additionalProperties": false
}
```

`draw_undo` 与 `draw_redo` 共用上述载荷。

### 4.6 ANNOTATION_RESTORE Payload Schema

与 **§4.4 ANNOTATION_DELETE** 相同（仅 `annotation_id`）。

---

## 5. 变换 (Transformations) 和去重

### 5.1 去重策略

- **客户端**: 每个请求必须生成唯一的 `msg_id`（UUID v4）
- **服务器**: 维护 `dedup_window`（默认 300 秒），对重复的消息进行去重
  - 如果收到相同 `msg_id` 的消息，返回之前的 ACK 而不重新处理

### 5.2 事件变换

| 输入消息 | 输出事件 | 是否改变 |
|---------|---------|-------|
| `draw` | `broadcast` (event_type: draw) | 否，仅添加 sequence_id |
| `annotation` | `broadcast` (event_type: annotation) | 否，仅添加 sequence_id |
| `annotation_delete` | `broadcast` (event_type: annotation_removed) | 否，仅添加 sequence_id |
| `draw_undo` | `broadcast` (event_type: stroke_undone) | 否，仅添加 sequence_id |
| `draw_redo` | `broadcast` (event_type: draw，重放被撤笔迹) | 否，仅添加 sequence_id |
| `annotation_restore` | `broadcast` (event_type: annotation，重复一条创建形载荷) | 否，仅添加 sequence_id |
| `clear` | **ERROR**（CLEAR_REQUIRES_CONSENSUS）或表决通过后 `broadcast` (event_type: clear) | 表决通过时会清空 `canvas_history`（实现相关） |
| `clear_propose` / `clear_vote` | 多条广播（clear_propose、clear_rejected、clear、等） | 依表决状态 |
| `join` | `broadcast` (event_type: user_joined) | 否 |
| `leave` | 2个事件: `user_left` + `room_idle` (如果是最后一个用户) | 是 |

---

## 6. 时序和顺序保证

### 6.1 全局序列号 (Global Sequence ID)

- **定义**: 服务器维护单调递增的计数器，每个事件（广播）赋予一个唯一的 `sequence_id`
- **初始值**: 从 0 开始
- **规则**:
  1. JOIN 消息不立即分配 sequence_id，而是在 ACK 中返回 room 的 current_sequence
  2. 首个 DRAW/CLEAR 消息获得 sequence_id = 0
  3. 后续事件递增

### 6.2 客户端重放顺序

客户端必须按 `sequence_id` 递增的顺序重放事件。异序到达的事件应该：
1. 放入优先队列
2. 按顺序从队列取出并应用

**标注叠加层**：笔迹仍仅由 `draw` / `clear` 等驱动；**标注**由 `annotation` 与 `annotation_removed` 成对维护。重放 `canvas_history` 时应对每个 `annotation_id` 应用与服务器相同的「最后事件 wins」规则（见 **§3.2.2**）。

**笔迹列表**：在 `clear` 之前，对 `draw` 与 `stroke_undone` 按序处理，对每个 `stroke_id` 取最后一次相关事件（见 **§3.2.3**）。

---

## 7. 错误处理

### 7.1 服务器端验证

| 检查项 | 操作 |
|--------|------|
| JSON 格式错误 | → `INVALID_MESSAGE` |
| 缺少必要字段 | → `INVALID_MESSAGE` |
| user_id 或 room_id 非法 | → `INVALID_MESSAGE` |
| 房间不存在 | → `ROOM_NOT_FOUND` |
| 用户已加入 | → `USER_ALREADY_JOINED` |
| 用户未加入（但发送 LEAVE/DRAW 等） | → `UNAUTHORIZED` |
| 非创建者发送 `annotation_delete` | → `UNAUTHORIZED` |
| 删除不存在的标注 / 重复删除 | → `ANNOTATION_NOT_FOUND` |
| 非作者 `draw_undo` / 重复撤销 | → `UNAUTHORIZED` / `STROKE_NOT_FOUND` |
| 无资格 `annotation_restore` | → `ANNOTATION_NOT_FOUND` |
| 速率超限 | → `RATE_LIMIT` |
| 消息大小超限 | → `INVALID_MESSAGE` |

### 7.2 客户端处理

| 错误类型 | 客户端操作 |
|---------|----------|
| `RATE_LIMIT` | 等待后重试（指数退避） |
| `ROOM_NOT_FOUND` | 提示用户"房间已销毁"，断开连接 |
| `UNAUTHORIZED` | 重新加入房间 |
| `INTERNAL_ERROR` | 重试或重连 |
| `SEQUENCE_CONFLICT` | 请求 state_sync 同步完整状态 |
| `ANNOTATION_NOT_FOUND` | 忽略或提示；勿假定标注仍存在 |
| `STROKE_NOT_FOUND` | 忽略或提示；勿假定笔迹仍可撤销 |

---

## 8. 传输层细节

### 8.1 WebSocket 配置

| 参数 | 值 | 说明 |
|------|-----|------|
| 连接超时 | 30 秒 | 建立 WebSocket 连接的超时 |
| 心跳间隔 | 30 秒 | Ping/Pong 间隔 |
| 读超时 | 60 秒 | 等待消息的超时 |
| 最大消息大小 | 1 MB | 单个消息大小限制 |
| 缓冲区大小 | 65536 bytes | 读写缓冲区大小 |

### 8.2 背压处理 (Backpressure)

- 如果客户端接收缓冲区满，服务器应停止广播该客户端的消息
- 客户端收到消息后应立即 ACK（隐式或显式）
- 服务器实现消息队列以缓冲待发送的消息

---

## 9. 安全约束

### 9.1 消息验证

```
1. JSON Schema 验证
2. 字段范围检查（如 color 格式、width 范围）
3. 时间戳有效性检查（±30 秒容差）
4. user_id 和 room_id 非空且长度 ≤ 100
```

### 9.2 速率限制

```
- 每个用户每秒最多 100 个消息
- 每个房间每秒最多 1000 个事件
- 连接建立后，JOINM 消息必须在 30 秒内发送
```

### 9.3 消息大小限制

```
- 单个消息: ≤ 1 MB
- draw 消息的 points 数组: ≤ 1000 个点
- stroke_id 长度: 36 字符（UUID）
- annotation.content 长度 ≤ 2000（可配置）
```

### 9.4 内容安全（标注与渲染）

```
1. annotation 在 Schema 之外增加「危险子串」拒绝（如 <script、javascript:、onerror=、<iframe 等），防止将 HTML/脚本注入协作载荷。
2. 客户端 MUST 使用 textContent 或受信任的公式渲染器（如 KaTeX）渲染；不得将 content 直接作为 innerHTML 拼接。
3. formula 模式仍可能被恶意 LaTeX 消耗 CPU；应限制长度并依赖渲染器沙箱/超时（前端责任）。
4. 清空画布 MUST 经 clear_propose + 全员 clear_vote 同意（单人房除外），防止单方毁损共享状态。
5. 表决提案 TTL 由服务器强制，避免悬挂提案永久阻塞新申请。
6. `annotation_delete` 仅允许创建者删除对应 `annotation_id`，避免他方恶意移除他人标注。
```

### 9.5 错误码补充

| `error_code` | 含义 |
|--------------|------|
| `CLEAR_REQUIRES_CONSENSUS` | 禁止使用裸 `clear`，应走表决流程 |
| `CLEAR_PROPOSAL_ACTIVE` | 房间已有待决清空提案 |
| `CLEAR_PROPOSAL_NOT_FOUND` | 提案 id 不匹配或已过期 |
| `CLEAR_VOTE_DUPLICATE` | 同一用户对同一提案重复投同意票 |
| `ANNOTATION_NOT_FOUND` | `annotation_id` 当前不可见（从未创建或已 `annotation_removed`），或无可恢复的删除 |
| `STROKE_NOT_FOUND` | `stroke_id` 当前不存在（已撤销或从未绘制） |

---

## 10. 示例完整交互序列

### 场景: 两个用户协作绘画

```
时间线:

T=0: Alice 加入房间 room_design1
    -> Alice 发送 JOIN
    <- Server ACK (sequence_id=0, canvas_history=[])

T=1: Bob 加入房间 room_design1
    -> Bob 发送 JOIN
    <- Server ACK (sequence_id=1, canvas_history=[])
    <- Alice 收到 BROADCAST (event_type: user_joined, user_id: Bob)

T=2: Alice 绘制红色笔迹
    -> Alice 发送 DRAW (stroke_id=stroke_001, ...)
    <- Server ACK (sequence_id=2)
    <- Alice 和 Bob 收到 BROADCAST (event_type: draw, stroke_id=stroke_001, ...)

T=3: Bob 绘制蓝色笔迹
    -> Bob 发送 DRAW (stroke_id=stroke_002, ...)
    <- Server ACK (sequence_id=3)
    <- Alice 和 Bob 收到 BROADCAST (event_type: draw, stroke_id=stroke_002, ...)

T=4: Alice 离开房间
    -> Alice 发送 LEAVE (reason: manual)
    <- Server ACK (sequence_id=4)
    <- Bob 收到 BROADCAST (event_type: user_left, user_id: Alice, remaining_users: 1)

T=5: Bob 继续绘制
    -> Bob 发送 DRAW (stroke_id=stroke_003, ...)
    <- Server ACK (sequence_id=5)
    <- Bob 收到 BROADCAST (sequence_id=5)

T=6: Bob 离开房间
    -> Bob 发送 LEAVE (reason: manual)
    <- Server ACK (sequence_id=6)
    <- Server 发送 BROADCAST (event_type: room_idle, ttl_seconds: 60)

T=7 ~ T=66: 房间处于 IDLE 状态，TTL 倒计时

T=67: TTL 过期
    <- 房间从存储中删除，状态转为 DESTROYED
```

### 场景: 标注创建、同步与删除

```
T=0: Alice 发送 ANNOTATION（annotation_id = A1，mode=text）
    <- ACK
    <- Alice、Bob 收到 BROADCAST (event_type: annotation, annotation_id=A1, ...)

T=1: Bob 发送 ANNOTATION_DELETE（annotation_id = A1）
    <- ERROR (error_code: UNAUTHORIZED)   // Bob 不是创建者

T=2: Alice 发送 ANNOTATION_DELETE（annotation_id = A1）
    <- ACK
    <- Alice、Bob 收到 BROADCAST (event_type: annotation_removed, annotation_id=A1)

T=3: Alice 再次发送 ANNOTATION_DELETE（annotation_id = A1）
    <- ERROR (error_code: ANNOTATION_NOT_FOUND)

T=4: 新客户端 Carol JOIN 后重放 canvas_history
    -> 按序应用 annotation(A1) 与 annotation_removed(A1)，最终无 A1 覆盖层
```

---

## 11. 协议设计总结

| 方面 | 设计决策 |
|------|---------|
| 消息格式 | 统一 JSON，包含 msg_id、type、sequence_id 等基础字段 |
| 事件顺序 | 服务器赋予全局 sequence_id，客户端按序重放 |
| 一致性 | 最终一致性（eventually consistent） |
| 容错 | 每个请求都有 ACK/ERROR 响应 |
| 去重 | UUID msg_id + 服务器端去重窗口 |
| 清理 | 参考计数 + TTL 定时器 |
| 安全 | JSON Schema、速率限制、消息大小、标注内容过滤、表决式清屏、标注仅创建者可删、笔迹仅作者可 undo |
| 客户端扩展 | 参考实现可在本地汇总 ACK 生成「离开房间小结」（停留时长、操作次数）；非协议字段，不参与同步 |

---

**下一步**: 转到 `02_STATE_MACHINE_DESIGN.md` 进行状态机设计
