# CollabBoard - 架构设计 (Architecture Design)

**文档版本**: 1.0  
**日期**: 2026-04-14

---

## 1. 系统架构总体视图

```
┌─────────────────────────────────────────────────────────────────┐
│                      CLIENT LAYER (Browser)                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Canvas Renderer                                         │   │
│  │    - 绘制笔迹                                             │   │
│  │    - 重放事件                                             │   │
│  │    - 显示用户列表                                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Message Handler                                         │   │
│  │    - 构建消息                                             │   │
│  │    - 发送 WebSocket 消息                                  │   │
│  │    - 处理 ACK/ERROR                                       │   │
│  │    - 缓冲消息                                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Connection Manager (Client)                            │   │
│  │    - WebSocket 连接/断开                                  │   │
│  │    - 心跳检测                                             │   │
│  │    - 自动重连                                             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────────┘
                  │
              WebSocket
              (JSON Messages)
                  │
┌─────────────────┴───────────────────────────────────────────────┐
│                      SERVER LAYER (FastAPI)                    │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Connection Handler (per client)                         │  │
│  │    - 接收 WebSocket 消息                                  │  │
│  │    - 路由消息到 MessageHandler                            │  │
│  │    - 向客户端发送 ACK/BROADCAST                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Message Router                                          │  │
│  │    - 验证消息格式                                         │  │
│  │    - 路由到对应处理器                                     │  │
│  │    - 去重 (msg_id + dedup_window)                         │  │
│  └───────────────────────────────────────────────────────────┘  │
│     │         │         │        │        │                    │
│     ↓         ↓         ↓        ↓        ↓                    │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌────────┐ ┌──────────┐           │
│  │ JOIN │ │LEAVE │ │ DRAW │ │ CLEAR  │ │STATE_SYNC│           │
│  │Handler│ │Handler│ │Handler│ │Handler│ │Handler  │           │
│  └──────┘ └──────┘ └──────┘ └────────┘ └──────────┘           │
│     │         │         │        │        │                    │
│     └─────────┴─────────┴────────┴────────┘                    │
│               │                                                │
│               ↓                                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  ConnectionManager                                       │  │
│  │    - 维护 {connection_id: WebSocketClient}               │  │
│  │    - 添加/移除连接                                       │  │
│  │    - 广播消息到指定连接                                   │  │
│  └───────────────────────────────────────────────────────────┘  │
│        ↕                                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  RoomManager                                             │  │
│  │    - 维护 {room_id: Room}                                │  │
│  │    - 创建/销毁房间                                       │  │
│  │    - 管理房间用户列表                                     │  │
│  │    - 检查房间状态合法性                                   │  │
│  └───────────────────────────────────────────────────────────┘  │
│        ↕                                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Room Object                                             │  │
│  │    - room_id, state, user_count                          │  │
│  │    - canvas_history: [events]                            │  │
│  │    - users: {user_id: UserSession}                       │  │
│  │    - sequence_id: global counter                         │  │
│  │    - idle_timer: TTL timer                               │  │
│  └───────────────────────────────────────────────────────────┘  │
│        ↕                                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  StateManager                                            │  │
│  │    - 维护全局状态（用户、房间、连接）                      │  │
│  │    - 线程安全的状态更新 (Lock)                             │  │
│  │    - 状态转移验证                                         │  │
│  └───────────────────────────────────────────────────────────┘  │
│        ↕                                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Storage Layer (In-Memory + Optional Persistence)        │  │
│  │    - 内存缓存: {room_id: canvas_history}                 │  │
│  │    - 可选: Redis 持久化                                  │  │
│  │    - 可选: 文件系统备份                                   │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 模块化架构详解

### 2.1 ConnectionManager

**职责**: 管理所有 WebSocket 客户端连接

```python
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocketClient] = {}
        self.lock = threading.RLock()
    
    def add_connection(self, connection_id: str, websocket) -> None:
        """添加新连接"""
        with self.lock:
            self.connections[connection_id] = websocket
    
    def remove_connection(self, connection_id: str) -> None:
        """移除连接"""
        with self.lock:
            if connection_id in self.connections:
                del self.connections[connection_id]
    
    def broadcast(self, room_id: str, message: dict, exclude: str = None) -> None:
        """向房间中的所有用户广播消息"""
        room = RoomManager.get_room(room_id)
        if not room:
            return
        
        for user_id in room.users:
            for conn_id, websocket in self.connections.items():
                if websocket.user_id == user_id and conn_id != exclude:
                    try:
                        websocket.send_json(message)
                    except Exception as e:
                        logger.error(f"Failed to send to {conn_id}: {e}")
    
    def send_to_connection(self, connection_id: str, message: dict) -> None:
        """向特定连接发送消息"""
        if connection_id in self.connections:
            try:
                self.connections[connection_id].send_json(message)
            except Exception as e:
                logger.error(f"Failed to send to {connection_id}: {e}")
