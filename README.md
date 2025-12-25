## 📋 项目概述

这是一个**教程级文生图应用**项目，用于演示如何通过 FastAPI 后端和原生 HTML/JavaScript 前端，与 ComfyUI 进行集成，实现文本生成图片的完整流程。
## 🚀 使用说明
### 前置条件

1. **ComfyUI 已安装并运行**（默认端口 8188）
2. **Python 3.x 环境**
3. **已准备好 workflow.json**（API 格式，放在 `backend/` 目录,本代码已集成）

### 安装步骤

1. **安装 Python 依赖**：
   ```bash
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


详细架构说明可参考 ./ARCHITECTURE.md