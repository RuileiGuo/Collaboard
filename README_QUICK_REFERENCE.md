# CollabBoard - 快速参考指南 (Quick Reference Guide)

**用途**: 实现阶段的快速查阅  
**日期**: 2026-05-07

---

## 1. 消息格式速查表

### 1.1 基础消息壳

```json
{
  "msg_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "join|leave|draw|draw_undo|draw_redo|annotation|annotation_delete|annotation_restore|clear|clear_propose|clear_vote|state_sync|ack|error|broadcast",
  "timestamp": 1712889600000,
  "user_id": "user_xxx",
  "room_id": "room_yyy",
  "sequence_id": 0,
  "payload": {}
}
```

### 1.2 消息类型速记

| Type | C/S | Seq | Payload | 广播 |
|------|-----|-----|---------|------|
| JOIN | C→S | null | metadata | 是(user_joined) |
| LEAVE | C→S | null | reason | 是(user_left) |
| DRAW | C→S | null | stroke | 是(draw) |
| ANNOTATION | C→S | null | text/formula + 坐标 | 是(annotation) |
| ANNOTATION_DELETE | C→S | null | `annotation_id` (UUID) | 是(annotation_removed)，仅创建者成功 |
| ANNOTATION_RESTORE | C→S | null | `annotation_id` | 是(annotation)，仅删除操作者可恢复 |
| DRAW_UNDO | C→S | null | `stroke_id` (UUID) | 是(stroke_undone)，仅笔迹作者 |
| DRAW_REDO | C→S | null | `stroke_id` (UUID) | 是(draw)，恢复被撤笔迹 |
| CLEAR | C→S | null | type | **拒绝**：须表决 |
| CLEAR_PROPOSE | C→S | null | 可选 message | 是(clear_propose) 或立即 clear |
| CLEAR_VOTE | C→S | null | proposal_id + vote | 可能 clear / clear_rejected |
| STATE_SYNC | C→S | null | last_seq | 否 |
| ACK | S→C | ✓ | status | 否 |
| ERROR | S→C | null | error_code | 否 |
| BROADCAST | S→C | ✓ | event | N/A |

---

## 2. 状态机速查表

### 2.1 用户状态转移规则

```
INIT
 └─ WebSocket 连接
    └─ CONNECTED
       ├─ JOIN (30秒超时)
       │  └─ JOINED
       │     ├─ DRAW / ANNOTATION / ANNOTATION_DELETE / CLEAR / …
       │     │  └─ ACTIVE
       │     │     ├─ 上述消息 (重置超时)
       │     │     ├─ LEAVE
       │     │     │  └─ LEFT
       │     │     │     └─ (5秒后自动)
       │     │     │        └─ DISCONNECTED
       │     │     └─ (3分钟无消息)
       │     │        └─ IDLE
       │     │           ├─ (消息恢复) → ACTIVE
       │     │           └─ (3分钟无恢复)
       │     │              └─ TIMEOUT
       │     │                 └─ DISCONNECTED
       │     │
       │     └─ LEAVE
       │        └─ LEFT
       │           └─ DISCONNECTED
       │
       └─ (30秒无JOIN)
          └─ DISCONNECTED
```

### 2.2 房间状态转移规则

```
创建时: PENDING_INIT (300秒超时无用户)

首个 JOIN
 └─ ACTIVE
    ├─ 用户加入 (ACTIVE 保持)
    ├─ 用户离开 (ACTIVE 保持, ref_count > 0)
    │
    └─ 最后一个用户离开 (ref_count == 0)
       └─ IDLE (启动 60秒 TTL)
          ├─ 用户重新加入 (TTL 取消)
          │  └─ ACTIVE (返回 ACTIVE)
          │
          └─ (60秒 TTL 过期)
             └─ DESTROYED (资源完全释放)
```

---

## 3. 错误码速查表

| 错误码 | HTTP等价 | 处理建议 | 客户端操作 |
|--------|---------|--------|----------|
| INVALID_MESSAGE | 400 | 检查消息格式 | 不重试，日志 |
| ROOM_NOT_FOUND | 404 | 房间已销毁 | 提示用户，断开 |
| UNAUTHORIZED | 403 | 用户权限问题 | 重新加入房间 |
| USER_ALREADY_JOINED | 409 | 重复加入 | 忽略或发送 LEAVE |
| RATE_LIMIT | 429 | 速率超限 | 指数退避重试 |
| SEQUENCE_CONFLICT | 409 | 序列号冲突 | 发送 STATE_SYNC |
| INTERNAL_ERROR | 500 | 服务器错误 | 自动重试 |
| ANNOTATION_NOT_FOUND | 404 | 标注已删或不存在 | 刷新 UI，勿重试删除 |
| STROKE_NOT_FOUND | 404 | 笔迹已撤销或不存在 | 同步或忽略 |
| CLEAR_REQUIRES_CONSENSUS | 400 | 禁止裸 clear | 走 clear_propose / clear_vote |
| CLEAR_PROPOSAL_ACTIVE | 409 | 已有清空表决 | 等待结束再申请 |
| CLEAR_PROPOSAL_NOT_FOUND | 404 | 提案无效/过期 | 重新发起或忽略 |
| CLEAR_VOTE_DUPLICATE | 409 | 重复投同意票 | 忽略 |