```

---

### 2.2 RoomManager

**职责**: 管理所有房间及其生命周期

```python
class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self.lock = threading.RLock()
        self.cleanup_scheduler = None
    
    def get_or_create_room(self, room_id: str) -> Room:
        """获取或创建房间"""
        with self.lock:
            if room_id not in self.rooms:
                self.rooms[room_id] = Room(room_id)
            return self.rooms[room_id]
    
    def get_room(self, room_id: str) -> Optional[Room]:
        """获取房间"""
        return self.rooms.get(room_id)
    
    def add_user_to_room(self, room_id: str, user_id: str) -> Room:
        """用户加入房间"""
        with self.lock:
            room = self.get_or_create_room(room_id)
            
            # 如果房间处于 IDLE，转移到 ACTIVE
            if room.state == RoomState.IDLE:
                room.state = RoomState.ACTIVE
                room.cancel_idle_timer()
            
            # 增加用户计数
            room.add_user(user_id)
            
            return room
    
    def remove_user_from_room(self, room_id: str, user_id: str) -> None:
        """用户离开房间"""
        with self.lock:
            room = self.get_room(room_id)
            if not room:
                return
            
            room.remove_user(user_id)
            
            # 检查是否为最后一个用户
            if room.user_count == 0:
                room.state = RoomState.IDLE
                room.start_idle_timer(ttl_seconds=60)
    
    def destroy_room(self, room_id: str) -> None:
        """销毁房间"""
        with self.lock:
            if room_id in self.rooms:
                room = self.rooms[room_id]
                room.state = RoomState.DESTROYED
                room.cancel_idle_timer()
                del self.rooms[room_id]
                logger.info(f"Room {room_id} destroyed")
    
    def cleanup_idle_rooms(self) -> None:
        """定期清理 IDLE 房间"""
        with self.lock:
            rooms_to_destroy = []
            for room_id, room in self.rooms.items():
                if room.state == RoomState.IDLE and room.is_ttl_expired():
                    rooms_to_destroy.append(room_id)
            
            for room_id in rooms_to_destroy:
                self.destroy_room(room_id)
```

---

### 2.3 StateManager

**职责**: 维护和验证全局状态

```python
class StateManager:
    def __init__(self):
        self.user_states: Dict[str, UserState] = {}
        self.room_states: Dict[str, RoomState] = {}
        self.lock = threading.RLock()
    
    def transition_user_state(
        self,
        user_id: str,
        current_state: UserState,
        target_state: UserState,
        event: str
    ) -> bool:
        """状态转移验证"""
        with self.lock:
            # 验证转移合法性
            if not self._is_valid_transition(current_state, target_state):
                logger.warning(
                    f"Invalid state transition: {current_state} -> {target_state}"
                )
                return False
            
            # 执行转移
            self.user_states[user_id] = target_state
            logger.info(f"User {user_id} transitioned: {current_state} -> {target_state}")
            return True
    
    def _is_valid_transition(self, from_state, to_state) -> bool:
        """检查转移合法性"""
        valid_transitions = {
            UserState.INIT: [UserState.CONNECTED],
            UserState.CONNECTED: [UserState.JOINED, UserState.DISCONNECTED],
            UserState.JOINED: [UserState.ACTIVE, UserState.LEFT, UserState.IDLE],
            UserState.ACTIVE: [UserState.LEFT, UserState.IDLE],
            UserState.LEFT: [UserState.DISCONNECTED],
            UserState.IDLE: [UserState.ACTIVE, UserState.TIMEOUT],
            UserState.TIMEOUT: [UserState.DISCONNECTED],
            UserState.DISCONNECTED: []
        }
        return to_state in valid_transitions.get(from_state, [])
