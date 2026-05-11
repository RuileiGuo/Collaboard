# CollabBoard - 状态机设计 (State Machine Design)

**文档版本**: 1.0  
**日期**: 2026-04-14

---

## 1. 用户状态机 (User State Machine)

### 1.1 状态定义

```
┌─────────────────────────────────────────────────────────────┐
│                     USER STATE MACHINE                      │
└─────────────────────────────────────────────────────────────┘

                         [INIT]
                           ↓
                           │ WebSocket 连接建立
                           ↓
                      [CONNECTED]
                           ↓
                           │ JOIN 消息
                           ↓
                        [JOINED]
                           ↓
                           │ 正常工作 (DRAW/CLEAR/STATE_SYNC)
                           ↓
                        [ACTIVE]
                    ⟲ 循环: 发送消息 ⟲
                           │
                           │ LEAVE 或 disconnect
                           ↓
                         [LEFT]
                           ↓
                      [DISCONNECTED]
```

### 1.2 状态详细描述

| 状态 | 描述 | 允许操作 | 超时触发 |
|------|------|---------|--------|
| **INIT** | 客户端初始化，未连接 | 无 | N/A |
| **CONNECTED** | WebSocket 已建立，等待 JOIN | JOIN 或主动断开 | 30秒后 → DISCONNECTED |
| **JOINED** | 已加入房间，等待其他操作 | DRAW/CLEAR/LEAVE/STATE_SYNC | 60秒无消息 → IDLE（见下） |
| **ACTIVE** | 正常活跃，可执行所有操作 | DRAW/CLEAR/LEAVE/STATE_SYNC | 3分钟无消息 → IDLE |
| **LEFT** | 用户明确发送 LEAVE 消息 | 无（等待 DISCONNECTED） | 5秒后 → DISCONNECTED |
| **IDLE** | 用户超时无活动，但仍连接 | 可恢复（发送任意消息） | 3分钟后 → TIMEOUT |
| **TIMEOUT** | 用户超时，即将断开 | 无 | 立即 → DISCONNECTED |
| **DISCONNECTED** | 断开连接，从房间移除 | 对服务器而言无操作 | N/A |

### 1.3 状态转移规则 (Transition Rules)

#### 从 INIT

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| WebSocket 连接成功 | CONNECTED | 标记连接建立时间 |
| 连接失败 | DISCONNECTED | 日志记录 |

#### 从 CONNECTED

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 收到有效 JOIN 消息 | JOINED | 将用户添加到房间 |
| 主动断开连接 | DISCONNECTED | 记录断开原因 |
| 30 秒内未收到 JOIN | DISCONNECTED | 超时断开（发送 ERROR） |

#### 从 JOINED

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 发送 DRAW/CLEAR 消息 | ACTIVE | 开始活跃计时 |
| 发送 LEAVE 消息 | LEFT | 触发房间清理检查 |
| 60 秒无消息 | IDLE | 记录进入闲置时间 |
| 网络断开 | TIMEOUT | 自动断开 |

#### 从 ACTIVE

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 发送 DRAW/CLEAR 消息 | ACTIVE | 重置活跃计时 |
| 发送 LEAVE 消息 | LEFT | 触发房间清理检查 |
| 3 分钟无消息 | IDLE | 记录进入闲置时间 |
| 网络断开 | TIMEOUT | 自动断开 |

#### 从 LEFT

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 5 秒 WebSocket 保活检测完成 | DISCONNECTED | 关闭连接 |
| 主动断开 | DISCONNECTED | 立即断开 |

#### 从 IDLE

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 收到任意消息 | ACTIVE | 恢复活跃计时 |
| 3 分钟超时 | TIMEOUT | 服务器主动踢出 |

#### 从 TIMEOUT

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 立即 | DISCONNECTED | 发送 ERROR (reason: timeout) |

#### 从 DISCONNECTED

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 无转移 | 最终状态 | 从房间删除，清理内存 |

---

## 2. 房间状态机 (Room State Machine)

### 2.1 状态定义

```
┌─────────────────────────────────────────────────────────────┐
│                     ROOM STATE MACHINE                      │
└─────────────────────────────────────────────────────────────┘

                      [PENDING_INIT]
                            ↓
                            │ 首个用户加入
                            ↓
                         [ACTIVE]
                    ⟲ 循环: 用户活动 ⟲
                            │
                            │ 最后一个用户离开
                            ↓
                          [IDLE]
                       (开始 TTL 计时)
                            │
                    ┌───────┴───────┐
                    │               │
              (用户重新加入)    (TTL 过期)
                    │               │
                    ↓               ↓
                 [ACTIVE]        [DESTROYED]
                            (最终状态)
```

### 2.2 状态详细描述

