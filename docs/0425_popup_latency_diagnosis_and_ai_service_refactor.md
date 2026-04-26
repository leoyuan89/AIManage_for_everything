# 主弹窗响应延迟诊断与 AI 服务层重构方案

> 文档日期：2026-04-25  
> 关联现象：账号详情弹窗/添加账号弹窗/设置弹窗打开时出现约 10 秒级无响应  
> 约束：不得预设卡顿一定由 AI 操作导致；先诊断、后重构。

---

## 一、背景与现象

用户报告右侧列表条目 hover 效果未生效，同时提出一个**关联性能问题**：

- 点击主列表条目打开详情弹窗（`AccountDialog`）
- 点击底部按钮打开"添加账号"弹窗（`AccountDialog`）
- 点击底部按钮打开"设置"弹窗（`SettingsDialog`）

以上三类弹窗均出现**约 10 秒级的打开延迟**——即点击后 UI 冻结约 10 秒，弹窗才出现。

该现象可能与 hover 失效共享同一个根因（UI 主线程被长时间阻塞导致事件队列无法处理），也可能独立存在。**必须先建立客观诊断数据，再决定修复优先级。**

---

## 二、第一阶段：系统性诊断与根因定位

### 2.1 诊断目标

精确到**函数级**定位 10 秒耗时的分布，区分以下四类根因：

| 根因类型 | 典型表现 |
|---|---|
| **数据库阻塞** | 弹窗构造时同步执行全表查询、遍历数百条记录重建分类树、重复打开 SQLite 连接 |
| **资源加载阻塞** | 同步加载图标字体、渲染复杂样式表、创建大量自定义 widget |
| **AI 同步调用阻塞** | `OllamaClient.is_available()` 同步 HTTP 探测超时、模型预热、`subprocess.run` 等待 |
| **UI 渲染阻塞** | 弹窗布局含深层嵌套容器、首次 `show()`/`exec()` 触发大量重排重绘 |

### 2.2 计时日志插入方案（最小侵入式）

在以下节点插入 `time.perf_counter()` 计时日志，输出到 `debug_output.txt`：

#### A. 弹窗类构造函数（`AccountDialog.__init__`）

```python
import time

class AccountDialog(QDialog):
    def __init__(self, db_manager, account=None, ollama_client=None, parent=None):
        t0 = time.perf_counter()
        super().__init__(parent)
        
        t1 = time.perf_counter(); print(f"[Perf] AccountDialog super().__init__: {(t1-t0)*1000:.1f} ms")
        
        self.db = db_manager
        self.ollama_client = ollama_client
        
        t2 = time.perf_counter(); print(f"[Perf] AccountDialog attr init: {(t2-t1)*1000:.1f} ms")
        
        # CategoryService / AIRemarkService 初始化
        self.category_service = CategoryService(db_manager, ollama_client)
        t3 = time.perf_counter(); print(f"[Perf] CategoryService init: {(t3-t2)*1000:.1f} ms")
        
        self.ai_remark_service = AIRemarkService(ollama_client)
        t4 = time.perf_counter(); print(f"[Perf] AIRemarkService init: {(t4-t3)*1000:.1f} ms")
        
        self.setup_ui()
        t5 = time.perf_counter(); print(f"[Perf] setup_ui total: {(t5-t4)*1000:.1f} ms")
        
        print(f"[Perf] AccountDialog __init__ TOTAL: {(t5-t0)*1000:.1f} ms")
```

#### B. `setup_ui()` 内部关键节点

在 `AccountDialog.setup_ui()` 中，对以下子阶段分别计时：

1. 创建 `QTabWidget` 及两个标签页
2. 创建表单控件（`QLineEdit`、`QComboBox`、`QTextEdit` 等）
3. **Ollama 可用性检查**（第 323 行、第 387 行）
   ```python
   t_check = time.perf_counter()
   if self.ollama_client and self.ollama_client.is_available():
       ...
   print(f"[Perf] Ollama is_available check: {(time.perf_counter()-t_check)*1000:.1f} ms")
   ```
4. 填充分类下拉框（`CategoryService.get_all_categories()`）
5. 绑定信号槽

#### C. `SettingsDialog.__init__` 同理

对 `SettingsDialog` 构造函数及 `setup_ui()` 插入相同模式计时。