```

---

### 2.4 MessageHandler 和子处理器

**职责**: 处理不同类型的消息

```python
class MessageHandler:
    def __init__(self, connection_mgr, room_mgr, state_mgr):
        self.connection_mgr = connection_mgr
        self.room_mgr = room_mgr
        self.state_mgr = state_mgr
        self.dedup_cache: Dict[str, tuple] = {}  # {msg_id: (timestamp, response)}
    
    async def handle_message(self, connection_id: str, raw_message: dict) -> None:
        """主消息处理入口"""
        try:
            # 1. 验证 JSON Schema
            self._validate_schema(raw_message)
            
            # 2. 检查去重
            if self._is_duplicate(raw_message):
                self._send_cached_response(connection_id, raw_message['msg_id'])
                return
            
            # 3. 消息类型路由
            message_type = raw_message['type']
            
            if message_type == 'join':
                await self._handle_join(connection_id, raw_message)
            elif message_type == 'leave':
                await self._handle_leave(connection_id, raw_message)
            elif message_type == 'draw':
                await self._handle_draw(connection_id, raw_message)
            elif message_type == 'clear':
                await self._handle_clear(connection_id, raw_message)
            elif message_type == 'state_sync':
                await self._handle_state_sync(connection_id, raw_message)
            else:
                self._send_error(connection_id, raw_message, 'INVALID_MESSAGE')
        
        except ValidateError as e:
            self._send_error(connection_id, raw_message, 'INVALID_MESSAGE', str(e))
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            self._send_error(connection_id, raw_message, 'INTERNAL_ERROR')
    
    async def _handle_join(self, connection_id: str, msg: dict) -> None:
        """处理 JOIN 消息"""
        user_id = msg['user_id']
        room_id = msg['room_id']
        
        # 添加用户到房间
        room = self.room_mgr.add_user_to_room(room_id, user_id)
        
        # 获取 canvas 历史
        canvas_history = room.get_canvas_history()
        
        # 发送 ACK
        ack_response = {
            'msg_id': msg['msg_id'],
            'type': 'ack',
            'timestamp': time.time() * 1000,
            'user_id': 'server',
            'room_id': room_id,
            'sequence_id': room.current_sequence,
            'payload': {
                'status': 'ok',
                'reason': 'joined',
                'room_state': {
                    'room_id': room_id,
                    'user_count': room.user_count,
                    'canvas_history': canvas_history
                }
            }
        }
        self.connection_mgr.send_to_connection(connection_id, ack_response)
        
        # 广播 user_joined 事件
        broadcast_msg = {
            'msg_id': msg['msg_id'],
            'type': 'broadcast',
            'timestamp': time.time() * 1000,
            'user_id': user_id,
            'room_id': room_id,
            'sequence_id': room.increment_sequence(),
            'payload': {
                'event_type': 'user_joined',
                'user_id': user_id,
                'user_name': msg['payload'].get('metadata', {}).get('user_name', user_id),
                'room_user_count': room.user_count
            }
        }
        self.connection_mgr.broadcast(room_id, broadcast_msg, exclude=connection_id)
    
    async def _handle_leave(self, connection_id: str, msg: dict) -> None:
        """处理 LEAVE 消息"""
        user_id = msg['user_id']
        room_id = msg['room_id']
        
        room = self.room_mgr.get_room(room_id)
        if not room:
            self._send_error(connection_id, msg, 'ROOM_NOT_FOUND')
            return
        
        # 从房间移除用户
        self.room_mgr.remove_user_from_room(room_id, user_id)
        
        # 发送 ACK
        ack_response = {
            'msg_id': msg['msg_id'],
            'type': 'ack',
            'timestamp': time.time() * 1000,
            'user_id': 'server',
            'room_id': room_id,
            'sequence_id': room.current_sequence,
            'payload': {
                'status': 'ok',
                'room_user_count': room.user_count
            }
        }
        self.connection_mgr.send_to_connection(connection_id, ack_response)
        
        # 广播 user_left 事件
        broadcast_msg = {
            'msg_id': msg['msg_id'],
            'type': 'broadcast',
            'timestamp': time.time() * 1000,
            'user_id': user_id,
            'room_id': room_id,
            'sequence_id': room.increment_sequence(),
            'payload': {
                'event_type': 'user_left',
                'user_id': user_id,
                'reason': msg['payload'].get('reason', 'unknown'),
                'remaining_users': room.user_count,
                'room_cleanup_started': room.state == RoomState.IDLE
            }
        }
        self.connection_mgr.broadcast(room_id, broadcast_msg)
        
        # 如果房间变为 IDLE，广播 room_idle 消息
        if room.state == RoomState.IDLE:
            idle_msg = {
                'type': 'broadcast',
                'timestamp': time.time() * 1000,
                'user_id': 'server',
                'room_id': room_id,
                'sequence_id': room.increment_sequence(),
                'payload': {
                    'event_type': 'room_idle',
                    'room_id': room_id,
                    'ttl_seconds': 60,
                    'message': 'Room will be destroyed in 60 seconds if no user rejoins'
                }
            }
            self.connection_mgr.broadcast(room_id, idle_msg)
    
    async def _handle_draw(self, connection_id: str, msg: dict) -> None:
        """处理 DRAW 消息"""
        user_id = msg['user_id']
        room_id = msg['room_id']
        
        room = self.room_mgr.get_room(room_id)
        if not room:
            self._send_error(connection_id, msg, 'ROOM_NOT_FOUND')
            return
        
        # 验证 payload
        self._validate_draw_payload(msg['payload'])
        
        # 分配序列号
        sequence_id = room.increment_sequence()
        
        # 记录事件到 canvas 历史
        room.add_event(sequence_id, msg)
        
        # 发送 ACK
        ack_response = {
            'msg_id': msg['msg_id'],
            'type': 'ack',
            'timestamp': time.time() * 1000,
            'user_id': 'server',
            'room_id': room_id,
            'sequence_id': sequence_id,
            'payload': {
                'status': 'ok',
                'stroke_id': msg['payload']['stroke_id'],
                'server_sequence': sequence_id
            }
        }
        self.connection_mgr.send_to_connection(connection_id, ack_response)
        
        # 广播 DRAW 事件
        broadcast_msg = {
            'msg_id': msg['msg_id'],
            'type': 'broadcast',
            'timestamp': msg['timestamp'],
            'user_id': user_id,
            'room_id': room_id,
            'sequence_id': sequence_id,
            'payload': {
                'event_type': 'draw',
                'stroke_id': msg['payload']['stroke_id'],
                'tool': msg['payload']['tool'],
                'color': msg['payload']['color'],
                'width': msg['payload']['width'],
                'points': msg['payload']['points']
            }
        }
        self.connection_mgr.broadcast(room_id, broadcast_msg)
    
    async def _handle_clear(self, connection_id: str, msg: dict) -> None:
        """处理 CLEAR 消息"""
        user_id = msg['user_id']
        room_id = msg['room_id']
        
        room = self.room_mgr.get_room(room_id)
        if not room:
            self._send_error(connection_id, msg, 'ROOM_NOT_FOUND')
            return
        
        # 分配序列号
        sequence_id = room.increment_sequence()
        
        # 清空 canvas 历史
        room.clear_canvas()
        
        # 发送 ACK
        ack_response = {
            'msg_id': msg['msg_id'],
            'type': 'ack',
            'timestamp': time.time() * 1000,
            'user_id': 'server',
            'room_id': room_id,
            'sequence_id': sequence_id,
            'payload': {
                'status': 'ok',
                'server_sequence': sequence_id
            }
        }
        self.connection_mgr.send_to_connection(connection_id, ack_response)
        
        # 广播 CLEAR 事件
        broadcast_msg = {
            'msg_id': msg['msg_id'],
            'type': 'broadcast',
            'timestamp': msg['timestamp'],
            'user_id': user_id,
            'room_id': room_id,
            'sequence_id': sequence_id,
            'payload': {
                'event_type': 'clear',
                'clear_type': msg['payload'].get('clear_type', 'full')
            }
        }
        self.connection_mgr.broadcast(room_id, broadcast_msg)
    
    async def _handle_state_sync(self, connection_id: str, msg: dict) -> None:
        """处理 STATE_SYNC 消息（重连支持）"""
        user_id = msg['user_id']
        room_id = msg['room_id']
        last_received = msg['payload'].get('last_received_sequence', -1)
        
        room = self.room_mgr.get_room(room_id)
        if not room:
            self._send_error(connection_id, msg, 'ROOM_NOT_FOUND')
            return
        
        # 计算需要同步的事件
        sync_events = room.get_events_since(last_received)
        
        # 发送 ACK（包含完整房间状态）
        ack_response = {
            'msg_id': msg['msg_id'],
            'type': 'ack',
            'timestamp': time.time() * 1000,
            'user_id': 'server',
            'room_id': room_id,
            'sequence_id': None,
            'payload': {
                'status': 'ok',
                'room_state': {
                    'room_id': room_id,
                    'current_sequence': room.current_sequence,
                    'canvas_events': sync_events,
                    'active_users': list(room.users.keys())
                }
            }
        }
        self.connection_mgr.send_to_connection(connection_id, ack_response)
    
    def _validate_schema(self, msg: dict) -> None:
        """验证消息 JSON Schema"""
        # 实现 jsonschema 验证...
        pass
    
    def _is_duplicate(self, msg: dict) -> bool:
        """检查消息是否重复"""
        return msg['msg_id'] in self.dedup_cache
    
    def _send_error(self, connection_id: str, original_msg: dict, error_code: str, message: str = '') -> None:
        """发送错误响应"""
        error_response = {
            'msg_id': original_msg['msg_id'],
            'type': 'error',
            'timestamp': time.time() * 1000,
            'user_id': 'server',
            'room_id': original_msg.get('room_id', ''),
            'sequence_id': None,
            'payload': {
                'status': 'fail',
                'error_code': error_code,
                'message': message or ERROR_MESSAGES.get(error_code, 'Unknown error')
            }
        }
        self.connection_mgr.send_to_connection(connection_id, error_response)
