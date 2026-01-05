import time
import threading
from typing import Dict, Optional, Tuple

class WorkerManager:
    """Worker管理器，负责Worker的注册、心跳、状态管理"""
    
    def __init__(self, max_task_time: int = 120, heartbeat_timeout: int = 15):
        self.workers: Dict[str, dict] = {}
        self.prompt_to_worker: Dict[str, str] = {}
        self.prompt_cleanup_time: Dict[str, float] = {}  # 记录prompt_id的清理时间
        self.lock = threading.Lock()
        self.max_task_time = max_task_time
        self.heartbeat_timeout = heartbeat_timeout
    
    def register_worker(self, worker_id: str) -> dict:
        """注册Worker或更新心跳"""
        now = time.time()
        
        if worker_id not in self.workers:
            # 构建Worker URL
            if worker_id in ['127.0.0.1', 'localhost']:
                worker_url = "http://127.0.0.1:8001"
            else:
                worker_url = f"http://{worker_id}:8001"
            
            self.workers[worker_id] = {
                'last_heartbeat': now,
                'busy': False,
                'busy_until': 0,
                'url': worker_url
            }
        else:
            self.workers[worker_id]['last_heartbeat'] = now
            # 如果busy_until已过期，自动重置busy状态
            if now > self.workers[worker_id].get('busy_until', 0):
                self.workers[worker_id]['busy'] = False
        
        return self.workers[worker_id]
    
    def is_worker_available(self, worker_info: dict) -> bool:
        """判断Worker是否可用"""
        now = time.time()
        last_heartbeat = worker_info.get('last_heartbeat', 0)
        busy = worker_info.get('busy', False)
        busy_until = worker_info.get('busy_until', 0)
        
        # 心跳超时
        if now - last_heartbeat > self.heartbeat_timeout:
            return False
        # 如果标记为busy，直接返回False
        if busy:
            return False
        # 任务超时（双重保护）
        if now <= busy_until:
            return False
        return True
    
    def get_available_worker(self) -> Optional[Tuple[str, dict]]:
        """获取第一个可用的Worker"""
        for worker_id, worker_info in self.workers.items():
            if self.is_worker_available(worker_info):
                return (worker_id, worker_info)
        return None
    
    def assign_task(self, worker_id: str) -> bool:
        """分配任务到Worker（需要先获取锁）"""
        if worker_id not in self.workers:
            return False
        
        worker_info = self.workers[worker_id]
        if not self.is_worker_available(worker_info):
            return False
        
        now = time.time()
        worker_info['busy'] = True
        worker_info['busy_until'] = now + self.max_task_time
        return True
    
    def release_worker(self, worker_id: str, prompt_id: Optional[str] = None):
        """释放Worker"""
        if worker_id not in self.workers:
            return
        
        worker_info = self.workers[worker_id]
        worker_info['busy'] = False
        worker_info['busy_until'] = 0
        
        # 延迟清理prompt_id映射（30秒后清理，确保前端有足够时间获取图片）
        if prompt_id and prompt_id in self.prompt_to_worker:
            self.prompt_cleanup_time[prompt_id] = time.time() + 30
            # 启动清理线程
            def cleanup_later():
                time.sleep(30)
                if prompt_id in self.prompt_cleanup_time:
                    cleanup_time = self.prompt_cleanup_time.get(prompt_id, 0)
                    if time.time() >= cleanup_time:
                        if prompt_id in self.prompt_to_worker:
                            del self.prompt_to_worker[prompt_id]
                        if prompt_id in self.prompt_cleanup_time:
                            del self.prompt_cleanup_time[prompt_id]
            
            cleanup_thread = threading.Thread(target=cleanup_later, daemon=True)
            cleanup_thread.start()
    
    def map_prompt_to_worker(self, prompt_id: str, worker_id: str):
        """记录prompt_id到worker_id的映射"""
        self.prompt_to_worker[prompt_id] = worker_id
    
    def get_worker_by_prompt(self, prompt_id: str) -> Optional[str]:
        """根据prompt_id获取worker_id"""
        return self.prompt_to_worker.get(prompt_id)
    
    def has_workers(self) -> bool:
        """检查是否有Worker注册"""
        return len(self.workers) > 0

