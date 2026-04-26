# 0426 AI Agent 改造与全量 Bug 修复实施文档

> 版本：v1.0  
> 日期：2026-04-26  
> 用途：基于项目实际代码状态，将需求文档转化为可直接执行的开发指令  
> 基线：PyQt6 + Ollama(gemma4:4b) + 双库 SQLite + 当前代码树

---

## 一、需求摘要与现状差距分析

### 1.1 核心需求（来自 v3.1 需求文档）

| 需求项 | 内容 | 优先级 |
|--------|------|--------|
| ReAct Agent 改造 | 从"文本解析模式"演进为"单步 ReAct Tool Calling Agent 模式" | P0 |
| 29 个 Tool | 语义搜索(4) + 批量新增(2) + 批量更新(8) + 批量删除(2) + 智能整理(4) + 查询统计(5) + 辅助生成(4) | P0 |
| 权限分级 | 🟢全自动 / 🟡预览确认 / 🔴二次确认 / ⛔禁止 AI | P0 |
| 预览标准 | 统一 preview_data 结构，字段对齐，密码掩码 | P0 |
| ReAct 状态机 | 暂停-确认-恢复，AWAITING_PREVIEW 状态下禁止新消息 | P0 |
| Bug 修复(6项) | 列表截断、AI预热、预览字段缺失、指代消解、网址库空白、网址库 AI 失效 | P1 |

### 1.2 实际代码现状 vs 目标差距

| 模块 | 当前状态 | 目标状态 | 差距评估 |
|------|---------|---------|---------|
| `ai/ollama_client.py` | `generate` / `generate_stream` / `parse_command` / `semantic_match` | 新增 `generate_tool_call(prompt, tools)`，要求严格 JSON 输出 | 中 |
| `services/ai_assistant_service.py` | 文本解析模式：`process_query` → `ollama.parse_command` → 正则提取 `<思考>` / `<动作>` / `<回复>` | ReAct 循环：最多 5 轮 Tool Call → Observation → 下一轮 | **大** |
| `services/conversation_context.py` | `TurnSnapshot` + `ReferenceResolver`（指代消解未激活） | 新增 `add_observation()` + `_db_summary_loaded` 标志 + 激活 `ReferenceResolver` | 中 |
| `services/ai_tools.py` | **不存在** | 新建：29 个 Tool 类 + `ToolRegistry` 装饰器注册 | **大** |
| `ui/main_window.py` | `ActionPreviewWidget`(L485-710) + `BatchAddPreviewWidget` | 改造为统一 preview_data 渲染；ReAct 暂停-确认-恢复状态机 | **大** |
| `ui/batch_add_preview_widget.py` | 现有表格模型支持 accounts/urls 列 | 支持 6.1 标准 preview_data 结构，密码掩码+切换 | 中 |

### 1.3 代码级 Bug 根因（已定位）

| Bug | 根因位置 | 根因描述 | 修复复杂度 |
|-----|---------|---------|-----------|
| **Bug 1：列表渲染截断** | `ui/main_window.py` `load_accounts()` L1678-1688 | `if idx % 20 == 0:` 缩进错误导致每 20 条账号才创建 1 个 `QListWidgetItem`，其余循环复用同一 item 反复 add/setWidget | **1行修复** |
| **Bug 5：网址库空白** | `ui/main_window.py` `__init__()` L731 | `AIAssistantService(db_manager)` **未传入 `url_db_manager`**，导致 `self.url_db=None`，`build_db_summary` 和 `semantic_query` 对网址库直接返回空 | **1行修复** |
| **Bug 6：网址库 AI 失效** | 同 Bug 5 | `AIAssistantService.url_db=None` 导致所有网址库 AI 操作无数据 | 随 Bug 5 修复 |
| Bug 2：AI 预热 | `ui/main_window.py` `on_ai_send_message()` / `services/ai_assistant_service.py` `process_query_stream()` | 首次输入直接进入完整 ReAct 循环，未做 `build_db_summary` 预加载分离 | 中 |
| Bug 3：预览字段缺失 | `services/ai_assistant_service.py` `build_action_preview()` | batch_add 类型的 preview_items 仅含占位文本，未展开具体字段值 | 中 |
| Bug 4：指代消解失效 | `services/conversation_context.py` `ReferenceResolver.resolve()` | 方法已存在但 `process_query` 中仅注入 scope_hint，未将历史实体 ID 绑定到 Tool 执行 | 中 |

---

## 二、任务清单（按执行顺序与依赖关系排序）

### Phase 1：紧急 Bug 修复（零依赖，可独立验证）

| # | 任务 | 文件 | 预估工时 |
|---|------|------|---------|
| 1.1 | **修复列表渲染截断**：删除 `load_accounts()` 中 `if idx % 20 == 0:` 错误缩进 | `ui/main_window.py` | 10min |
| 1.2 | **修复网址库空白**：`AIAssistantService` 初始化传入 `_url_db`；调整初始化顺序 | `ui/main_window.py` | 15min |
| 1.3 | **修复网址库 AI 失效**：验证 Bug 1.2 修复后 `build_db_summary('urls')` 和 `semantic_query('urls')` 正常 | `services/ai_assistant_service.py` | 15min |

### Phase 2：基础设施建设（Phase 1 完成后）

| # | 任务 | 文件 | 依赖 | 预估工时 |
|---|------|------|------|---------|
| 2.1 | 新建 `services/ai_tools.py`：定义 `AITool` 基类、`ToolRegistry` 装饰器、权限枚举 | `services/ai_tools.py` | 无 | 1h |
| 2.2 | 实现 🟢 只读 Tool（语义搜索 4 + 查询统计 5 + 辅助生成 3 = 12 个） | `services/ai_tools.py` | 2.1 | 2h |
| 2.3 | 实现 🟡 预览 Tool（批量新增 2 + 批量更新 8 + 智能整理 4 = 14 个） | `services/ai_tools.py` | 2.1 | 3h |
| 2.4 | 实现 🔴 二次确认 Tool（批量删除 2 + generate_password 1 = 3 个） | `services/ai_tools.py` | 2.1 | 1h |
| 2.5 | `ollama_client.py` 新增 `generate_tool_call()`：Prompt 要求严格 JSON，保留 `_extract_command` 容错 | `ai/ollama_client.py` | 无 | 1h |
| 2.6 | `conversation_context.py` 新增 `add_observation()` + `_db_summary_loaded` 标志 + `_db_summary_cache` | `services/conversation_context.py` | 无 | 45min |

### Phase 3：AI Assistant 核心改造（Phase 2 完成后）

| # | 任务 | 文件 | 依赖 | 预估工时 |
|---|------|------|------|---------|
| 3.1 | `ai_assistant_service.py` 重构 `process_query()` → `process_react_query()` ReAct 主循环（最多 5 轮） | `services/ai_assistant_service.py` | 2.1-2.6 | 3h |
| 3.2 | `build_action_preview()` 改造：所有 Tool 返回统一 `preview_data` 结构（6.1 标准） | `services/ai_assistant_service.py` | 2.3 | 2h |
| 3.3 | `execute_build_action_with_transaction()` 改造：接收 `confirmed_items` 而非自行构建 | `services/ai_assistant_service.py` | 3.2 | 1h |
| 3.4 | Bug 2 修复：首次交互预热逻辑，`_db_summary_loaded` 标志控制 | `services/ai_assistant_service.py` + `ui/main_window.py` | 2.6 | 1h |
| 3.5 | Bug 4 修复：`ReferenceResolver` 激活，Observation 中注入历史实体 ID | `services/ai_assistant_service.py` + `services/conversation_context.py` | 2.6 | 1.5h |

### Phase 4：UI 预览对接与状态机（Phase 3 完成后）