```

---

### 2.5 Room 数据结构

```python
class Room:
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.state = RoomState.ACTIVE
        self.users: Dict[str, UserSession] = {}
        self.canvas_history: List[dict] = []
        self.current_sequence = 0
        self.idle_timer = None
        self.idle_start_time = None
        self.lock = threading.RLock()
    
    @property
    def user_count(self) -> int:
        return len(self.users)
    
    def add_user(self, user_id: str) -> None:
        with self.lock:
            self.users[user_id] = UserSession(user_id)
    
    def remove_user(self, user_id: str) -> None:
        with self.lock:
            if user_id in self.users:
                del self.users[user_id]
    
    def increment_sequence(self) -> int:
        with self.lock:
            self.current_sequence += 1
            return self.current_sequence
    
    def add_event(self, sequence_id: int, event: dict) -> None:
        with self.lock:
            self.canvas_history.append({
                'sequence_id': sequence_id,
                'event': event
            })
    
    def get_canvas_history(self) -> List[dict]:
        with self.lock:
            return self.canvas_history.copy()
    
    def get_events_since(self, last_sequence: int) -> List[dict]:
        with self.lock:
            return [e for e in self.canvas_history if e['sequence_id'] > last_sequence]
    
    def clear_canvas(self) -> None:
        with self.lock:
            self.canvas_history.clear()
    
    def start_idle_timer(self, ttl_seconds: int = 60) -> None:
        with self.lock:
            self.idle_start_time = time.time()
            self.idle_timer = threading.Timer(
                ttl_seconds,
                self._on_idle_timeout
            )
            self.idle_timer.start()
    
    def cancel_idle_timer(self) -> None:
        with self.lock:
            if self.idle_timer:
                self.idle_timer.cancel()
                self.idle_timer = None
    
    def is_ttl_expired(self) -> bool:
        with self.lock:
            if self.idle_start_time:
                return time.time() - self.idle_start_time > 60
            return False
    
    def _on_idle_timeout(self) -> None:
        """TTL 过期回调"""
        logger.info(f"Room {self.room_id} TTL expired, marking for destruction")
        # 由 RoomManager 处理销毁逻辑
