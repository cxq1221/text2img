# 文生图 Demo - 架构文档

## 📋 项目概述

这是一个**教程级文生图 Demo**项目，用于演示如何通过 FastAPI 后端和原生 HTML/JavaScript 前端，与 ComfyUI 进行集成，实现文本生成图片的完整流程。

## 🏗️ 架构设计

### 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        浏览器（前端）                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  访问 http://{host}:8000/ 获取前端页面                │  │
│  │  index.html (原生 HTML + JavaScript)                  │  │
│  │  - 输入 prompt                                        │  │
│  │  - 调用后端 /generate                                 │  │
│  │  - 直连 ComfyUI WebSocket 监听进度（不经过后端）        │  │
│  │  - 通过后端获取 /history 和图片                       │  │
│  └──────────────────────────────────────────────────────┘  │
└───────────┬───────────────────────────────┬─────────────────┘
            │                               │
            │ HTTP (GET / → index.html)    │ WebSocket (ws://.../ws)
            │ HTTP (POST /generate)        │ （前端直连，不经过后端）
            │ HTTP (GET /history/{id})     │
            │ HTTP (GET /image)            │
            │                               │
┌───────────▼───────────────────────────────┴─────────────────┐
│                    FastAPI 后端 (端口 8000)                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  backend/main.py                                      │  │
│  │  - GET /: 重定向到 /static/index.html（托管前端页面）   │  │
│  │  - /static/*: 静态文件服务（前端资源）                 │  │
│  │  - POST /generate: 读取 workflow，替换 prompt，调用    │  │
│  │    ComfyUI /prompt                                    │  │
│  │  - GET /history/{prompt_id}: 转发到 ComfyUI /history │  │
│  │  - GET /image: 转发到 ComfyUI /view，返回图片二进制    │  │
│  │  ⚠️ 注意：WebSocket 不经过后端，前端直连 ComfyUI        │  │
│  └──────────────────────────────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            │ HTTP (POST /prompt)
                            │ HTTP (GET /history/{prompt_id})
                            │ HTTP (GET /view)
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                  ComfyUI 服务 (端口 8188)                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  - /prompt: 接收 workflow，开始生成任务                │  │
│  │  - /ws: WebSocket 推送执行进度（前端直连）              │  │
│  │  - /history/{prompt_id}: 返回任务历史记录和输出        │  │
│  │  - /view: 返回生成的图片二进制                          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 数据流说明

1. **生成请求流程**：
   ```
   用户输入 prompt
   → 前端 POST /generate (后端 8000)
   → 后端读取 workflow.json，替换 prompt，调用 ComfyUI /prompt (8188)
   → 返回 prompt_id 和 client_id
   → 前端用 client_id 直连 ComfyUI WebSocket (8188)
   ⚠️ 注意：WebSocket 连接是前端直接连接到 ComfyUI，不经过后端
   ```

2. **进度监听流程**：
   ```
   ComfyUI 执行任务
   → 通过 WebSocket 直接推送到前端（ws://{host}:8188/ws?clientId=...）
   → 前端实时接收 progress / executing / executed 等消息
   → 前端实时更新状态显示
   → 收到 execution_complete / execution_success 后，调用后端 /history
   ⚠️ 注意：WebSocket 通信全程在前端和 ComfyUI 之间，后端不参与
   ```

3. **图片获取流程**：
   ```
   前端调用 GET /history/{prompt_id} (后端 8000)
   → 后端转发到 ComfyUI /history/{prompt_id} (8188)
   → 解析 outputs，提取图片信息
   → 前端调用 GET /image?filename=... (后端 8000)
   → 后端转发到 ComfyUI /view?filename=... (8188)
   → 返回图片二进制，前端展示
   ```

---

## 🎯 功能说明

### 1. 文本生成图片

- **输入**：用户在页面输入 prompt（支持中英文）
- **处理**：后端读取 `workflow.json`，使用 `deepcopy` 复制，替换正向 CLIPTextEncode 节点的 `text` 字段
- **提交**：调用 ComfyUI `/prompt` 接口，提交完整 workflow
- **返回**：返回 `prompt_id` 和 `client_id`，用于后续进度监听和结果查询

### 2. 实时进度监听

- **WebSocket 连接**：前端使用 `client_id` **直连** ComfyUI WebSocket `ws://{host}:8188/ws?clientId=...`
  - ⚠️ **重要**：WebSocket 连接不经过后端，前端直接连接到 ComfyUI
  - 原因：WebSocket 不受 CORS 限制，且实时性要求高，直连可减少延迟
- **消息类型处理**：
  - `execution_start`: 执行开始
  - `executing`: 正在执行某个节点
  - `progress`: 显示进度百分比（value / max）
  - `executed`: 某个节点执行完成
  - `execution_complete` / `execution_success`: 整个任务完成

### 3. 图片自动展示

- **历史记录查询**：任务完成后，前端调用后端 `/history/{prompt_id}`
- **图片信息解析**：从 `outputs[node_id].images[0]` 提取 `filename`、`subfolder`、`type`
- **图片获取**：通过后端 `/image` 接口获取图片二进制（解决 CORS 问题）
- **自动展示**：设置到 `<img>` 标签的 `src` 属性

### 4. 模板提示词功能

- **预设模板**：提供 4 种风格模板，快速开始生成
  - 奇幻风景：魔法森林、紫色天空、发光植物
  - 赛博朋克城市：未来主义城市、霓虹灯、科技感
  - 动漫角色：可爱动漫女孩、多彩头发、日系风格
  - 抽象艺术：流动抽象形状、渐变色彩、现代艺术

### 6. 自动适配部署环境

- **前端自动检测**：使用 `window.location.hostname` 获取当前访问的主机名
- **动态拼接地址**：
  - 后端：`http://${CURRENT_HOST}:8000`
  - ComfyUI：`http://${CURRENT_HOST}:8188`
- **优势**：部署到不同实例时，无需修改代码，只需确保端口映射一致

---

## 📁 目录结构

```
text2img/                       #业务项目目录
├── backend/                    # 后端目录
│   ├── main.py                # FastAPI 后端主文件
│   └── z-image_base.json      # ComfyUI workflow（API 格式）
│
├── frontend/                   # 前端目录
│   └── index.html             # 原生 HTML + JavaScript 页面
│
├── requirements.txt           # Python 依赖列表
└── README.md                  # 项目说明

```

### 文件说明

- **backend/main.py**：
  - FastAPI 应用入口
  - **静态文件托管**：通过 `/static` 路径托管 `frontend/` 目录，根路径 `/` 重定向到前端页面
  - 实现 `/generate`、`/history/{prompt_id}`、`/image` 三个接口
  - 处理 workflow 读取、prompt 替换、ComfyUI 调用

- **backend/z-image_base.json**：
  - ComfyUI workflow（通过 "Save (API)" 导出）
  - 结构：`{ "node_id": { "class_type": "...", "inputs": {...} } }`
  - 正向 prompt 节点：`node_id="6"` 或 `_meta.title` 含 "Positive Prompt"

- **frontend/index.html**：
  - 单文件前端应用（HTML + CSS + JavaScript）
  - 功能模块：
    - 输入提示词区域：文本输入框、字符计数、生成/清空按钮
    - 模板提示词区域：4 种预设模板卡片，一键填充
    - 生成结果区域：图片展示
    - 调试日志区域：技术日志

---

## 🛠️ 技术栈

### 后端

- **Python 3.x**
- **FastAPI**：Web 框架
- **uvicorn**：ASGI 服务器
- **requests**：HTTP 客户端（调用 ComfyUI API）
- **pydantic**：数据验证

### 前端

- **原生 HTML5**
- **原生 JavaScript (ES6+)**
- **CSS3**：渐变、动画、响应式布局
- **WebSocket API**：连接 ComfyUI 进度推送
- **Fetch API**：HTTP 请求

### 外部依赖

- **ComfyUI**：文生图服务（需单独部署，默认端口 8188）

---

## 📡 API 接口说明

### 后端接口（FastAPI，端口 8000）

#### 1. POST /generate

**功能**：接收 prompt，提交到 ComfyUI 生成图片

**请求**：
```json
{
  "prompt": "a cute cat sitting on the moon"
}
```

**响应**：
```json
{
  "prompt_id": "7c1f636b-ca6f-4ba7-89a8-66d6ad606463",
  "client_id": "a3ea0230-508d-4d1f-a31d-7304d2913055"
}
```

**流程**：
1. 读取 `backend/z-image_base.json`
2. `deepcopy` 复制 workflow
3. 找到正向 CLIPTextEncode 节点（node_id="6" 或 title 含 "Positive Prompt"）
4. 替换 `inputs.text = prompt`
5. 生成 `client_id`（UUID）
6. 调用 `POST http://127.0.0.1:8188/prompt`
7. 返回 `prompt_id` 和 `client_id`

---

#### 2. GET /history/{prompt_id}

**功能**：获取 ComfyUI 任务历史记录（转发接口，解决 CORS）

**请求**：
```
GET http://{host}:8000/history/7c1f636b-ca6f-4ba7-89a8-66d6ad606463
```

**响应**：
```json
{
  "7c1f636b-ca6f-4ba7-89a8-66d6ad606463": {
    "prompt": [...],
    "outputs": {
      "9": {
        "images": [
          {
            "filename": "ComfyUI_00027_.png",
            "subfolder": "",
            "type": "output"
          }
        ]
      }
    },
    "status": {
      "status_str": "success",
      "completed": true
    }
  }
}
```

**说明**：直接转发 ComfyUI `/history/{prompt_id}` 的响应

---

#### 3. GET /image

**功能**：获取生成的图片（转发接口，解决 CORS）

**请求**：
```
GET http://{host}:8000/image?filename=ComfyUI_00027_.png&subfolder=&type=output
```

**响应**：
- Content-Type: `image/png`（或其他图片格式）
- Body: 图片二进制数据

**说明**：转发 ComfyUI `/view` 接口，使用 `StreamingResponse` 流式返回

---

### ComfyUI 接口（端口 8188，仅作参考）

#### POST /prompt

**功能**：提交 workflow，开始生成任务

**请求**：
```json
{
  "prompt": { /* workflow dict */ },
  "client_id": "uuid-string"
}
```

**响应**：
```json
{
  "prompt_id": "7c1f636b-ca6f-4ba7-89a8-66d6ad606463"
}
```

---

#### WebSocket /ws

**功能**：推送任务执行进度

**连接**：
```
ws://{host}:8188/ws?clientId={client_id}
```

**消息格式**：
```json
{
  "type": "progress",
  "data": {
    "value": 5,
    "max": 9
  }
}
```

**消息类型**：
- `execution_start`: 开始执行
- `executing`: 正在执行节点
- `progress`: 进度更新
- `executed`: 节点完成
- `execution_complete`: 整个任务完成
- `execution_success`: 任务成功（部分版本）

---

## 🚀 使用说明

### 前置条件

1. **ComfyUI 已安装并运行**（默认端口 8188）
2. **Python 3.x 环境**
3. **已准备好 workflow.json**（API 格式，放在 `backend/` 目录）

### 安装步骤

1. **安装 Python 依赖**：
   ```bash
   cd text2img
   pip install -r requirements.txt
   ```

2. **确认 workflow 文件**：
   - 确保 `backend/z-image_base.json` 存在
   - 确保 workflow 中有正向 CLIPTextEncode 节点（node_id="6" 或 title 含 "Positive Prompt"）

3. **启动后端**（后端同时托管前端页面）：
   ```bash
   uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **打开前端页面**：
   - 直接在浏览器访问：`http://{服务器IP}:8000/`
   - 根路径会自动重定向到前端页面
   - 前端页面由后端通过 `/static` 路径提供

