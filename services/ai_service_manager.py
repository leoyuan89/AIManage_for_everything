"""
AI Service Manager
全软件 AI 交互的唯一入口（单例）

职责：
- 状态缓存与查询（毫秒级，绝不阻塞 UI）
- 异步任务提交与结果分发
- 配置管理（host / model / timeout）

禁止：
- 弹窗 __init__ 中直接调用 OllamaClient.is_available()
- 模块各自创建 OllamaClient 实例
- 在主线程执行 requests.post(..., timeout=None)
"""
import threading
import uuid
from typing import Any, Dict

from PyQt6.QtCore import QObject, pyqtSignal

from services.ai_worker_thread import (
    AIStateCache,
    AIStateSnapshot,
    AIStatus,
    AIWorkerThread,
    AITaskType,
)


class AIServiceManager(QObject):
    """AI 服务管理单例：全软件 AI 交互的唯一入口"""

    # ── 信号 ──
    state_changed = pyqtSignal(object)   # AIStateSnapshot（供状态栏监听）
    task_finished = pyqtSignal(str, object)  # (task_id, result)
    task_failed = pyqtSignal(str, str)       # (task_id, error_message)

    # ── 单例 ──
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "AIServiceManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """测试/重置用：销毁当前单例"""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
                cls._instance = None

    def __init__(self):
        super().__init__()
        self._state_cache = AIStateCache()
        self._worker_thread = AIWorkerThread(self._state_cache)
        self._worker_thread.state_updated.connect(self._on_state_updated)
        self._worker_thread.task_finished.connect(self.task_finished.emit)
        self._worker_thread.task_failed.connect(self.task_failed.emit)
        self._worker_thread.start()

    def _on_state_updated(self, snapshot: AIStateSnapshot):
        """内部桥接：Worker 状态更新 → 外部信号"""
        self.state_changed.emit(snapshot)

    # ── 配置 ──
    def configure(self, host: str, model: str, timeout: int = 30):
        """更新连接配置，触发后台重新探测"""
        self._worker_thread.update_config(host, model, timeout)

    # ── 状态查询（非阻塞，读取缓存） ──
    def get_state(self) -> AIStateSnapshot:
        """获取当前状态快照（毫秒级，绝不阻塞）"""
        return self._state_cache.get()

    def is_available(self) -> bool:
        """快速判断 AI 是否可用（读取缓存，非实时探测）"""
        return self._state_cache.get().status == AIStatus.ONLINE

    def is_cache_expired(self, ttl_seconds: float = 120.0) -> bool:
        """判断缓存是否已过期（默认 2 分钟）"""
        state = self._state_cache.get()
        if state.status == AIStatus.UNKNOWN:
            return True
        import time
        return (time.time() - state.last_probe_time) > ttl_seconds

    # ── 异步任务提交 ──
    def submit_task(self, task_type: AITaskType, payload: Dict[str, Any]) -> str:
        """
        提交 AI 任务到后台队列。
        返回 task_id，调用方通过 task_finished / task_failed 信号接收结果。
        """
        task_id = str(uuid.uuid4())
        self._worker_thread.enqueue(task_id, task_type, payload)
        return task_id

    # ── 便捷接口 ──
    def categorize_async(self, app_name: str, url: str = "", existing_categories: list = None, parent_hint: str = None, remark: str = "", ai_remark: str = "") -> str:
        """异步智能分类，返回 task_id
        
        Args:
            app_name: 应用名称/标题
            url: 网址（可选）
            existing_categories: 当前已有的分类列表（可选），供 AI 参考
            parent_hint: 当前已选中的一级分类（可选）。传入时 AI 只返回二级子类
            remark: 用户手动备注（可选）
            ai_remark: AI 生成备注（可选）
        """
        payload = {"app_name": app_name, "url": url}
        if existing_categories:
            payload["existing_categories"] = existing_categories
        if parent_hint:
            payload["parent_hint"] = parent_hint
        if remark:
            payload["remark"] = remark
        if ai_remark:
            payload["ai_remark"] = ai_remark
        return self.submit_task(AITaskType.CATEGORIZE, payload)

    def generate_remark_async(self, app_name: str, url: str = "", category: str = "", remark: str = "") -> str:
        """异步生成备注，返回 task_id"""
        return self.submit_task(AITaskType.GENERATE_REMARK, {
            "app_name": app_name, "url": url, "category": category, "remark": remark
        })

    def chat_async(self, messages: list, temperature: float = 0.3) -> str:
        """异步对话，返回 task_id"""
        return self.submit_task(AITaskType.CHAT, {
            "messages": messages, "temperature": temperature
        })

    def parse_command_async(self, query: str, db_summary: str, history: list = None) -> str:
        """异步解析指令，返回 task_id"""
        return self.submit_task(AITaskType.PARSE_COMMAND, {
            "query": query, "db_summary": db_summary, "history": history
        })

    def semantic_search_async(self, query: str, app_list: list, accounts_info: list = None) -> str:
        """异步语义搜索，返回 task_id"""
        return self.submit_task(AITaskType.SEMANTIC_SEARCH, {
            "query": query, "app_list": app_list, "accounts_info": accounts_info or []
        })

    def classify_batch_async(self, prompt: str) -> str:
        """异步批量分类（prompt 由调用方构建），返回 task_id"""
        return self.submit_task(AITaskType.CLASSIFY_BATCH, {
            "prompt": prompt
        })

    # ── 刷新请求 ──
    def request_refresh(self):
        """请求后台立即刷新状态（不阻塞 UI）"""
        self._worker_thread.request_refresh()

    # ── 优雅关闭 ──
    def shutdown(self):
        """优雅关闭：等待当前任务完成，清空队列，终止线程"""
        self._worker_thread.shutdown()
        self._worker_thread.wait(5000)
