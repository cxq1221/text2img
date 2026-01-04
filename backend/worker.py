from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import requests
import time
import threading
import socket

app = FastAPI()

SCHEDULER_URL = "http://localhost:8000"  # 调度中心地址
HEARTBEAT_INTERVAL = 5  # 心跳间隔（秒）
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

@app.post("/run")
def run(payload: dict):
    """接收任务，转发到ComfyUI"""
    try:
        response = requests.post(COMFYUI_URL, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

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
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