```

---

## 3. 数据流 (Data Flow)

### 3.1 典型的 DRAW 事件流

```
1. 客户端事件
   用户在画布上绘制 → Canvas EventListener 捕获
   
2. 客户端消息构建
   MessageBuilder 构建 DRAW 消息
   msg_id = UUID()
   timestamp = current_time_ms
   
3. WebSocket 发送
   ClientConnection.send(DRAW_message)

4. 服务器接收
   ServerConnection.on_message(raw_message)
   
5. 消息验证和路由
   MessageRouter.validate_schema(raw_message)
   MessageRouter.check_dedup(msg_id)
   MessageRouter.route(message_type)
   
6. 处理器执行
   HandleDraw.execute():
     - 获取房间对象
     - 验证 payload (color, width, points)
     - sequence_id = room.increment_sequence()
     - room.add_event(sequence_id, message)
     - 发送 ACK 给发送者
     - 构建广播消息
   
7. 广播
   ConnectionManager.broadcast(room_id, broadcast_msg):
     - 遍历房间中的所有用户
     - 获取每个用户的连接
     - 向每个连接发送广播消息
   
8. 客户端接收和重放
   ClientConnection.on_message(broadcast_msg):
     - BroadcastHandler 处理广播消息
     - 按 sequence_id 重新排序（如果需要）
     - CanvasRenderer 重放笔迹
     - 更新视图