---

## 4. 数据结构速查表

### 4.1 JSON Schema 验证

**客户端请求**:
```python
{
    "msg_id": str(uuid4),
    "type": enum("join", "leave", "draw", "draw_undo", "draw_redo", "annotation", "annotation_delete",
                 "annotation_restore", "clear", "clear_propose", "clear_vote", "state_sync"),
    "timestamp": int,  # >= 0
    "user_id": str,    # 1-100 chars
    "room_id": str,    # 1-100 chars
    "sequence_id": None,  # 客户端请求必须为 None
    "payload": dict    # 根据 type 而定
}
```

**ANNOTATION_DELETE Payload**:
```python
{
    "annotation_id": str(uuid4),
}
```

**DRAW Payload**:
```python
{
    "stroke_id": str(uuid4),
    "tool": enum("pen", "eraser", "line", "rectangle", "circle"),
    "color": str,      # #RRGGBB format
    "width": float,    # 0.5-50
    "points": [
        {"x": float, "y": float, "pressure": float}  # pressure 0-1
    ]
}
```

### 4.2 内存数据结构示意

```python
# Room 对象
class Room:
    room_id: str
    state: RoomState              # PENDING_INIT|ACTIVE|IDLE|DESTROYED
    users: Dict[str, UserSession] # {user_id: session}
    canvas_history: List[Event]   # [{sequence_id, event_data}]
    current_sequence: int         # 自增计数器
    idle_timer: TimerHandle       # TTL 定时器

# Connection 对象
class WebSocketClient:
    connection_id: str
    user_id: str
    room_id: str
    websocket: WebSocket
    user_state: UserState       # INIT|CONNECTED|JOINED|ACTIVE|...

# Message 对象 (接收后)
class Message:
    msg_id: str
    type: str
    user_id: str
    room_id: str
    timestamp: int
    payload: dict
    sequence_id: int (服务器设置)
```

---

## 5. 处理流程速查

### 5.1 消息接收处理流程

```
1. WebSocket 收到消息 (raw_data: str)
   ↓
2. JSON 反序列化 (try-except)
   ↓
3. 基础 Schema 验证 (msg_id, type, user_id, room_id)
   ↓ (失败)
4. 发送 ERROR(INVALID_MESSAGE)
   ↓ (成功)
5. 检查 msg_id 去重缓存
   ↓ (重复)
6. 返回缓存的响应 (ACK 或 ERROR)
   ↓ (新消息)
7. 消息类型路由
   ├─ JOIN    → JoinHandler.handle()
   ├─ LEAVE   → LeaveHandler.handle()
   ├─ DRAW    → DrawHandler.handle()
   ├─ ANNOTATION → AnnotationHandler.handle()
   ├─ ANNOTATION_DELETE → AnnotationDeleteHandler.handle()
   ├─ ANNOTATION_RESTORE → AnnotationRestoreHandler.handle()
   ├─ DRAW_UNDO → DrawUndoHandler.handle()
   ├─ DRAW_REDO → DrawRedoHandler.handle()
   ├─ CLEAR   → ClearHandler.handle()（通常返回 CLEAR_REQUIRES_CONSENSUS）
   ├─ CLEAR_PROPOSE / CLEAR_VOTE → 对应 Handler
   └─ STATE_SYNC → StateSyncHandler.handle()
   ↓ (失败)
8. 发送 ERROR
   ↓ (成功)
9. 执行业务逻辑
   ├─ 更新状态
   ├─ 赋予 sequence_id
   └─ 返回 ACK
   ↓
10. 构建广播消息
   ↓
11. 广播到房间所有用户
   ↓
12. 消息缓存到 dedup_window
```

### 5.2 DRAW 消息处理细节