#### D. `MainWindow` 弹窗调用前后

```python
t0 = time.perf_counter()
dialog = AccountDialog(self.db, account, self._ollama_client, parent=self)
t1 = time.perf_counter(); print(f"[Perf] AccountDialog construct: {(t1-t0)*1000:.1f} ms")

result = dialog.exec()
t2 = time.perf_counter(); print(f"[Perf] AccountDialog exec: {(t2-t1)*1000:.1f} ms")
```

### 2.3 性能分析工具使用

#### 方案 A：`cProfile` 生成火焰图

在弹窗打开代码处包裹 `cProfile`：

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

dialog = AccountDialog(self.db, account, self._ollama_client, parent=self)
dialog.exec()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(30)  # 打印前 30 个热点函数
stats.dump_stats('profile_account_dialog.prof')
```

使用 `snakeviz` 可视化：
```bash
python -m snakeviz profile_account_dialog.prof
```

#### 方案 B：PyQt `QElapsedTimer`（更精准，排除 Python GIL 开销）

```python
from PyQt6.QtCore import QElapsedTimer

timer = QElapsedTimer()
timer.start()
# ... 被测代码 ...
print(f"[Perf] elapsed: {timer.elapsed()} ms")
```

### 2.4 四大嫌疑路径审查清单

#### 嫌疑路径 1：UI 主线程同步阻塞

- [ ] `CategoryService.__init__` 是否同步查询数据库全量分类？
- [ ] `AccountDialog.setup_ui()` 中 `QComboBox` 填充是否遍历大量数据？
- [ ] 弹窗是否重复创建 `DatabaseManager` 连接？
- [ ] `load_accounts()` 是否在弹窗打开时被动触发？

#### 嫌疑路径 2：AI 相关同步调用

- [ ] `OllamaClient.is_available()` 同步 HTTP `requests.get(..., timeout=2)` 是否被调用多次？
  - `AccountDialog` 中至少出现 **2 次**（第 323 行、第 387 行，分别用于"AI分类"和"AI备注"按钮的可用性检查）
  - 若 Ollama 未启动，每次 `timeout=2` 会阻塞 2 秒；两次累积即 4 秒
  - 若存在重试或级联调用，可能逼近 10 秒
- [ ] `CategoryService` / `AIRemarkService` 初始化时是否隐式触发 AI 探测？
- [ ] 底部状态栏是否在弹窗打开期间执行高频 Ollama 心跳探测？
- [ ] `SettingsDialog` 是否同步执行模型列表获取？

#### 嫌疑路径 3：信号槽与事件循环

- [ ] 弹窗构造时是否触发了级联的信号槽链（如 `textChanged` → 密码强度评估 → UI 更新）？
- [ ] `AccountDialog` 打开时是否触发了 `MainWindow` 的某些全局刷新信号？
- [ ] `QComboBox.currentIndexChanged` 是否在填充时误触发？

#### 嫌疑路径 4：首次渲染开销

- [ ] 弹窗是否包含深层嵌套布局（如 `QTabWidget` → `QVBoxLayout` → `QHBoxLayout` → ...）？
- [ ] 样式表是否包含复杂规则（如大量 `border-radius`、渐变、阴影）？
- [ ] 首次 `exec()` 时是否触发字体度量计算、图标渲染缓存冷启动？

### 2.5 诊断输出模板

完成计时应输出以下格式的技术报告：

```
=== 弹窗延迟诊断报告 ===
测试场景：打开"添加账号"弹窗（AccountDialog，无预填数据）

阶段耗时明细：
  1. __init__ 入口 → super() 结束:     0.5 ms
  2. CategoryService 初始化:            8.2 ms
  3. AIRemarkService 初始化:            1.1 ms
  4. setup_ui() 总耗时:                 8,450.3 ms  <-- 热点
     4a. TabWidget + 页面创建:          12.4 ms
     4b. 表单控件创建:                  89.6 ms
     4c. Ollama is_available() 第1次:   2,012.5 ms  <-- 异常（timeout=2 却耗时 2s）
     4d. Ollama is_available() 第2次:   2,008.3 ms  <-- 异常
     4e. 分类下拉框填充:                45.2 ms
     4f. 信号槽绑定:                    3.1 ms
  5. dialog.exec() 首次渲染:            234.7 ms
  -----------------------------------------------
  TOTAL:                                ~10.7 s