| # | 任务 | 文件 | 依赖 | 预估工时 |
|---|------|------|------|---------|
| 4.1 | `ActionPreviewWidget` 改造：`set_preview_data(preview_data)` 动态构建表格，支持全部 operation_type | `ui/main_window.py` | 3.2 | 2h |
| 4.2 | `BatchAddPreviewWidget` 改造：支持 6.1 标准 preview_data，密码掩码+切换按钮 | `ui/batch_add_preview_widget.py` | 3.2 | 1.5h |
| 4.3 | `MainWindow` 实现 ReAct 状态机：`AWAITING_PREVIEW` → `CONFIRMED`/`CANCELLED` | `ui/main_window.py` | 3.1, 4.1, 4.2 | 2.5h |
| 4.4 | `MainWindow._on_ai_query_finished()` 改造：分发 ReAct 结果（direct_answer / preview / error） | `ui/main_window.py` | 3.1, 4.3 | 1.5h |
| 4.5 | Bug 3 修复：`build_action_preview()` 对 batch_add 展开具体字段值 | `services/ai_assistant_service.py` | 4.1 | 随 3.2 完成 |

### Phase 5：验证与调优

| # | 任务 | 内容 |
|---|------|------|
| 5.1 | 单 Tool 单元测试 | 每个 Tool 的 execute() 独立测试，验证 preview_data 格式 |
| 5.2 | ReAct 循环集成测试 | 模拟 1-5 轮循环，验证 Observation 注入和状态机 |
| 5.3 | 双库端到端测试 | 密码库 + 网址库分别测试全部 29 个 Tool |
| 5.4 | 预览对接测试 | 验证 ActionPreviewWidget / BatchAddPreviewWidget 渲染完整、勾选、确认、取消 |
| 5.5 | 边界测试 | 空数据、超长内容、>50条删除、网络断开、JSON 解析失败 |

---

## 三、总体规划

### 3.1 架构演进路线（当前 → 目标）

```
当前架构：
  用户输入 → ai_assistant_service.process_query() 
    → ollama.parse_command() 【单次调用，正则提取 <思考>/<动作>/<回复>】
    → 返回 {action, params, response, semantic_result}
    → MainWindow 根据 action 类型分发（search直接高亮 / write操作展示预览）

目标架构：
  用户输入 → ai_assistant_service.process_react_query()
    → _build_react_prompt() 【含历史 Observation + Tool Schema】
    → ollama.generate_tool_call() 【严格 JSON: {thought, tool, params}】
    → ToolRegistry.get(tool) → tool.execute(params)
      ├─ 🟢 只读 Tool → 返回 result → add_observation() → 继续下一轮
      ├─ 🟡 预览 Tool → 返回 preview_data → MainWindow 展示预览 → 用户确认
      │                → 恢复循环 或 终止
      ├─ 🔴 删除 Tool → 返回 preview_data → ActionPreviewWidget → (>50二次确认)
      │                → 用户确认 → soft_delete + audit_log → add_observation()
      └─ direct_answer → 返回最终 response → 结束循环
    
    循环上限：max_turns=5，超限自动终止
```

### 3.2 文件变更矩阵

| 文件 | 变更类型 | 变更内容 | 影响范围 |
|------|---------|---------|---------|
| `services/ai_tools.py` | **新建** | 29 Tool + ToolRegistry + AITool 基类 | 全链路 |
| `ai/ollama_client.py` | 新增方法 | `generate_tool_call()` + JSON Schema 校验 | AI 调用层 |
| `services/ai_assistant_service.py` | **重度重构** | `process_query` → `process_react_query`；`build_action_preview` 输出标准结构 | 核心逻辑 |
| `services/conversation_context.py` | 新增方法 | `add_observation()`；`_db_summary_loaded`；`_db_summary_cache` | 上下文管理 |
| `ui/main_window.py` | **重度改造** | Bug 1/2/5 修复；`ActionPreviewWidget` 支持动态表格；ReAct 状态机 | 主 UI |
| `ui/batch_add_preview_widget.py` | 中度改造 | `set_preview_data()` 标准接口；密码掩码 | 预览组件 |
| `services/ai_worker_thread.py` | 无变更 | 保持现有任务队列机制 | — |
| `services/ai_service_manager.py` | 无变更 | 保持现有单例 + 信号机制 | — |
| `core/crypto.py` | 无变更 | 保持现有加密逻辑 | — |
| `core/database.py` | 无变更 | 保持现有软删除 + audit_log | — |
| `core/repositories.py` | 无变更 | 保持现有 Repository 抽象 | — |

### 3.3 核心类关系图（目标状态）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              UI 层                                       │
│  MainWindow ──→ ActionPreviewWidget (set_preview_data)                  │
│       │    ──→ BatchAddPreviewWidget (set_preview_data)                 │
│       │    ──→ AIQueryThread                                            │
│       ↓                                                                 │
│  ReActState Enum: RUNNING / AWAITING_PREVIEW / CONFIRMED / CANCELLED   │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↑↓
┌─────────────────────────────────────────────────────────────────────────┐
│                         AI Assistant Service                             │
│  AIAssistantService                                                      │
│    ├─ process_react_query(query, mode, max_turns=5)                     │
│    │    ├─ _build_react_prompt() ← 含 Observation 历史                  │
│    │    ├─ ollama.generate_tool_call()                                  │
│    │    ├─ ToolRegistry.get(tool).execute()                             │
│    │    ├─ build_action_preview() → 标准化 preview_data                 │
│    │    └─ execute_build_action_with_transaction(confirmed_items)       │
│    ├─ conversation_context: ConversationContext                         │
│    │    ├─ add_observation()                                            │
│    │    ├─ _db_summary_loaded / _db_summary_cache                       │
│    │    └─ ReferenceResolver.resolve()                                  │
│    └─ _history (兼容旧代码)                                              │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↑↓
┌─────────────────────────────────────────────────────────────────────────┐
│                         Tool 层 (新建)                                    │
│  ToolRegistry (装饰器注册)                                               │
│    ├─ @ToolRegistry.register("semantic_search_accounts")                │
│    ├─ @ToolRegistry.register("batch_add_accounts")                      │
│    ├─ @ToolRegistry.register("batch_delete_accounts")                   │
│    └─ ... 共 29 个                                                       │
│                                                                          │
│  每个 Tool 类：                                                           │
│    - name: str                                                           │
│    - readonly: bool                                                      │
│    - need_preview: bool                                                  │
│    - need_confirm: bool                                                  │
│    - execute(params, context) -> result_dict                             │
│    - result_dict 必须包含 preview_data（need_preview=True 时）           │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↑↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       Ollama Client 层                                   │
│  OllamaClient                                                            │
│    ├─ generate_tool_call(prompt, tools)                                  │
│    │    → Prompt 注入 Tool Schema                                         │
│    │    → 要求严格 JSON 输出 {thought, tool, params}                     │
│    │    → _extract_command 容错提取                                       │
│    ├─ semantic_match() 【现有，复用】                                     │
│    └─ generate() / generate_stream() 【现有，保留】                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 四、具体细节规划

### 4.1 Phase 1：紧急 Bug 修复（根因已定位）

#### 4.1.1 Bug 1：列表渲染截断

**根因**：`ui/main_window.py` L1678-1680
```python
for idx, account in enumerate(accounts):
    if idx % 20 == 0:          # ← 错误：应为每条都创建 item
                item = QListWidgetItem()
    item.setSizeHint(...)      # ← 当 idx%20!=0 时，复用同一 item
```

**修复**：删除 `if idx % 20 == 0:` 及其缩进，改为：
```python
for idx, account in enumerate(accounts):
    item = QListWidgetItem()
    item.setSizeHint(QSize(self.account_list.width() - 20, 56))
    item.setData(Qt.ItemDataRole.UserRole, account)
    self.account_list.addItem(item)
    
    widget = AccountListItem(account, selection_mode=self._selection_mode)
    if self._selection_mode and account.id in self._selected_ids:
        widget.set_checked(True)
    self.account_list.setItemWidget(item, widget)
```

**验证**：在数据库中插入 30 条测试账号，确认列表完整渲染 30 条，可滚动。

#### 4.1.2 Bug 5：网址库空白 + Bug 6：网址库 AI 失效