```
1. 验证 user_id 在房间内
   ↓ (否) → ERROR(UNAUTHORIZED)
   ↓ (是)

2. 验证 payload (Pydantic)
   ├─ stroke_id 是否 UUID
   ├─ tool 是否 enum
   ├─ color 是否 #RRGGBB
   ├─ width 是否 0.5-50
   └─ points 是否 ≤ 1000 个点
   ↓ (任何失败) → ERROR(INVALID_MESSAGE)
   ↓ (全部通过)

3. 获取房间对象
   ↓ (不存在) → ERROR(ROOM_NOT_FOUND)
   ↓ (存在)

4. 分配 sequence_id
   sequence_id = room.current_sequence + 1
   room.current_sequence = sequence_id

5. 添加到 canvas_history
   room.canvas_history.append({
       'sequence_id': sequence_id,
       'event': message
   })

6. 发送 ACK 给客户端
   ack_msg = {
       'msg_id': msg['msg_id'],
       'type': 'ack',
       'sequence_id': sequence_id,
       'payload': {'status': 'ok', 'server_sequence': sequence_id}
   }

7. 广播给房间所有用户
   broadcast_msg = {
       'type': 'broadcast',
       'sequence_id': sequence_id,
       'payload': {
           'event_type': 'draw',
           'stroke_id': payload['stroke_id'],
           'tool': payload['tool'],
           'color': payload['color'],
           'width': payload['width'],
           'points': payload['points']
       }
   }
   for user in room.users:
       for conn in connections_for_user:
           send_json(conn, broadcast_msg)
```

---

## 6. 超时配置速采表

| 事件 | 超时时间 | 操作 | 转移 |
|------|---------|------|------|
| WebSocket 连接建立 | 30秒 | 仍未收到 JOIN，断开 | CONNECTED→DISCONNECTED |
| JOIN 消息 | 30秒 | 必须在连接后 30秒内发送 | 否则 DISCONNECTED |
| 无活动（JOINED） | 60秒 | 无消息则转为 IDLE | JOINED→IDLE |
| 无活动（ACTIVE） | 3分钟 | 无消息则转为 IDLE | ACTIVE→IDLE |
| IDLE 持续 | 3分钟 | 仍无消息则 TIMEOUT | IDLE→TIMEOUT |
| LEFT 状态 | 5秒 | 进行连接关闭 | LEFT→DISCONNECTED |
| TIMEOUT 状态 | 立即 | 服务器主动断开 | TIMEOUT→DISCONNECTED |
| IDLE 房间 | 60秒 | TTL 过期则销毁 | IDLE→DESTROYED |
| PENDING_INIT 房间 | 300秒 | 无用户加入则销毁 | PENDING_INIT→DESTROYED |

---

## 7. 速率限制配置

```
每个用户:
  - 最大 100 消息/秒
  - 超过 → 返回 ERROR(RATE_LIMIT)
  
每个房间:
  - 最大 1000 事件/秒 (广播)
  - 超过 → 丢弃消息 (不返回 ACK，日志记录)

实现方式: 令牌桶算法 (Token Bucket)
  初始令牌: = 限制值
  每秒补充: = 限制值
  消息成本: = 1 令牌
  令牌不足: 拒绝消息
```

---

## 8. 广播规则速查

| 事件类型 | 触发消息 | 包含信息 | 接收者 |
|---------|---------|--------|--------|
| user_joined | JOIN | user_id, user_name, user_count | 房间所有人 |
| user_left | LEAVE | user_id, reason, remaining_users | 房间所有人 |
| draw | DRAW | stroke_id, tool, color, width, points | 房间所有人 + 发起者 |
| annotation | ANNOTATION | annotation_id, mode, content, x, y, font_size, color, user_name | 房间所有人 |
| annotation_removed | ANNOTATION_DELETE | annotation_id, user_id, user_name | 房间所有人 |
| stroke_undone | DRAW_UNDO | stroke_id, user_id, user_name | 房间所有人 |
| clear | 表决通过后 | clear_type, consensus, proposal_id, … | 房间所有人 |
| clear_propose 等 | CLEAR_PROPOSE / VOTE | proposal_id, voters, … | 房间所有人 |
| room_idle | (最后离开) | room_id, ttl_seconds | 房间所有人 |
| room_destroyed | (TTL 过期) | room_id | 房间所有人 |

**广播策略**:
- 始终包括发起者
- 对异常断开的连接进行重试（最多 3 次）
- 连接失败则记录日志，继续处理下一个连接

---

## 9. 去重机制速查

```
客户端:
  每个消息生成唯一 msg_id = uuid4()

服务器:
  维护 dedup_cache = {msg_id: (timestamp, response)}
  
  接收消息时:
    if msg_id in dedup_cache:
        age = current_time - timestamp
        if age < 300秒:  # dedup_window = 300秒
            return 缓存的响应 (ACK 或 ERROR)
        else:
            从缓存删除，重新处理
    else:
        处理消息，将响应加入缓存

优点:
  - 处理网络重传
  - 保证幂等性
  - 重启前的重复被算作新消息（可接受）
```

---

## 10. 重连支持速查

### 10.1 客户端重连流程

