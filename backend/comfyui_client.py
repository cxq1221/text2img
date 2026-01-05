import requests
from typing import Dict, Optional

class ComfyUIClient:
    """ComfyUI客户端，封装对ComfyUI的调用"""
    
    def __init__(self, api_url: str = "http://127.0.0.1:8188"):
        self.api_url = api_url
    
    def submit_prompt(self, workflow: dict, client_id: str, timeout: int = 10) -> str:
        """提交workflow到ComfyUI，返回prompt_id"""
        url = f"{self.api_url}/prompt"
        payload = {
            "prompt": workflow,
            "client_id": client_id
        }
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ValueError("ComfyUI 响应中未包含 prompt_id")
        return prompt_id
    
    def get_history(self, prompt_id: str, timeout: int = 5) -> dict:
        """获取任务历史记录"""
        url = f"{self.api_url}/history/{prompt_id}"
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    
    def get_image(self, filename: str, subfolder: str = "", type: str = "output", timeout: int = 5):
        """获取图片（返回响应对象，用于流式传输）"""
        params = {"filename": filename, "subfolder": subfolder, "type": type}
        url = f"{self.api_url}/view"
        resp = requests.get(url, params=params, stream=True, timeout=timeout)
        resp.raise_for_status()
        return resp