根因假设（按概率排序）：
  H1 (高): Ollama 未运行时，is_available() 同步阻塞 2s×2=4s，
           若 CategoryService/AIRemarkService 内部再各调一次，累计 8s+
  H2 (中): setup_ui() 中创建了大量自定义 widget，首次样式表解析耗时
  H3 (低): 数据库查询阻塞

验证方法：
  - 临时注释 is_available() 调用后复测，若延迟消失则确认 H1
  - 若延迟仍在，用 cProfile 分析 setup_ui() 子阶段
```

---

## 三、第二阶段：全局 AI 服务管理层架构（AI Service Manager）

> 无论诊断结论如何，均实施本重构。目标是根治"各模块独立处理 AI 逻辑"的架构隐患，实现 AI 能力与 UI 主线程的完全解耦。

### 3.1 设计目标

| 目标 | 说明 |
|---|---|
| **唯一入口** | 全软件所有 AI 交互（Ollama HTTP 调用、进程探测、状态查询）必须经过 AI Service Manager |
| **后台初始化** | 软件启动时于后台线程完成单例初始化，不阻塞主窗口显示 |
| **状态缓存** | 模型在线状态、加载模型名、响应延迟写入线程安全缓存，供全模块读取 |
| **按需探测** | 取消固定高频心跳，仅在用户触发 AI 操作时后台异步验证状态 |
| **异步任务队列** | LLM 推理任务（分类、语义搜索、摘要、对话）全部由专属工作线程执行，结果通过 Qt 信号回传 |
| **指数退避重连** | Ollama 离线时，探测间隔 30s → 60s → 120s 逐步拉长；期间 AI 按钮置灰 |
| **UI 懒加载** | 弹窗构造阶段仅完成 UI 渲染，AI 内容后台生成后增量填充 |

### 3.2 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                        UI 主线程                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ MainWindow  │  │AccountDialog│  │ SettingsDialog      │  │
│  │ (底部状态栏) │  │ (AI分类按钮) │  │ (Ollama状态显示)    │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                    │              │
│         ▼                ▼                    ▼              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           AI Service Manager（单例，主线程驻留）        │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐  │   │
│  │  │ 状态缓存快照 │  │  配置存储   │  │  信号分发器  │  │   │
│  │  │ (thread-safe)│  │(host, model)│  │(pyqtSignal)  │  │   │
│  │  └─────────────┘  └─────────────┘  └──────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│                           ▼ (Qt信号: 提交任务、查询状态)       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           AI Worker Thread（QThread，专属后台线程）     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐  │   │
│  │  │ 任务队列    │  │ HTTP 客户端 │  │ 状态探测循环 │  │   │
│  │  │ (deque)     │  │ (requests)  │  │ (退避策略)   │  │   │
│  │  └─────────────┘  └─────────────┘  └──────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 状态缓存与探测机制

#### 3.3.1 缓存数据结构

```python
from dataclasses import dataclass
from enum import Enum

class AIStatus(Enum):
    UNKNOWN = "unknown"      # 尚未完成首次探测
    ONLINE = "online"        # 服务正常，模型可加载
    OFFLINE = "offline"      # 服务不可达
    ERROR = "error"          # 服务可达但模型加载失败

@dataclass
class AIStateSnapshot:
    status: AIStatus
    model_name: str          # 当前加载的模型名（如 "gemma4:4b"）
    response_latency_ms: float  # 最后一次探测的 RTT
    last_probe_time: float   # 时间戳
    error_message: str = ""  # 若状态为 ERROR/OFFLINE，记录原因
```

#### 3.3.2 探测策略

| 场景 | 行为 |
|---|---|
| **软件启动** | 后台线程执行一次异步探测，更新缓存；UI 显示"检测中..." |
| **用户悬停状态栏** | 读取缓存快照立即显示；同时触发一次**后台异步刷新**（不阻塞 UI） |
| **用户点击 AI 按钮** | 先读缓存；若缓存状态为 ONLINE 且未过期（< 2min），直接允许；否则后台异步验证，验证期间按钮显示"检查中..." |
| **Ollama 离线** | 进入指数退避：30s → 60s → 120s → 120s（封顶）；期间所有 AI 按钮置灰；保留每 5 分钟一次的低频兜底探测 |
| **AI 任务执行后** | 任务完成时附带更新一次状态（复用同一次 HTTP 连接） |

#### 3.3.3 线程安全

状态缓存使用 `QMutex` 或 `threading.Lock` 保护：

```python
from PyQt6.QtCore import QMutex, QMutexLocker

