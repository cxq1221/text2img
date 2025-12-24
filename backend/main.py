import json
import uuid
import copy
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# =====================
# 配置区域（按需修改）
# =====================

# ComfyUI 的 HTTP 接口地址（默认本机 8188）
COMFYUI_API_URL = "http://127.0.0.1:8188"

# 使用的 ComfyUI workflow 文件路径（相对本文件）
# 你已经提供了 z-image_base.json，这里直接使用它
WORKFLOW_FILE = Path(__file__).parent / "z-image_base.json"


# =====================
# FastAPI 基础设置
# =====================

app = FastAPI(title="Text2Img Demo Backend")

# 简单允许所有来源跨域，方便前端 Demo 直接访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 教程 Demo，不做安全限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------
# 静态前端托管
# ---------------------

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if FRONTEND_DIR.exists():
    # 将 frontend 目录挂载为静态资源，直接由后端托管前端页面
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    """
    重定向根路径到前端首页。
    访问 http://host:8000/ 时直接看到前端页面。
    """
    # 如果使用 StaticFiles(html=True) 也可以直接返回 index.html，
    # 这里用一个简单的重定向到 /static/index.html。
    return RedirectResponse(url="/static/index.html")


# =====================
# 请求 / 响应 模型
# =====================


class GenerateRequest(BaseModel):
    prompt: str  # 前端只传最小参数：prompt 文本


class GenerateResponse(BaseModel):
    prompt_id: str
    client_id: str


# =====================
# 工具函数
# =====================


def load_workflow() -> dict:
    """读取 workflow.json 并返回为 Python dict。"""
    if not WORKFLOW_FILE.exists():
        raise FileNotFoundError(f"workflow.json 不存在：{WORKFLOW_FILE}")
    with WORKFLOW_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def replace_prompt_in_workflow(workflow: dict, prompt: str) -> dict:
    """
    在 workflow 中找到「正向」CLIPTextEncode 节点，替换其文本为新的 prompt。
    使用 deepcopy，避免修改原始 workflow。

    ⚠️ 说明：这里针对「导出 API」后的 z-image_base.json 结构做适配：
        - 顶层结构是一个 dict：
          {
            "3": { "class_type": "KSampler", "inputs": {...} },
            "6": { "class_type": "CLIPTextEncode", "inputs": { "text": "...", "clip": [...] }, "_meta": {...} },
            "7": { "class_type": "CLIPTextEncode", "inputs": { "text": "...", "clip": [...] }, "_meta": {...} },
            ...
          }
        - 正向 prompt：key 为 "6"，class_type 为 "CLIPTextEncode"，_meta.title 含 "Positive Prompt"
        - 负向 prompt：key 为 "7"，_meta.title 含 "Negative Prompt"
    """
    wf = copy.deepcopy(workflow)

    clip_positive_found = False

    # 顶层就是 { node_id(str): node_dict }
    for node_id, node in wf.items():
        if not isinstance(node, dict):
            continue

        # 只操作 CLIPTextEncode 节点
        if node.get("class_type") != "CLIPTextEncode":
            continue

        meta = node.get("_meta", {}) or {}
        title = meta.get("title", "") or ""

        # 只改「正向」Prompt：
        # - _meta.title 包含 "Positive Prompt"
        #   或
        # - node_id == "6"（根据当前 z-image_base.json）
        if ("Positive Prompt" in title) or (str(node_id) == "6"):
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                raise ValueError("CLIPTextEncode 正向节点的 inputs 结构异常。")

            if "text" not in inputs:
                raise ValueError("CLIPTextEncode 正向节点的 inputs 中缺少 text 字段。")

            inputs["text"] = prompt
            clip_positive_found = True

    if not clip_positive_found:
        # 教学目的：给出明确提示，方便你检查 workflow 结构/节点 id
        raise ValueError(
            "在 workflow 中没有找到正向 CLIPTextEncode 节点（node_id='6' 或 _meta.title 含 Positive Prompt）。"
        )

    return wf


def send_prompt_to_comfyui(prompt_data: dict, client_id: str) -> str:
    """
    调用 ComfyUI 的 /prompt 接口。
    返回 ComfyUI 生成的 prompt_id。
    """
    url = f"{COMFYUI_API_URL}/prompt"
    payload = {
        "prompt": prompt_data,
        "client_id": client_id,
    }

    try:
        resp = requests.post(url, json=payload)
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"请求 ComfyUI /prompt 失败: {e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"ComfyUI /prompt 返回错误: {resp.text}",
        )

    data = resp.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise HTTPException(status_code=500, detail="ComfyUI 响应中未包含 prompt_id")

    return prompt_id


# =====================
# 路由：POST /generate
# =====================


@app.post("/generate", response_model=GenerateResponse)
def generate_image(req: GenerateRequest):
    """
    教程级文生图接口：
    1. 读取 workflow.json
    2. deepcopy 一份
    3. 替换 CLIPTextEncode 文本节点中的 prompt
    4. 生成 client_id
    5. 调用 ComfyUI /prompt
    6. 返回 prompt_id 和 client_id
    """

    # 1. 读取 workflow.json
    try:
        workflow = load_workflow()
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"workflow.json 解析失败: {e}")

    # 2 & 3. deepcopy + 替换 CLIPTextEncode 的 text
    try:
        modified_workflow = replace_prompt_in_workflow(workflow, req.prompt)
    except ValueError as e:
        # 比如没找到 CLIPTextEncode
        raise HTTPException(status_code=500, detail=str(e))

    # 4. 生成 client_id（用 UUID 即可）
    client_id = str(uuid.uuid4())

    # 5. 调用 ComfyUI /prompt
    prompt_id = send_prompt_to_comfyui(modified_workflow, client_id)

    # 6. 返回 prompt_id 和 client_id（前端会用它们去连 WebSocket 和获取 /history）
    return GenerateResponse(prompt_id=prompt_id, client_id=client_id)


# ===========================
# 额外路由：代理 ComfyUI 接口
# ===========================


@app.get("/history/{prompt_id}")
def get_history(prompt_id: str):
    """
    简单转发到 ComfyUI 的 /history/{prompt_id}，解决浏览器直接请求 8188 的 CORS 问题。
    前端只需要请求后端 8000 端口。
    """
    url = f"{COMFYUI_API_URL}/history/{prompt_id}"
    try:
        resp = requests.get(url)
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"请求 ComfyUI /history 失败: {e}")

    # 直接把 ComfyUI 的 JSON 内容返回出去
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@app.get("/image")
def get_image(filename: str, subfolder: str = "", type: str = "output"):
    """
    简单转发到 ComfyUI 的 /view 接口，返回图片二进制。
    通过后端中转避免前端跨域。
    """
    params = {
        "filename": filename,
        "subfolder": subfolder,
        "type": type,
    }
    url = f"{COMFYUI_API_URL}/view"

    try:
        resp = requests.get(url, params=params, stream=True)
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"请求 ComfyUI /view 失败: {e}")

    if resp.status_code != 200:
        # 把错误文本直接抛给前端
        text = resp.text
        raise HTTPException(status_code=resp.status_code, detail=f"ComfyUI /view 返回错误: {text}")

    # 使用 StreamingResponse 把图片流转发给前端
    content_type = resp.headers.get("Content-Type", "image/png")
    return StreamingResponse(resp.raw, media_type=content_type)


# =====================
# 启动说明（仅注释）
# =====================
# 在项目根目录 text2img-demo/ 下运行：
#   pip install -r requirements.txt
#   uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
#
# 然后你可以通过：
#   POST http://127.0.0.1:8000/generate
#   Body: { "prompt": "a cute cat" }
# 来测试。


