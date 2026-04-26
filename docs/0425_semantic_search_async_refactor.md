# AI 语义搜索异步化重构方案

## 一、背景与问题分析

### 1.1 现状

当前搜索流程由 `MainWindow.on_search()` 委托 `SearchService.search()` 一次性完成三层搜索：

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────────┐
│ MainWindow  │────▶│ SearchService   │────▶│ OllamaClient     │
│ on_search() │     │ search() 同步   │     │ semantic_search()│
│  阻塞等待   │     │ 内部直接HTTP    │     │  同步HTTP请求    │
└─────────────┘     └─────────────────┘     └──────────────────┘
```

**问题：**
- `SearchService.search()` 第 122-125 行直接实例化 `OllamaClient` 并发起同步 HTTP 请求
- 违反架构规范：所有 AI 调用必须通过 `AIServiceManager` → `AIWorkerThread` 后台队列
- 同步调用阻塞 UI 主线程，Ollama 响应慢时（模型冷启动可达 10-30 秒）整个界面冻结
- 触发条件过于苛刻：`len(results) < 5` 时才会触发语义搜索，大量搜索场景被跳过
- 异常被静默捕获（`except Exception: print(...)`），用户看不到 AI 是否失败

### 1.2 架构现状

`AIServiceManager` 已经提供完善的异步语义搜索能力：

```python
# AIServiceManager (已完成)
def semantic_search_async(self, query: str, app_list: list) -> str:
    return self.submit_task(AITaskType.SEMANTIC_SEARCH, {
        "query": query, "app_list": app_list
    })
```

`AIWorkerThread` 也已实现 `SEMANTIC_SEARCH` 任务类型的消费逻辑（第 272-276 行）。

**结论：** 异步基础设施完备，仅需在 UI 层重构调用方式。

---

## 二、方案目标

1. **零阻塞**：搜索永远不在主线程等待 AI 响应
2. **即时反馈**：精确/拼音匹配结果在 50ms 内渲染到列表
3. **动态追加**：AI 语义结果返回后，自动追加到列表底部（带"AI增强"分区头）
4. **阈值调整**：精确匹配触发语义搜索的阈值从 `< 5` 改为 `< 8`
5. **架构合规**：所有 AI 调用唯一入口为 `AIServiceManager`
6. **可感知失败**：AI 服务不可用时，列表底部给出友好提示（不弹窗打断）

---

## 三、架构设计

### 3.1 目标数据流（异步）

```
用户输入 ──▶ on_search()
                │
                ├──▶ SearchService.search_sync() ──▶ 精确/拼音结果
                │                                          │
                │◀─────────────────────────────────────────┘
                │  立即渲染精确/拼音结果到 account_list
                │
                ├──▶ 精确结果 < 8 条 ?
                │       │
                │       ├── 是 ──▶ AIServiceManager.semantic_search_async()
                │       │                      │
                │       │                      ▼
                │       │              AIWorkerThread 后台队列
                │       │                      │
                │       │                      ▼
                │       │              OllamaClient.semantic_search()
                │       │                      │
                │       │◀─────────────────────┘
                │       │  task_finished 信号
                │       │
                │       └── 否 ──▶ 不触发语义搜索
                │
                └──▶ AI结果返回 ?
                        │
                        ├── 是 ──▶ 追加"AI增强"分区 + 语义结果项
                        │
                        └── 否/超时 ──▶ 列表底部显示灰色提示行
```

### 3.2 时序图

```
Time ──────────────────────────────────────────────────────────────▶