class AIStateCache:
    def __init__(self):
        self._mutex = QMutex()
        self._snapshot = AIStateSnapshot(status=AIStatus.UNKNOWN, ...)
    
    def get(self) -> AIStateSnapshot:
        with QMutexLocker(self._mutex):
            return self._snapshot  # dataclass 是可读的，返回副本更安全
    
    def update(self, snapshot: AIStateSnapshot):
        with QMutexLocker(self._mutex):
            self._snapshot = snapshot
```

### 3.4 异步任务队列

#### 3.4.1 任务类型定义

```python
from enum import Enum, auto
from typing import Callable, Any

class AITaskType(Enum):
    CATEGORIZE = auto()        # 智能分类
    SEMANTIC_SEARCH = auto()   # 语义搜索
    GENERATE_REMARK = auto()   # AI 生成备注
    CLASSIFY_BATCH = auto()    # 批量分类
    CHAT = auto()              # AI 助手对话
    PARSE_COMMAND = auto()     # 指令解析

@dataclass
class AITask:
    task_type: AITaskType
    payload: dict              # 任务参数
    callback: Callable[[Any, Exception], None]  # 完成回调（主线程通过信号触发）
    priority: int = 0          # 优先级（数字越小越优先）
```

#### 3.4.2 任务调度流程

```
调用方（UI线程）
   │
   │  ai_manager.submit_task(AITaskType.CATEGORIZE,
   │                         payload={"app_name": "微信"},
   │                         callback=on_result)
   ▼
AI Service Manager
   │  将任务加入队列 (deque)
   │  若 Worker Thread 空闲，发送信号唤醒
   ▼
AI Worker Thread（后台）
   │  从队列取出任务
   │  执行 HTTP 请求（requests，阻塞在线程内，不影响 UI）
   │  获取结果后，emit 信号到主线程
   ▼
主线程槽函数
   │  调用 callback(result, None)
   │  更新 UI（增量填充）
```

#### 3.4.3 与现有 Worker 的整合

当前已有 `AIWorker(QThread)`、`AIRemarkWorker(QThread)`、`ClassificationWorker(QThread)` 等零散线程。

重构后：
- **保留**现有 Worker 的 UI 交互逻辑（信号定义、进度条更新）
- **替换** Worker 内部的直接 HTTP 调用，改为向 `AI Manager` 提交任务
- 长期目标：逐步将 Worker 统一收编到 `AI Manager` 的标准任务队列中

### 3.5 接口定义

```python
from PyQt6.QtCore import QObject, pyqtSignal

class AIServiceManager(QObject):
    """AI 服务管理单例：全软件 AI 交互的唯一入口"""
    
    # ── 信号 ──
    state_changed = pyqtSignal(AIStateSnapshot)   # 状态变化通知（供状态栏监听）
    task_finished = pyqtSignal(str, object)         # (task_id, result)
    task_failed = pyqtSignal(str, str)              # (task_id, error_message)
    
    # ── 单例获取 ──
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def instance(cls) -> "AIServiceManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        super().__init__()
        self._state_cache = AIStateCache()
        self._worker_thread = AIWorkerThread(self._state_cache)
        self._worker_thread.state_updated.connect(self.state_changed.emit)
        self._worker_thread.start()
    
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
    
    # ── 异步任务提交 ──
    def submit_task(self, task_type: AITaskType, payload: dict) -> str:
        """
        提交 AI 任务到后台队列。
        返回 task_id，调用方通过 task_finished / task_failed 信号接收结果。
        """
        task_id = str(uuid.uuid4())
        self._worker_thread.enqueue(task_id, task_type, payload)
        return task_id
    
    # ── 便捷接口 ──
    def categorize_async(self, app_name: str, url: str = "") -> str:
        """异步智能分类，返回 task_id"""
        return self.submit_task(AITaskType.CATEGORIZE, {
            "app_name": app_name, "url": url
        })
    
    def generate_remark_async(self, app_name: str, url: str, category: str) -> str:
        """异步生成备注，返回 task_id"""
        return self.submit_task(AITaskType.GENERATE_REMARK, {
            "app_name": app_name, "url": url, "category": category
        })
    
    def chat_async(self, messages: list, temperature: float = 0.3) -> str:
        """异步对话，返回 task_id"""
        return self.submit_task(AITaskType.CHAT, {
            "messages": messages, "temperature": temperature
        })
    
    def shutdown(self):
        """优雅关闭：等待当前任务完成，清空队列，终止线程"""
        self._worker_thread.shutdown()
        self._worker_thread.wait(5000)
