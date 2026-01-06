# 系统架构文档

## 概述

这是一个基于 FastAPI 的局域网文本生成图片调度系统，采用 Scheduler-Worker 架构，支持多 Worker 节点分布式执行 ComfyUI 图片生成任务。

## 系统架构

```
┌─────────────┐
│   Frontend  │ (HTML + JavaScript)
│  (Browser)  │
└──────┬──────┘
       │ HTTP (POST /generate, GET /status)
       │
┌──────▼──────────────────────────────────────┐
│           Scheduler (调度器)                  │
│  - Worker 注册与心跳管理                      │
│  - 任务调度与分配                              │
│  - 任务状态查询                                │
│  Port: 8000                                   │
└──────┬───────────────────────────────────────┘
       │ HTTP (POST /task, POST /complete)
       │
       ├──────────────┬──────────────┐
       │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐
│   Worker 1  │ │  Worker 2  │ │  Worker N  │
│  Port: 8001 │ │ Port: 8002 │ │ Port: 800N │
└──────┬──────┘ └─────┬──────┘ └─────┬──────┘
       │              │              │
       │ WebSocket    │ WebSocket    │ WebSocket
       │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐
│  ComfyUI 1  │ │ ComfyUI 2  │ │ ComfyUI N  │
│  Port: 8188 │ │ Port: 8188 │ │ Port: 8188 │
└─────────────┘ └────────────┘ └────────────┘
```

## 核心组件

### 1. Scheduler (调度器)

**文件**: `backend/scheduler.py`

**职责**:
- Worker 注册与心跳管理
- 任务调度与分配（使用调度锁保证原子性）
- 任务状态查询
- Worker 状态监控（自动清理离线 Worker）

**主要 API**:
- `POST /register` - Worker 注册
- `POST /heartbeat` - Worker 心跳
- `POST /generate` - 提交生成任务
- `GET /status/{prompt_id}` - 查询任务状态
- `POST /task` - Worker 获取任务
- `POST /complete` - Worker 通知任务完成

**核心机制**:
- **调度锁**: 使用 `threading.Lock` 保证任务分配的原子性
- **心跳机制**: Worker 每 5 秒发送心跳，超时 15 秒视为离线
- **任务队列**: 使用内存中的任务队列管理待分配任务
- **Worker 状态**: `idle`（空闲）、`busy`（忙碌）、`offline`（离线）

### 2. Worker (工作节点)

**文件**: `backend/worker.py`

**职责**:
- 连接本地 ComfyUI 实例
- 接收 Scheduler 分配的任务
- 执行图片生成任务
- 保存生成的图片到本地静态目录
- 通过 WebSocket 获取 ComfyUI 执行进度

**主要 API**:
- `GET /status/{prompt_id}` - 查询任务状态（Worker 本地）
- `GET /images/{filename}` - 获取生成的图片（静态文件服务）
- `POST /task` - 从 Scheduler 获取任务（内部调用）

**核心机制**:
- **WebSocket 连接**: 启动时建立与 ComfyUI 的 WebSocket 连接，保持长连接
- **任务状态管理**: 使用内存字典 `task_status` 管理任务状态
- **图片保存**: 从 ComfyUI 获取图片后保存到 `images/` 目录
- **状态流转**: `pending` → `running` → `completed` / `failed`
- **图片验证**: 只有图片成功保存后才标记任务为完成

### 3. WorkerManager (Worker 管理器)

**文件**: `backend/worker_manager.py`

**职责**:
- 封装 Worker 状态管理逻辑
- 提供 Worker 查询、更新、清理等操作

**核心功能**:
- `get_available_worker()` - 获取可用 Worker
- `update_worker_status()` - 更新 Worker 状态
- `cleanup_offline_workers()` - 清理离线 Worker

## 数据流

### 任务提交流程

```
1. Frontend → Scheduler: POST /generate
   {
     "prompt": "a beautiful landscape",
     "negative_prompt": "...",
     "width": 512,
     "height": 512
   }

2. Scheduler:
   - 生成 prompt_id
   - 查找可用 Worker
   - 将任务加入队列
   - 返回 prompt_id

3. Worker → Scheduler: POST /task
   - Scheduler 分配任务给 Worker
   - Worker 返回任务信息

4. Worker:
   - 构建 ComfyUI workflow
   - 通过 HTTP API 提交到 ComfyUI
   - 通过 WebSocket 监听执行进度
   - 更新本地任务状态

5. Worker:
   - 收到 execution_complete 消息
   - 从 ComfyUI 获取图片
   - 保存图片到本地
   - 更新状态为 completed（只有图片保存成功）
   - 通知 Scheduler: POST /complete

6. Frontend → Scheduler: GET /status/{prompt_id}
   - Scheduler 查询 Worker 状态
   - 返回任务状态和图片 URL
```

