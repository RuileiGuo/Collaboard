# CollabBoard - 项目设计文档总览

**项目名称**: CollabBoard - 生产级实时协作白板系统  
**完成日期**: 2026-04-14  
**状态**: 设计阶段完成 ✅  
**下一步**: 实现阶段（Phase 1 开始）

---

## 📚 文档清单

### 1️⃣ **00_RESEARCH_PLAN_SUMMARY.md** (15 KB)
   - **用途**: 项目总体研究计划和设计决策总结
   - **包含内容**:
     - 项目目标和核心原则
     - 协议严格性要求
     - 状态机显式建模
     - 事件驱动 + 全局序列号
     - 清理策略详解
     - 完整的消息交互序列
     - 架构模块分解
     - 可靠性和容错机制
     - 安全性和验证
     - 性能考虑
     - 测试策略
     - 部署考虑
   - **读者**: 架构师、项目经理、所有团队成员

### 2️⃣ **01_PROTOCOL_SPECIFICATION.md** (20 KB)
   - **用途**: 详细的 WebSocket 消息协议规范
   - **包含内容**:
     - 基础消息格式（7 个字段）
     - 7 种消息类型的完整定义:
       - JOIN (加入房间)
       - DRAW (绘制笔迹)
       - CLEAR (清空画布)
       - LEAVE (离开房间)
       - STATE_SYNC (同步状态)
       - ACK (成功响应)
       - ERROR (错误响应)
       - BROADCAST (事件广播)
     - JSON Schema 定义
     - 变换和去重策略
     - 时序和顺序保证
     - 错误处理（8 种错误码）
     - 传输层细节
     - 安全约束
     - 完整交互序列示例
   - **读者**: 后端开发、前端开发、QA

### 3️⃣ **02_STATE_MACHINE_DESIGN.md** (18 KB)
   - **用途**: 用户和房间的状态机设计
   - **包含内容**:
     - 用户状态机 (8 个状态):
       - INIT → CONNECTED → JOINED → ACTIVE → LEFT → DISCONNECTED
       - 还有 IDLE, TIMEOUT 中间状态
     - 房间状态机 (4 个状态):
       - PENDING_INIT → ACTIVE ↔ IDLE → DESTROYED
     - 详细的状态转移规则（矩阵形式）
     - 消息处理状态转移流程图
     - 清理策略 (参考计数 + TTL)
     - 无效状态转移处理
     - 连接管理状态机
     - 并发和同步问题
   - **读者**: 后端开发、系统设计师

### 4️⃣ **03_ARCHITECTURE_DESIGN.md** (22 KB)
   - **用途**: 完整的系统架构设计
   - **包含内容**:
     - 系统架构总体视图（分层）
     - 5 个核心管理器详解:
       - ConnectionManager (连接管理)
       - RoomManager (房间管理)
       - StateManager (状态管理)
       - MessageHandler (消息路由和处理)
       - 各类型消息处理器
     - Room 数据结构设计
     - 完整的数据流分析
     - 文件组织结构 (26 个文件)
     - 关键设计决策说明
   - **读者**: 后端架构师、Tech Lead

### 5️⃣ **04_IMPLEMENTATION_PLAN.md** (20 KB)
   - **用途**: 分阶段的实现计划和路线图
   - **包含内容**:
     - 5 个实现阶段 (Phase 1-5)
     - 每个阶段的里程碑和交付物
     - 技术栈细节 (FastAPI, WebSockets, Pydantic, asyncio...)
     - 核心实现概要 (伪代码)
     - 关键实现检查清单 (14 项)
     - 开发顺序建议
     - 依赖关系图
     - 测试策略 (单元 + 集成 + E2E)
     - 性能目标
     - 故障处理场景
     - 文档输出清单
   - **读者**: 项目经理、后端开发、测试

### 6️⃣ **README_QUICK_REFERENCE.md** (16 KB)
   - **用途**: 快速参考指南，用于实现阶段查阅
   - **包含内容**:
     - 消息格式速查表
     - 状态机转移规则（可视化）
     - 错误码速查表
     - 数据结构速查
     - 处理流程详图
     - 超时配置表
     - 速率限制配置
     - 广播规则表
     - 去重机制说明
     - 重连支持流程
     - 清理策略详解
     - 性能优化建议
     - 调试技巧
     - 常见错误清单
   - **读者**: 开发人员（实现阶段查阅）