**根因**：`ui/main_window.py` L731
```python
self.ai_assistant = AIAssistantService(db_manager)
# 未传入第二个参数 url_db_manager
```

而 `_url_db` 直到 L788 才初始化：
```python
self._url_db = URLDatabaseManager(str(url_db_path))
```

**修复**：调整初始化顺序，在 `_url_db` 创建后重新设置 `ai_assistant.url_db`：
```python
# L731 保持兼容：
self.ai_assistant = AIAssistantService(db_manager)

# L788-789 之后增加：
self.ai_assistant.url_db = self._url_db
```

或在 L788 之后重建 `ai_assistant`（更安全，避免中间状态不一致）：
```python
# 延迟初始化 ai_assistant 到 _url_db 创建之后
# 将 L731 的初始化移到 L789 之后
self.ai_assistant = AIAssistantService(db_manager, self._url_db)
```

**推荐方案**：将 `ai_assistant` 的初始化从 L731 后移到 L789 之后。

**验证**：
1. 切换至网址库标签页，确认 248 条网址正常渲染
2. 向 AI 助手输入"列出所有网址"，确认 `build_db_summary('urls')` 返回非空摘要

---

### 4.2 Phase 2：基础设施

#### 4.2.1 新建 `services/ai_tools.py`

**文件定位**：`services/ai_tools.py`（新建，约 800-1200 行）

**核心设计**：

```python
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass


class PermissionLevel(Enum):
    READONLY = "readonly"      # 🟢 全自动
    PREVIEW = "preview"        # 🟡 预览确认
    CONFIRM = "confirm"        # 🔴 二次确认
    FORBIDDEN = "forbidden"    # ⛔ 禁止 AI


@dataclass
class ToolResult:
    """Tool 执行结果统一包装"""
    success: bool
    data: Any = None           # 执行结果数据
    preview_data: Optional[Dict] = None  # 需要预览时的标准结构
    error: str = ""
    message: str = ""          # 给用户的自然语言说明


class AITool:
    """Tool 基类"""
    name: str = ""
    description: str = ""
    permission: PermissionLevel = PermissionLevel.READONLY
    params_schema: Dict[str, Any] = {}  # JSON Schema 参数定义
    
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        raise NotImplementedError
    
    def validate_params(self, params: Dict) -> (bool, str):
        """参数 Schema 校验"""
        # 基础校验：检查必填字段
        for key, config in self.params_schema.items():
            if config.get("required", False) and key not in params:
                return False, f"缺少必填参数: {key}"
        return True, ""


class ToolRegistry:
    """Tool 注册表（装饰器模式）"""
    _tools: Dict[str, AITool] = {}
    
    @classmethod
    def register(cls, name: str, description: str = "", 
                 permission: PermissionLevel = PermissionLevel.READONLY,
                 params_schema: Dict = None):
        def decorator(tool_class):
            tool_instance = tool_class()
            tool_instance.name = name
            tool_instance.description = description
            tool_instance.permission = permission
            tool_instance.params_schema = params_schema or {}
            cls._tools[name] = tool_instance
            return tool_class
        return decorator
    
    @classmethod
    def get(cls, name: str) -> Optional[AITool]:
        return cls._tools.get(name)
    
    @classmethod
    def list(cls) -> List[Dict]:
        """返回 Tool 列表（供 Prompt 注入）"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "permission": t.permission.value,
                "params_schema": t.params_schema
            }
            for t in cls._tools.values()
        ]
    
    @classmethod
    def list_for_prompt(cls) -> str:
        """生成 Prompt 可用的 Tool 描述文本"""
        lines = ["你可以调用以下工具："]
        for t in cls._tools.values():
            perm_icon = {"readonly": "🟢", "preview": "🟡", "confirm": "🔴"}.get(t.permission.value, "")
            lines.append(f"- {t.name} {perm_icon}: {t.description}")
            if t.params_schema:
                lines.append(f"  参数: {json.dumps(t.params_schema, ensure_ascii=False)}")
        return "\n".join(lines)
```

**29 个 Tool 实现顺序**：

由于全部展开篇幅过大，此处给出**关键 Tool 的伪代码模板**和**全部 Tool 的签名清单**。实际编码时按此清单逐一实现。

**关键模板：语义搜索 Tool**

```python
@ToolRegistry.register(
    "semantic_search_accounts",
    description="基于语义理解搜索账号，返回最相关的账号ID列表",
    permission=PermissionLevel.READONLY,
    params_schema={
        "query": {"type": "string", "required": True, "description": "用户搜索意图"},
        "top_k": {"type": "integer", "required": False, "default": 10}
    }
)
class SemanticSearchAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        query = params.get("query", "")
        top_k = params.get("top_k", 10)
        
        # 从 context 获取 accounts 缓存
        accounts = context.get("accounts", [])
        if not accounts:
            return ToolResult(success=True, data=[], message="数据库为空")
        
        # 构建摘要
        lines = []
        for acc in accounts:
            tags_str = ""
            if acc.tags:
                try:
                    tags = json.loads(acc.tags) if isinstance(acc.tags, str) else acc.tags
                    tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
                except:
                    tags_str = str(acc.tags)
            lines.append(f"{acc.id} | {acc.app_name} | {acc.category or '未分类'} | {tags_str} | {(acc.remark or '')[:20]}")
        
        items_summary = "\n".join(lines)
        
        # 调用 OllamaClient.semantic_match
        from ai.ollama_client import OllamaClient
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        state = ai_manager.get_state()
        ollama = OllamaClient(model=state.model_name or "gemma4:4b")
        result = ollama.semantic_match(query, items_summary)
        
        matched_ids = result.get("matched_ids", [])[:top_k]
        return ToolResult(
            success=True,
            data={"matched_ids": matched_ids, "reasoning": result.get("reasoning", "")},
            message=f"找到 {len(matched_ids)} 条相关账号"
        )
```

**关键模板：批量新增 Tool（🟡 预览）**

```python
@ToolRegistry.register(
    "batch_add_accounts",
    description="批量新增账号到密码库",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "items": {"type": "array", "required": True, "description": "账号列表，每个元素包含 app_name, username, password 等字段"}
    }
)
class BatchAddAccountsTool(AITool):
    MAX_ITEMS = 50
    
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        items = params.get("items", [])
        if len(items) > self.MAX_ITEMS:
            return ToolResult(success=False, error=f"单次最多新增 {self.MAX_ITEMS} 条")
        
        # 构建标准 preview_data
        preview_items = []
        for idx, item in enumerate(items):
            preview_items.append({
                "row_id": f"temp_{idx:03d}",
                "display_name": item.get("app_name", ""),
                "secondary_name": item.get("username", ""),
                "fields": [
                    {"field_name": "应用名", "old_value": "-", "new_value": item.get("app_name", "")},
                    {"field_name": "用户名", "old_value": "-", "new_value": item.get("username", "")},
                    {"field_name": "密码", "old_value": "-", "new_value": item.get("password", "")},
                    {"field_name": "分类", "old_value": "-", "new_value": item.get("category", "其他")},
                    {"field_name": "备注", "old_value": "-", "new_value": item.get("remark", "")},
                    {"field_name": "标签", "old_value": "-", "new_value": ",".join(item.get("tags", []))},
                ],
                "raw_data": item
            })
        
        preview_data = {
            "operation_type": "add",
            "target_vault": "account",
            "total_items": len(preview_items),
            "items": preview_items
        }
        
        return ToolResult(
            success=True,
            data={"items": items},
            preview_data=preview_data,
            message=f"准备新增 {len(items)} 个账号"
        )
```

**29 个 Tool 完整签名清单**：

