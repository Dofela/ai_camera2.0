# brain/planner/task_planner.py
"""
任务规划器 - 根据用户意图规划执行任务
"""

from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import logging
from datetime import datetime


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """任务数据类"""
    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None


class TaskPlanner:
    """
    任务规划器类
    负责根据用户意图规划和执行任务
    """

    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.logger = logging.getLogger(__name__)

    async def plan_task(self, intent: str, parameters: Dict[str, Any] = None) -> Task:
        """
        规划任务
        
        Args:
            intent: 用户意图
            parameters: 参数
            
        Returns:
            Task: 任务对象
        """
        # 生成任务ID
        task_id = f"task_{int(datetime.now().timestamp() * 1000)}"
        
        # 创建任务
        task = Task(
            id=task_id,
            name=intent,
            description=f"执行{intent}任务",
            parameters=parameters or {}
        )
        
        # 存储任务
        self.tasks[task_id] = task
        self.logger.info(f"规划任务: {task_id} - {intent}")
        
        return task

    async def execute_task(self, task_id: str) -> Task:
        """
        执行任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            Task: 任务对象
        """
        if task_id not in self.tasks:
            raise ValueError(f"任务不存在: {task_id}")
        
        task = self.tasks[task_id]
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        
        self.logger.info(f"执行任务: {task_id} - {task.name}")
        
        try:
            # 这里应该调用实际的任务执行逻辑
            # 暂时模拟执行
            await self._simulate_task_execution(task)
            
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.result = f"任务{task.name}执行完成"
            
            self.logger.info(f"任务完成: {task_id}")
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.error = str(e)
            
            self.logger.error(f"任务失败: {task_id} - {str(e)}")
            raise
        
        return task

    async def _simulate_task_execution(self, task: Task):
        """
        模拟任务执行
        
        Args:
            task: 任务对象
        """
        # 模拟任务执行时间
        import asyncio
        await asyncio.sleep(0.1)

    def get_task(self, task_id: str) -> Optional[Task]:
        """
        获取任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            Optional[Task]: 任务对象
        """
        return self.tasks.get(task_id)

    def get_tasks(self) -> List[Task]:
        """
        获取所有任务
        
        Returns:
            List[Task]: 任务列表
        """
        return list(self.tasks.values())

    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否取消成功
        """
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        if task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.error = "任务被取消"
            self.logger.info(f"取消任务: {task_id}")
            return True
        
        return False