```

### 3.6 与现有模块的集成

#### 3.6.1 底部状态栏

```python
# 当前（问题代码）：可能在主线程同步调用 is_available()
# 重构后：
from services.ai_service_manager import AIServiceManager, AIStatus

class MainWindow:
    def __init__(self):
        self._ai_manager = AIServiceManager.instance()
        self._ai_manager.state_changed.connect(self._on_ai_state_changed)
        
        # 初始化时直接读缓存（毫秒级）
        self._update_ollama_status(self._ai_manager.get_state())
    
    def _on_ai_state_changed(self, state: AIStateSnapshot):
        # 状态变化时更新状态栏（信号自动在主线程触发）
        if state.status == AIStatus.ONLINE:
            self.lbl_ollama_status.setText(f"AI模型: {state.model_name} 运行中")
            self.lbl_ollama_status.setStyleSheet("color: #4CAF50;")
        elif state.status == AIStatus.OFFLINE:
            self.lbl_ollama_status.setText("AI模型: 未连接")
            self.lbl_ollama_status.setStyleSheet("color: #f44336;")
        # ...
    
    def _on_status_bar_hover(self, event):
        # 悬停时触发一次后台异步刷新（不阻塞 UI）
        self._ai_manager.request_refresh()
```

#### 3.6.2 AccountDialog（添加/编辑账号弹窗）

```python
class AccountDialog(QDialog):
    def __init__(self, db_manager, account=None, parent=None):
        super().__init__(parent)
        # 不再直接接收 ollama_client，改为获取 AI Manager
        self._ai_manager = AIServiceManager.instance()
        
        self.setup_ui()
        
        # 绑定 AI 状态变化信号，动态更新按钮可用性
        self._ai_manager.state_changed.connect(self._update_ai_buttons)
        self._update_ai_buttons(self._ai_manager.get_state())  # 初始状态
    
    def _update_ai_buttons(self, state: AIStateSnapshot):
        enabled = state.status == AIStatus.ONLINE
        self.btn_ai_categorize.setEnabled(enabled)
        self.btn_ai_remark.setEnabled(enabled)
        tooltip = "AI 智能分类" if enabled else f"Ollama 未连接 ({state.error_message})"
        self.btn_ai_categorize.setToolTip(tooltip)
    
    def on_ai_categorize_clicked(self):
        # 异步提交分类任务，不阻塞 UI
        app_name = self.txt_app_name.text()
        task_id = self._ai_manager.categorize_async(app_name)
        self._ai_manager.task_finished.connect(self._on_categorize_result)
        self.btn_ai_categorize.setEnabled(False)
        self.btn_ai_categorize.setText("分类中...")
    
    def _on_categorize_result(self, task_id: str, result: object):
        # 主线程回调，更新 UI
        self.cmb_category.setCurrentText(result)
        self.btn_ai_categorize.setEnabled(True)
        self.btn_ai_categorize.setText("AI 分类")
```

#### 3.6.3 SettingsDialog

```python
class SettingsDialog(QDialog):
    def __init__(self, db_manager, config_path, parent=None):
        super().__init__(parent)
        self._ai_manager = AIServiceManager.instance()
        
        # 设置页中的 Ollama 状态显示直接读缓存
        state = self._ai_manager.get_state()
        self._update_ollama_display(state)
    
    def _update_ollama_display(self, state: AIStateSnapshot):
        if state.status == AIStatus.ONLINE:
            self.lbl_status.setText(f"Ollama 状态：运行中 ({state.model_name}, {state.response_latency_ms:.0f}ms)")
        else:
            self.lbl_status.setText(f"Ollama 状态：未连接 ({state.error_message})")