```
1. 检测到网络断开
   → 记录 last_sequence_received = N

2. 主动重连 (指数退避: 1s, 2s, 4s, 最多 10s)
   → WebSocket.connect()
   → 转移到 CONNECTED 状态

3. 重新 JOIN
   → 发送 JOIN 消息
   → 进入 JOINED 状态

4. 同步缺失事件
   → 发送 STATE_SYNC + last_sequence_received
   → 服务器返回 [N+1, current_sequence] 的所有事件

5. 重放缺失事件
   → 按 sequence_id 排序并应用
   → Canvas 恢复到最新状态

6. 恢复为 ACTIVE
```

### 10.2 服务器重连处理

```
收到 STATE_SYNC 请求:
  1. 验证 user_id 在房间
  2. 查询 canvas_history
  3. 过滤出 sequence_id > last_received_sequence 的事件
  4. 返回完整房间状态 + 缺失事件
  5. 不发送 ACK 或 ERROR（直接响应）
```

---

## 11. 清理策略速查

### 11.1 参考计数

```
Room 对象有 user_count 分子:

JOIN 事件:
  user_count += 1

LEAVE 事件:
  user_count -= 1
  
  if user_count == 0:
      Room.state = IDLE
      Room.start_idle_timer(60秒)

用户 TIMEOUT:
  user_count -= 1
  
  if user_count == 0:
      Room.state = IDLE
      (如果还未启动 TTL，启动之)
```

### 11.2 TTL 定时器

```
启动条件:
  Room.state == IDLE && user_count == 0

定时器动作 (60秒后):
  1. 检查 Room 是否仍在 IDLE 状态
  2. 如果有新用户加入 (user_count > 0)
     → 取消 TTL
  3. 否则
     → room_mgr.destroy_room()
     → 释放内存

取消条件:
  用户重新 JOIN
  → cancel_idle_timer()
  → Room.state = ACTIVE
  → user_count = 1
```

---

## 12. 性能优化建议

### 12.1 关键路径优化

```
消息处理循环:
  O(1) JSON 解析 (使用高效库)
  ↓
  O(1) Schema 验证 (缓存 schema 对象)
  ↓
  O(1) 去重查询 (哈希表)
  ↓
  O(1) 消息路由 (字典分发)
  ↓
  Handler:
    O(1) 房间查询 (global dict)
    O(1) 状态转移 (Lock)
    O(n) 广播 (n = room users, 通常 ≤ 100)

总体: O(n) per message, 其中 n 为房间用户数
```

### 12.2 内存优化

```
Canvas 历史压缩:
  - 不压缩 DRAW events
  - CLEAR 事件后清空历史
  - 定期快照（可选）

连接缓冲:
  - 使用固定大小缓冲区 (64 KB)
  - 背压处理 (Backpressure)

去重缓存:
  - 使用 LRU 缓存 (最多 10000 条)
  - 300秒过期（自动清理）
```

---

## 13. 调试技巧

### 13.1 消息追踪

在每个消息处理步骤添加日志:
```python
logger.info(f"[{msg_id}] Received {msg_type} from {user_id}")
logger.info(f"[{msg_id}] Validated payload")
logger.info(f"[{msg_id}] Assigned sequence_id={seq_id}")
logger.info(f"[{msg_id}] Broadcasting to {user_count} users")
```

### 13.2 状态转移追踪

```python
logger.info(f"[User {user_id}] {from_state} → {to_state}")
logger.info(f"[Room {room_id}] {from_state} → {to_state}")
```

### 13.3 性能分析

```python
import time

start = time.time()
# 业务逻辑
duration = time.time() - start

if duration > 0.1:  # 超过 100ms 警告
    logger.warning(f"Slow operation: {duration}s")
```

---

## 14. 常见错误清单

| 错误 | 原因 | 处理 |
|------|------|------|
| 消息乱序 | 网络延迟不同 | 客户端缓冲+按 seq_id 排序 |
| 重复事件 | 网络重传 | 服务器去重 (msg_id) |
| Sequence 冲突 | 竞态条件 | 使用 Lock 保护计数器 |
| TTL 提前销毁 | 时间戳不准 | 使用 time.time() 而非 system() |
| 内存泄漏 | 房间永不销毁 | 确保 TTL 机制工作 |
| 连接堆积 | 忘记关闭 | 异常时调用 websocket.close() |

---

## 总结

本快速参考指南涵盖了 CollabBoard 系统的关键设计决策、协议细节、状态转移规则和实现建议。

**记住最重要的三点**:
1. 🔑 **每个消息都有 msg_id** - 用于去重
2. 📊 **序列号保证顺序** - 客户端按 sequence_id 重放
3. 🧹 **清理策略很重要** - 参考计数 + TTL 防止资源泄漏

---

