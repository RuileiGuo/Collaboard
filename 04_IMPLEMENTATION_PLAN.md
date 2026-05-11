# CollabBoard - 实现计划 (Implementation Plan)

**文档版本**: 1.0  
**日期**: 2026-04-14

---

## 1. 实现分阶段规划

### Phase 1: 核心基础设施 (Week 1)

#### 1.1 后端基础
- [ ] FastAPI 应用框架初始化
- [ ] WebSocket 端点设置
- [ ] JSON Schema 定义和验证
- [ ] 基础数据模型（User, Room, Message）
- [ ] 日志系统配置

#### 1.2 核心管理器
- [ ] ConnectionManager 实现
- [ ] RoomManager 实现（基础版本）
- [ ] StateManager 实现
- [ ] 线程安全机制（Lock）

#### 1.3 消息处理框架
- [ ] MessageRouter 实现
- [ ] 去重机制（msg_id缓存）
- [ ] 错误处理框架

**交付物**: 
- 可以建立 WebSocket 连接
- 可以接收和验证消息
- 可以路由消息到处理器

---

### Phase 2: 业务逻辑实现 (Week 2)

#### 2.1 消息处理器
- [ ] JoinHandler 实现（JOIN 消息）
- [ ] LeaveHandler 实现（LEAVE 消息）
- [ ] DrawHandler 实现（DRAW 消息）
- [ ] ClearHandler 实现（CLEAR 消息）
- [ ] StateSyncHandler 实现（STATE_SYNC 消息）

#### 2.2 房间状态管理
- [ ] 房间状态机转移逻辑
- [ ] Canvas 历史记录管理
- [ ] 清理策略实现（参考计数 + TTL）
- [ ] 事件排序和去重

#### 2.3 用户会话管理
- [ ] 用户状态机实现
- [ ] 超时检测
- [ ] 连接恢复支持

**交付物**:
- 完整的服务器端消息处理
- 房间的创建、更新、销毁
- 状态机的严格实现

---

### Phase 3: 前端实现 (Week 2-3)

#### 3.1 基础连接
- [ ] WebSocket 连接管理
- [ ] 消息序列化/反序列化
- [ ] ACK 匹配和超时处理
- [ ] 错误处理和重连

#### 3.2 Canvas 渲染
- [ ] Canvas 基础绘制
- [ ] 笔迹重放（按 sequence_id 排序）
- [ ] 清屏操作
- [ ] 多用户笔迹渲染

#### 3.3 用户交互
- [ ] 房间加入/离开 UI
- [ ] 绘图工具选择（pen, eraser, 等）
- [ ] 颜色/宽度调整
- [ ] 在线用户列表显示

**交付物**:
- 完整的前端界面
- 实时绘画功能
- 多用户同步显示

---

### Phase 4: 集成和测试 (Week 3-4)

#### 4.1 单元测试
- [ ] 后端单元测试
- [ ] 消息处理器测试
- [ ] 状态机转移测试
- [ ] 前端单元测试

#### 4.2 集成测试
- [ ] 本地集成测试（1+1 用户）
- [ ] 并发测试（多用户）
- [ ] 网络中断恢复测试
- [ ] 极限压力测试

#### 4.3 端到端测试
- [ ] 完整的协作流程
- [ ] 清理策略验证
- [ ] 错误场景处理

**交付物**:
- 完整的测试套件
- 集成测试报告

---

### Phase 5: 文档和部署 (Week 4)

#### 5.1 文档完善
- [ ] API 参考文档
- [ ] 例子代码
- [ ] 教程
- [ ] 部署指南

#### 5.2 部署准备
- [ ] Docker 镜像
- [ ] 生产配置
- [ ] 性能调优

**交付物**:
- 完整的项目文档
- 生产级部署脚本

---

## 2. 技术栈细节

### 后端技术栈