```python
# === 语义搜索类（4个）===
semantic_search_accounts(query, top_k=10) → ToolResult(data={matched_ids, reasoning})
semantic_search_urls(query, top_k=10) → ToolResult(data={matched_ids, reasoning})
semantic_filter_accounts(condition) → ToolResult(data={matched_ids, reasoning})
semantic_filter_urls(condition) → ToolResult(data={matched_ids, reasoning})

# === 批量新增类（2个）===
batch_add_accounts(items: List[Dict]) → ToolResult(preview_data={operation_type:"add", target_vault:"account"})
batch_add_urls(items: List[Dict]) → ToolResult(preview_data={operation_type:"add", target_vault:"url"})

# === 批量更新类（8个）===
batch_update_accounts(updates: [{identifier, match_field?, field, new_value}]) → ToolResult(preview_data={operation_type:"update"})
batch_update_urls(updates: [{identifier, match_field?, field, new_value}]) → ToolResult(preview_data={operation_type:"update"})
batch_reorganize_accounts(mappings: [{identifier, new_category}]) → ToolResult(preview_data={operation_type:"reorganize"})
batch_reorganize_urls(mappings: [{identifier, new_category}]) → ToolResult(preview_data={operation_type:"reorganize"})
batch_add_remark_accounts(items: [{identifier, remark}]) → ToolResult(preview_data={operation_type:"update"})
batch_add_remark_urls(items: [{identifier, remark}]) → ToolResult(preview_data={operation_type:"update"})
batch_add_tags_accounts(items: [{identifier, tags:[]}]) → ToolResult(preview_data={operation_type:"update"})
batch_add_tags_urls(items: [{identifier, tags:[]}]) → ToolResult(preview_data={operation_type:"update"})

# === 批量删除类（2个）===
batch_delete_accounts(identifiers:[], match_field="app_name") → ToolResult(preview_data={operation_type:"delete"})
batch_delete_urls(identifiers:[], match_field="title") → ToolResult(preview_data={operation_type:"delete"})

# === 智能整理类（4个）===
smart_classify_accounts(strategy="auto") → ToolResult(preview_data={operation_type:"classify"})
smart_classify_urls(strategy="auto") → ToolResult(preview_data={operation_type:"classify"})
smart_merge_duplicate_accounts(threshold=0.85) → ToolResult(preview_data={operation_type:"merge"})
smart_merge_duplicate_urls(threshold=0.85) → ToolResult(preview_data={operation_type:"merge"})

# === 查询统计类（5个）===
get_account_detail(identifier, match_field="app_name") → ToolResult(data={...})
get_url_detail(identifier, match_field="title") → ToolResult(data={...})
list_all_categories(vault_type) → ToolResult(data={categories:[]})
get_statistics(vault_type) → ToolResult(data={total, category_dist, ...})
get_recent_changes(limit=10) → ToolResult(data={changes:[]})

# === 辅助生成类（4个）===
generate_account_remark(app_name, url?, category?) → ToolResult(data={remark})
generate_url_remark(title, url, category?) → ToolResult(data={remark})
generate_password(length=16, has_special=true) → ToolResult(data={password})
check_password_strength(password) → ToolResult(data={score, level})
```

#### 4.2.2 `ai/ollama_client.py` 新增 `generate_tool_call()`

**新增方法签名**：
```python
def generate_tool_call(self, query: str, db_summary: str, 
                       observations: List[Dict], tools: List[Dict],
                       temperature: float = 0.2) -> Dict:
    """
    生成 Tool Call 决策。
    
    Returns:
        {
            "thought": "思考过程",
            "tool": "tool_name 或 direct_answer",
            "params": {...},
            "response": "direct_answer 时的回复文本"
        }
    """
```

**Prompt 模板**：
```python
TOOL_CALL_PROMPT = """你是密码保险箱 AI 助手"炽阳"。你拥有调用工具的能力，每轮必须且只能输出一个工具调用或最终回答。

当前数据库摘要：
{db_summary}

历史执行记录（Observation）：
{observations}

可用工具列表：
{tools_desc}

重要规则：
1. 如果任务已完成，输出 tool="direct_answer" 并给出最终回复
2. 如果还需要操作，输出 tool="工具名" 和具体 params
3. params 必须严格匹配工具定义的 schema
4. 禁止输出任何工具定义外的内容
5. 对于批量操作，优先使用 batch_* 工具而非单条操作
6. 语义搜索必须使用 semantic_search_* 工具，禁止自行推断

输出格式（严格 JSON，不要 markdown 代码块）：
{{"thought": "...", "tool": "...", "params": {{...}}}}

当任务完成时：
{{"thought": "任务已完成", "tool": "direct_answer", "response": "..."}}

用户当前输入：{query}
"""
```

**容错机制**：
- 模型可能输出 markdown 代码块（```json ... ```），需 strip
- 模型可能遗漏 `"tool"` 字段，默认降级为 `"direct_answer"`
- `params` 解析失败时返回 `{}` 并附带错误信息
- 复用现有 `_extract_command` 的括号深度计数法做 JSON 容错提取

#### 4.2.3 `conversation_context.py` 改造

**新增内容**：

```python
@dataclass
class Observation:
    """Tool 执行观测记录"""
    turn: int
    tool: str
    params: Dict
    result: Any
    timestamp: float = field(default_factory=time.time)

class ConversationContext:
    def __init__(self, max_turns=6, idle_timeout=300):
        self.history: deque[TurnSnapshot] = deque(maxlen=max_turns)
        self.observations: deque[Observation] = deque(maxlen=max_turns)  # 新增
        self.last_active_timestamp = time.time()
        self.idle_timeout = idle_timeout
        self.current_vault_type: Optional[str] = None
        
        # Bug 2 修复：数据库摘要预热标志
        self._db_summary_loaded: bool = False
        self._db_summary_cache: Optional[str] = None
        self._db_summary_vault_type: Optional[str] = None
    
    def add_observation(self, tool: str, params: Dict, result: Any, turn: int):
        """记录一轮 Tool 执行结果"""
        self.observations.append(Observation(
            turn=turn, tool=tool, params=params, result=result
        ))
        self.last_active_timestamp = time.time()
    
    def get_observations_text(self, max_count: int = 5) -> str:
        """将最近 N 条 Observation 序列化为文本供 Prompt 使用"""
        lines = []
        for obs in list(self.observations)[-max_count:]:
            result_summary = str(obs.result)[:200]
            lines.append(f"[Round {obs.turn}] Tool: {obs.tool} | Params: {obs.params} | Result: {result_summary}")
        return "\n".join(lines)
    
    def set_db_summary(self, summary: str, vault_type: str):
        """缓存数据库摘要"""
        self._db_summary_loaded = True
        self._db_summary_cache = summary
        self._db_summary_vault_type = vault_type
    
    def get_db_summary(self, vault_type: str) -> Optional[str]:
        """获取缓存的数据库摘要（仅当 vault_type 匹配时）"""
        if self._db_summary_loaded and self._db_summary_vault_type == vault_type:
            return self._db_summary_cache
        return None
    
    def clear_db_summary(self):
        """清空数据库摘要缓存（用户点击'清空历史'时调用）"""
        self._db_summary_loaded = False
        self._db_summary_cache = None
        self._db_summary_vault_type = None
    
    def reset(self):
        """重置对话上下文（新增清空 observations 和 db_summary）"""
        self.history.clear()
        self.observations.clear()
        self.last_active_timestamp = time.time()
        self.current_vault_type = None
        self.clear_db_summary()
```

---

### 4.3 Phase 3：AI Assistant 核心改造

#### 4.3.1 `process_react_query()` 主循环

**新增方法**（保留旧 `process_query` 兼容）：