UI Thread          MainWindow              SearchService      AIServiceManager
   │                   │                       │                      │
   │  输入"支付"       │                       │                      │
   │──────────────────▶│                       │                      │
   │                   │  search_sync()        │                      │
   │                   │──────────────────────▶│                      │
   │                   │                       │ 精确/拼音匹配(20ms)  │
   │                   │◀──────────────────────│                      │
   │                   │                       │                      │
   │  渲染精确区        │                       │                      │
   │◀──────────────────│                       │                      │
   │                   │                       │                      │
   │                   │  精确结果<8? 是        │                      │
   │                   │  semantic_search_async│                      │
   │                   │─────────────────────────────────────────────▶│
   │                   │                       │         入队(task_id)│
   │                   │                       │                      │
   │                   │                       │         AIWorkerThread
   │                   │                       │              (后台线程)
   │                   │                       │                      │
   │                   │                       │         Ollama HTTP
   │                   │                       │         (可能2-10s)  │
   │                   │                       │                      │
   │                   │◀─────────────────────────────────────────────│
   │                   │  task_finished 信号   │                      │
   │                   │  (异步回调)            │                      │
   │                   │                       │                      │
   │  追加AI增强区      │                       │                      │
   │◀──────────────────│                       │                      │
   │                   │                       │                      │
```

### 3.3 状态机（搜索任务生命周期）

```
                    ┌─────────────┐
         用户输入   │   IDLE      │
        ──────────▶│  空闲状态   │
                    └──────┬──────┘
                           │ on_search()
                           ▼
                    ┌─────────────┐
                    │  SYNC_DONE  │◀────── 精确/拼音结果已渲染
                    │ 同步搜索完成 │
                    └──────┬──────┘
                           │ 精确结果<8 ?
              否 ──────────┼──────────▶ 结束 (STABLE)
                           │ 是
                           ▼
                    ┌─────────────┐
                    │ AI_PENDING  │
                    │ AI搜索进行中 │────── 记录 _pending_search_id
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │ AI_SUCCESS │  │ AI_TIMEOUT │  │ AI_FAILED  │
    │ 结果追加   │  │ 提示超时   │  │ 提示失败   │
    └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
          │               │               │
          └───────────────┼───────────────┘
                          ▼
                   ┌─────────────┐
                   │   STABLE    │
                   │  最终稳定态  │
                   └─────────────┘
```

**关键状态：AI_PENDING**
- 记录当前正在进行的 AI 搜索任务 ID (`_pending_search_id`)
- 如果用户在 AI 返回前输入了新关键词，旧任务的结果必须被**丢弃**（防串结果）

---

## 四、模块改动清单

### 4.1 文件改动总览

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `services/search_service.py` | 修改 | 移除语义搜索逻辑，只保留精确+拼音匹配 |
| `ui/main_window.py` | 修改 | 重构 `on_search()` + 新增 AI 结果回调 |
| `docs/0425_semantic_search_async_refactor.md` | 新增 | 本文档 |

### 4.2 SearchService 改动

**当前：**
```python
def search(self, query, accounts, enable_semantic=False):
    # 精确匹配
    # 拼音匹配
    # 语义搜索（直接 HTTP，阻塞）
    return results
```

**目标：**
```python
def search(self, query, accounts, enable_semantic=False):
    # 精确匹配
    # 拼音匹配
    return results  # 不再包含语义结果

def get_remaining_for_semantic(self, query, accounts, existing_results):
    """返回语义搜索候选账号列表"""
    # 排除已精确/拼音匹配的账号
    # 返回剩余账号 + 查询词
```

语义搜索逻辑完全上移到 `MainWindow`，`SearchService` 只负责本地文本匹配。

### 4.3 MainWindow 改动

**新增成员：**
```python
self._pending_search_id: Optional[str] = None  # 当前进行中的 AI 搜索任务 ID
```

**信号连接（`__init__` 中）：**
```python
self._ai_manager.task_finished.connect(self._on_ai_search_finished)
self._ai_manager.task_failed.connect(self._on_ai_search_failed)
```

**`on_search()` 重构：**
```python
def on_search(self):
    text = self.search_box.text().strip()
    if not text:
        # 恢复默认列表
        return
    
    # 1. 取消之前未完成的 AI 搜索任务（防串结果）
    self._pending_search_id = None
    
    # 2. 同步搜索：精确 + 拼音
    all_accounts = self._get_cached_accounts()
    sync_results = self.search_service.search_sync(text, all_accounts)
    exact_results = [...]
    
    # 3. 立即渲染精确/拼音结果
    self._display_search_results(exact_results, ai_results=[])
    
    # 4. 判断是否需要语义搜索
    if self.enable_ai_search and len(exact_results) < 8:
        remaining = self.search_service.get_remaining_for_semantic(
            text, all_accounts, sync_results
        )
        if remaining:
            app_names = [acc.app_name for acc in remaining if acc.app_name]
            task_id = self._ai_manager.semantic_search_async(text, app_names)
            self._pending_search_id = task_id
            self._pending_remaining_accounts = remaining