## 🔧 部署说明

### 单机部署（所有服务在同一台机器）

1. **ComfyUI**：监听 `0.0.0.0:8188`
2. **后端**：监听 `0.0.0.0:8000`（同时托管前端页面）

**启动后端**：
```bash
cd text2img
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**访问**：`http://{机器IP}:8000/`

- 根路径 `/` 会自动重定向到前端页面
- 前端页面由后端通过 `/static` 路径提供
- 前端会自动使用 `{机器IP}` 作为后端和 ComfyUI 的地址

### 前端、后端、ComfyUI 在不同机器

如需分布式部署，需要修改：
- 前端配置：手动指定后端和 ComfyUI 的 IP/域名
- 后端配置：修改 `COMFYUI_API_URL` 为 ComfyUI 的实际地址

---

### Docker 镜像部署

1. **构建镜像**（假设已有 Dockerfile）：
   ```bash
   docker build -t text2img .
   ```

2. **运行容器**（只需映射 8000 端口，后端同时托管前端）：
   ```bash
   docker run -d \
     -p 8000:8000 \
     --network host \
     text2img
   ```

3. **访问**：`http://{容器IP}:8000/`

**注意**：
- ComfyUI 需要单独部署，或通过 `--network host` 共享网络
- 前端页面由后端直接提供，无需额外端口映射