| 组件 | 选择 | 原因 |
|------|------|------|
| Web 框架 | FastAPI | 异步，高性能，WebSocket 支持好 |
| WebSocket | `websockets` 库 | 纯 Python，符合 ASGI 标准 |
| 数据验证 | `pydantic` | JSON Schema 集成，性能好 |
| 异步运行时 | `asyncio` | Python 标准库 |
| 日志 | `logging` | Python 标准库 |
| 测试 | `pytest` + `pytest-asyncio` | 异步测试支持 |

### 前端技术栈

| 组件 | 选择 | 原因 |
|------|------|------|
| Canvas API | HTML5 原生 | 高效绘制 |
| WebSocket | 原生 JS WebSocket API | 标准支持，无依赖 |
| UI 框架 | 原生 HTML/CSS/JS | 轻量级，无依赖 |

---

## 3. 核心实现概要

### 3.1 消息处理流程

```python
# 伪代码

async def websocket_endpoint(websocket: WebSocket, connection_id: str):
    """WebSocket 连接处理"""
    connection_mgr.add_connection(connection_id, websocket)
    
    try:
        while True:
            # 1. 接收消息
            raw_data = await websocket.receive_text()
            raw_message = json.loads(raw_data)
            
            # 2. 消息验证和路由
            try:
                await message_handler.handle_message(connection_id, raw_message)
            except ValidateError as e:
                error_msg = build_error_message(raw_message, 'INVALID_MESSAGE')
                await websocket.send_json(error_msg)
            except Exception as e:
                logger.error(f"Error: {e}")
                error_msg = build_error_message(raw_message, 'INTERNAL_ERROR')
                await websocket.send_json(error_msg)
    
    except WebSocketDisconnect:
        # 3. 连接断开处理
        connection_mgr.remove_connection(connection_id)
        # 触发用户 TIMEOUT 逻辑
        notify_room_user_disconnected(connection_id)
    
    finally:
        try:
            await websocket.close()
        except:
            pass
```

### 3.2 状态机转移代码示例

```python
# JOIN 处理器中的状态转移

class JoinHandler:
    def handle(self, connection_id: str, msg: dict):
        user_id = msg['user_id']
        room_id = msg['room_id']
        
        # 1. 用户状态转移: CONNECTED → JOINED
        state_mgr.transition_user_state(
            user_id,
            current_state=UserState.CONNECTED,
            target_state=UserState.JOINED,
            event='join'
        )
        
        # 2. 房间状态转移
        room = room_mgr.get_or_create_room(room_id)
        
        if room.state == RoomState.PENDING_INIT:
            # PENDING_INIT → ACTIVE
            room.state = RoomState.ACTIVE
        elif room.state == RoomState.IDLE:
            # IDLE → ACTIVE（用户重新加入）
            room.state = RoomState.ACTIVE
            room.cancel_idle_timer()
        
        # 3. 添加到房间
        room_mgr.add_user_to_room(room_id, user_id)
        
        # 4. 发送 ACK 和广播
        # ...
```

### 3.3 清理策略实现

```python
# TTL 定时器实现

class RoomCleanupManager:
    def __init__(self):
        self.idle_timers = {}
    
    def mark_room_idle(self, room_id: str, ttl_seconds: int = 60):
        """房间变为 IDLE 时调用"""
        
        # 取消现有计时器
        if room_id in self.idle_timers:
            self.idle_timers[room_id].cancel()
        
        # 启动新计时器
        def cleanup_callback():
            room_mgr.destroy_room(room_id)
            del self.idle_timers[room_id]
        
        import threading
        timer = threading.Timer(ttl_seconds, cleanup_callback)
        timer.daemon = True
        timer.start()
        
        self.idle_timers[room_id] = timer
    
    def cancel_idle_timer(self, room_id: str):
        """用户重新加入时取消计时器"""
        if room_id in self.idle_timers:
            self.idle_timers[room_id].cancel()
            del self.idle_timers[room_id]
```

### 3.4 前端消息处理