```

**新增回调方法：**
```python
def _on_ai_search_finished(self, task_id: str, result: list):
    """AI 语义搜索完成回调"""
    if task_id != self._pending_search_id:
        return  # 丢弃过期任务结果
    
    self._pending_search_id = None
    
    # result: [(app_name, confidence), ...]
    semantic_results = self._parse_semantic_results(result)
    
    if semantic_results:
        self._append_ai_results(semantic_results)
    else:
        self._append_ai_no_result_tip()

def _on_ai_search_failed(self, task_id: str, error: str):
    """AI 语义搜索失败回调"""
    if task_id != self._pending_search_id:
        return
    
    self._pending_search_id = None
    self._append_ai_error_tip(error)
```

---

## 五、竞态条件与边界处理

### 5.1 快速输入（Debouncing）

**场景：** 用户在 500ms 内连续输入 "支" → "支付" → "支付宝"

**处理：**
- 每次 `on_search()` 都将 `_pending_search_id = None`
- 旧任务的 `task_finished` 信号到来时，发现 `task_id != _pending_search_id`，直接丢弃
- UI 只展示最后一次输入的搜索结果

### 5.2 AI 结果返回前清空搜索框

**场景：** 用户输入"支付"后，在 AI 结果返回前按 Esc 或清空搜索框

**处理：**
- 清空搜索框时，`on_search()` 会重新执行，`_pending_search_id` 被重置
- AI 结果回调中比对 `task_id`，过期则丢弃，不会错误追加到当前列表

### 5.3 AI 结果返回前切换分类/保险库

**场景：** 用户在 AI 搜索进行中点击左侧分类切换或 tabs 切换保险库

**处理：**
- 切换保险库时，清空 `_pending_search_id = None`
- AI 结果回调中比对 `task_id`，过期则丢弃
- 列表已被新分类/保险库的内容覆盖，不会出现串结果

### 5.4 Ollama 不可用

**场景：** AI 搜索开关开启，但 Ollama 未启动

**处理：**
- `AIServiceManager.semantic_search_async()` 仍会提交任务
- `AIWorkerThread` 探测到 Ollama 不可用，`task_failed` 信号发射
- `_on_ai_search_failed()` 在列表底部追加灰色提示行："AI 增强搜索暂不可用（Ollama 未启动）"
- 不弹窗、不打断用户操作

### 5.5 语义结果为空

**场景：** AI 返回 "无 | 0.0" 或所有置信度 < 0.6

**处理：**
- 不渲染 "AI增强" 分区头
- 可选：在列表底部追加一行灰色提示 "AI 未找到更多相关结果"

---

## 六、实现步骤

### Step 1: 修改 SearchService
- [ ] 将 `search()` 中的语义搜索逻辑（第 105-141 行）全部删除
- [ ] 新增 `get_remaining_for_semantic(query, accounts, existing_results)` 方法
- [ ] 确认精确+拼音匹配逻辑不受影响
- [ ] 将精确匹配触发语义搜索的阈值从 `< 5` 改为 `< 8`（在 MainWindow 中控制）

### Step 2: 修改 MainWindow.__init__
- [ ] 新增成员：`self._pending_search_id = None`
- [ ] 连接信号：`self._ai_manager.task_finished.connect(self._on_ai_search_finished)`
- [ ] 连接信号：`self._ai_manager.task_failed.connect(self._on_ai_search_failed)`

### Step 3: 重构 MainWindow.on_search()
- [ ] 先取消之前的 AI 搜索：`self._pending_search_id = None`
- [ ] 调用 `search_service.search_sync()` 获取精确/拼音结果
- [ ] 立即调用 `self._display_search_results(exact_results, ai_results=[])`
- [ ] 判断 `len(exact_results) < 8 and self.enable_ai_search`
- [ ] 若满足，调用 `self._ai_manager.semantic_search_async()`，记录 task_id

### Step 4: 新增 AI 结果回调
- [ ] `_on_ai_search_finished(task_id, result)`：解析结果，追加到列表
- [ ] `_on_ai_search_failed(task_id, error)`：显示失败提示
- [ ] `_append_ai_results(semantic_results)`：动态插入"AI增强"分区 + 结果项
- [ ] `_append_ai_error_tip(error)`：插入灰色提示行

### Step 5: 清理与测试
- [ ] 移除 `search_service.py` 中对 `ai.ollama_client` 的导入
- [ ] 验证精确搜索正常
- [ ] 验证 AI 搜索结果能正确追加
- [ ] 验证快速输入时不会串结果
- [ ] 验证 Ollama 不可用时给出友好提示

---

## 七、回退方案

如果异步重构引入不可预期的 bug，可快速回退到以下状态：

1. `SearchService.search()` 恢复语义搜索逻辑（从 git 历史恢复）
2. `MainWindow` 移除 `_pending_search_id` 和 AI 回调
3. 仅保留阈值调整（`< 5` → `< 8`）

回退后搜索功能仍可用，只是恢复为同步阻塞模式。

---

## 八、附录：关键代码片段（目标态）

### SearchService.search_sync()（目标）

```python
def search(self, query: str, accounts: List[Account] = None) -> List[SearchResult]:
    """同步搜索：仅精确匹配 + 拼音匹配，不包含语义搜索"""
    if not query or not query.strip():
        ...
    
    query = query.strip().lower()
    results = []
    
    # 第一层：精确匹配
    for account in accounts:
        match_info = self._exact_match(query, account)
        if match_info:
            results.append(SearchResult(account, 'exact', match_info[1], match_info[0]))
    
    # 第二层：拼音匹配
    if not results or query.isalpha():
        for account in accounts:
            if any(r.account.id == account.id for r in results):
                continue
            match_info = self._pinyin_match(query, account)
            if match_info:
                results.append(SearchResult(account, 'pinyin', match_info[1], match_info[0]))
    
    return results

