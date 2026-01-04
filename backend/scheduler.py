from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import requests
import time
import json
import uuid
import copy
import asyncio
from pathlib import Path
from typing import Dict
import websockets

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 前端托管
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse(url="/static/index.html")

# Worker注册表
workers: Dict[str, dict] = {}

MAX_TASK_TIME = 120  # 任务最大执行时间（秒）
HEARTBEAT_TIMEOUT = 15  # 心跳超时时间（秒）

WORKFLOW_FILE = Path(__file__).parent / "z-image_base.json"
COMFYUI_API_URL = "http://127.0.0.1:8188"
COMFYUI_WS_URL = "ws://127.0.0.1:8188/ws"

class HeartbeatRequest(BaseModel):
    worker_id: str

class GenerateRequest(BaseModel):
    prompt: str

def load_workflow() -> dict:
    """读取workflow.json"""
    if not WORKFLOW_FILE.exists():
        raise FileNotFoundError(f"workflow.json不存在：{WORKFLOW_FILE}")
    with WORKFLOW_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)

def replace_prompt_in_workflow(workflow: dict, prompt: str) -> dict:
    """替换workflow中的prompt"""
    wf = copy.deepcopy(workflow)
    for node_id, node in wf.items():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") != "CLIPTextEncode":
            continue
        meta = node.get("_meta", {}) or {}
        title = meta.get("title", "") or ""
        if ("Positive Prompt" in title) or (str(node_id) == "6"):
            inputs = node.get("inputs")
            if isinstance(inputs, dict) and "text" in inputs:
                inputs["text"] = prompt
                return wf
    raise ValueError("未找到正向CLIPTextEncode节点")

def is_worker_available(worker_info: dict) -> bool:
    """判断Worker是否可用"""
    now = time.time()
    if now - worker_info.get('last_heartbeat', 0) > HEARTBEAT_TIMEOUT:
        return False
    if now <= worker_info.get('busy_until', 0):
        return False
    return True

def get_available_worker():
    """获取第一个可用的Worker"""
    for worker_id, worker_info in workers.items():
        if is_worker_available(worker_info):
            return (worker_id, worker_info)
    return None

@app.post("/heartbeat")
def heartbeat(req: HeartbeatRequest):
    """接收Worker心跳"""
    worker_id = req.worker_id
    now = time.time()
    
    if worker_id not in workers:
        # 如果worker_id是127.0.0.1或localhost，使用127.0.0.1访问
        # 否则使用worker_id（可能是本机IP或其他机器IP）
        if worker_id in ['127.0.0.1', 'localhost']:
            worker_url = "http://127.0.0.1:8001"
        else:
            worker_url = f"http://{worker_id}:8001"
        
        workers[worker_id] = {
            'last_heartbeat': now,
            'busy_until': 0,
            'url': worker_url
        }
    else:
        workers[worker_id]['last_heartbeat'] = now
    
    return {"status": "ok"}

@app.post("/generate")
def generate(req: GenerateRequest):
    """接收prompt，处理workflow，调度到Worker或直接调用ComfyUI"""
    # 读取并处理workflow
    try:
        workflow = load_workflow()
        modified_workflow = replace_prompt_in_workflow(workflow, req.prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    client_id = str(uuid.uuid4())
    
    # 如果有可用Worker，调度到Worker
    available_worker = get_available_worker()
    if available_worker:
        worker_id, worker_info = available_worker
        now = time.time()
        worker_info['busy_until'] = now + MAX_TASK_TIME
        
        try:
            worker_url = worker_info['url']
            payload = {
                "prompt": modified_workflow,
                "client_id": client_id
            }
            response = requests.post(f"{worker_url}/run", json=payload, timeout=5)
            response.raise_for_status()
            result = response.json()
            
            return {
                "worker_id": worker_id,
                "prompt_id": result.get("prompt_id"),
                "client_id": client_id
            }
        except Exception as e:
            worker_info['busy_until'] = 0
            raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")
    
    # 没有Worker，直接调用本机ComfyUI
    try:
        url = f"{COMFYUI_API_URL}/prompt"
        payload = {
            "prompt": modified_workflow,
            "client_id": client_id
        }
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise HTTPException(status_code=500, detail="ComfyUI 响应中未包含 prompt_id")
        
        return {
            "prompt_id": prompt_id,
            "client_id": client_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ComfyUI error: {str(e)}")

@app.get("/history/{prompt_id}")
def get_history(prompt_id: str):
    """转发到Worker或ComfyUI的/history接口"""
    available_worker = get_available_worker()
    if available_worker:
        worker_id, worker_info = available_worker
        worker_url = worker_info['url']
        try:
            response = requests.get(f"{worker_url}/history/{prompt_id}", timeout=5)
            response.raise_for_status()
            return JSONResponse(content=response.json())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # 没有Worker，直接调用本机ComfyUI
    url = f"{COMFYUI_API_URL}/history/{prompt_id}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ComfyUI error: {str(e)}")

@app.get("/image")
def get_image(filename: str, subfolder: str = "", type: str = "output"):
    """转发到Worker或ComfyUI的/image接口"""
    available_worker = get_available_worker()
    if available_worker:
        worker_id, worker_info = available_worker
        worker_url = worker_info['url']
        try:
            params = {"filename": filename, "subfolder": subfolder, "type": type}
            response = requests.get(f"{worker_url}/image", params=params, stream=True, timeout=5)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "image/png")
            return StreamingResponse(response.raw, media_type=content_type)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # 没有Worker，直接调用本机ComfyUI
    params = {"filename": filename, "subfolder": subfolder, "type": type}
    url = f"{COMFYUI_API_URL}/view"
    try:
        resp = requests.get(url, params=params, stream=True, timeout=5)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/png")
        return StreamingResponse(resp.raw, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ComfyUI error: {str(e)}")

@app.websocket("/ws")
async def websocket_proxy(websocket: WebSocket):
    """WebSocket代理，转发到ComfyUI"""
    await websocket.accept()
    
    query_params = dict(websocket.query_params)
    client_id = query_params.get("clientId", str(uuid.uuid4()))
    
    comfyui_ws_url = f"{COMFYUI_WS_URL}?clientId={client_id}"
    comfyui_ws = None
    
    try:
        comfyui_ws = await websockets.connect(comfyui_ws_url)
        
        async def forward_to_client():
            try:
                while True:
                    message = await comfyui_ws.recv()
                    await websocket.send_text(message)
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                print(f"转发到客户端错误: {e}")
        
        async def forward_to_comfyui():
            try:
                while True:
                    message = await websocket.receive_text()
                    await comfyui_ws.send(message)
            except WebSocketDisconnect:
                pass
            except Exception as e:
                print(f"转发到ComfyUI错误: {e}")
        
        await asyncio.gather(
            forward_to_client(),
            forward_to_comfyui(),
            return_exceptions=True
        )
    except Exception as e:
        print(f"WebSocket代理错误: {e}")
    finally:
        if comfyui_ws:
            try:
                await comfyui_ws.close()
            except:
                pass
        try:
            await websocket.close()
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
