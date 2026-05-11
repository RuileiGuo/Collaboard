# CollabBoard - 研究计划总结 (Research Plan Summary)

**项目**: 生产级实时协作白板系统 (CollabBoard)  
**日期**: 2026-04-14  
**状态**: 设计阶段完成，准备进入实现

---

## 1. 项目目标

构建一个**严格遵循协议、实现完整状态机、采用模块化架构**的 WebSocket 实时协作白板系统，支持：

- ✓ 多用户实时协作绘画
- ✓ 事件驱动的一致性模型（最终一致性）
- ✓ 完整的错误处理和容错机制
- ✓ 自动清理策略（参考计数 + TTL）
- ✓ 网络中断恢复（STATE_SYNC）
- ✓ 生产级别的安全性和消息验证

---

## 2. 核心设计原则

### 2.1 协议严格性

```
原则: "所有消息必须遵循统一的 JSON 结构"

{
  "msg_id":        UUID(v4),              // 消息去重
  "type":          enum,                  // 消息类型
  "timestamp":     milliseconds,          // 客户端时间戳
  "user_id":       string,                // 用户标识
  "room_id":       string,                // 房间标识
  "sequence_id":   int | null,            // 服务器赋予的全局序列号
  "payload":       object                 // 消息内容
}
```

**好处**:
- 清晰的消息格式
- 易于验证和序列化
- 便于调试和日志分析

---

### 2.2 状态机显式建模

**用户状态**:
```
INIT → CONNECTED → JOINED → ACTIVE → LEFT → DISCONNECTED
                      ↓
                     IDLE ↔ TIMEOUT
```

**房间状态**:
```
PENDING_INIT → ACTIVE ↔ IDLE → DESTROYED
```

**好处**:
- 清晰的状态转移逻辑
- 防止非法状态
- 易于追踪和调试

---

### 2.3 事件驱动 + 全局序列号

```
所有操作 → 事件 → 服务器赋予序列号 → 广播到所有客户端 → 客户端重放
```

**一致性保证**:
- 所有客户端看到相同的事件序列
- 通过重放相同的事件序列，所有客户端达到相同的最终状态

---

### 2.4 清理策略 (优雅)

```
最后一个用户离开 → 房间标记为 IDLE → 启动 TTL 计时器 (60秒)
    ├─ 用户重新加入 → 接收 IDLE_CANCEL → 房间恢复 ACTIVE
    └─ 60 秒后无用户 → 房间销毁，资源释放
```

**好处**:
- 避免资源泄漏
- 支持用户快速重连
- 参考计数确保准确性

---

## 3. 核心协议设计

### 3.1 消息类型 (7 种)

| 类型 | 方向 | 说明 | 状态转移 |
|------|------|------|--------|
| **JOIN** | C→S | 用户加入房间 | CONNECTED→JOINED |
| **LEAVE** | C→S | 用户离开房间 | JOINED/ACTIVE→LEFT |
| **DRAW** | C→S | 绘制笔迹 | JOINED→ACTIVE |
| **CLEAR** | C→S | 清空画布 | ACTIVE 保持 |
| **STATE_SYNC** | C→S | 同步完整状态（重连） | ACTIVE 保持 |
| **ACK** | S→C | 成功响应 | N/A |
| **ERROR** | S→C | 错误响应 | N/A |
| **BROADCAST** | S→C | 事件广播 | N/A |

### 3.2 关键协议细节

| 细节 | 设计 |
|------|------|
| 去重 | `msg_id` (UUID) + 服务器 300秒 dedup_window |
| 序列 | 全局单调递增 `sequence_id`（从 0 开始） |
| 心跳 | WebSocket 原生 Ping/Pong（30秒间隔） |
| 超时 | 连接: 30秒，JOIN: 30秒，无活动: 3分钟 |
| TTL | IDLE 房间: 60 秒后销毁 |
| 速率限制 | 100 msg/sec per user, 1000 event/sec per room |
| 消息大小 | ≤ 1 MB, DRAW points ≤ 1000 |

---

## 4. 状态机转移规则

### 4.1 用户状态转移矩阵