---

## 📊 文档统计

| 文档名称 | 大小 | 行数 | 重点内容 |
|---------|------|------|--------|
| 00_RESEARCH_PLAN_SUMMARY.md | 15 KB | ~450 | 总体规划 |
| 01_PROTOCOL_SPECIFICATION.md | 20 KB | ~600 | 协议细节 |
| 02_STATE_MACHINE_DESIGN.md | 18 KB | ~550 | 状态机 |
| 03_ARCHITECTURE_DESIGN.md | 22 KB | ~650 | 系统架构 |
| 04_IMPLEMENTATION_PLAN.md | 20 KB | ~600 | 实现路线 |
| README_QUICK_REFERENCE.md | 16 KB | ~500 | 快速查阅 |
| **总计** | **~111 KB** | **~3350** | 完整设计蓝图 |

---

## 🎯 核心设计亮点

### ✨ 1. 严格的协议规范

- ✅ 所有消息统一的 JSON 格式（7 个基础字段）
- ✅ 8 种消息类型完整定义
- ✅ JSON Schema 自动验证
- ✅ 明确的错误处理 (8 种错误码)

### ✨ 2. 显式状态机

- ✅ 用户状态: 8 个状态 + 清晰转移规则
- ✅ 房间状态: 4 个状态 + 参考计数验证
- ✅ 防止非法状态转移
- ✅ 完整的边界情况处理

### ✨ 3. 事件驱动一致性模型

- ✅ 全局序列号 (从 0 递增)
- ✅ 客户端按序重放事件
- ✅ 最终一致性保证
- ✅ 异序消息缓冲处理

### ✨ 4. 自动清理策略

- ✅ 参考计数 (ref_count)
- ✅ TTL 定时器 (60秒 IDLE)
- ✅ 优雅的资源释放
- ✅ 支持用户快速重连

### ✨ 5. 完整的容错机制

- ✅ 消息去重 (msg_id + dedup_window)
- ✅ 请求-响应模式 (ACK/ERROR)
- ✅ 超时检测 (多层级)
- ✅ 网络中断恢复 (STATE_SYNC)

### ✨ 6. 模块化架构

- ✅ 5 个核心管理器
- ✅ 独立的消息处理器
- ✅ 清晰的职责分离
- ✅ 易于维护和扩展

---

## 🔄 实现建议流程

```
第 1 步: 理解设计

  阅读顺序:
  1. 00_RESEARCH_PLAN_SUMMARY.md (获得全貌)
  2. 01_PROTOCOL_SPECIFICATION.md (理解协议)
  3. 02_STATE_MACHINE_DESIGN.md (理解状态)
  4. 03_ARCHITECTURE_DESIGN.md (理解架构)


第 2 步: 规划实现

  参考:
  - 04_IMPLEMENTATION_PLAN.md (5 个实现阶段)
  - README_QUICK_REFERENCE.md (快速查阅)


第 3 步: 开始编码

  推荐顺序:
  1. models.py (数据模型 + 枚举)
  2. schemas.py (JSON Schema)
  3. state_manager.py (状态管理)
  4. connection_manager.py (连接管理)
  5. room_manager.py (房间管理)
  6. message_handler.py (消息路由)
  7. 各类型处理器 (join, leave, draw...)
  8. main.py (FastAPI 应用)
  9. 前端代码
  10. 测试代码


第 4 步: 实现过程中参考

  - README_QUICK_REFERENCE.md (状态转移表、错误码、配置)
  - 对应文档的伪代码部分
```

---

## 💡 关键概念速记

### 🔑 消息结构

```json
{
  "msg_id": "UUID",
  "type": "join|leave|draw|clear|state_sync|ack|error|broadcast",
  "timestamp": "毫秒",
  "user_id": "用户标识",
  "room_id": "房间标识",
  "sequence_id": "服务器赋予（客户端请求为 null）",
  "payload": "消息内容"
}
```

### 🔑 状态转移

```
用户:  INIT → CONNECTED → JOINED → ACTIVE → LEFT → DISCONNECTED
房间:  PENDING_INIT → ACTIVE ↔ IDLE → DESTROYED
```