```python
def process_react_query(self, query: str, context_items: List = None,
                        mode: str = 'plan', vault_type: str = 'accounts',
                        max_turns: int = 5) -> Dict:
    """
    ReAct 主循环：最多 5 轮 Tool Call。
    
    Returns:
        {
            "success": bool,
            "done": bool,                    # 是否已完成
            "turns_used": int,               # 实际使用轮数
            "response": str,                 # 最终回复文本
            "preview": Dict or None,         # 需要预览时的 preview_data
            "awaiting_confirm": bool,        # 是否暂停等待用户确认
            "pending_tool": Dict or None,    # 待确认的 Tool 调用信息
            "observations": List,            # 完整的 Observation 历史
            "error": str
        }
    """
    # 1. 数据库摘要（使用缓存）
    db_summary = self.conversation_context.get_db_summary(vault_type)
    if db_summary is None:
        db_summary = self.build_db_summary(context_items, vault_type=vault_type, max_items=500)
        self.conversation_context.set_db_summary(db_summary, vault_type)
    
    # 2. 指代消解
    from services.conversation_context import ReferenceResolver
    enhanced_query, inherited_ids = ReferenceResolver.resolve(query, self.conversation_context)
    
    # 3. ReAct 循环
    for turn in range(max_turns):
        # 组装 Prompt
        observations_text = self.conversation_context.get_observations_text(max_count=5)
        tools_desc = ToolRegistry.list_for_prompt()
        
        prompt = f"""...（见 4.2.2 Prompt 模板）..."""
        
        # 调用模型
        from services.ai_service_manager import AIServiceManager
        from ai.ollama_client import OllamaClient
        ai_manager = AIServiceManager.instance()
        state = ai_manager.get_state()
        ollama = OllamaClient(model=state.model_name or "gemma4:4b")
        decision = ollama.generate_tool_call(
            query=enhanced_query,
            db_summary=db_summary,
            observations=observations_text,
            tools=ToolRegistry.list()
        )
        
        # direct_answer：结束循环
        if decision.get("tool") == "direct_answer":
            return {
                "success": True,
                "done": True,
                "turns_used": turn + 1,
                "response": decision.get("response", ""),
                "preview": None,
                "awaiting_confirm": False,
                "pending_tool": None,
                "observations": list(self.conversation_context.observations),
                "error": ""
            }
        
        # 获取 Tool
        tool = ToolRegistry.get(decision.get("tool", ""))
        if not tool:
            return {
                "success": False,
                "done": True,
                "turns_used": turn + 1,
                "response": f"未知工具：{decision.get('tool')}",
                "error": "unknown_tool"
            }
        
        # 权限检查（Plan 模式禁止写操作）
        if mode == "plan" and tool.permission != PermissionLevel.READONLY:
            return {
                "success": True,
                "done": True,
                "turns_used": turn + 1,
                "response": f"该操作（{tool.name}）需切换到 Build 模式并经您确认后执行。",
                "needs_switch": True,
                "error": ""
            }
        
        # 参数校验
        valid, err_msg = tool.validate_params(decision.get("params", {}))
        if not valid:
            self.conversation_context.add_observation(
                tool=tool.name,
                params=decision.get("params", {}),
                result={"error": err_msg},
                turn=turn + 1
            )
            continue  # 进入下一轮，让 AI 修正参数
        
        # 执行 Tool
        tool_context = {
            "accounts": context_items if vault_type == 'accounts' else None,
            "urls": context_items if vault_type == 'urls' else None,
            "vault_type": vault_type,
            "inherited_ids": inherited_ids,
            "db": self.db,
            "url_db": self.url_db,
            "repo": RepositoryFactory.get_repository(vault_type)
        }
        result = tool.execute(decision.get("params", {}), tool_context)
        
        # 🟡/🔴 需要预览：暂停循环
        if tool.permission in (PermissionLevel.PREVIEW, PermissionLevel.CONFIRM) and mode == "build":
            preview = self.build_action_preview_from_tool_result(result, tool)
            return {
                "success": True,
                "done": False,
                "turns_used": turn + 1,
                "response": decision.get("thought", ""),
                "preview": preview,
                "awaiting_confirm": True,
                "pending_tool": {
                    "tool": tool.name,
                    "params": decision.get("params", {})
                },
                "observations": list(self.conversation_context.observations),
                "error": ""
            }
        
        # 记录 Observation
        self.conversation_context.add_observation(
            tool=tool.name,
            params=decision.get("params", {}),
            result=result.data if result.success else {"error": result.error},
            turn=turn + 1
        )
        
        # 如果 Tool 执行失败，让 AI 知道
        if not result.success:
            # 直接进入下一轮循环，AI 会基于错误 Observation 调整策略
            continue
    
    # 防循环保护
    return {
        "success": True,
        "done": True,
        "turns_used": max_turns,
        "response": "操作步骤过多（已达5轮上限），已自动终止。建议您拆分指令分步执行。",
        "error": "max_turns_reached"
    }
```

#### 4.3.2 `build_action_preview()` 改造（统一 preview_data）

**核心改造**：不再根据 action 类型分别构建 preview，而是统一由 Tool 返回 `preview_data`，`build_action_preview` 只做封装和校验。

```python
def build_action_preview_from_tool_result(self, tool_result: ToolResult, tool: AITool) -> Dict:
    """
    将 Tool 返回的 preview_data 封装为 UI 可用的预览结构。
    做格式校验和默认值填充。
    """
    preview_data = tool_result.preview_data or {}
    
    # 校验必填字段
    if "operation_type" not in preview_data:
        preview_data["operation_type"] = "unknown"
    if "target_vault" not in preview_data:
        preview_data["target_vault"] = "account"
    if "total_items" not in preview_data:
        preview_data["total_items"] = len(preview_data.get("items", []))
    if "items" not in preview_data:
        preview_data["items"] = []
    
    # 校验每个 item 的字段
    for item in preview_data["items"]:
        if "row_id" not in item:
            item["row_id"] = str(uuid.uuid4())[:8]
        if "display_name" not in item:
            item["display_name"] = "未命名"
        if "fields" not in item:
            item["fields"] = []
        if "raw_data" not in item:
            item["raw_data"] = {}
    
    return {
        "preview_data": preview_data,
        "tool_name": tool.name,
        "tool_permission": tool.permission.value,
        "message": tool_result.message
    }
```

**Bug 3 修复**：`batch_add_accounts` Tool 的 `preview_data` 中 `fields` 必须包含具体字段值（见 4.2.1 模板），禁止 `"新增入库"` `"-"` `"account"` 等占位文本。

#### 4.3.3 `execute_build_action_with_transaction()` 改造

**改造要点**：
- 参数从 `(action_preview, user_query)` 改为 `(confirmed_items: List[Dict], tool_name: str, user_query: str)`
- `confirmed_items` 来自预览组件 `get_confirmed_items()`，即用户勾选后的 `raw_data` 列表
- 根据 `tool_name` 分发到具体执行逻辑
- 保留 audit_log 写入和软删除机制

```python
def execute_build_action_with_transaction(self, confirmed_items: List[Dict],
                                          tool_name: str, user_query: str) -> Dict:
    """
    执行用户确认的批量操作。
    
    Args:
        confirmed_items: 用户勾选的 raw_data 列表
        tool_name: 原始 Tool 名称
        user_query: 用户原始查询（用于 audit_log）
    """
    if not confirmed_items:
        return {"success": False, "error": "未选择任何条目"}
    
    repo = RepositoryFactory.get_repository(self.current_vault_type or 'accounts')
    
    # 二次确认：删除操作且 >50 条
    if tool_name in ('batch_delete_accounts', 'batch_delete_urls') and len(confirmed_items) > 50:
        return {
            "success": False,
            "needs_confirmation": True,
            "message": f"即将删除 {len(confirmed_items)} 条记录，是否确认？"
        }
    
    executed = 0
    errors = []
    
    for item in confirmed_items:
        try:
            if tool_name == 'batch_add_accounts':
                account = Account(**item)
                repo.insert(account.to_dict())
            elif tool_name == 'batch_add_urls':
                url_item = URLItem(**item)
                repo.insert(url_item.to_dict())
            elif tool_name.startswith('batch_update_'):
                # ... 根据 item 中的 identifier 和 field/new_value 更新
                pass
            elif tool_name.startswith('batch_delete_'):
                item_id = item.get('id')
                if item_id:
                    if self.current_vault_type == 'accounts':
                        account = repo.get_by_id(item_id)
                        self.db.soft_delete_account(item_id, account.to_dict())
                    else:
                        url_item = repo.get_by_id(item_id)
                        self.db.soft_delete_url(item_id, url_item.to_dict())
                        self.url_db.delete_url(item_id)
            # ... 其他 Tool 分发
            executed += 1
        except Exception as e:
            errors.append(str(e))
    
    # 写入 audit_log
    self.db.insert_audit_log(
        action=tool_name,
        query=user_query,
        details=f"确认执行 {tool_name}，共 {executed}/{len(confirmed_items)} 条成功",
        affected_count=executed
    )
    
    return {
        "success": len(errors) == 0,
        "affected_count": executed,
        "result_msg": f"✅ 成功执行 {tool_name}，共影响 {executed} 个条目" + (f"\n❌ 失败 {len(errors)} 条" if errors else ""),
        "error": "; ".join(errors) if errors else ""
    }
```

