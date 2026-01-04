from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import requests
import time
import threading
import socket

app = FastAPI()

SCHEDULER_URL = "http://localhost:8000"  # 调度中心地址
HEARTBEAT_INTERVAL = 10  # 心跳间隔（秒）
COMFYUI_URL = "http://127.0.0.1:8188/prompt"

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

# 记录当前执行的任务
current_prompt_id = None

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
    """定期检查任务是否完成"""
    global current_prompt_id
    while True:
        if current_prompt_id:
            try:
                # 检查任务状态
                response = requests.get(f"http://127.0.0.1:8188/history/{current_prompt_id}", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if current_prompt_id in data:
                        task_info = data[current_prompt_id]
                        status = task_info.get("status", {})
                        # 检查任务是否完成
                        if status.get("completed", False):
                            # 任务完成，通知scheduler
                            try:
                                requests.post(
                                    f"{SCHEDULER_URL}/complete",
                                    json={
                                        "worker_id": worker_id,
                                        "prompt_id": current_prompt_id
                                    },
                                    timeout=2
                                )
                                print(f"任务完成，已通知scheduler: prompt_id={current_prompt_id}")
                            except Exception as e:
                                print(f"通知scheduler失败: {e}")
                            current_prompt_id = None
            except Exception as e:
                pass  # 静默失败，继续检查
        time.sleep(2)  # 每5秒检查一次

@app.post("/run")
def run(payload: dict):
    """接收任务，转发到ComfyUI"""
    global current_prompt_id
    try:
        print(f"Worker收到任务，转发到ComfyUI: {COMFYUI_URL}")
        response = requests.post(COMFYUI_URL, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"ComfyUI返回结果: {result}")
        # 检查是否有错误
        if "error" in result:
            raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
        if "prompt_id" not in result:
            print(f"警告: ComfyUI返回结果中没有prompt_id: {result}")
        else:
            # 记录当前执行的prompt_id
            current_prompt_id = result.get("prompt_id")
            print(f"开始执行任务: prompt_id={current_prompt_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"Worker转发任务失败: {str(e)}")
        current_prompt_id = None
        raise HTTPException(status_code=500, detail=f"ComfyUI error: {str(e)}")

@app.get("/history/{prompt_id}")
def get_history(prompt_id: str):
    """转发到ComfyUI的/history接口"""
    try:
        response = requests.get(f"http://127.0.0.1:8188/history/{prompt_id}", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

@app.get("/image")
def get_image(filename: str, subfolder: str = "", type: str = "output"):
    """转发到ComfyUI的/image接口"""
    try:
        params = {"filename": filename, "subfolder": subfolder, "type": type}
        response = requests.get("http://127.0.0.1:8188/view", params=params, stream=True, timeout=5)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "image/png")
        return StreamingResponse(response.raw, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # 启动心跳线程
    heartbeat_thread = threading.Thread(target=send_heartbeat, daemon=True)
    heartbeat_thread.start()
    
    # 启动任务完成检查线程
    check_thread = threading.Thread(target=check_task_complete, daemon=True)
    check_thread.start()
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

