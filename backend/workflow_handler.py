import json
import copy
import random
from pathlib import Path
from typing import Dict

class WorkflowHandler:
    """Workflow处理器，负责读取和修改workflow"""
    
    def __init__(self, workflow_file: Path):
        self.workflow_file = workflow_file
    
    def load(self) -> dict:
        """读取workflow.json"""
        if not self.workflow_file.exists():
            raise FileNotFoundError(f"workflow.json不存在：{self.workflow_file}")
        with self.workflow_file.open("r", encoding="utf-8") as f:
            return json.load(f)
    
    def replace_prompt(self, workflow: dict, prompt: str) -> dict:
        """替换workflow中的prompt，并更新随机种子确保每次都是新任务"""
        wf = copy.deepcopy(workflow)
        
        # 找到并替换prompt
        prompt_found = False
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
                    prompt_found = True
                    break
        
        if not prompt_found:
            raise ValueError("未找到正向CLIPTextEncode节点")
        
        # 找到KSampler节点，更新随机种子
        for node_id, node in wf.items():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") == "KSampler":
                inputs = node.get("inputs")
                if isinstance(inputs, dict) and "seed" in inputs:
                    # 生成随机种子，确保每次都是新任务
                    inputs["seed"] = random.randint(0, 2**32 - 1)
                    break
        
        return wf