```

---

## 4. 文件组织结构

```
Collaboard/
├── 01_PROTOCOL_SPECIFICATION.md      # 协议规范
├── 02_STATE_MACHINE_DESIGN.md         # 状态机设计
├── 03_ARCHITECTURE_DESIGN.md          # 本文件
│
├── backend/
│   ├── main.py                        # FastAPI 应用入口
│   ├── config.py                      # 配置文件
│   ├── requirements.txt               # Python 依赖
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── connection_manager.py      # 连接管理
│   │   ├── room_manager.py            # 房间管理
│   │   ├── state_manager.py           # 状态管理
│   │   ├── message_handler.py         # 消息处理路由
│   │   └── models.py                  # 数据模型
│   │
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── join_handler.py            # JOIN 消息处理
│   │   ├── leave_handler.py           # LEAVE 消息处理
│   │   ├── draw_handler.py            # DRAW 消息处理
│   │   ├── clear_handler.py           # CLEAR 消息处理
│   │   └── state_sync_handler.py      # STATE_SYNC 处理
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── message_schemas.py         # JSON Schema 定义
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── logger.py                  # 日志配置
│   │   ├── validation.py              # 消息验证工具
│   │   └── helpers.py                 # 辅助函数
│   │
│   └── tests/
│       ├── __init__.py
│       ├── test_protocol.py           # 协议测试
│       ├── test_state_machine.py      # 状态机测试
│       └── test_integration.py        # 集成测试
│
├── frontend/
│   ├── index.html                     # 主页面
│   ├── style.css                      # 样式
│   │
│   ├── js/
│   │   ├── main.js                    # 入口点
│   │   ├── canvas_renderer.js         # Canvas 渲染
│   │   ├── message_builder.js         # 消息构建
│   │   ├── connection_manager.js      # 连接管理
│   │   ├── broadcast_handler.js       # 广播处理
│   │   └── utils.js                   # 工具函数
│   │
│   └── test/
│       └── test_frontend.html         # 前端测试页面
│
├── docs/
│   ├── 04_IMPLEMENTATION_PLAN.md      # 实现计划
│   ├── 05_API_REFERENCE.md            # API 参考
│   ├── 06_EXAMPLES.md                 # 示例代码
│   └── 07_DEPLOYMENT.md               # 部署指南
│
└── README.md                          # 项目说明
```

---

## 5. 关键设计决策

| 决策 | 理由 |
|------|------|
| 事件驱动架构 | 解耦客户端和服务器，支持多对多通信 |
| 全局序列号 | 保证事件顺序，实现最终一致性 |
| 参考计数 + TTL | 优雅的清理策略，避免资源泄漏 |
| 消息去重（msg_id + dedup_window） | 处理网络重传，保证幂等性 |
| 单线程消息队列处理房间事件 | 避免竞态条件，保证事件顺序 |
| 状态机显式建模 | 清晰的状态转移逻辑，易于维护 |
| JSON Schema 验证 | 自动化客户端输入验证 |

---

**下一步**: 转到 `04_IMPLEMENTATION_PLAN.md` 查看详细的实现计划