| 状态 | 描述 | 用户数 | 允许操作 | 超时触发 |
|------|------|--------|---------|--------|
| **PENDING_INIT** | 房间已创建但无用户 | 0 | 接受 JOIN | 300秒 → DESTROYED |
| **ACTIVE** | 有活跃用户 | ≥ 1 | DRAW/CLEAR/LEAVE/JOIN | N/A |
| **IDLE** | 所有用户已离开 | 0 | 接受 JOIN（恢复为 ACTIVE） | 60秒 → DESTROYED |
| **DESTROYED** | 房间销毁 | 0 | 无操作 | N/A（最终状态） |

### 2.3 状态转移规则 (Transition Rules)

#### 从 PENDING_INIT

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 首个用户发送 JOIN | ACTIVE | 初始化房间数据结构 |
| 300 秒无用户加入 | DESTROYED | 销毁房间 |

#### 从 ACTIVE

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 用户发送 DRAW/CLEAR | ACTIVE | 记录事件，广播，赋予 sequence_id |
| 用户发送 LEAVE，但仍有其他用户 | ACTIVE | 将用户从房间移除，广播 user_left |
| 最后一个用户发送 LEAVE | IDLE | 将用户从房间移除，广播 room_idle，启动 TTL |
| 新用户 JOIN | ACTIVE | 添加用户到房间，返回 canvas_history |

#### 从 IDLE

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 用户发送 JOIN | ACTIVE | 停止 TTL 计时，恢复房间为活跃 |
| 60 秒 TTL 过期 | DESTROYED | 销毁房间，清理内存 |

#### 从 DESTROYED

| 条件 | 目标状态 | 操作 |
|------|---------|------|
| 无转移 | 最终状态 | 房间从全局注册表删除 |

---

## 3. 消息处理状态转移

### 3.1 完整的消息路由状态机

```
收到消息
    ↓
  JSON 格式验证
    ↓ (Success)
  字段完整性检查
    ↓ (Success)
  消息类型路由：
    ├─ JOIN
    │     ↓
    │   验证 user_id 和 room_id
    │     ↓
    │   用户状态: CONNECTED → JOINED
    │   房间状态: PENDING_INIT → ACTIVE
    │     ↓
    │   返回 ACK (with canvas_history)
    │     ↓
    │   广播 user_joined
    │
    ├─ LEAVE
    │     ↓
    │   验证用户在房间
    │   用户状态: ACTIVE/JOINED → LEFT
    │     ↓
    │   从房间移除用户
    │   房间用户计数 -1
    │     ↓
    │   if 房间用户计数 == 0:
    │     房间状态: ACTIVE → IDLE
    │     启动 TTL 计时器
    │   else:
    │     房间保持 ACTIVE
    │     ↓
    │   返回 ACK
    │     ↓
    │   广播 user_left (and room_idle if applicable)
    │
    ├─ DRAW
    │     ↓
    │   验证用户在房间
    │   验证 payload (color, width, points 等)
    │     ↓
    │   用户状态: JOINED/ACTIVE → ACTIVE
    │   赋予 sequence_id += 1
    │     ↓
    │   返回 ACK (with sequence_id)
    │     ↓
    │   广播给所有用户
    │
    ├─ CLEAR
    │     ↓
    │   验证用户在房间
    │     ↓
    │   用户状态: ACTIVE 保持
    │   赋予 sequence_id += 1
    │     ↓
    │   返回 ACK
    │     ↓
    │   广播给所有用户
    │     ↓
    │   清空 canvas_history
    │
    ├─ STATE_SYNC
    │     ↓
    │   验证用户在房间
    │     ↓
    │   计算需要同步的事件
    │   events = canvas_events[last_received_sequence+1:]
    │     ↓
    │   返回 ACK (with full_state)
    │     ↓
    │   (不广播)
    │
    └─ 未知消息类型
          ↓
        返回 ERROR (INVALID_MESSAGE)

(Success) / (Error)
    ↓
  日志记录
    ↓
  连接保持 (除非 ERROR 要求断开)
```

---

## 4. 清理策略 (Cleanup Policy)

### 4.1 参考计数模型

```
┌────────────────────────────────────────────┐
│     ROOM REFERENCE COUNT MODEL             │
└────────────────────────────────────────────┘

每个房间维护一个计数器: ref_count

规则:
1. 房间创建: ref_count = 0
2. 用户加入: ref_count += 1
3. 用户离开: ref_count -= 1
4. 检查: if ref_count == 0:
         房间状态 = IDLE
         启动 TTL 计时

定时检查 (每 10 秒):
  for room in IDLE_rooms:
    if current_time - idle_start_time > 60:
      删除房间
      状态 = DESTROYED
```

### 4.2 TTL 定时器实现