#### 4.3.4 Bug 2 修复：AI 预热

**修复位置**：`ui/main_window.py` `on_ai_send_message()` + `services/ai_assistant_service.py`

**流程**：
```
用户首次发送消息
  ↓
检查 conversation_context._db_summary_loaded
  ├─ False（首次）→ 仅执行 build_db_summary() + 缓存
  │                 → AI 返回 "⚡ 神经连接已建立，请发送您的指令"
  │                 → 不进入 ReAct 循环
  │                 → _db_summary_loaded = True
  └─ True（后续）→ 正常进入 process_react_query() ReAct 循环
```

**代码变更**：
```python
# ui/main_window.py on_ai_send_message() 中
# 在构建 context 之后、启动 AIQueryThread 之前

if not self.ai_assistant.conversation_context._db_summary_loaded:
    # 预热模式：只加载数据库摘要
    db_summary = self.ai_assistant.build_db_summary(
        context, vault_type=vault_type, max_items=500
    )
    self.ai_assistant.conversation_context.set_db_summary(db_summary, vault_type)
    
    # 显示预热完成消息
    self._append_ai_system_msg("⚡ 神经连接已建立，请发送您的指令")
    self._update_send_button_style(False)
    return  # 不启动 AIQueryThread
```

**欢迎语文案更新**（`ui/main_window.py` `_ai_welcome_md()` 和 `_ai_show_welcome()`）：
```markdown
🦁🔥 **密码库模式**

炽阳 已觉醒

你好，狮子座的主人。

⚡ **首次同步**：请发送任意消息完成神经连接预热，预热完成后即可执行操作。
```

#### 4.3.5 Bug 4 修复：指代消解

**当前问题**：`ReferenceResolver.resolve()` 已存在，但 `process_query()` 中仅将 `enhanced_query` 传给模型，未将 `inherited_ids` 绑定到 Tool 执行。

**修复方案**：
1. `ReferenceResolver.resolve()` 的返回值 `inherited_ids` 已获取
2. 在 `process_react_query()` 中，将 `inherited_ids` 注入 `tool_context`
3. 在语义搜索 Tool 中，如果 `params.get("query")` 包含指代词且无明确 ID，优先使用 `inherited_ids` 作为匹配候选
4. 在 `add_observation()` 中记录 `inherited_ids`，供后续轮次使用

```python
# 在 tool_context 中传递
.tool_context = {
    ...
    "inherited_ids": inherited_ids,
}

# 在 semantic_search_accounts Tool 中
def execute(self, params, context):
    query = params.get("query", "")
    inherited_ids = context.get("inherited_ids")
    
    # 如果用户使用了指代（如"刚才找到的"），优先在历史结果中筛选
    if inherited_ids and any(p in query for p in ["刚才", "之前", "那个", "这个"]):
        accounts = context.get("accounts", [])
        matched = [acc for acc in accounts if acc.id in inherited_ids]
        if matched:
            return ToolResult(
                success=True,
                data={"matched_ids": [acc.id for acc in matched], "reasoning": "基于历史指代匹配"},
                message=f"在历史范围内找到 {len(matched)} 条相关账号"
            )
    
    # 否则走正常语义搜索
    ...
```

---

### 4.4 Phase 4：UI 预览对接与状态机

#### 4.4.1 `ActionPreviewWidget` 改造

**当前问题**：`ActionPreviewWidget` 位于 `ui/main_window.py` L485-710，仅支持 `reorganize` / `add_remark` / `delete` / `add` 四种 action 的硬编码预览，不支持动态列。

**目标**：支持 6.1 标准 `preview_data` 的动态表格渲染。

**改造方案**（伪代码，实际需修改 `ui/main_window.py`）：

```python
class ActionPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview_data = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 顶部：操作类型 + 影响数量
        self.summary_label = QLabel()
        layout.addWidget(self.summary_label)
        
        # 中部：动态表格
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        
        # 底部：全选/反选 + 确认/取消
        btn_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("全选")
        self.btn_invert = QPushButton("反选")
        self.btn_confirm = QPushButton("✅ 确认执行")
        self.btn_cancel = QPushButton("❌ 取消")
        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_invert)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_confirm)
        layout.addLayout(btn_layout)
    
    def set_preview_data(self, preview_data: dict):
        """接收标准化 preview_data，动态构建表格"""
        self._preview_data = preview_data
        op_type = preview_data.get("operation_type", "unknown")
        target_vault = preview_data.get("target_vault", "account")
        items = preview_data.get("items", [])
        total = preview_data.get("total_items", len(items))
        
        # 空数据降级
        if total == 0 or not items:
            self.summary_label.setText("⚠️ 未找到符合条件的条目")
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
        
        # 动态列定义
        columns = self._get_columns_for_operation(op_type, target_vault)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([c["header"] for c in columns])
        self.table.setRowCount(len(items))
        
        # 勾选列使用 QCheckBox
        for row_idx, item in enumerate(items):
            for col_idx, col_def in enumerate(columns):
                if col_def["type"] == "checkbox":
                    checkbox = QCheckBox()
                    checkbox.setChecked(True)
                    self.table.setCellWidget(row_idx, col_idx, checkbox)
                else:
                    value = self._extract_value(item, col_def["field_path"], col_def.get("default", ""))
                    
                    # 密码掩码
                    if col_def.get("mask_password"):
                        value = "***"
                    
                    cell = QTableWidgetItem(str(value))
                    
                    # 删除操作标红
                    if op_type == "delete" and col_def.get("highlight_delete"):
                        cell.setForeground(QColor("#f44336"))
                    
                    # 超长内容 Tooltip
                    if len(str(value)) > 30:
                        cell.setToolTip(str(value))
                    
                    self.table.setItem(row_idx, col_idx, cell)
        
        self.table.resizeColumnsToContents()
        self._update_summary()
    
    def _get_columns_for_operation(self, op_type: str, target_vault: str) -> List[Dict]:
        """根据操作类型返回列定义"""
        base = [{"header": "☑", "type": "checkbox", "field_path": None}]
        
        if op_type == "add":
            if target_vault == "account":
                return base + [
                    {"header": "应用名", "field_path": "display_name"},
                    {"header": "用户名", "field_path": "secondary_name"},
                    {"header": "密码", "field_path": "fields.2.new_value", "mask_password": True},
                    {"header": "分类", "field_path": "fields.3.new_value"},
                    {"header": "备注", "field_path": "fields.4.new_value"},
                ]
            else:
                return base + [
                    {"header": "标题", "field_path": "display_name"},
                    {"header": "URL", "field_path": "secondary_name"},
                    {"header": "分类", "field_path": "fields.3.new_value"},
                    {"header": "备注", "field_path": "fields.4.new_value"},
                ]
        elif op_type == "update":
            return base + [
                {"header": "名称", "field_path": "display_name"},
                {"header": "变更字段", "field_path": "fields.0.field_name"},
                {"header": "原值", "field_path": "fields.0.old_value"},
                {"header": "新值", "field_path": "fields.0.new_value"},
            ]
        elif op_type == "reorganize":
            return base + [
                {"header": "名称", "field_path": "display_name"},
                {"header": "原分类", "field_path": "fields.0.old_value"},
                {"header": "新分类", "field_path": "fields.0.new_value"},
            ]
        elif op_type == "delete":
            return base + [
                {"header": "名称", "field_path": "display_name"},
                {"header": "副名称", "field_path": "secondary_name"},
                {"header": "分类", "field_path": "fields.2.new_value"},
                {"header": "操作", "field_path": "fields.3.new_value", "highlight_delete": True},
            ]
        elif op_type == "classify":
            return base + [
                {"header": "名称", "field_path": "display_name"},
                {"header": "原分类", "field_path": "fields.0.old_value"},
                {"header": "建议分类", "field_path": "fields.0.new_value"},
                {"header": "理由", "field_path": "fields.0.reason"},
            ]
        else:
            return base + [{"header": "数据", "field_path": "display_name"}]
    
    def get_confirmed_items(self) -> List[Dict]:
        """返回用户勾选确认的 raw_data 列表"""
        confirmed = []
        items = self._preview_data.get("items", [])
        for row_idx in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row_idx, 0)
            if checkbox and checkbox.isChecked():
                if row_idx < len(items):
                    confirmed.append(items[row_idx]["raw_data"])
        return confirmed
```