| 当前 / 事件 | JOIN | LEAVE | DRAW | TIMEOUT | RECONNECT |
|-----------|------|-------|------|---------|-----------|
| CONNECTED | →JOINED | ✗ | ✗ | →DISCONNECTED | ✗ |
| JOINED | ✗ | →LEFT | →ACTIVE | →TIMEOUT | N/A |
| ACTIVE | ✗ | →LEFT | ACTIVE | →TIMEOUT | N/A |
| LEFT | ✗ | ✗ | ✗ | ✗ | →DISCONNECTED |
| IDLE | ✗ | ✗ | →ACTIVE | →TIMEOUT | ✗ |
| DISCONNECTED | ✗ | ✗ | ✗ | ✗ | ✗ |

### 4.2 房间状态转移矩阵

| 当前 / 事件 | 首个JOIN | 用户LEAVE | 最后离开 | 用户重入 | TTL超期 |
|-----------|---------|----------|--------|--------|--------|
| PENDING_INIT | →ACTIVE | N/A | N/A | N/A | →DESTROYED |
| ACTIVE | ACTIVE | 保持 | →IDLE | N/A | N/A |
| IDLE | →ACTIVE | N/A | N/A | →ACTIVE | →DESTROYED |
| DESTROYED | N/A | N/A | N/A | ✗ | N/A |

---

## 5. 完整的消息交互序列

### 5.1 最小场景: 1 用户加入

```
时间轴:

T=0: 客户端建立 WebSocket 连接
    ↓
    ClientConnection: NEW → OPEN

T=1: 客户端发送 JOIN 消息
    → {msg_id: UUID1, type: "join", user_id: "alice", room_id: "room1", ...}
    ↓
    Server: 验证消息
    Server: User State CONNECTED → JOINED
    Server: Room State PENDING_INIT → ACTIVE
    Server: 赋予 sequence_id = 0

T=2: 服务器发送 ACK
    ← {msg_id: UUID1, type: "ack", sequence_id: 0, payload: {room_state: {...}}}
    ↓
    ClientConnection: 收到 ACK，确认 JOIN 成功

T=3+: 客户端可以发送 DRAW/CLEAR/STATE_SYNC
```

### 5.2 完整场景: 2 用户协作

```
T=0: Alice 加入房间
    Alice: JOIN → ack (seq=0)
    所有人: broadcast user_joined (seq=1) [仅 Alice]

T=1: Bob 加入房间
    Bob: JOIN → ack (seq=1)
    所有人: broadcast user_joined (seq=2) [Alice, Bob]

T=2: Alice 绘制红笔
    Alice: DRAW stroke_001 → ack (seq=2)
    所有人: broadcast draw stroke_001 (seq=3) [Alice, Bob]

T=3: Bob 绘制蓝笔
    Bob: DRAW stroke_002 → ack (seq=3)
    所有人: broadcast draw stroke_002 (seq=4) [Alice, Bob]

T=4: Alice 离开房间
    Alice: LEAVE → ack (seq=4)
    所有人: broadcast user_left (seq=5) [Bob]

T=5: Bob 继续绘制
    Bob: DRAW stroke_003 → ack (seq=5)
    所有人: broadcast draw stroke_003 (seq=6) [Bob]

T=6: Bob 离开房间
    Bob: LEAVE → ack (seq=6)
    所有人: broadcast user_left (seq=7) [无人]
    
    → 房间从 ACTIVE 转移到 IDLE
    → 广播 room_idle 事件 (seq=8)
    → 启动 60 秒 TTL 计时器

T=7~66: 房间维持 IDLE 状态

T=67: TTL 过期
    → 房间销毁，状态转移到 DESTROYED
    → 从服务器内存中删除
```

### 5.3 重连场景: 网络中断恢复

```
T=0: Alice 和 Bob 正常绘画 (seq=50)

T=1: Alice 网络中断
    → WebSocket 连接断开
    → ClientConnection: OPEN → CLOSED
    → 服务器标记 Alice 为 IDLE（超时）

T=2: 超过 3 分钟无消息
    → 服务器触发 TIMEOUT 状态转移
    → Alice 从房间移除
    → 广播 user_left (seq=51)

T=3: Alice 恢复网络，自动重连

T=4: Alice 重新 JOIN
    → 客户端发送 STATE_SYNC (last_received_sequence: 50)
    → 服务器返回 ack 包含 seq=51 之后的事件

T=5: Alice 接收完整房间状态
    → 重放事件 seq=51～当前
    → Canvas 恢复到最新状态
```