```python
class RoomCleanupPolicy:
    def __init__(self, ttl_seconds=60):
        self.ttl_seconds = ttl_seconds
        self.idle_rooms_timers = {}  # {room_id: (idle_start_time, timer_handle)}
    
    def mark_room_idle(self, room_id):
        """房间变为 IDLE 时调用"""
        idle_start_time = time.time()
        
        # 取消任何现有计时器
        if room_id in self.idle_rooms_timers:
            self.idle_rooms_timers[room_id][1].cancel()
        
        # 启动新计时器
        timer = threading.Timer(
            self.ttl_seconds,
            self.destroy_room,
            args=[room_id]
        )
        timer.start()
        
        self.idle_rooms_timers[room_id] = (idle_start_time, timer)
    
    def cancel_idle_timer(self, room_id):
        """用户重新加入时取消计时器"""
        if room_id in self.idle_rooms_timers:
            self.idle_rooms_timers[room_id][1].cancel()
            del self.idle_rooms_timers[room_id]
    
    def destroy_room(self, room_id):
        """销毁房间"""
        if room_id in self.idle_rooms_timers:
            del self.idle_rooms_timers[room_id]
        # 持久化或清理代码...
```

---

## 5. 无效状态转移处理

### 5.1 检查表

| 当前状态 | 操作 | 结果 |
|---------|------|------|
| CONNECTED | DRAW | ✗ UNAUTHORIZED |
| JOINED | DRAW | ✓ 转移到 ACTIVE，执行 |
| ACTIVE | DRAW | ✓ 保持 ACTIVE，执行 |
| LEFT | DRAW | ✗ UNAUTHORIZED |
| DISCONNECTED | JOIN | ✗ UNAUTHORIZED |

### 5.2 错误处理代码示例

```python
def validate_state_transition(current_state, message_type, room):
    """验证状态转移合法性"""
    
    valid_transitions = {
        'CONNECTED': ['join'],
        'JOINED': ['draw', 'clear', 'leave', 'state_sync'],
        'ACTIVE': ['draw', 'clear', 'leave', 'state_sync'],
        'LEFT': [],
        'TIMEOUT': [],
        'DISCONNECTED': []
    }
    
    if message_type not in valid_transitions[current_state]:
        raise InvalidStateTransition(
            f"Cannot perform {message_type} in state {current_state}"
        )
    
    # 额外的房间状态检查
    if room.state == 'DESTROYED':
        raise RoomDestroyedException(room.room_id)
```

---

## 6. 连接管理状态机

### 6.1 WebSocket 连接生命周期

```
客户端                                    服务器
   ├─ 发起连接 ──────────────────────────→ 接受连接
   │                                      状态: CONNECTED
   ├─ 发送 JOIN ──────────────────────────→ 处理 JOIN
   │                                      更新用户状态
   │                                      更新房间状态
   ← ─ ─ ─ ─ ─ ─ ─ ─ ACK + 历史 ─ ─ ─ ─ ←
   │
   ├─ 发送 DRAW ──────────────────────────→ 处理 DRAW
   │                                      赋予 sequence_id
   │                                      广播
   ← ─ ─ ─ ─ ─ ─ ─ ─ ACK ─ ─ ─ ─ ─ ─ ─ ←
   ├─ 接收广播 ←  ─ ─ ─ ─ BROADCAST ─ ─ ←
   │
   ├─ [Idle for 3 分钟]
   │
   ├─ [连接超时或显式 LEAVE]
   │
   ├─ 发送 LEAVE ──────────────────────────→ 处理 LEAVE
   │                                      更新房间状态
   │                                      触发清理
   ← ─ ─ ─ ─ ─ ─ ─ ─ ACK ─ ─ ─ ─ ─ ─ ─ ←
   │
   ├─ 断开连接 ─────────────────────────────→ 关闭连接
   │                                      状态: DISCONNECTED
```

---

## 7. 并发和同步

### 7.1 状态转移的原子性

由于多个消息可能同时到达，所有状态转移必须是原子的：

```python
import threading

class UserStateManager:
    def __init__(self):
        self.state_lock = threading.RLock()
        self.state = UserState.INIT
    
    def transition(self, event):
        """原子状态转移"""
        with self.state_lock:
            new_state = self._calculate_new_state(event)
            self._validate_transition(self.state, new_state)
            self.state = new_state
            return new_state
```

### 7.2 房间事件顺序

所有房间事件必须通过单线程消息队列处理：

```python
class RoomEventQueue:
    def __init__(self):
        self.queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_events)
    
    def enqueue(self, event):
        """接收事件（非阻塞）"""
        self.queue.put(event)
    
    def _process_events(self):
        """按顺序处理事件（阻塞）"""
        while True:
            event = self.queue.get()
            self._handle_event(event)
            self.queue.task_done()
```

---

## 8. 状态机设计总结

| 组件 | 状态数 | 关键特性 |
|------|-------|---------|
| 用户 (User) | 8 | 超时、恢复、断开 |
| 房间 (Room) | 4 | 参考计数、TTL 清理 |
| 消息处理 | 多条分支 | 路由、验证、广播 |
| 连接 (WebSocket) | 集成于用户状态 | 心跳、自适应 |

---

**下一步**: 转到 `03_ARCHITECTURE_DESIGN.md` 进行架构设计