### 状态查询流程

```
Frontend → Scheduler: GET /status/{prompt_id}
  ↓
Scheduler 查找任务所属 Worker
  ↓
Scheduler → Worker: GET /status/{prompt_id}
  ↓
Worker 返回本地任务状态
  ↓
Scheduler 返回给 Frontend
```

## 技术栈

### 后端
- **FastAPI**: Web 框架
- **WebSockets**: 与 ComfyUI 通信
- **Requests**: HTTP 客户端
- **Threading**: 并发控制（调度锁）

### 前端
- **HTML + JavaScript**: 原生前端实现
- **HTTP 轮询**: 定期查询任务状态

### 外部依赖
- **ComfyUI**: 图片生成引擎（每个 Worker 连接一个 ComfyUI 实例）

## 关键设计决策

### 1. HTTP 轮询 vs WebSocket

**选择**: HTTP 轮询

**原因**:
- 简化架构，避免跨 LAN 的 WebSocket 连接问题
- Frontend 只需定期轮询 Scheduler
- Scheduler 查询 Worker 状态，Worker 查询 ComfyUI 状态

### 2. 图片存储

**选择**: Worker 本地静态目录

**原因**:
- 避免图片传输开销
- 每个 Worker 管理自己的图片
- 通过 HTTP 静态文件服务提供访问

### 3. 任务状态管理

**选择**: 分布式状态管理

- **Scheduler**: 管理任务分配和 Worker 状态
- **Worker**: 管理本地任务执行状态
- **查询流程**: Frontend → Scheduler → Worker

### 4. 调度锁机制

**选择**: `threading.Lock` 全局锁

**原因**:
- 保证任务分配的原子性
- 避免多个请求同时获取同一个 Worker
- 简单可靠，适合单机 Scheduler

### 5. 图片保存验证

**选择**: 只有图片成功保存才标记任务完成

**原因**:
- 避免竞态条件
- 确保前端获取结果时 image_url 一定存在
- 提供重试机制处理 ComfyUI 历史记录延迟

## 文件结构

```
text2img-demo/
├── backend/
│   ├── scheduler.py          # 调度器主程序
│   ├── worker.py             # Worker 主程序
│   └── worker_manager.py     # Worker 管理器
├── frontend/
│   └── index.html            # 前端界面
├── images/                    # 图片存储目录（Worker 本地）
└── ARCHITECTURE.md            # 本文档
```

## 配置说明

### Scheduler 配置

- **端口**: 8000
- **Worker 心跳超时**: 15 秒
- **调度锁**: 全局 `threading.Lock`

### Worker 配置

- **端口**: 8001, 8002, ... (可配置)
- **ComfyUI 地址**: `http://localhost:8188` (可配置)
- **Scheduler 地址**: `http://localhost:8000` (可配置)
- **图片目录**: `images/` (相对路径)
- **心跳间隔**: 5 秒

## 部署说明

### 单机部署

1. 启动 Scheduler:
   ```bash
   cd backend
   python scheduler.py
   ```

2. 启动 Worker (可启动多个):
   ```bash
   cd backend
   python worker.py
   ```

3. 确保每个 Worker 都有独立的 ComfyUI 实例运行

### 分布式部署

1. 在一台机器上启动 Scheduler
2. 在多台机器上启动 Worker，配置正确的 Scheduler 地址
3. 每台 Worker 机器需要运行 ComfyUI
4. 确保网络互通

## 扩展性考虑

### 当前限制

- Scheduler 使用内存存储，重启后状态丢失
- 单机 Scheduler，存在单点故障风险
- 无持久化存储

### 未来改进方向

- 添加 Redis 等持久化存储
- 支持 Scheduler 集群
- 添加任务队列持久化
- 支持任务优先级
- 添加监控和日志系统

## 故障处理

### Worker 离线

- Scheduler 通过心跳检测 Worker 离线
- 超时 15 秒自动清理离线 Worker
- 正在执行的任务会丢失（需要前端重试）

### ComfyUI 连接失败

- Worker 启动时检测 ComfyUI 连接
- WebSocket 断线自动重连
- 任务失败时标记为 `failed` 状态

### 图片保存失败

- 任务标记为 `failed`
- 前端显示错误信息
- 需要用户重新提交任务

## 性能特性

- **并发处理**: 支持多 Worker 并行执行任务
- **任务调度**: 使用调度锁保证原子性，避免冲突
- **状态查询**: HTTP 轮询，简单可靠
- **图片访问**: 静态文件服务，性能良好

## 安全考虑

- 当前版本无认证机制，适合内网使用
- 生产环境建议添加认证和授权
- 建议使用 HTTPS（如需要）