```

### 3.7 废除的代码模式

重构后，以下代码模式**严格禁止**：

| 禁止模式 | 原因 | 替换方式 |
|---|---|---|
| 弹窗 `__init__` 中直接调用 `OllamaClient.is_available()` | 同步 HTTP 阻塞 UI 线程 | 读 `AIStateCache` 快照 |
| 模块各自创建 `OllamaClient` 实例 | 连接管理分散，重复探测 | 统一走 `AIServiceManager` |
| 在主线程执行 `requests.post(..., timeout=None)` | LLM 推理可能耗时数十秒，完全冻结 UI | 提交到 `AIWorkerThread` 队列 |
| 固定间隔 `QTimer` 高频探测 Ollama（如每 5 秒） | 无意义的网络开销，加速电池消耗 | 按需探测 + 指数退避 |
| `subprocess.run(['ollama', ...])` 同步等待 | 子进程启动慢，阻塞 UI | 后台线程执行或完全避免 |

---

## 四、实施计划

### Phase 0：诊断（1 天）

1. 插入计时日志到 `AccountDialog`、`SettingsDialog`、`MainWindow`
2. 执行 `cProfile` 分析，生成热点函数排名
3. 输出诊断报告，确认根因（数据库 / 资源 / AI / UI 渲染）

### Phase 1：AI Service Manager 核心（2 天）

1. 新建 `services/ai_service_manager.py`，实现 `AIServiceManager` 单例
2. 新建 `services/ai_worker_thread.py`，实现 `AIWorkerThread` 任务队列
3. 实现 `AIStateCache` 线程安全状态缓存
4. 实现指数退避探测策略
5. 单元测试：模拟 Ollama 离线/在线场景

### Phase 2：存量代码迁移（2 天）

1. `MainWindow` 底部状态栏接入 `AIServiceManager`
2. `AccountDialog` 移除 `ollama_client` 参数，接入 `AIServiceManager`
3. `SettingsDialog` 接入 `AIServiceManager`
4. `AIClassifyDialog`、`AIAssistantService` 等存量 AI 模块逐步迁移
5. 废弃 `OllamaClient` 的直接使用（保留为 `AIWorkerThread` 的内部依赖）

### Phase 3：弹窗延迟专项修复（根据 Phase 0 结论，1-2 天）

- 若根因确认为 **AI 同步调用**：Phase 2 完成后自动解决
- 若根因确认为 **数据库阻塞**：将全量查询改为按需加载/缓存
- 若根因确认为 **资源加载**：延迟加载/异步加载图标字体资源
- 若根因确认为 **UI 渲染**：简化弹窗布局层级，减少重排

### Phase 4：回归测试（1 天）

1. Ollama 在线/离线两种场景下的弹窗打开速度测试
2. AI 功能（分类、备注、对话）正确性测试
3. 内存泄漏检查（`AIServiceManager` 长生命周期）

---

## 五、待确认问题

在正式启动开发前，请确认以下事项：

1. **诊断优先级**：是否同意先执行 Phase 0 计时日志诊断，确认 10 秒延迟的根因后再启动 Phase 1 重构？还是直接同步推进？
2. **Ollama 部署现状**：当前开发/测试机器上 Ollama 是否常驻运行？若 Ollama 未运行是常态，则 `is_available()` 超时阻塞的嫌疑极高。
3. **状态栏探测频率**：当前底部状态栏"AI模型: gemma4:4b 运行中"的刷新机制是什么频率？是否使用了 `QTimer` 固定间隔探测？
4. **弹窗传参方式**：`AccountDialog` 当前接收 `ollama_client` 实例作为参数。重构后是否同意改为弹窗内部通过 `AIServiceManager.instance()` 获取，不再由 `MainWindow` 注入？
5. **向后兼容**：`OllamaClient` 类当前被多处直接引用。重构策略是 A) 保留 `OllamaClient` 作为底层 HTTP 客户端，仅禁止外部直接调用；还是 B) 完全内化为 `AIWorkerThread` 的私有实现？
6. **hover 修复与性能修复的优先级**：右侧列表 hover 效果与弹窗延迟是否作为同一批次修复，还是分批次处理？