def get_remaining_for_semantic(self, accounts: List[Account], 
                                existing_results: List[SearchResult]) -> List[Account]:
    """返回语义搜索候选账号（排除已匹配的）"""
    matched_ids = {r.account.id for r in existing_results}
    return [acc for acc in accounts if acc.id not in matched_ids]
```

### MainWindow.on_search()（目标）

```python
def on_search(self):
    text = self.search_box.text().strip()
    if not text:
        self.load_accounts()
        return
    
    # 取消之前的 AI 搜索
    self._pending_search_id = None
    
    if self.current_vault == 'accounts':
        all_accounts = self._get_cached_accounts()
        
        # 同步搜索
        sync_results = self.search_service.search(text, all_accounts)
        exact_results = [r for r in sync_results if r.match_type in ('exact', 'pinyin')]
        
        # 立即渲染
        self._display_search_results(exact_results, ai_results=[])
        
        # 异步语义搜索
        if self.enable_ai_search and len(exact_results) < 8:
            remaining = self.search_service.get_remaining_for_semantic(all_accounts, sync_results)
            if remaining:
                app_names = [acc.app_name for acc in remaining if acc.app_name]
                self._pending_search_id = self._ai_manager.semantic_search_async(text, app_names)
                self._pending_remaining_accounts = remaining
```

### MainWindow._on_ai_search_finished()（目标）

```python
def _on_ai_search_finished(self, task_id: str, result: list):
    if task_id != self._pending_search_id:
        return  # 丢弃过期结果
    
    self._pending_search_id = None
    semantic_results = []
    
    for app_name, confidence in result:
        if confidence >= 0.6:
            for account in self._pending_remaining_accounts:
                if account.app_name == app_name:
                    semantic_results.append(
                        SearchResult(account, 'semantic', confidence, 'app_name')
                    )
                    break
    
    if semantic_results:
        self._append_ai_results(semantic_results)
```

---

*文档版本: v1.0*
*日期: 2025-04-25*