```javascript
// JS 伪代码

class ClientMessageHandler {
    constructor(canvas, connection) {
        this.canvas = canvas;
        this.connection = connection;
        this.messageQueue = []; // 异序消息队列
        this.lastSequence = -1;
    }
    
    handleBroadcast(msg) {
        // 1. 按 sequence_id 排序
        this.messageQueue.push(msg);
        this.messageQueue.sort((a, b) => a.sequence_id - b.sequence_id);
        
        // 2. 处理已排序的消息
        this.processOrderedMessages();
    }
    
    processOrderedMessages() {
        while (this.messageQueue.length > 0) {
            const msg = this.messageQueue[0];
            
            // 检查是否是下一个序列号
            if (msg.sequence_id === this.lastSequence + 1) {
                this.messageQueue.shift();
                this.applyEvent(msg);
                this.lastSequence = msg.sequence_id;
            } else {
                break; // 等待缺失的消息
            }
        }
    }
    
    applyEvent(msg) {
        const eventType = msg.payload.event_type;
        
        switch (eventType) {
            case 'draw':
                this.canvas.drawStroke(msg.payload);
                break;
            case 'clear':
                this.canvas.clear();
                break;
            case 'user_joined':
                this.updateUserList();
                break;
            case 'user_left':
                this.updateUserList();
                break;
        }
    }
}
```

---

## 4. 关键实现检查清单

### 4.1 协议遵循检查

- [ ] 所有消息都有 `msg_id` UUID
- [ ] 每个消息都有 `type` 字段
- [ ] 消息包含 `user_id`, `room_id`, `timestamp`
- [ ] 基础消息包含 `payload` 字段
- [ ] 服务器赋予 `sequence_id`（对于广播和 ACK）
- [ ] 错误消息格式正确（error_code + message）

### 4.2 状态机检查

- [ ] 用户状态转移验证
- [ ] 房间状态转移验证
- [ ] 无效转移被拒绝
- [ ] 所有可能的边界情况都被处理

### 4.3 一致性检查

- [ ] 服务器维护单调递增的 sequence_id
- [ ] 所有广播都包含 sequence_id
- [ ] 客户端按 sequence_id 重放事件
- [ ] 异序消息被缓存和排序

### 4.4 清理策略检查

- [ ] 参考计数正确（+1 JOIN, -1 LEAVE）
- [ ] 房间变为 IDLE 时启动 TTL
- [ ] TTL 过期时销毁房间
- [ ] 用户重新加入时取消 TTL

### 4.5 安全性检查

- [ ] JSON Schema 验证所有输入
- [ ] 消息大小限制（≤ 1 MB）
- [ ] 速率限制实现（100 msgs/sec per user）
- [ ] 马指可信性检查（user_id 和 room_id）

---

## 5. 开发顺序建议

### 建议开发顺序

1. **定义数据模型** (`models.py`)
   - User, Room, Message, Event 等
   - 枚举: UserState, RoomState, MessageType

2. **实现 JSON Schema** (`schemas.py`)
   - 基础消息 Schema
   - 各类型消息 Payload Schema
   - 创建验证函数

3. **实现核心管理器** (按顺序)
   - StateManager (最基础)
   - ConnectionManager
   - RoomManager

4. **实现消息处理框架**
   - MessageRouter
   - 去重缓存
   - 错误处理

5. **实现消息处理器** (按顺序)
   - JoinHandler
   - LeaveHandler
   - DrawHandler
   - ClearHandler
   - StateSyncHandler

6. **实现 FastAPI 端点**
   - WebSocket 连接点
   - 消息接收循环
   - 错误处理

7. **实现前端**
   - WebSocket 连接
   - 消息发送
   - Canvas 绘制
   - 消息接收和处理

8. **测试和优化**
   - 单元测试
   - 集成测试
   - 性能调优

---

## 6. 依赖关系图

