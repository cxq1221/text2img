# HTTP 轮询方案改造说明

## 📋 改造概述

本次改造将系统从 **WebSocket 实时推送** 改为 **HTTP 轮询** 方案，简化了架构，提高了稳定性。

## 🔄 主要改动

### 1. Worker 端改造

#### 新增功能
- ✅ **任务状态管理**：在内存中维护 `prompt_id -> {status, progress, image_url}` 映射
- ✅ **`/status/{prompt_id}` 接口**：返回任务状态和进度
  ```json
  {
    "status": "pending|running|completed|failed",
    "progress": {"value": 50, "max": 100},
    "image_url": "http://worker:8001/images/xxx.png",
    "error": "错误信息（如果失败）"
  }
  ```
- ✅ **`/result/{prompt_id}` 接口**：返回任务结果（包含图片URL）
  ```json
  {
    "status": "completed",
    "image_url": "http://worker:8001/images/xxx.png",
    "completed_at": 1234567890
  }
  ```
- ✅ **图片本地存储**：任务完成时，从 ComfyUI 获取图片并保存到本地 `images/` 目录
- ✅ **静态文件服务**：通过 `/images/{filename}` 提供图片访问

#### 移除功能
- ❌ 移除了 `/history` 和 `/image` 接口（不再需要）

### 2. Scheduler 端改造

#### 新增功能
- ✅ **`/status/{prompt_id}` 接口**：转发到对应 Worker 的 `/status/{prompt_id}`
- ✅ **`/result/{prompt_id}` 接口**：转发到对应 Worker 的 `/result/{prompt_id}`
- ✅ **`/generate` 接口增强**：返回 `worker_url`，方便前端直接访问 Worker

#### 移除功能
- ❌ 移除了 WebSocket 代理相关代码（`/ws` 接口、`WebSocketProxy` 类）
- ❌ 移除了 `/history` 和 `/image` 接口

### 3. 前端改造

#### 新增功能
- ✅ **HTTP 轮询机制**：每 1.5 秒调用 `/status/{prompt_id}` 获取任务状态
- ✅ **状态显示**：根据任务状态（pending/running/completed/failed）更新 UI
- ✅ **进度显示**：显示执行进度（value/max）
- ✅ **结果获取**：任务完成后，调用 `/result/{prompt_id}` 获取图片 URL

#### 移除功能
- ❌ 移除了 WebSocket 连接代码
- ❌ 移除了 `fetchHistoryAndShowImage` 函数（不再需要两次 HTTP 请求）

## 🚀 使用流程

### 1. 启动服务

```bash
# 启动 Scheduler（端口 8000）
cd /root/text2img-demo
python -m backend.scheduler

# 启动 Worker（端口 8001，每台 GPU 机器一个）
python -m backend.worker
```

### 2. 前端使用流程

1. **提交任务**：前端调用 `POST /generate`，返回 `prompt_id`
2. **轮询状态**：前端每 1.5 秒调用 `GET /status/{prompt_id}`，获取任务状态
3. **获取结果**：当状态为 `completed` 时，调用 `GET /result/{prompt_id}` 获取图片 URL
4. **显示图片**：直接使用返回的 `image_url` 显示图片

## 📊 架构对比

### 改造前（WebSocket 方案）
```
前端 → WebSocket → Scheduler → WebSocket代理 → Worker → ComfyUI
前端 → HTTP GET /history → Scheduler → Worker → ComfyUI
前端 → HTTP GET /image → Scheduler → Worker → ComfyUI
```

### 改造后（HTTP 轮询方案）
```
前端 → HTTP GET /status/{prompt_id} → Scheduler → Worker（内存状态）
前端 → HTTP GET /result/{prompt_id} → Scheduler → Worker（返回图片URL）
前端 → 直接访问 Worker 的图片 URL（http://worker:8001/images/xxx.png）
```

## ✅ 优势

1. **架构简化**：
   - 移除了 WebSocket 代理的复杂性
   - 减少了连接管理和错误处理的复杂度

2. **稳定性提升**：
   - HTTP 请求更容易调试和排查问题
   - 避免了 WebSocket 连接断开的问题

3. **性能优化**：
   - 图片直接访问 Worker，不经过 Scheduler 中转
   - 减少了 Scheduler 的负载

4. **维护性提升**：
   - 代码更简单，易于理解和维护
   - 符合"能跑 > 优雅"的设计理念

## ⚠️ 注意事项

1. **图片存储**：
   - 图片保存在 Worker 的 `images/` 目录
   - 需要定期清理旧图片，避免磁盘空间不足
   - 建议实现图片清理策略（如保留最近 100 张，或按时间清理）

2. **Worker 地址**：
   - Worker 需要监听 `0.0.0.0:8001`，确保前端可以访问
   - 如果 Worker 只监听 `127.0.0.1`，前端无法直接访问图片

3. **轮询频率**：
   - 当前设置为 1.5 秒轮询一次
   - 可以根据实际需求调整（建议 1-3 秒）

4. **任务状态清理**：
   - Worker 内存中的任务状态不会自动清理
   - 建议实现清理策略（如任务完成后 1 小时清理）

## 🔧 后续优化建议

1. **图片清理策略**：
   - 实现 LRU 缓存，自动清理旧图片
   - 或按时间清理（如保留最近 24 小时）

2. **任务状态清理**：
   - 任务完成后，延迟清理状态（如 1 小时后）
   - 避免内存泄漏

3. **错误重试**：
   - 前端轮询失败时，实现指数退避重试
   - 避免频繁请求导致的问题

4. **进度信息优化**：
   - 从 ComfyUI 的 WebSocket 获取更详细的进度信息
   - 在 Worker 端缓存，通过 `/status` 接口返回

