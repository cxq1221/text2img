from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import requests
import time
import threading
import socket
import shutil
import websockets
import asyncio
import json
import uuid
from pathlib import Path
from typing import Dict, Optional

app = FastAPI()

SCHEDULER_URL = "http://10.118.237.7:8000"  # 调度中心地址
HEARTBEAT_INTERVAL = 10  # 心跳间隔（秒）
COMFYUI_URL = "http://127.0.0.1:8188/prompt"
COMFYUI_BASE = "http://127.0.0.1:8188"
COMFYUI_WS_URL = "ws://127.0.0.1:8188/ws"

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

# 任务状态管理：prompt_id -> {status, progress, image_url, error, current_node, message}
task_status: Dict[str, dict] = {}

# 全局 WebSocket 连接
global_ws_client_id = str(uuid.uuid4())
global_ws_task = None
global_ws_running = False

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

async def listen_comfyui_progress():
    """监听 ComfyUI WebSocket 获取所有任务的详细进度（全局连接）"""
    global global_ws_running
    
    ws_url = f"{COMFYUI_WS_URL}?clientId={global_ws_client_id}"
    
    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                print(f"已连接 ComfyUI WebSocket (全局连接), client_id={global_ws_client_id}")
                global_ws_running = True
                
                while True:
                    try:
                        message = await websocket.recv()
                        data = json.loads(message)
                        
                        msg_type = data.get("type")
                        msg_data = data.get("data", {})
                        
                        # 根据消息类型提取 prompt_id
                        prompt_id = None
                        if msg_type in ["execution_start", "execution_complete", "execution_success", "execution_cached", "execution_error"]:
                            # 这些消息类型直接包含 prompt_id
                            prompt_id = msg_data.get("prompt_id")
                            if prompt_id:
                                print(f"[WebSocket] 收到 {msg_type} 消息, prompt_id={prompt_id}")
                        elif msg_type in ["progress", "executing"]:
                            # progress 和 executing 消息可能没有 prompt_id，需要从当前执行的任务推断
                            # 查找状态为 running 或 pending 的任务（通常只有一个）
                            for pid, status_info in task_status.items():
                                if status_info.get("status") in ["running", "pending"]:
                                    prompt_id = pid
                                    break
                        
                        if msg_type == "progress":
                            # 进度更新
                            progress_data = msg_data
                            value = progress_data.get("value", 0)
                            max_value = progress_data.get("max", 100)
                            
                            if prompt_id and prompt_id in task_status:
                                task_status[prompt_id]["progress"] = {
                                    "value": value,
                                    "max": max_value
                                }
                                task_status[prompt_id]["status"] = "running"
                        
                        elif msg_type == "executing":
                            # 节点执行状态
                            node = msg_data.get("node")
                            
                            if prompt_id and prompt_id in task_status:
                                if node is None:
                                    # 节点执行完成
                                    task_status[prompt_id]["current_node"] = None
                                else:
                                    # 正在执行某个节点
                                    task_status[prompt_id]["current_node"] = str(node)
                                    task_status[prompt_id]["status"] = "running"
                        
                        elif msg_type == "execution_start":
                            # 执行开始
                            if prompt_id and prompt_id in task_status:
                                task_status[prompt_id]["status"] = "running"
                                task_status[prompt_id]["message"] = "执行开始"
                        
                        elif msg_type == "execution_cached":
                            # 使用缓存
                            if prompt_id and prompt_id in task_status:
                                task_status[prompt_id]["message"] = "使用缓存节点"
                        
                        elif msg_type in ["execution_complete", "execution_success"]:
                            # 执行完成
                            if prompt_id and prompt_id in task_status:
                                task_status[prompt_id]["status"] = "completed"
                                task_status[prompt_id]["progress"] = {"value": 100, "max": 100}
                                task_status[prompt_id]["message"] = "执行完成"
                                
                                # 获取图片
                                await fetch_and_save_image(prompt_id)
                                
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
                        
                        elif msg_type == "execution_error":
                            # 执行错误
                            error_msg = msg_data.get("error", "未知错误")
                            
                            if prompt_id and prompt_id in task_status:
                                task_status[prompt_id]["status"] = "failed"
                                task_status[prompt_id]["error"] = error_msg
                                task_status[prompt_id]["failed_at"] = time.time()
                    
                    except websockets.exceptions.ConnectionClosed:
                        print(f"WebSocket 连接已关闭，5秒后重连...")
                        global_ws_running = False
                        await asyncio.sleep(5)  # 等待5秒后重连
                        break
                    except Exception as e:
                        print(f"处理 WebSocket 消息失败: {e}")
                        continue
        
        except Exception as e:
            print(f"WebSocket 连接失败，5秒后重连: {e}")
            global_ws_running = False
            await asyncio.sleep(5)  # 等待5秒后重连

async def fetch_and_save_image(prompt_id: str):
    """获取并保存图片"""
    try:
        # 获取任务历史
        response = requests.get(f"{COMFYUI_BASE}/history/{prompt_id}", timeout=5)
        if response.status_code != 200:
            return
        
        data = response.json()
        if prompt_id not in data:
            return
        
        task_info = data[prompt_id]
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
        
        # 更新任务状态
        if prompt_id in task_status:
            task_status[prompt_id]["image_url"] = image_url
            task_status[prompt_id]["completed_at"] = time.time()
    
    except Exception as e:
        print(f"获取图片失败: {e}")

def start_global_websocket_listener():
    """启动全局 WebSocket 监听线程（启动时调用一次）"""
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(listen_comfyui_progress())
        loop.close()
    
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread

@app.post("/run")
def run(payload: dict):
    """接收任务，转发到ComfyUI"""
    try:
        print(f"Worker收到任务，转发到ComfyUI: {COMFYUI_URL}")
        
        # 使用全局 WebSocket 的 client_id，确保能收到消息
        payload["client_id"] = global_ws_client_id
        print(f"使用全局 WebSocket client_id: {global_ws_client_id}")
        
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
            "current_node": None,
            "message": "任务已提交，等待执行",
            "created_at": time.time()
        }
        
        print(f"开始执行任务: prompt_id={prompt_id}, 使用全局WebSocket client_id={global_ws_client_id}")
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
    # 启动全局 WebSocket 监听（启动时建立连接，一直保持）
    global_ws_task = start_global_websocket_listener()
    print("已启动全局 WebSocket 监听线程")
    
    # 启动心跳线程
    heartbeat_thread = threading.Thread(target=send_heartbeat, daemon=True)
    heartbeat_thread.start()
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

