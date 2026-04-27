"""
AI Worker Thread
后台线程：任务队列 + 状态探测循环 + 指数退避重连策略

设计约束：
- 所有 HTTP 请求（requests）阻塞在线程内，不影响 UI 主线程
- 状态缓存通过 AIStateCache 与外界交互（线程安全）
- 任务结果通过 Qt 信号回传到主线程
"""
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from PyQt6.QtCore import QMutex, QMutexLocker, QThread, QWaitCondition, pyqtSignal

from ai.ollama_client import OllamaClient


class AIStatus(Enum):
    UNKNOWN = "unknown"      # 尚未完成首次探测
    ONLINE = "online"        # 服务正常，模型可加载
    OFFLINE = "offline"      # 服务不可达
    ERROR = "error"          # 服务可达但模型加载失败


@dataclass
class AIStateSnapshot:
    status: AIStatus = AIStatus.UNKNOWN
    model_name: str = ""          # 当前加载的模型名（如 "gemma4:4b"）
    response_latency_ms: float = 0.0  # 最后一次探测的 RTT
    last_probe_time: float = 0.0  # 时间戳
    error_message: str = ""       # 若状态为 ERROR/OFFLINE，记录原因

    def copy(self) -> "AIStateSnapshot":
        """返回深拷贝，避免跨线程引用问题"""
        return AIStateSnapshot(
            status=self.status,
            model_name=self.model_name,
            response_latency_ms=self.response_latency_ms,
            last_probe_time=self.last_probe_time,
            error_message=self.error_message,
        )


class AIStateCache:
    """线程安全状态缓存（QMutex 保护）"""

    def __init__(self):
        self._mutex = QMutex()
        self._snapshot = AIStateSnapshot()

    def get(self) -> AIStateSnapshot:
        with QMutexLocker(self._mutex):
            return self._snapshot.copy()

    def update(self, snapshot: AIStateSnapshot):
        with QMutexLocker(self._mutex):
            self._snapshot = snapshot.copy()


class AITaskType(Enum):
    CATEGORIZE = "categorize"           # 智能分类
    SEMANTIC_SEARCH = "semantic_search"  # 语义搜索
    GENERATE_REMARK = "generate_remark"  # AI 生成备注
    CLASSIFY_BATCH = "classify_batch"    # 批量分类
    CHAT = "chat"                        # AI 助手对话
    PARSE_COMMAND = "parse_command"      # 指令解析


@dataclass
class AITask:
    task_type: AITaskType
    payload: Dict[str, Any]
    task_id: str = ""