```
models.py (数据模型)
    ↓
schemas.py (JSON Schema)
    ↓
    ├─→ state_manager.py (状态管理)
    │       ↓
    ├─→ connection_manager.py (连接管理)
    │       ↓
    ├─→ room_manager.py (房间管理)
    │       ↓
message_handler.py (消息路由)
    ├─→ join_handler.py
    ├─→ leave_handler.py
    ├─→ draw_handler.py
    ├─→ clear_handler.py
    └─→ state_sync_handler.py
    ↓
main.py (FastAPI 应用)
    ↓
前端 (HTML/JS)
```

---

## 7. 测试策略

### 7.1 单元测试

```python
# test_state_machine.py
def test_user_state_transition_valid():
    """测试合法的用户状态转移"""
    state_mgr = StateManager()
    result = state_mgr.transition_user_state(
        'user1',
        UserState.CONNECTED,
        UserState.JOINED,
        'join'
    )
    assert result == True
    assert state_mgr.get_user_state('user1') == UserState.JOINED

def test_user_state_transition_invalid():
    """测试非法的用户状态转移"""
    state_mgr = StateManager()
    state_mgr.transition_user_state('user1', UserState.INIT, UserState.CONNECTED, '')
    
    result = state_mgr.transition_user_state(
        'user1',
        UserState.CONNECTED,
        UserState.ACTIVE,  # 非法，应该先 JOIN
        'draw'
    )
    assert result == False
```

### 7.2 集成测试

```python
# test_integration.py
@pytest.mark.asyncio
async def test_two_users_drawing():
    """测试两个用户协作绘画"""
    # 1. Alice 加入房间
    alice_msg = build_join_msg('alice', 'room1')
    # 2. Bob 加入房间
    bob_msg = build_join_msg('bob', 'room1')
    # 3. Alice 绘制
    draw_msg = build_draw_msg('alice', 'room1', ...)
    # 4. 验证 Bob 收到广播
    # 5. Alice 离开
    # 6. 验证房间状态转移到 IDLE
    # 7. 验证 TTL 启动
```

---

## 8. 性能目标

| 指标 | 目标 | 备注 |
|------|------|------|
| 消息延迟 | < 100 ms | 从客户端发送到其他客户端接收 |
| 吞吐量 | 1000 msgs/sec per room | 对于 10 个用户高频绘制 |
| 并发连接数 | 支持 100+ 并发 | 本地开发环境 |
| 内存占用 | < 100 MB | 对于 10 个活跃房间 |
| CPU 使用率 | < 50% | 单核处理 1000 msgs/sec |

---

## 9. 故障处理场景

| 场景 | 处理策略 |
|------|---------|
| 客户端连接中断 | 服务器标记用户为 TIMEOUT，触发清理 |
| 服务器消息处理异常 | 发送 ERROR (INTERNAL_ERROR) 给客户端 |
| 消息格式错误 | 发送 ERROR (INVALID_MESSAGE)，不处理 |
| 房间不存在 | 发送 ERROR (ROOM_NOT_FOUND) |
| 用户重复 JOIN | 发送 ERROR (USER_ALREADY_JOINED) |
| 速率超限 | 发送 ERROR (RATE_LIMIT)，等待重试 |
| 消息乱序到达 | 客户端缓冲并按 sequence_id 排序 |
| 客户端重连 | 发送 STATE_SYNC 获取完整房间状态 |

---

## 10. 文档输出清单

项目完成时应包含:

- [ ] 01_PROTOCOL_SPECIFICATION.md (✓ 已完成)
- [ ] 02_STATE_MACHINE_DESIGN.md (✓ 已完成)
- [ ] 03_ARCHITECTURE_DESIGN.md (✓ 已完成)
- [ ] 04_IMPLEMENTATION_PLAN.md (本文件, ✓ 已完成)
- [ ] 05_API_REFERENCE.md (待实现)
- [ ] 06_EXAMPLES.md (待实现)
- [ ] 07_DEPLOYMENT.md (待实现)
- [ ] README.md (待实现)
- [ ] 源代码注释 (待实现)
- [ ] 单元测试代码 (待实现)
- [ ] 集成测试代码 (待实现)

---

**下一步**: 开始 Phase 1 实现 - 后端基础设施

