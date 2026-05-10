# P3 任务实施规划与总结文档

**项目名称**：本地密码保险箱（SecretManage）  
**版本**：P3 阶段 —— 架构优化与代码重构  
**日期**：2026-05-10  
**状态**：已完成（P3-6.1、P3-6.3），已回退（P3-6.2 —— 见下方说明）

---

## 目录

1. [项目背景](#1-项目背景)
2. [实施原则](#2-实施原则)
3. [详细拆分方案](#3-详细拆分方案)
   - 3.1 [AI 客户端模块拆分](#31-ai-客户端模块拆分)
   - 3.2 [AI 工具模块拆分](#32-ai-工具模块拆分)
   - 3.3 [AI 助手服务拆分](#33-ai-助手服务拆分)
   - 3.4 [主窗口 UI 拆分](#34-主窗口-ui-拆分)
4. [性能优化方案](#4-性能优化方案)
5. [硬编码路径集中化方案](#5-硬编码路径集中化方案)
6. [验证结果](#6-验证结果)
7. [风险与回滚策略](#7-风险与回滚策略)
8. [后续建议](#8-后续建议)

---

## 1. 项目背景

### 1.1 目标

P3 阶段的核心目标是**解决代码膨胀和维护困难问题**，通过以下三个维度进行架构优化：

| 维度 | 目标 | 对应任务 |
|------|------|----------|
| **模块拆分** | 将超大文件（>1000行）拆分为职责单一的小模块 | P3-6.1 |
| **性能优化** | 提升列表渲染性能，改善大数据量下的用户体验 | P3-6.2 |
| **代码质量** | 消除硬编码路径，集中管理全局常量 | P3-6.3 |

### 1.2 范围

本次重构涉及以下核心模块：

- `ai/` —— Ollama 客户端相关代码
- `services/` —— AI 工具与助手服务
- `ui/` —— 主窗口及内部组件
- `core/` —— 全局常量配置

### 1.3 拆分前代码规模

| 文件 | 行数 | 问题 |
|------|------|------|
| `ai/ollama_client.py` | 1,162 | 混合基础通信、语义搜索、工具调用 |
| `services/ai_tools.py` | 2,198 | 包含8类工具，职责过重 |
| `services/ai_assistant_service.py` | 1,742 | 历史管理、动作处理、查询逻辑混杂 |
| `ui/main_window.py` | 7,194 | 内含多个独立 UI 组件类 |
| **合计** | **12,296** | 难以维护、协作冲突风险高 |

---

## 2. 实施原则

为确保重构过程平稳、安全，本次工作严格遵循以下原则：

### 2.1 向后兼容优先

- **所有原文件保留**，改为**聚合入口（Facade）**模式
- 原有 `import` 语句无需修改即可正常工作
- 外部调用方无感知迁移

### 2.2 不改变业务逻辑

- 代码迁移采用**物理移动**而非逻辑重写
- 所有方法签名、返回值、异常处理保持不变
- 仅在必要时进行最小化的变量名调整

### 2.3 保持信号连接和 UI 交互不变

- PyQt 信号（`pyqtSignal`）的定义和发射位置不变
- UI 组件的槽函数（`@pyqtSlot`）保持原样
- 事件处理链不受影响

### 2.4 所有现有测试必须通过

- 重构前后执行完整单元测试套件
- 测试用例不做任何修改（验证兼容性）
- 目标：**22/22 测试用例通过**

---

## 3. 详细拆分方案

### 3.1 AI 客户端模块拆分

#### 3.1.1 拆分理由

原 `ai/ollama_client.py`（1,162 行）同时承担以下职责：

1. HTTP 基础通信（超时重试、错误处理）
2. 语义搜索向量计算
3. AI 工具调用执行
4. JSON 解析与流式响应处理

这些职责跨越了不同的抽象层次，违反了**单一职责原则（SRP）**。

#### 3.1.2 新文件结构

```
ai/
├── __init__.py
├── ollama_client.py      # 聚合入口（22行）
├── client_base.py        # 基础客户端（254行）
├── client_semantic.py    # 语义搜索（344行）
├── client_tools.py       # 工具调用（395行）
└── client_utils.py       # JSON 工具函数（97行）
```

#### 3.1.3 行数对比

| 文件 | 拆分前行数 | 拆分后行数 | 变化 |
|------|-----------|-----------|------|
| `ollama_client.py` | 1,162 | 22 | -1,140 |
| `client_base.py` | — | 254 | 新增 |
| `client_semantic.py` | — | 344 | 新增 |
| `client_tools.py` | — | 395 | 新增 |
| `client_utils.py` | — | 97 | 新增 |
| **合计** | **1,162** | **1,090** | **-72** |

> 注：行数减少主要由于消除了重复导入和注释块，实际代码逻辑完全保留。

#### 3.1.4 方法分配

| 新文件 | 职责 | 核心方法 |
|--------|------|----------|
| `client_base.py` | HTTP 通信基础 | `__init__`, `generate`, `_call_api`, `_handle_error` |
| `client_semantic.py` | 语义搜索 | `semantic_search`, `calculate_similarity`, `build_query_vector` |
| `client_tools.py` | 工具调用 | `call_tool`, `parse_tool_request`, `execute_function` |
| `client_utils.py` | JSON 工具 | `safe_json_loads`, `extract_json_block`, `clean_response` |

#### 3.1.5 向后兼容入口

```python
# ai/ollama_client.py
"""向后兼容的聚合入口，所有符号从子模块重新导出。"""
from .client_base import OllamaClientBase
from .client_semantic import OllamaClientSemantic
from .client_tools import OllamaClientTools
from .client_utils import safe_json_loads, extract_json_block

__all__ = [
    'OllamaClientBase',
    'OllamaClientSemantic', 
    'OllamaClientTools',
    'safe_json_loads',
    'extract_json_block',
]
```

---

### 3.2 AI 工具模块拆分

#### 3.2.1 拆分理由

原 `services/ai_tools.py`（2,198 行）是项目中最大的单文件，包含 8 类完全不同的工具：

- 搜索工具（语义搜索、关键词搜索）
- 过滤工具（按分类、标签过滤）
- 批量工具（批量添加、删除）
- 分类工具（AI 自动分类）
- 合并工具（去重、合并条目）
- 信息工具（获取统计、生成报告）
- 基础工具（工具注册、参数校验）
- 辅助工具（字符串处理、格式转换）

#### 3.2.2 新文件结构

```
services/
├── ai_tools.py           # 聚合入口（107行）
└── tools/
    ├── __init__.py       # 重新导出（109行）
    ├── base.py           # 基础工具与注册机制（169行）
    ├── search_tools.py   # 搜索工具（113行）
    ├── filter_tools.py   # 过滤工具（112行）
    ├── batch_tools.py    # 批量操作工具（563行）
    ├── classify_tools.py # 分类工具（699行）
    ├── merge_tools.py    # 合并工具（102行）
    ├── info_tools.py     # 信息查询工具（271行）
    └── utility_tools.py  # 辅助工具（124行）
```

#### 3.2.3 行数对比

| 文件 | 拆分前行数 | 拆分后行数 | 变化 |
|------|-----------|-----------|------|
| `ai_tools.py` | 2,198 | 107 | -2,091 |
| `tools/base.py` | — | 169 | 新增 |
| `tools/search_tools.py` | — | 113 | 新增 |
| `tools/filter_tools.py` | — | 112 | 新增 |
| `tools/batch_tools.py` | — | 563 | 新增 |
| `tools/classify_tools.py` | — | 699 | 新增 |
| `tools/merge_tools.py` | — | 102 | 新增 |
| `tools/info_tools.py` | — | 271 | 新增 |
| `tools/utility_tools.py` | — | 124 | 新增 |
| **合计** | **2,198** | **2,153** | **-45** |

#### 3.2.4 方法分配

| 新文件 | 职责 | 代表方法 |
|--------|------|----------|
| `base.py` | 工具注册、参数校验基类 | `register_tool`, `ToolRegistry`, `validate_params` |
| `search_tools.py` | 语义/关键词搜索 | `search_accounts`, `semantic_search`, `fuzzy_search` |
| `filter_tools.py` | 分类与标签过滤 | `filter_by_category`, `filter_by_tag`, `filter_by_date` |
| `batch_tools.py` | 批量增删改查 | `batch_add`, `batch_delete`, `batch_update_category` |
| `classify_tools.py` | AI 智能分类 | `classify_account`, `suggest_category`, `batch_classify` |
| `merge_tools.py` | 去重与合并 | `find_duplicates`, `merge_accounts`, `compare_entries` |
| `info_tools.py` | 统计与报告 | `get_statistics`, `generate_password_report`, `audit_log` |
| `utility_tools.py` | 字符串/格式处理 | `sanitize_input`, `format_account_info`, `truncate_text` |

---

### 3.3 AI 助手服务拆分

#### 3.3.1 拆分理由

原 `services/ai_assistant_service.py`（1,742 行）采用单类实现，包含：

1. **历史管理** —— 对话历史存储、上下文截断
2. **动作处理** —— 工具调用结果的 UI 动作转换
3. **查询处理** —— 自然语言理解、查询路由

使用 **Mixin 策略**拆分，可在不破坏继承链的情况下分离关注点。

#### 3.3.2 新文件结构

```
services/
├── ai_assistant_service.py    # 聚合入口（178行）
└── assistant/
    ├── __init__.py            # 主类组合（16行）
    ├── models.py              # 数据模型（11行）
    ├── history_mixin.py       # 历史管理（63行）
    ├── action_mixin.py        # 动作处理（712行）
    └── query_mixin.py         # 查询处理（771行）
```

#### 3.3.3 行数对比

| 文件 | 拆分前行数 | 拆分后行数 | 变化 |
|------|-----------|-----------|------|
| `ai_assistant_service.py` | 1,742 | 178 | -1,564 |
| `assistant/models.py` | — | 11 | 新增 |
| `assistant/history_mixin.py` | — | 63 | 新增 |
| `assistant/action_mixin.py` | — | 712 | 新增 |
| `assistant/query_mixin.py` | — | 771 | 新增 |
| **合计** | **1,742** | **1,557** | **-185** |

#### 3.3.4 Mixin 组合设计

```python
# services/assistant/__init__.py
from .history_mixin import HistoryMixin
from .action_mixin import ActionMixin
from .query_mixin import QueryMixin

class AIAssistantService(HistoryMixin, ActionMixin, QueryMixin):
    """AI 助手服务主类，通过 Mixin 组合功能。
    
    - HistoryMixin: 管理对话历史、上下文窗口
    - ActionMixin: 将工具结果转换为 UI 动作
    - QueryMixin: 处理自然语言查询、路由到对应工具
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_history()
        self._init_actions()
        self._init_query()
```

#### 3.3.5 Mixin 职责分配

| Mixin 类 | 行数 | 核心职责 | 关键方法 |
|----------|------|----------|----------|
| `HistoryMixin` | 63 | 对话历史管理 | `add_message`, `get_context`, `clear_history` |
| `ActionMixin` | 712 | UI 动作生成 | `create_add_action`, `create_delete_action`, `apply_action` |
| `QueryMixin` | 771 | 查询解析路由 | `parse_query`, `route_to_tool`, `build_response` |

---

### 3.4 主窗口 UI 拆分

#### 3.4.1 拆分理由

原 `ui/main_window.py`（7,194 行）是项目最大的文件，内部定义了多个独立 Widget 类：

- `ActionPreviewWidget` —— 动作预览面板
- `CategoryTreeWidget` —— 分类树形控件
- `AIInputEdit` —— AI 输入框（支持快捷键）
- `LocalHelpDialog` —— 本地帮助对话框
- AI 聊天渲染逻辑

这些组件具有**独立的 UI 状态和行为**，适合提取为可复用的独立组件。

#### 3.4.2 新文件结构

```
ui/
├── main_window.py                    # 主窗口（5,793行，-1,401）
├── ai_chat_renderer.py               # AI 聊天渲染器
├── widgets/
│   ├── action_preview_widget.py      # 动作预览（474行）
│   ├── category_tree_widget.py       # 分类树（530行）
│   └── ai_input_edit.py              # AI 输入框（35行）
└── dialogs/
    └── local_help_dialog.py          # 本地帮助对话框
```

#### 3.4.3 行数对比

| 文件 | 拆分前行数 | 拆分后行数 | 变化 |
|------|-----------|-----------|------|
| `main_window.py` | 7,194 | 5,793 | -1,401 |
| `widgets/action_preview_widget.py` | — | 474 | 提取 |
| `widgets/category_tree_widget.py` | — | 530 | 提取 |
| `widgets/ai_input_edit.py` | — | 35 | 提取 |
| `ai_chat_renderer.py` | — | ~200 | 提取（估算） |
| `dialogs/local_help_dialog.py` | — | ~150 | 提取（估算） |
| **合计** | **7,194** | **~7,182** | **~0** |

#### 3.4.4 组件职责

| 组件 | 文件 | 职责 | 信号/槽 |
|------|------|------|---------|
| `ActionPreviewWidget` | `widgets/action_preview_widget.py` | 预览 AI 建议的操作（增删改） | `apply_clicked`, `discard_clicked` |
| `CategoryTreeWidget` | `widgets/category_tree_widget.py` | 分类层级展示与拖拽排序 | `category_selected`, `category_moved` |
| `AIInputEdit` | `widgets/ai_input_edit.py` | AI 对话输入框，支持 Enter 发送 | `send_message` |
| `LocalHelpDialog` | `dialogs/local_help_dialog.py` | 本地帮助文档弹窗 | — |
| `AIChatRenderer` | `ai_chat_renderer.py` | 渲染 Markdown/代码块消息 | — |

---

## 4. 性能优化方案（已回退）

> **⚠️ 重要说明**：`QListWidget` → `QListView + QAbstractListModel + QStyledItemDelegate` 迁移在首次集成测试中引发了 **0xC0000409（STATUS_STACK_BUFFER_OVERRUN）** 崩溃。经排查，崩溃发生在 `MainWindow` 初始化阶段，与 `QListView` 的 delegate paint 机制在特定数据条件下的交互有关。
>
> **决策**：回退至原始 `QListWidget` 实现，保留所有新建的 `ui/models/` 和 `ui/delegates/` 子模块文件作为后续迭代的技术储备，但不启用。
>
> **影响**：`ui/main_window.py` 保持原始的 `QListWidget` + `setItemWidget` 方案，其他 P3 改动（模块拆分、硬编码路径集中化）不受影响。
>
> **后续计划**：待有更充分的隔离测试和边界条件验证后，在专门的分支中重新尝试 `QListView` 迁移。

## 4. 性能优化方案（原始设计）

### 4.1 当前问题

`QListWidget` + `setItemWidget` 方案在数据量增大时存在性能瓶颈：

- 每个列表项创建独立的 QWidget 实例
- 滚动时需要创建/销毁大量控件
- 内存占用随数据量线性增长

### 4.2 迁移方案

采用 **`QListView` + `QAbstractListModel` + `QStyledItemDelegate`** 架构：

```
┌─────────────────┐
│   QListView     │  ← 只负责视图渲染，不持有数据
├─────────────────┤
│ QAbstractListModel │  ← 统一数据模型，支持懒加载
├─────────────────┤
│QStyledItemDelegate│  ← 自定义绘制，无独立 Widget
└─────────────────┘
```

### 4.3 技术原理

| 特性 | QListWidget | QListView + Model |
|------|------------|-------------------|
| 数据存储 | 内部 QListWidgetItem | 外部 QAbstractListModel |
| 渲染方式 | setItemWidget（创建 QWidget） | paint() 方法直接绘制 |
| 内存占用 | 高（每个项一个 Widget） | 低（仅数据模型） |
| 滚动性能 | 创建/销毁 Widget 开销大 | 仅重绘可见区域 |
| 数据量支持 | < 1,000 条 | > 10,000 条 |

### 4.4 预期性能提升

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 1,000 条加载时间 | ~800ms | ~150ms | **5x** |
| 内存占用（1,000条） | ~45MB | ~8MB | **5.6x** |
| 滚动帧率 | ~15fps | ~60fps | **4x** |

### 4.5 实施状态

- **当前状态**：进行中（由另一个 agent 负责）
- **已完成**：模型层设计、数据迁移
- **待完成**：自定义 Delegate 绘制、交互事件处理

---

## 5. 硬编码路径集中化方案

### 5.1 问题描述

项目中存在多处硬编码的数据路径，分散在不同文件中：

```python
# 优化前（分散在多个文件）
Path.home() / '.local_password_vault' / 'vault.db'
Path.home() / '.local_password_vault' / 'config.json'
```

### 5.2 解决方案

创建 `core/constants.py` 集中管理所有路径常量：

```python
# core/constants.py
"""全局常量配置 —— 集中管理项目中的硬编码路径和配置项"""
from pathlib import Path

# 数据目录（密码保险箱主数据目录）
DATA_DIR = Path.home() / '.local_password_vault'

# 数据库文件路径
VAULT_DB_PATH = DATA_DIR / 'vault.db'
VAULT_URLS_DB_PATH = DATA_DIR / 'vault_urls.db'

# 备份目录
BACKUP_DIR = DATA_DIR / 'backups'

# 配置文件路径
CONFIG_PATH = DATA_DIR / 'config.json'
COMPACT_VIEW_PATH = DATA_DIR / 'compact_view.json'

# 日志文件路径
LOG_PATH = DATA_DIR / 'app.log'
```

### 5.3 替换文件列表

| 序号 | 文件 | 替换内容 |
|------|------|----------|
| 1 | `_test_init.py` | 测试数据目录初始化 |
| 2 | `main.py` | 应用启动时的目录创建 |
| 3 | `ui/main_window.py` | 配置文件读写路径 |
| 4 | `scripts/migrate_category_separator.py` | 数据库迁移脚本路径 |
| 5 | `services/semantic_search_service.py` | 数据库连接路径 |

### 5.4 使用示例

```python
# 优化后（统一导入）
from core.constants import DATA_DIR, VAULT_DB_PATH, CONFIG_PATH

# 初始化数据目录
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 连接数据库
conn = sqlite3.connect(str(VAULT_DB_PATH))

# 加载配置
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)
```

---

## 6. 验证结果

### 6.1 单元测试

执行完整测试套件验证重构正确性：

```bash
$ conda activate Passwordmanage
$ python -m pytest tests/ -v
```

| 测试文件 | 用例数 | 状态 |
|----------|--------|------|
| `test_account_service.py` | 8 | ✅ 通过 |
| `test_crypto.py` | 5 | ✅ 通过 |
| `test_id_type_consistency.py` | 4 | ✅ 通过 |
| `test_search_service.py` | 5 | ✅ 通过 |
| **合计** | **22** | **22/22 通过** |

### 6.2 导入验证

验证所有模块的向后兼容导入：

```python
# 测试脚本：验证所有聚合入口可正常导入
from ai.ollama_client import OllamaClientBase, OllamaClientSemantic
from services.ai_tools import ToolRegistry, search_accounts, batch_add
from services.ai_assistant_service import AIAssistantService

# 验证主类可正常实例化
service = AIAssistantService()
print("✅ 所有导入验证通过")
```

### 6.3 验证清单

- [x] `ai/ollama_client.py` 兼容导入测试
- [x] `services/ai_tools.py` 兼容导入测试
- [x] `services/ai_assistant_service.py` 兼容导入测试
- [x] 22 个单元测试全部通过
- [x] 手动启动应用无导入错误
- [x] 核心功能（增删改查、AI对话）手动验证正常

---

## 7. 风险与回滚策略

### 7.1 风险评估

| 风险项 | 概率 | 影响 | 缓解措施 |
|--------|------|------|----------|
| 循环导入 | 低 | 高 | 使用延迟导入（`import` 在函数内部） |
| Mixin 方法冲突 | 低 | 中 | 确保方法名前缀区分，如 `_history_*` |
| 信号连接断开 | 中 | 高 | 保留原文件作为过渡，逐步迁移 |
| 性能回归 | 低 | 中 | 原文件保留，可随时对比测试 |

### 7.2 回滚策略

#### 策略一：使用兼容入口（推荐）

所有原文件均保留为兼容入口，**无需任何回滚操作**：

```python
# 外部代码仍可使用原有导入
from ai.ollama_client import OllamaClientBase  # ✅ 正常工作
```

#### 策略二：完整回滚

若需完全回滚到重构前状态：

```bash
# 恢复步骤
1. 删除拆分出的子目录：
   rm -rf ai/client_*.py
   rm -rf services/tools/
   rm -rf services/assistant/
   rm -rf ui/widgets/action_preview_widget.py
   rm -rf ui/widgets/category_tree_widget.py
   rm -rf ui/widgets/ai_input_edit.py

2. 从 git 历史恢复原始文件：
   git checkout HEAD~1 -- ai/ollama_client.py
   git checkout HEAD~1 -- services/ai_tools.py
   git checkout HEAD~1 -- services/ai_assistant_service.py
   git checkout HEAD~1 -- ui/main_window.py

3. 删除 core/constants.py（或保留不影响功能）
```

### 7.3 原文件保留的作用

| 原文件 | 当前作用 | 建议保留期限 |
|--------|----------|-------------|
| `ai/ollama_client.py` | 重新导出所有子模块符号 | 至少 2 个版本周期 |
| `services/ai_tools.py` | 重新导出所有工具函数 | 至少 2 个版本周期 |
| `services/ai_assistant_service.py` | 组合 Mixin 并导出 | 长期保留（作为官方 API） |

---

## 8. 后续建议

### 8.1 main_window 进一步拆分

当前 `main_window.py` 仍有 5,793 行，建议进一步提取以下独立面板：

| 目标面板 | 建议文件 | 预估可减少行数 |
|----------|----------|--------------|
| AI 聊天面板 | `ui/panels/ai_chat_panel.py` | ~800 |
| 分类管理面板 | `ui/panels/category_panel.py` | ~600 |
| 工具栏/菜单 | `ui/components/app_toolbar.py` | ~400 |
| 状态栏 | `ui/components/status_bar.py` | ~200 |

### 8.2 建议的后续优化方向

#### 方向一：引入依赖注入容器

当前服务类之间存在直接实例化，建议引入轻量级 DI：

```python
# 建议模式
from core.container import Container

container = Container()
container.register(DatabaseService, lambda: DatabaseService(VAULT_DB_PATH))
container.register(AIAssistantService, lambda: AIAssistantService(
    db_service=container.resolve(DatabaseService)
))
```

#### 方向二：事件总线解耦

当前 UI 组件通过直接信号连接耦合，建议引入事件总线：

```python
# 建议模式
from core.events import event_bus

event_bus.emit('account.added', account_id=123)
event_bus.subscribe('account.added', refresh_list)
```

#### 方向三：配置管理升级

当前配置分散在多个 JSON 文件，建议统一为强类型配置类：

```python
# 建议模式
@dataclass
class AppConfig:
    data_dir: Path = field(default_factory=lambda: DATA_DIR)
    ai_timeout: int = 300
    max_history: int = 50
    theme: str = 'dark'
```

#### 方向四：持续重构清单

| 优先级 | 任务 | 预估工作量 |
|--------|------|-----------|
| P1 | 提取 AI 聊天面板 | 2-3 天 |
| P1 | 完成 QListView 迁移 | 3-5 天 |
| P2 | 提取分类管理面板 | 2 天 |
| P2 | 引入事件总线 | 3 天 |
| P3 | 依赖注入容器 | 5 天 |
| P3 | 配置管理升级 | 2 天 |

---

## 附录 A：文件变更总览

### 新增文件（21个）

```
ai/client_base.py
ai/client_semantic.py
ai/client_tools.py
ai/client_utils.py

core/constants.py

services/tools/__init__.py
services/tools/base.py
services/tools/search_tools.py
services/tools/filter_tools.py
services/tools/batch_tools.py
services/tools/classify_tools.py
services/tools/merge_tools.py
services/tools/info_tools.py
services/tools/utility_tools.py

services/assistant/__init__.py
services/assistant/models.py
services/assistant/history_mixin.py
services/assistant/action_mixin.py
services/assistant/query_mixin.py

ui/widgets/action_preview_widget.py
ui/widgets/category_tree_widget.py
ui/widgets/ai_input_edit.py
ui/ai_chat_renderer.py
ui/dialogs/local_help_dialog.py
```

### 修改文件（7个）

```
ai/ollama_client.py          # 改为聚合入口
services/ai_tools.py          # 改为聚合入口
services/ai_assistant_service.py  # 改为聚合入口
ui/main_window.py             # 提取内部类
_test_init.py                 # 使用 core.constants
main.py                       # 使用 core.constants
scripts/migrate_category_separator.py  # 使用 core.constants
services/semantic_search_service.py    # 使用 core.constants
```

---

## 附录 B：AGENTS.md 更新记录

本次重构同步更新了 `AGENTS.md`：

- **新增**：AI 大模型超时限制（最低 5 分钟，最长 10 分钟）
- **修复**：全项目 `timeout=30` → `timeout=300`

---

*文档结束*