---

## 6. 架构模块分解

```
┌─────────────────────────────────────────────────────────────┐
│                    Server Architecture                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  HTTP/WebSocket Layer (FastAPI)                            │
│    └─ /ws/{connection_id}                                  │
│                                                             │
│  Message Router (验证 + 路由)                              │
│    ├─ Schema 验证                                          │
│    ├─ 去重检查 (msg_id window)                             │
│    └─ 消息类型路由                                        │
│                                                             │
│  Handler Layer (业务逻辑)                                 │
│    ├─ JoinHandler                                          │
│    ├─ LeaveHandler                                         │
│    ├─ DrawHandler                                          │
│    ├─ ClearHandler                                         │
│    └─ StateSyncHandler                                     │
│                                                             │
│  Manager Layer (状态管理)                                 │
│    ├─ StateManager (用户 + 房间状态)                       │
│    ├─ ConnectionManager (WebSocket 连接)                   │
│    └─ RoomManager (房间生命周期)                           │
│                                                             │
│  Storage Layer (数据存储)                                 │
│    ├─ Memory (Room + Canvas 历史)                          │
│    ├─ Dedup Cache (msg_id → response)                     │
│    └─ TTL Scheduler (IDLE 房间清理)                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. 可靠性和容错机制

### 7.1 消息可靠性

```
机制: 请求-响应 (Request-Response) 模式

所有客户端消息必须收到响应:
  ✓ 成功 → ACK
  ✓ 失败 → ERROR

客户端超时未收到响应:
  → 重试 (指数退避)
  → 最多重试 3 次
  → 重试间隔: 1s, 2s, 4s
  → 最后仍失败: 主动断开并重连
```

### 7.2 状态一致性

```
机制: 事件重放 (Event Replay)

客户端维护:
  - 最后接收的 sequence_id
  - 消息优先队列 (按 sequence_id 排序)

异序消息到达时:
  1. 放入优先队列
  2. 等待缺失的消息
  3. 当有序时，从队列取出并应用
  4. 更新最后接收的 sequence_id

重连时:
  1. 发送 STATE_SYNC + last_received_sequence
  2. 服务器返回该 sequence 之后的所有事件
  3. 客户端重放这些事件，回到最新状态
```

### 7.3 故障隔离

```
单个用户连接失败:
  → 标记为 TIMEOUT
  → 从房间移除
  → 广播 user_left
  → 不影响其他用户

服务器消息处理异常:
  → 捕获异常
  → 发送 ERROR (INTERNAL_ERROR) 给客户端
  → 继续处理其他连接

TTL 过期但用户仍在:
  → 不会销毁 (参考计数>0)
  → 继续正常工作
```

---

## 8. 安全性和验证

### 8.1 输入验证

```
1. JSON 格式验证
   → 使用 Pydantic + JSON Schema

2. 字段类型验证
   → user_id: string, 1-100 chars
   → room_id: string, 1-100 chars
   → msg_id: UUID v4 format
   → color: #RRGGBB format
   → width: 0.5-50 float
   → pressure: 0-1 float

3. 消息大小验证
   → 单个消息 ≤ 1 MB
   → draw.points 数组 ≤ 1000 个点

4. 业务规则验证
   → 用户是否在房间中
   → 房间是否存在
   → 状态转移是否合法
```

### 8.2 速率限制

```
1. 每用户速率限制
   → 100 消息/秒
   → 超过 → ERROR (RATE_LIMIT)
   → 客户端等待后重试

2. 每房间速率限制
   → 1000 事件/秒
   → 防止单个房间过载

3. 实现方式
   → 令牌桶算法 (Token Bucket)
   → O(1) 时间复杂度
```

---

## 9. 性能考虑

### 9.1 时间复杂度

| 操作 | 复杂度 | 说明 |
|------|-------|------|
| 消息路由 | O(1) | 直接字典查询 |
| 广播 | O(n) | n = 房间用户数 |
| 去重检查 | O(1) | 哈希表查询 |
| 状态转移 | O(1) | 字典查询 + Lock |
| Canvas 历史查询 | O(1) | 直接数组访问 |

### 9.2 空间复杂度

```
单个房间开销:
  - 房间元数据: ~1 KB
  - 用户列表: 100 bytes/user
  - Canvas 历史: ~100 bytes/event (平均)
  
