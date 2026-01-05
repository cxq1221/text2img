import asyncio
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from typing import Optional

class WebSocketProxy:
    """WebSocket代理，转发到Worker的ComfyUI"""
    
    def __init__(self):
        pass
    
    def get_worker_ws_url(self, worker_id: str, client_id: str) -> str:
        """获取Worker的WebSocket URL"""
        worker_ip = worker_id if worker_id not in ['127.0.0.1', 'localhost'] else '127.0.0.1'
        return f"ws://{worker_ip}:8188/ws?clientId={client_id}"
    
    async def proxy(self, websocket: WebSocket, client_id: str, 
                   worker_id: Optional[str] = None, workers: Optional[dict] = None):
        """代理WebSocket连接"""
        await websocket.accept()
        
        # 必须有worker_id才能代理
        if not worker_id or not workers or worker_id not in workers:
            await websocket.close(code=1008, reason="未找到对应的Worker")
            return
        
        comfyui_ws_url = self.get_worker_ws_url(worker_id, client_id)
        
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