---

## ⚠️ 注意事项

### 1. workflow.json 格式

- **必须使用 API 格式**：在 ComfyUI 中通过 "Save (API)" 导出
- **结构要求**：顶层是 `{ "node_id": { "class_type": "...", "inputs": {...} } }`
- **节点识别**：正向 prompt 节点需满足：
  - `class_type == "CLIPTextEncode"`
  - `node_id == "6"` 或 `_meta.title` 含 "Positive Prompt"

### 2. 错误处理

- **workflow 未找到**：检查 `backend/z-image_base.json` 是否存在
- **CLIPTextEncode 节点未找到**：检查 workflow 结构和节点 ID
- **WebSocket 连接失败**：检查 ComfyUI 是否运行、端口是否正确、防火墙是否开放
- **图片未显示**：检查调试日志中的 `/history` 响应和图片 URL
- **结果区域未显示**：确认图片已成功生成并设置了 `src` 属性

---

## 📝 开发说明

### 修改 workflow

1. 在 ComfyUI UI 中修改工作流
2. 通过 "Save (API)" 导出新的 JSON
3. 替换 `backend/z-image_base.json`
4. 如果节点 ID 或结构变化，可能需要修改 `replace_prompt_in_workflow` 函数

### 添加新功能

- **后端**：在 `backend/main.py` 中添加新路由
- **前端**：在 `frontend/index.html` 的 `<script>` 中添加新函数