#### 4.4.2 `BatchAddPreviewWidget` 改造

**当前问题**：`BatchAddPreviewWidget` 已有表格模型，但仅支持旧格式的 `BatchItem` 列表，不支持 6.1 标准 `preview_data`。

**改造方案**：
```python
class BatchAddPreviewWidget(QWidget):
    def set_preview_data(self, preview_data: dict):
        """新增：支持标准 preview_data 接口"""
        items = preview_data.get("items", [])
        # 将 preview_data.items 转换为 BatchItem 列表后调用现有 set_items
        batch_items = []
        for item in items:
            raw = item.get("raw_data", {})
            batch_items.append(BatchItem(
                app_name=raw.get("app_name", ""),
                username=raw.get("username", ""),
                password=raw.get("password", ""),
                category=raw.get("category", "其他"),
                remark=raw.get("remark", ""),
                tags=raw.get("tags", []),
                url=raw.get("url", "")
            ))
        
        vault_type = preview_data.get("target_vault", "account")
        repo = RepositoryFactory.get_repository(vault_type)
        categories = repo.get_categories()
        self.set_items(batch_items, vault_type, categories)
    
    def get_confirmed_items(self) -> List[Dict]:
        """返回勾选的 raw_data 列表（需与 ActionPreviewWidget 接口一致）"""
        # 基于现有模型的勾选状态，返回 raw_data
        confirmed = []
        # ... 遍历模型获取勾选行 ...
        return confirmed
```

#### 4.4.3 ReAct 状态机（`MainWindow`）

**状态定义**：
```python
from enum import Enum

class ReActState(Enum):
    IDLE = "idle"                           # 空闲
    RUNNING = "running"                     # ReAct 循环中
    AWAITING_PREVIEW = "awaiting_preview"   # 暂停，等待用户确认预览
    CONFIRMED = "confirmed"                 # 用户已确认，准备恢复循环
    CANCELLED = "cancelled"                 # 用户取消，终止当前指令
```

**MainWindow 新增属性**：
```python
self._react_state = ReActState.IDLE
self._pending_tool = None           # 待确认的 Tool 调用
self._current_preview_widget = None # 当前展示的预览组件
self._react_turns_used = 0          # 已使用轮数
self._react_max_turns = 5           # 最大轮数
```

**核心流程改造**：

```python
def on_ai_send_message(self):
    """发送 AI 指令（ReAct 版本）"""
    query = self.ai_input.toPlainText().strip()
    if not query:
        return
    
    # 防重复提交
    if self._react_state == ReActState.RUNNING:
        return
    if self._react_state == ReActState.AWAITING_PREVIEW:
        self._append_ai_system_msg("请先处理当前预览确认")
        return
    
    # 清空输入
    self.ai_input.setPlainText("")
    self._current_ai_query = query
    
    # 记录用户消息
    self._append_user_message(query)
    
    # 预热检查（Bug 2）
    if not self.ai_assistant.conversation_context._db_summary_loaded:
        self._do_warmup(query)
        return
    
    # 启动 ReAct 循环
    self._start_react_loop(query)

def _start_react_loop(self, query: str):
    """启动 ReAct 循环（后台线程）"""
    self._react_state = ReActState.RUNNING
    self._update_send_button_style(True)
    
    if self.current_vault == 'accounts':
        context = self._cached_accounts if not self._cache_dirty else self.account_service.get_all_accounts()
        self._cached_accounts = context
        self._cache_dirty = False
        vault_type = 'accounts'
    else:
        context = self._cached_urls if not self._url_cache_dirty else self._url_service.get_all_urls()
        self._cached_urls = context
        self._url_cache_dirty = False
        vault_type = 'urls'
    
    self._ai_thread = AIQueryThread(
        self.ai_assistant, query, context, 
        self._ai_mode, vault_type,
        react_mode=True  # 新增参数
    )
    self._ai_thread.result_ready.connect(self._on_react_result)
    self._ai_thread.thinking_token.connect(self._on_thinking_token)
    self._ai_thread.result_token.connect(self._on_result_token)
    self._ai_thread.start()

def _on_react_result(self, result_json: str):
    """ReAct 循环结果回调"""
    import json
    result = json.loads(result_json)
    
    self._react_turns_used = result.get("turns_used", 0)
    
    if result.get("awaiting_confirm"):
        # 暂停循环，展示预览
        self._react_state = ReActState.AWAITING_PREVIEW
        self._pending_tool = result.get("pending_tool")
        
        preview_data = result["preview"]["preview_data"]
        
        # 选择预览组件
        if preview_data["operation_type"] == "add":
            widget = BatchAddPreviewWidget(parent=self.ai_panel)
            widget.set_preview_data(preview_data)
        else:
            widget = ActionPreviewWidget(parent=self.ai_panel)
            widget.set_preview_data(preview_data)
        
        self._current_preview_widget = widget
        
        # 嵌入 AI 面板
        self._insert_preview_card(widget)
        
        # 显示思考过程
        self._append_ai_message(result["response"])
        
        # 连接确认/取消按钮
        widget.btn_confirm.clicked.connect(self._on_preview_confirmed)
        widget.btn_cancel.clicked.connect(self._on_preview_cancelled)
        
    elif result.get("done"):
        # 循环结束
        self._react_state = ReActState.IDLE
        self._append_ai_message(result["response"])
        self._update_send_button_style(False)
    
    else:
        # 异常情况
        self._react_state = ReActState.IDLE
        self._append_ai_message(result.get("response", "处理完成"))
        self._update_send_button_style(False)

def _on_preview_confirmed(self):
    """用户确认预览"""
    if self._react_state != ReActState.AWAITING_PREVIEW:
        return
    
    confirmed_items = self._current_preview_widget.get_confirmed_items()
    if not confirmed_items:
        QMessageBox.information(self, "提示", "请至少勾选 1 条")
        return
    
    # 显示 Loading
    self._append_ai_system_msg("⏳ 执行中...")
    
    # 执行事务
    try:
        result = self.ai_assistant.execute_build_action_with_transaction(
            confirmed_items,
            self._pending_tool["tool"],
            self._current_ai_query
        )
        
        # 处理二次确认（删除 >50 条）
        if result.get("needs_confirmation"):
            reply = QMessageBox.question(self, "二次确认", result["message"])
            if reply == QMessageBox.StandardButton.Yes:
                result = self.ai_assistant.execute_build_action_with_transaction(
                    confirmed_items, self._pending_tool["tool"],
                    self._current_ai_query, _force=True
                )
            else:
                result = {"success": False, "error": "用户取消"}
        
        # 写入 Observation
        self.ai_assistant.conversation_context.add_observation(
            tool=self._pending_tool["tool"],
            params=self._pending_tool["params"],
            result=result,
            turn=self._react_turns_used
        )
        
        if result.get("success"):
            self._append_ai_message(result.get("result_msg", "✅ 执行成功"))
        else:
            self._append_ai_message(f"❌ {result.get('error', '执行失败')}")
        
        # 刷新列表
        self._cache_dirty = True
        self._url_cache_dirty = True
        if self.current_vault == 'accounts':
            self.load_accounts()
        else:
            self.load_urls()
        
    except Exception as e:
        self._append_ai_message(f"❌ 执行异常：{str(e)}")
    
    finally:
        # 清理预览组件
        if self._current_preview_widget:
            self._current_preview_widget.deleteLater()
            self._current_preview_widget = None
        
        self._react_state = ReActState.IDLE
        self._pending_tool = None
        self._update_send_button_style(False)

def _on_preview_cancelled(self):
    """用户取消预览"""
    if self._react_state != ReActState.AWAITING_PREVIEW:
        return
    
    self.ai_assistant.conversation_context.add_observation(
        tool=self._pending_tool["tool"],
        params=self._pending_tool["params"],
        result={"executed": False, "reason": "user_cancelled"},
        turn=self._react_turns_used
    )
    
    self._append_ai_message("❌ 已取消当前操作。")
    
    if self._current_preview_widget:
        self._current_preview_widget.deleteLater()
        self._current_preview_widget = None
    
    self._react_state = ReActState.IDLE
    self._pending_tool = None
    self._update_send_button_style(False)
```

