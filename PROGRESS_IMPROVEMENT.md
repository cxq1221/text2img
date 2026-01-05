# 进度显示改进说明

## 📋 改进概述

本次改进在保持 HTTP 轮询架构的基础上，通过 Worker 端连接 ComfyUI 的 WebSocket 获取详细进度信息，解决了之前只能显示"排队中"或"完成"的问题。

## 🔄 实现方案

### 核心思路

- **前端**：继续使用 HTTP 轮询（每 1.5 秒调用 `/status/{prompt_id}`）
- **Worker**：在后台连接 ComfyUI 的 WebSocket，接收实时进度信息
- **数据流**：ComfyUI WebSocket → Worker 内存 → HTTP 接口 → 前端轮询

### 架构图

```
前端 (HTTP 轮询)
  ↓ GET /status/{prompt_id}
Scheduler (转发)
  ↓ GET /status/{prompt_id}
Worker (返回内存中的状态)
  ↑ (实时更新)
Worker WebSocket 线程 (连接 ComfyUI)
  ↑ (实时接收)
ComfyUI WebSocket (ws://127.0.0.1:8188/ws)
```

## ✅ 新增功能

### 1. Worker 端 WebSocket 监听

- **`listen_comfyui_progress(prompt_id, client_id)`**：异步函数，连接 ComfyUI WebSocket 并监听进度
- **支持的消息类型**：
  - `progress`：进度更新（value/max）
  - `executing`：节点执行状态（当前执行的节点）
  - `execution_start`：执行开始
  - `execution_cached`：使用缓存节点
  - `execution_complete`：执行完成
  - `execution_error`：执行错误

### 2. 任务状态增强

现在 `/status/{prompt_id}` 返回的信息包括：

```json
{
  "status": "pending|running|completed|failed",
  "progress": {
    "value": 50,
    "max": 100
  },
  "current_node": "3",  // 当前执行的节点ID
  "message": "执行开始",  // 状态消息
  "image_url": "http://worker:8001/images/xxx.png",  // 完成后的图片URL
  "error": "错误信息",  // 失败时的错误信息
  "created_at": 1234567890,
  "completed_at": 1234567890
}
```

### 3. 前端显示优化

前端现在可以显示：
- **进度百分比**：`执行中: 50 / 100 (50.0%)`
- **当前节点**：`执行中: 50 / 100 (50.0%) - 节点: 3`
- **状态消息**：`执行中: 50 / 100 (50.0%) - 节点: 3 - 执行开始`

## 🔧 实现细节

### Worker 端实现

1. **任务提交时启动 WebSocket 监听**：
   ```python
   # 在 /run 接口中
   client_id = payload.get("client_id", str(uuid.uuid4()))
   ws_connections[prompt_id] = {
       "client_id": client_id,
       "thread": start_websocket_listener(prompt_id, client_id)
   }
   ```

2. **WebSocket 监听线程**：
   - 使用独立的 asyncio 事件循环
   - 在后台线程中运行，不阻塞主线程
   - 实时更新 `task_status` 字典

3. **进度信息更新**：
   - `progress` 消息：更新 `progress.value` 和 `progress.max`
   - `executing` 消息：更新 `current_node`
   - `execution_start`：更新 `message` 为"执行开始"
   - `execution_complete`：更新状态为 `completed`，获取并保存图片

### 前端实现

前端轮询时解析返回的状态信息：

```javascript
const status = data.status;
const progress = data.progress || {};
const current_node = data.current_node;
const message = data.message;

if (status === "running") {
    const percent = ((progress.value / progress.max) * 100).toFixed(1);
    let statusText = `执行中: ${progress.value} / ${progress.max} (${percent}%)`;
    
    if (current_node) {
        statusText += ` - 节点: ${current_node}`;
    }
    
    if (message) {
        statusText += ` - ${message}`;
    }
    
    setStatus(statusText);
}
```

## 📊 进度信息说明

### ComfyUI WebSocket 消息类型

1. **`progress`**：
   ```json
   {
     "type": "progress",
     "data": {
       "value": 10,
       "max": 100
     }
   }
   ```
   - `value`：当前进度值
   - `max`：最大进度值
   - 用于计算百分比：`(value / max) * 100`

2. **`executing`**：
   ```json
   {
     "type": "executing",
     "data": {
       "node": "3"  // 节点ID，null 表示节点执行完成
     }
   }
   ```
   - `node`：当前执行的节点ID
   - `null`：节点执行完成

3. **`execution_start`**：
   ```json
   {
     "type": "execution_start",
     "data": {
       "prompt_id": "xxx"
     }
   }
   ```
   - 表示任务开始执行

4. **`execution_complete`**：
   ```json
   {
     "type": "execution_complete",
     "data": {
       "prompt_id": "xxx"
     }
   }
   ```
   - 表示任务执行完成

## ⚠️ 注意事项

1. **WebSocket 连接管理**：
   - 每个任务启动一个独立的 WebSocket 连接
   - 任务完成后自动关闭连接
   - 连接失败时标记任务为 `failed`

2. **资源清理**：
   - WebSocket 连接在任务完成后自动清理
   - `ws_connections` 字典在连接关闭时清理

3. **错误处理**：
   - WebSocket 连接失败时，任务状态标记为 `failed`
   - 前端会显示错误信息

4. **性能考虑**：
   - WebSocket 连接在后台线程运行，不影响主线程
   - 每个 Worker 可以同时处理多个任务的 WebSocket 连接

## 🎯 优势

1. **保持架构简单**：前端仍然使用 HTTP 轮询，无需 WebSocket 客户端代码
2. **实时进度**：通过 Worker 端 WebSocket 获取 ComfyUI 的实时进度
3. **详细信息**：显示进度百分比、当前节点、状态消息等
4. **向后兼容**：不影响现有的 HTTP 轮询架构

## 📝 使用示例

### 前端显示效果

- **排队中**：`任务排队中...`
- **执行中**：`执行中: 50 / 100 (50.0%) - 节点: 3 - 执行开始`
- **完成**：`任务完成，获取结果...`
- **失败**：`任务失败: 错误信息`

### API 响应示例

```json
// GET /status/{prompt_id}
{
  "status": "running",
  "progress": {
    "value": 50,
    "max": 100
  },
  "current_node": "3",
  "message": "执行开始",
  "image_url": null,
  "created_at": 1234567890
}
```

