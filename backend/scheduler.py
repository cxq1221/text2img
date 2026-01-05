from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import requests
import uuid
from pathlib import Path

try:
    from .worker_manager import WorkerManager
    from .workflow_handler import WorkflowHandler
    from .websocket_proxy import WebSocketProxy
except ImportError:
    from worker_manager import WorkerManager
    from workflow_handler import WorkflowHandler
    from websocket_proxy import WebSocketProxy

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

# 初始化组件
WORKFLOW_FILE = Path(__file__).parent / "z-image_base.json"

worker_manager = WorkerManager(max_task_time=120, heartbeat_timeout=15)
workflow_handler = WorkflowHandler(WORKFLOW_FILE)
ws_proxy = WebSocketProxy()

# 请求模型
class HeartbeatRequest(BaseModel):
    worker_id: str

class CompleteRequest(BaseModel):
    worker_id: str
    prompt_id: str

class GenerateRequest(BaseModel):
    prompt: str

@app.post("/heartbeat")
def heartbeat(req: HeartbeatRequest):
    """接收Worker心跳"""
    worker_info = worker_manager.register_worker(req.worker_id)
    return {"status": "ok"}

@app.post("/complete")
def complete(req: CompleteRequest):
    """接收Worker任务完成通知"""
    worker_manager.release_worker(req.worker_id, req.prompt_id)
    print(f"Worker {req.worker_id} 任务完成 (prompt_id={req.prompt_id})，已释放")
    return {"status": "ok"}

@app.post("/generate")
def generate(req: GenerateRequest):
    """接收prompt，处理workflow，调度到Worker"""
    # 读取并处理workflow
    try:
        workflow = workflow_handler.load()
        modified_workflow = workflow_handler.replace_prompt(workflow, req.prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    client_id = str(uuid.uuid4())
    
    # 使用锁确保调度操作的原子性
    with worker_manager.lock:
        available_worker = worker_manager.get_available_worker()
        if available_worker:
            worker_id, worker_info = available_worker
            if worker_manager.assign_task(worker_id):
                print(f"分配任务到Worker {worker_id}")
            else:
                worker_id = None
                worker_info = None
        else:
            worker_id = None
            worker_info = None
    
    if worker_id and worker_info:
        try:
            worker_url = worker_info['url']
            payload = {
                "prompt": modified_workflow,
                "client_id": client_id
            }
            response = requests.post(f"{worker_url}/run", json=payload, timeout=5)
            response.raise_for_status()
            result = response.json()
            prompt_id = result.get("prompt_id")
            
            # 记录prompt_id到worker_id的映射
            if prompt_id:
                worker_manager.map_prompt_to_worker(prompt_id, worker_id)
            
            print(f"Worker {worker_id} 任务提交成功, prompt_id={prompt_id}")
            return {
                "worker_id": worker_id,
                "prompt_id": prompt_id,
                "client_id": client_id
            }
        except Exception as e:
            worker_manager.release_worker(worker_id)
            print(f"Worker {worker_id} 任务失败，释放Worker: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")
    
    # 没有可用Worker
    raise HTTPException(status_code=503, detail="当前没有空闲机器，请稍后再试")

@app.get("/history/{prompt_id}")
def get_history(prompt_id: str):
    """转发到Worker的/history接口"""
    worker_id = worker_manager.get_worker_by_prompt(prompt_id)
    if not worker_id or worker_id not in worker_manager.workers:
        raise HTTPException(status_code=404, detail="未找到对应的Worker")
    
    worker_info = worker_manager.workers[worker_id]
    worker_url = worker_info['url']
    try:
        response = requests.get(f"{worker_url}/history/{prompt_id}", timeout=5)
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")

@app.get("/image")
def get_image(filename: str, subfolder: str = "", type: str = "output", prompt_id: str = ""):
    """转发到Worker的/image接口"""
    worker_id = None
    if prompt_id:
        worker_id = worker_manager.get_worker_by_prompt(prompt_id)
    
    if not worker_id or worker_id not in worker_manager.workers:
        raise HTTPException(status_code=404, detail="未找到对应的Worker")
    
    worker_info = worker_manager.workers[worker_id]
    worker_url = worker_info['url']
    try:
        params = {"filename": filename, "subfolder": subfolder, "type": type}
        response = requests.get(f"{worker_url}/image", params=params, stream=True, timeout=5)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "image/png")
        return StreamingResponse(response.raw, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")

@app.websocket("/ws")
async def websocket_proxy(websocket: WebSocket):
    """WebSocket代理，转发到Worker的ComfyUI"""
    query_params = dict(websocket.query_params)
    client_id = query_params.get("clientId", str(uuid.uuid4()))
    prompt_id = query_params.get("promptId", "")
    
    # 根据prompt_id找到对应的worker_id
    worker_id = None
    if prompt_id:
        worker_id = worker_manager.get_worker_by_prompt(prompt_id)
    
    print(f"WebSocket代理: prompt_id={prompt_id}, worker_id={worker_id}")
    await ws_proxy.proxy(websocket, client_id, worker_id, worker_manager.workers)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