---

## 五、审查清单（Code Review Checklist）

### 5.1 架构审查

- [ ] `services/ai_tools.py` 是否成功新建且 29 个 Tool 全部注册到 `ToolRegistry`
- [ ] `AITool.execute()` 的返回值是否统一为 `ToolResult` 类型
- [ ] `ToolRegistry.list_for_prompt()` 生成的文本是否能在 32K 上下文窗口内容纳
- [ ] `PermissionLevel` 四个级别是否与需求文档的 🟢🟡🔴⛔ 完全对应
- [ ] ⛔ 禁止 AI 的操作（hard_delete, change_master_password 等）是否确实未出现在 Tool 清单中

### 5.2 安全审查

- [ ] Plan 模式下调用非 `readonly` Tool 时，是否被正确拦截并提示切换 Build 模式
- [ ] Build 模式下 `batch_delete_*` 是否强制走 `soft_delete` + `audit_log`
- [ ] `batch_delete_*` 超过 50 条时是否触发二次确认弹窗
- [ ] 预览组件中密码字段是否默认掩码显示（***）
- [ ] `execute_build_action_with_transaction` 是否逐条执行并捕获异常，避免部分成功部分失败
- [ ] `ReferenceResolver._sanitize_query()` 是否正确过滤了 `<` `>` 等 Prompt 注入字符

### 5.3 数据流审查

- [ ] `preview_data` 结构是否严格符合 6.1 标准（operation_type / target_vault / total_items / items / fields）
- [ ] `ActionPreviewWidget.set_preview_data()` 是否能正确处理全部 6 种 operation_type
- [ ] `BatchAddPreviewWidget.get_confirmed_items()` 与 `ActionPreviewWidget.get_confirmed_items()` 返回格式是否一致（均为 `List[Dict]`）
- [ ] `get_confirmed_items()` 返回的 `raw_data` 是否包含 Tool 执行所需的全部字段
- [ ] ReAct 循环的 `Observation` 是否被正确注入下一轮 Prompt

### 5.4 UI 审查

- [ ] Bug 1 修复后，139 条账号是否能完整渲染且可滚动
- [ ] Bug 5 修复后，248 条网址是否正常显示
- [ ] `AWAITING_PREVIEW` 状态下，输入框是否被置灰或提示
- [ ] 预览组件是否锚定在 AI 面板中，不会被后续消息顶出可视区域
- [ ] 确认按钮点击后是否显示 Loading 态，防止重复点击
- [ ] 空数据时（total_items == 0）是否显示 "⚠️ 未找到符合条件的条目"

### 5.5 兼容性审查

- [ ] 旧代码中直接访问 `ai_assistant._history` 的地方是否仍能工作
- [ ] `AIQueryThread` 的 `react_mode=False` 时是否保持旧行为（兼容过渡）
- [ ] `process_query()` 旧方法是否保留（或标记 `@deprecated`）
- [ ] `services/semantic_search_service.py` 未被新代码引用

---

## 六、总体校验（验收标准）

### 6.1 功能验收

| 验收项 | 通过标准 |
|--------|---------|
| ReAct 循环 | 输入"把没分类的账号移到工作类"，AI 应执行 `semantic_filter_accounts` → `batch_reorganize_accounts`，最多 2 轮完成 |
| 预览完整性 | Build 模式下批量新增，预览表格必须显示应用名、用户名、密码（掩码）、分类、备注的具体值，禁止占位符 |
| 指代消解 | 先输入"找出支付类账号"，再输入"把刚才那些加上备注'金融相关'"，AI 应正确识别"刚才那些"并执行 `batch_add_remark_accounts` |
| 权限拦截 | Plan 模式下输入"删除所有测试账号"，AI 应提示"需切换到 Build 模式"，不执行任何操作 |
| 二次确认 | Build 模式下删除 60 条账号，必须先展示预览，再弹窗"即将删除 60 条记录，是否确认？" |
| 防循环保护 | 输入极其复杂的嵌套指令，ReAct 循环达到 5 轮后自动终止，提示"建议拆分指令" |
| 网址库对等 | 网址库下全部 29 个 Tool 行为与密码库一致，AI 助手能正确读取 248 条网址数据 |
| 预热机制 | 首次交互只执行 `build_db_summary`，返回"神经连接已建立"，不进入 ReAct 循环 |

### 6.2 性能验收

| 验收项 | 通过标准 |
|--------|---------|
| 列表渲染 | 139 条账号在 500ms 内完成渲染，滚动流畅无卡顿 |
| ReAct 延迟 | 单轮 Tool Call（含语义搜索）在 3 秒内完成 |
| 预览加载 | 50 条 batch_add 预览在 1 秒内渲染完成 |
| 内存安全 | 连续 20 轮 AI 对话不触发 `0xC0000409` 崩溃 |

### 6.3 回归验收

| 验收项 | 通过标准 |
|--------|---------|
| 旧搜索 | 搜索框精确匹配、拼音匹配功能正常 |
| 旧导入 | Excel / 文本导入功能正常 |
| 旧导出 | Excel / 加密备份 / PWA 密包导出功能正常 |
| 旧锁定 | 5 分钟空闲锁定 + 手动锁定功能正常 |
| 旧主题 | 浅色 / 深色主题切换正常 |
| 旧分类 | 拖拽排序、批量删除分类功能正常 |

---

## 附录：关键代码位置速查

| 目标 | 文件 | 行号/位置 |
|------|------|----------|
| Bug 1 修复点 | `ui/main_window.py` | L1678-1688 `load_accounts()` 循环体 |
| Bug 5 修复点 | `ui/main_window.py` | L731 `AIAssistantService(db_manager)` |
| AI 预热入口 | `ui/main_window.py` | L3068 `on_ai_send_message()` |
| ReAct 结果回调 | `ui/main_window.py` | L3145 `_on_ai_query_finished()` |
| ActionPreviewWidget | `ui/main_window.py` | L485-710 |
| BatchAddPreviewWidget | `ui/batch_add_preview_widget.py` | L237-436 |
| process_query | `services/ai_assistant_service.py` | L201-363 |
| build_action_preview | `services/ai_assistant_service.py` | L610-760 |
| execute_build_action_with_transaction | `services/ai_assistant_service.py` | L899-1000+ |
| build_db_summary | `services/ai_assistant_service.py` | L51-133 |
| semantic_match | `ai/ollama_client.py` | L309-389 |
| parse_command | `ai/ollama_client.py` | L417-507 |
| ConversationContext | `services/conversation_context.py` | L25-114 |
| ReferenceResolver | `services/conversation_context.py` | L117-166 |

---

*文档结束。本文档为开发实施的唯一依据，任何变更须经评审后同步更新本文档。*