class AIWorkerThread(QThread):
    """
    AI 后台工作线程

    职责：
    1. 状态探测循环（指数退避 + 兜底探测）
    2. 任务队列消费（deque）
    3. 所有 HTTP 调用均发生在线程内部
    """

    # ── 信号 ──
    state_updated = pyqtSignal(object)     # AIStateSnapshot（通知 UI 更新）
    task_finished = pyqtSignal(str, object)  # (task_id, result)
    task_failed = pyqtSignal(str, str)       # (task_id, error_message)

    # 指数退避间隔（秒）：30s → 60s → 120s → 120s（封顶）
    BACKOFF_INTERVALS = [30, 60, 120, 120]
    # 兜底探测间隔：无论状态如何，最多 5 分钟探测一次
    MAX_PROBE_INTERVAL = 300
    # 缓存有效期：ONLINE 状态下超过 2 分钟视为过期
    CACHE_TTL_ONLINE = 120

    def __init__(self, state_cache: AIStateCache, parent=None):
        super().__init__(parent)
        self._state_cache = state_cache
        self._queue: deque = deque()
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._running = True

        self._config = {
            "host": "http://localhost:11434",
            "model": "gemma4:4b",
            "timeout": 30,
        }
        self._ollama_client: Optional[OllamaClient] = None

        # 退避状态
        self._backoff_level = 0
        self._last_probe_time = 0.0
        self._next_probe_time = 0.0

    # ── 配置 ──
    def _get_client(self) -> OllamaClient:
        """懒加载 OllamaClient（线程安全，因为只在线程内调用）"""
        if self._ollama_client is None:
            self._ollama_client = OllamaClient(
                model=self._config["model"],
                host=self._config["host"],
            )
        return self._ollama_client

    def update_config(self, host: str, model: str, timeout: int = 30):
        """更新连接配置，触发后台重新探测"""
        with QMutexLocker(self._mutex):
            self._config = {
                "host": host,
                "model": model,
                "timeout": timeout,
            }
            self._ollama_client = None  # 强制重建客户端
            self._next_probe_time = 0.0  # 立即触发探测
            self._condition.wakeOne()

    # ── 任务队列 ──
    def enqueue(self, task_id: str, task_type: AITaskType, payload: Dict[str, Any]):
        """将任务加入队列并唤醒线程"""
        with QMutexLocker(self._mutex):
            self._queue.append(AITask(task_type=task_type, payload=payload, task_id=task_id))
            self._condition.wakeOne()

    def request_refresh(self):
        """请求立即刷新状态（不阻塞 UI）"""
        with QMutexLocker(self._mutex):
            self._next_probe_time = 0.0
            self._condition.wakeOne()

    # ── 生命周期 ──
    def shutdown(self):
        """优雅关闭：清空队列，终止线程"""
        with QMutexLocker(self._mutex):
            self._running = False
            self._queue.clear()
            self._condition.wakeAll()

    # ── 主循环 ──
    def run(self):
        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break

            now = time.time()
            task: Optional[AITask] = None
            need_probe = False

            with QMutexLocker(self._mutex):
                if self._queue:
                    task = self._queue.popleft()
                elif now >= self._next_probe_time:
                    need_probe = True
                else:
                    # 等待到下次探测时间，或新任务到来，或 1 秒超时（周期性检查）
                    wait_ms = max(1, int((self._next_probe_time - now) * 1000))
                    self._condition.wait(self._mutex, min(wait_ms, 1000))
                    continue

            if task is not None:
                self._process_task(task)
            elif need_probe:
                self._do_probe()

    # ── 状态探测 ──
    def _do_probe(self):
        """执行一次 Ollama 状态探测"""
        now = time.time()
        client = self._get_client()

        try:
            t0 = time.perf_counter()
            available = client.is_available()
            latency_ms = (time.perf_counter() - t0) * 1000.0

            if available:
                snapshot = AIStateSnapshot(
                    status=AIStatus.ONLINE,
                    model_name=client.model,
                    response_latency_ms=latency_ms,
                    last_probe_time=now,
                    error_message="",
                )
                self._backoff_level = 0
            else:
                snapshot = AIStateSnapshot(
                    status=AIStatus.OFFLINE,
                    model_name=client.model,
                    response_latency_ms=0.0,
                    last_probe_time=now,
                    error_message="Ollama 服务未响应（HTTP 非 200）",
                )
                self._backoff_level = min(
                    self._backoff_level + 1, len(self.BACKOFF_INTERVALS) - 1
                )
        except Exception as e:
            snapshot = AIStateSnapshot(
                status=AIStatus.ERROR,
                model_name=client.model,
                response_latency_ms=0.0,
                last_probe_time=now,
                error_message=str(e),
            )
            self._backoff_level = min(
                self._backoff_level + 1, len(self.BACKOFF_INTERVALS) - 1
            )

        self._state_cache.update(snapshot)
        self.state_updated.emit(snapshot)

        self._last_probe_time = now
        # 计算下次探测间隔（指数退避 vs 兜底探测）
        backoff = self.BACKOFF_INTERVALS[self._backoff_level]
        next_interval = min(backoff, self.MAX_PROBE_INTERVAL)
        self._next_probe_time = now + next_interval

    # ── 任务执行 ──
    def _process_task(self, task: AITask):
        """消费单个任务"""
        client = self._get_client()
        result = None

        try:
            if task.task_type == AITaskType.CATEGORIZE:
                result = client.categorize(
                    task.payload.get("app_name", ""),
                    task.payload.get("url", ""),
                    task.payload.get("existing_categories"),
                    task.payload.get("parent_hint"),
                    task.payload.get("remark", ""),
                    task.payload.get("ai_remark", ""),
                )

            elif task.task_type == AITaskType.GENERATE_REMARK:
                result = self._generate_remark(client, task.payload)

            elif task.task_type == AITaskType.CHAT:
                result = client.chat(
                    task.payload.get("messages", []),
                    temperature=task.payload.get("temperature", 0.3),
                )

            elif task.task_type == AITaskType.PARSE_COMMAND:
                result = client.parse_command(
                    task.payload.get("query", ""),
                    task.payload.get("db_summary", ""),
                    history=task.payload.get("history", None),
                )

            elif task.task_type == AITaskType.SEMANTIC_SEARCH:
                result = client.semantic_search(
                    task.payload.get("query", ""),
                    task.payload.get("app_list", []),
                    task.payload.get("accounts_info"),
                )

            elif task.task_type == AITaskType.CLASSIFY_BATCH:
                # 批量分类：payload 中需提供完整 prompt，结果由调用方解析
                prompt = task.payload.get("prompt", "")
                if not prompt:
                    raise ValueError("CLASSIFY_BATCH 任务需要提供 prompt")
                raw = client.generate(prompt, temperature=0.2, num_predict=500)
                result = raw

            else:
                raise ValueError(f"未知任务类型: {task.task_type}")

            # 任务成功：顺带更新状态（复用同一次 HTTP 连接后的状态感知）
            self._update_state_post_task(client, success=True)
            self.task_finished.emit(task.task_id, result)

        except Exception as e:
            self._update_state_post_task(client, success=False, error=str(e))
            self.task_failed.emit(task.task_id, str(e))

    def _generate_remark(self, client: OllamaClient, payload: Dict[str, Any]) -> str:
        """构建备注生成 prompt 并调用模型"""
        app_name = payload.get("app_name", "")
        url = payload.get("url", "")
        category = payload.get("category", "")
        remark = payload.get("remark", "")

        if not app_name:
            raise ValueError("应用名称不能为空")

        prompt = f"""根据应用名称、网址、分类和用户手动备注，用一句话描述这个账号的用途。

要求：
- 不超过20个字
- 简洁明了
- 直接返回描述内容，不要加引号或额外解释

应用名称：{app_name}
网址：{url or '无'}
分类：{category or '未分类'}
用户手动备注：{remark or '无'}

用途描述："""

        result = client.generate(prompt=prompt, temperature=0.3, num_predict=50)
        remark = result.strip().strip('"').strip("'")
        # 备注完整保留，不做截断
        return remark

    def _update_state_post_task(self, client: OllamaClient, success: bool = True, error: str = ""):
        """任务执行后附带更新一次状态"""
        now = time.time()
        if success:
            snapshot = AIStateSnapshot(
                status=AIStatus.ONLINE,
                model_name=client.model,
                response_latency_ms=0.0,
                last_probe_time=now,
                error_message="",
            )
            self._backoff_level = 0
        else:
            # 任务失败不立即标记为 OFFLINE，仅记录错误，由探测循环负责状态判定
            current = self._state_cache.get()
            snapshot = AIStateSnapshot(
                status=current.status,
                model_name=client.model,
                response_latency_ms=0.0,
                last_probe_time=now,
                error_message=error,
            )

        self._state_cache.update(snapshot)
        self.state_updated.emit(snapshot)
