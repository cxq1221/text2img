from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
import requests
import uuid
from pathlib import Path

try:
    from .worker_manager import WorkerManager
    from .workflow_handler import WorkflowHandler
except ImportError:
    from worker_manager import WorkerManager
    from workflow_handler import WorkflowHandler

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 前端托管（生产环境建议先在 frontend 目录执行 `npm run build`）
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"
if FRONTEND_DIR.exists():
    # html=True 使得直接访问目录时返回 index.html，便于前端路由
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")

@app.get("/", include_in_schema=False)
def index():
    """
    根路径重定向到前端静态资源。
    访问 http://host:8000/ 即可打开打包后的前端。
    """
    if FRONTEND_DIR.exists():
        return RedirectResponse(url="/static")
    # 如果还没构建前端，给出简单提示
    return JSONResponse(
        status_code=200,
        content={"message": "前端尚未构建，请在 frontend 目录执行 `npm run build` 后重试。"},
    )

# 初始化组件
WORKFLOW_FILE = Path(__file__).parent / "z-image_base.json"

worker_manager = WorkerManager(max_task_time=120, heartbeat_timeout=15)
workflow_handler = WorkflowHandler(WORKFLOW_FILE)

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
                "worker_url": worker_url,
                "prompt_id": prompt_id,
                "client_id": client_id
            }
        except Exception as e:
            worker_manager.release_worker(worker_id)
            print(f"Worker {worker_id} 任务失败，释放Worker: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")
    
    # 没有可用Worker
    raise HTTPException(status_code=503, detail="当前没有空闲机器，请稍后再试")

@app.get("/status/{prompt_id}")
def get_status(prompt_id: str):
    """获取任务状态和进度（转发到Worker）"""
    worker_id = worker_manager.get_worker_by_prompt(prompt_id)
    if not worker_id or worker_id not in worker_manager.workers:
        raise HTTPException(status_code=404, detail="未找到对应的Worker")
    
    worker_info = worker_manager.workers[worker_id]
    worker_url = worker_info['url']
    try:
        response = requests.get(f"{worker_url}/status/{prompt_id}", timeout=5)
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="任务不存在")
        raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")

@app.get("/result/{prompt_id}")
def get_result(prompt_id: str):
    """获取任务结果（转发到Worker）"""
    worker_id = worker_manager.get_worker_by_prompt(prompt_id)
    if not worker_id or worker_id not in worker_manager.workers:
        raise HTTPException(status_code=404, detail="未找到对应的Worker")
    
    worker_info = worker_manager.workers[worker_id]
    worker_url = worker_info['url']
    try:
        response = requests.get(f"{worker_url}/result/{prompt_id}", timeout=5)
        response.raise_for_status()
        return JSONResponse(content=response.json())
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="任务不存在")
        if e.response.status_code == 400:
            # Worker返回400表示任务未完成，返回状态信息
            try:
                status_response = requests.get(f"{worker_url}/status/{prompt_id}", timeout=5)
                if status_response.status_code == 200:
                    return JSONResponse(content=status_response.json())
            except:
                pass
            raise HTTPException(status_code=400, detail="任务尚未完成")
        raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Worker error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
