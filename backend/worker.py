from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import requests
import time
import threading
import socket
import shutil
from pathlib import Path
from typing import Dict, Optional

app = FastAPI()

SCHEDULER_URL = "http://10.118.237.7:8000"  # 调度中心地址
HEARTBEAT_INTERVAL = 10  # 心跳间隔（秒）
COMFYUI_URL = "http://127.0.0.1:8188/prompt"
COMFYUI_BASE = "http://127.0.0.1:8188"

# 获取本机IP作为worker_id
def get_worker_id():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

worker_id = get_worker_id()

# 任务状态管理：prompt_id -> {status, progress, image_url, error}
task_status: Dict[str, dict] = {}

# 图片存储目录
IMAGES_DIR = Path(__file__).parent.parent / "images"
IMAGES_DIR.mkdir(exist_ok=True)

# 静态文件服务：提供图片访问
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")

def send_heartbeat():
    """定期发送心跳"""
    while True:
        try:
            requests.post(
                f"{SCHEDULER_URL}/heartbeat",
                json={"worker_id": worker_id},
                timeout=2
            )
        except Exception:
            pass  # 静默失败，继续重试
        time.sleep(HEARTBEAT_INTERVAL)

def check_task_complete():
    """定期检查任务状态和进度"""
    while True:
        # 检查所有正在执行的任务
        for prompt_id in list(task_status.keys()):
            status_info = task_status.get(prompt_id)
            if not status_info:
                continue
            
            if status_info.get("status") in ["completed", "failed"]:
                continue  # 已完成的任务跳过
            
            try:
                # 获取任务历史
                response = requests.get(f"{COMFYUI_BASE}/history/{prompt_id}", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if prompt_id in data:
                        task_info = data[prompt_id]
                        status = task_info.get("status", {})
                        
                        # 更新进度信息
                        queue_remaining = status.get("queue_remaining", 0)
                        if queue_remaining == 0:
                            # 任务正在执行或已完成
                            if status.get("completed", False):
                                # 如果已经完成过，跳过
                                if task_status[prompt_id].get("status") == "completed":
                                    continue
                                
                                # 任务完成，获取图片信息
                                outputs = task_info.get("outputs", {})
                                image_url = None
                                
                                # 查找图片输出
                                for node_id, output in outputs.items():
                                    if output and "images" in output:
                                        images = output["images"]
                                        if images and len(images) > 0:
                                            img_info = images[0]
                                            filename = img_info.get("filename")
                                            subfolder = img_info.get("subfolder", "")
                                            img_type = img_info.get("type", "output")
                                            
                                            if filename:
                                                # 从ComfyUI获取图片并保存到本地
                                                try:
                                                    img_params = {
                                                        "filename": filename,
                                                        "subfolder": subfolder,
                                                        "type": img_type
                                                    }
                                                    img_response = requests.get(
                                                        f"{COMFYUI_BASE}/view",
                                                        params=img_params,
                                                        stream=True,
                                                        timeout=10
                                                    )
                                                    if img_response.status_code == 200:
                                                        # 保存图片到本地
                                                        local_filename = f"{prompt_id}_{filename}"
                                                        local_path = IMAGES_DIR / local_filename
                                                        with open(local_path, "wb") as f:
                                                            shutil.copyfileobj(img_response.raw, f)
                                                        
                                                        # 生成可访问的URL
                                                        image_url = f"http://{worker_id}:8001/images/{local_filename}"
                                                        print(f"图片已保存: {local_path}, URL: {image_url}")
                                                except Exception as e:
                                                    print(f"保存图片失败: {e}")
                                                
                                                break
                                
                                # 更新任务状态为完成
                                task_status[prompt_id] = {
                                    "status": "completed",
                                    "progress": {"value": 100, "max": 100},
                                    "image_url": image_url,
                                    "completed_at": time.time()
                                }
                                
                                # 通知scheduler
                                try:
                                    requests.post(
                                        f"{SCHEDULER_URL}/complete",
                                        json={
                                            "worker_id": worker_id,
                                            "prompt_id": prompt_id
                                        },
                                        timeout=2
                                    )
                                    print(f"任务完成，已通知scheduler: prompt_id={prompt_id}")
                                except Exception as e:
                                    print(f"通知scheduler失败: {e}")
                            else:
                                # 任务执行中，更新状态
                                task_status[prompt_id]["status"] = "running"
                        else:
                            # 任务在队列中
                            task_status[prompt_id]["status"] = "pending"
                            task_status[prompt_id]["progress"] = {"value": 0, "max": 100}
            except Exception as e:
                # 检查失败，标记为错误
                task_status[prompt_id] = {
                    "status": "failed",
                    "error": str(e),
                    "failed_at": time.time()
                }
        
        time.sleep(2)  # 每2秒检查一次

@app.post("/run")
def run(payload: dict):
    """接收任务，转发到ComfyUI"""
    try:
        print(f"Worker收到任务，转发到ComfyUI: {COMFYUI_URL}")
        response = requests.post(COMFYUI_URL, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"ComfyUI返回结果: {result}")
        # 检查是否有错误
        if "error" in result:
            raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
        
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            print(f"警告: ComfyUI返回结果中没有prompt_id: {result}")
            raise HTTPException(status_code=500, detail="ComfyUI未返回prompt_id")
        
        # 初始化任务状态
        task_status[prompt_id] = {
            "status": "pending",
            "progress": {"value": 0, "max": 100},
            "image_url": None,
            "created_at": time.time()
        }
        
        print(f"开始执行任务: prompt_id={prompt_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"Worker转发任务失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"ComfyUI error: {str(e)}")

@app.get("/status/{prompt_id}")
def get_status(prompt_id: str):
    """获取任务状态和进度"""
    if prompt_id not in task_status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    status_info = task_status[prompt_id].copy()
    return status_info

@app.get("/result/{prompt_id}")
def get_result(prompt_id: str):
    """获取任务结果（包含图片URL）"""
    if prompt_id not in task_status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    status_info = task_status[prompt_id]
    
    if status_info.get("status") != "completed":
        raise HTTPException(status_code=400, detail=f"任务尚未完成，当前状态: {status_info.get('status')}")
    
    return {
        "status": "completed",
        "image_url": status_info.get("image_url"),
        "completed_at": status_info.get("completed_at")
    }

if __name__ == "__main__":
    # 启动心跳线程
    heartbeat_thread = threading.Thread(target=send_heartbeat, daemon=True)
    heartbeat_thread.start()
    
    # 启动任务完成检查线程
    check_thread = threading.Thread(target=check_task_complete, daemon=True)
    check_thread.start()
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