示例: 10 用户, 10000 事件
  → 1 KB + 1 KB + 1 MB = ~1 MB 内存

100 个这样的房间:
  → 100 MB 内存

可扩展性: 使用 Redis + 分库分表可扩展到 10000+ 并发房间
```

---

## 10. 测试策略

### 10.1 单元测试 (最高优先级)

```python
# 状态机转移测试
test_user_state_valid_transition()
test_user_state_invalid_transition()
test_room_state_valid_transition()

# 消息处理测试
test_join_handler_creates_room()
test_leave_handler_triggers_cleanup()
test_draw_handler_assigns_sequence()

# 工具函数测试
test_dedup_cache()
test_message_validation()
```

### 10.2 集成测试 (中等优先级)

```python
# 完整流程测试
test_single_user_join_draw_leave()
test_two_users_collaborative_drawing()
test_user_reconnection_after_network_failure()
test_room_cleanup_after_all_users_leave()
test_concurrent_users_in_multiple_rooms()

# 压力测试
test_high_frequency_draw_commands()
test_100_concurrent_users()
test_message_reordering_under_network_jitter()
```

### 10.3 端到端测试 (低优先级)

```javascript
// 前端 + 后端集成
test_canvas_update_matches_server_broadcast()
test_multi_user_canvas_consistency()
test_error_message_display()
```

---

## 11. 部署考虑

### 11.1 本地开发

```
环境: Python 3.8+, FastAPI, websockets
运行: python main.py
访问: http://localhost:8000
```

### 11.2 生产部署

```
容器化: Docker
Web 服务器: Uvicorn (4 workers)
进程管理: systemd 或 Supervisor
负载均衡: Nginx (如果多实例)
缓存: Redis (如果需要分布式)
持久化: PostgreSQL (如果需要)?
监控: Prometheus + Grafana
日志: ELK Stack (可选)
```

---

## 12. 文档完成状态

✅ **已完成**:
- 01_PROTOCOL_SPECIFICATION.md
- 02_STATE_MACHINE_DESIGN.md
- 03_ARCHITECTURE_DESIGN.md
- 04_IMPLEMENTATION_PLAN.md
- 00_RESEARCH_PLAN_SUMMARY.md (本文件)

⏳ **待实现**:
- 05_API_REFERENCE.md
- 06_EXAMPLES.md
- 07_DEPLOYMENT.md
- 08_TROUBLESHOOTING.md
- README.md
- 源代码 + 注释
- 测试用例

---

## 13. 关键里程碑

| 里程碑 | 目标完成日期 | 状态 |
|--------|-----------|------|
| 设计阶段完成 | 2026-04-14 | ✅ 完成 |
| Phase 1: 核心基础设施 | TBD | ⏳ 待开始 |
| Phase 2: 业务逻辑 | TBD | ⏳ 待开始 |
| Phase 3: 前端实现 | TBD | ⏳ 待开始 |
| Phase 4: 测试和优化 | TBD | ⏳ 待开始 |
| Phase 5: 文档和部署 | TBD | ⏳ 待开始 |
| **项目交付** | TBD | ⏳ 待开始 |

---

## 14. 关键参考资源

### 协议相关
- RFC 6455 - WebSocket Protocol
- JSON Schema Specification

### 架构相关
- Event-Driven Architecture
- State Machine Design Patterns

### 技术栈
- FastAPI 官方文档
- Pydantic 验证
- asyncio 异步编程
- Python threading (同步原语)

---

## 总结

本研究计划为 CollabBoard 系统提供了**完整的设计蓝图**，包括：

1. **严格的协议规范** - 所有消息遵循统一 JSON 格式
2. **显式的状态机** - 用户和房间状态的完整建模
3. **模块化架构** - 清晰的职责分离和依赖关系
4. **一致性保证** - 全局序列号 + 事件重放
5. **自动清理策略** - 参考计数 + TTL 定时器
6. **完整的错误处理** - 异常捕获、去重、重试机制
7. **安全性验证** - JSON Schema、速率限制、消息大小限制

系统设计符合**研究级别的严谨性**和**生产级别的可靠性**。

---

**下一步**: 开始实现阶段（Phase 1: 后端基础设施）