### 🔑 序列号

- 每条广播消息获得唯一的 `sequence_id`
- 从 0 开始递增
- 客户端按 sequence_id 重放事件

### 🔑 清理策略

- **参考计数**: JOIN +1, LEAVE -1
- **TTL 定时器**: 当 ref_count == 0，启动 60秒 TTL
- **销毁**: TTL 过期且 ref_count 仍为 0 时

### 🔑 去重机制

- **客户端**: 每个请求生成 UUID msg_id
- **服务器**: 维护 300秒的 dedup_window
- **幂等性**: 相同 msg_id 返回相同响应

---

## 📋 验收标准

### 设计阶段完成标准 (✅ 已完成)

- [x] 协议完整定义 (7 种消息类型, 8 种错误码)
- [x] 状态机清晰建模 (用户 8 态, 房间 4 态)
- [x] 架构分层设计 (5 个核心管理器)
- [x] 实现阶段规划 (5 个 Phase, 详细里程碑)
- [x] 文档完整 (6 份共 3350+ 行)
- [x] 示例代码和伪代码
- [x] 错误处理和容错设计

### 实现阶段待完成

- [ ] 后端代码实现 (Python + FastAPI)
- [ ] 前端代码实现 (HTML5 + Canvas)
- [ ] 单元测试 (pytest)
- [ ] 集成测试 (多用户模拟)
- [ ] 压力测试 (1000+ messages/sec)
- [ ] E2E 测试 (真实场景)
- [ ] 部署文档和脚本

---

## 📞 文档导航

### 我想了解...

**整个系统?**
→ 从 `00_RESEARCH_PLAN_SUMMARY.md` 开始

**消息格式?**
→ `01_PROTOCOL_SPECIFICATION.md` 第 3 节

**状态如何转移?**
→ `02_STATE_MACHINE_DESIGN.md` 第 1、2 节

**如何实现架构?**
→ `03_ARCHITECTURE_DESIGN.md` 第 2 节

**分阶段怎么做?**
→ `04_IMPLEMENTATION_PLAN.md` 第 1 节

**快速查阅配置?**
→ `README_QUICK_REFERENCE.md` 全部

---

## 🎓 学习资源链接

### 相关技术文档
- WebSocket 协议: https://tools.ietf.org/html/rfc6455
- JSON Schema: https://json-schema.org/
- FastAPI 官方: https://fastapi.tiangolo.com/
- asyncio 指南: https://docs.python.org/3/library/asyncio.html

### 设计模式参考
- Event-Driven Architecture
- State Machine Pattern
- Message Queue Pattern
- Reference Counting & GC

---

## 🚀 下一步行动

### 立即可做

1. 📖 完整阅读本设计文档集 (建议 2-3 小时)
2. 📝 团队讨论和确认设计细节
3. 📋 准备开发环境 (Python 3.8+, FastAPI)

### 实现阶段 (Phase 1)

1. 👨‍💻 创建项目骨架
2. 📦 定义数据模型和枚举
3. 🔍 实现 JSON Schema 验证
4. ⚙️ 构建 5 个核心管理器

### 后续阶段 (Phase 2-5)

- 实现消息处理器
- 前端实现
- 集成和测试
- 文档和部署

---

## 📝 版本历史

| 版本 | 日期 | 状态 | 说明 |
|------|------|------|------|
| 1.0 | 2026-04-14 | ✅ 完成 | 初始设计完成，已提交 |
| 1.1 | TBD | ⏳ 待定 | 实现过程中的更新 |
| 2.0 | TBD | ⏳ 待定 | 生产部署版本 |

---

## 📞 联系方式

- 项目架构师: [TBD]
- 技术主管: [TBD]
- 文档维护: [TBD]

---

## ⚖️ 许可证

本设计文档属于 CollabBoard 项目，版权属于开发团队。

---

**📌 最后提醒**:

> 这是一份**研究级别严谨、生产级别完整**的设计文档。请在实现代码时严格遵循协议和状态机设计。即使在开发过程中发现改进，也应该更新文档以保持代码和设计的一致性。

---

**✅ 设计阶段完成！准备进入实现阶段。**

