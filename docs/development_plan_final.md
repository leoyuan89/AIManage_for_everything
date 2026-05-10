# SecretManage 后续开发实施计划

> 版本：v1.0 | 日期：2026-05-10 | 状态：待实施
>
> 本文档基于代码库现状调研，覆盖「功能补齐」「Bug 修复」「测试补齐」「帮助系统」四大维度，是项目从"可用"走向"成熟桌面级密码管理器"的落地蓝图。

---

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [功能开发计划](#2-功能开发计划)
   - 2.1 [1Password CSV 导入](#21-1password-csv-导入)
   - 2.2 [KeePass XML 导入](#22-keepass-xml-导入)
3. [Bug 修复计划](#3-bug-修复计划)
   - 3.1 [P0 — 阻塞性/稳定性问题](#31-p0--阻塞性稳定性问题)
   - 3.2 [P1 — 性能/可靠性问题](#32-p1--性能可靠性问题)
4. [测试覆盖补齐计划](#4-测试覆盖补齐计划)
5. [用户使用说明（帮助系统）设计方案](#5-用户使用说明帮助系统设计方案)
6. [实施排期与依赖关系](#6-实施排期与依赖关系)
7. [风险与验收标准](#7-风险与验收标准)

---

## 1. 项目背景与目标

### 1.1 当前现状

SecretManage 是一款基于 PyQt6 + SQLite 的本地密码保险箱，已具备：
- AES-256-GCM 加密存储
- 本地 AI 助手（Ollama + gemma4:4b）智能分类、语义搜索、对话助手
- 双库管理（账号库 + 网址库）
- 批量导入/导出、回收站、密码生成器、健康检查等桌面级功能

### 1.2 待补齐短板

通过代码审计和静态分析，当前存在四类短板：

| 维度 | 现状 | 目标 |
|------|------|------|
| **功能完整性** | 仅支持 Bitwarden/LastPass 导入 | 补齐 1Password、KeePass 导入 |
| **稳定性** | 14 处 AI 主线程阻塞、批量操作无事务 | 全部异步化、关键操作事务保护 |
| **性能** | 聊天全量重绘、部分场景全表加载 | 增量渲染、SQL 层过滤下沉 |
| **质量保障** | 22 个测试，大量核心模块无覆盖 | 核心模块测试覆盖率达到 60%+ |
| **用户体验** | 无帮助文档入口 | 内置帮助弹窗，降低学习成本 |

### 1.3 总体目标

在完成本文档全部任务后，SecretManage 应达到：
1. **UI 永不冻结** —— 所有 AI 调用走异步队列，主线程只做 UI 更新
2. **数据零损坏** —— 关键批量操作具备事务保护，失败可回滚
3. **导入全兼容** —— 覆盖主流密码管理器导出格式（Bitwarden、LastPass、1Password、KeePass）
4. **质量可度量** —— 测试数量从 22 个提升到 80+，覆盖 services、core、models 核心路径
5. **上手零门槛** —— 主窗口内置帮助按钮，点击弹出与「炽阳」风格一致的文档弹窗

---

## 2. 功能开发计划

### 2.1 1Password CSV 导入

#### 背景

`ManagerImportService`（`services/import_service.py`）目前仅支持 Bitwarden（JSON/CSV）和 LastPass（CSV）。1Password 是全球用户量最大的商业密码管理器之一，其 CSV 导出格式稳定，补齐后可覆盖主流管理器迁移需求。

#### 1Password CSV 格式分析

1Password 导出 CSV 的典型表头（macOS/Windows 通用导出）：

```csv
title,website,username,password,notes,url,category,otpAuth
GitHub,github.com,myuser,mypassword,,https://github.com,Developer Tools,
```

字段映射关系：

| 1Password 字段 | SecretManage 字段 | 说明 |
|----------------|-------------------|------|
| `title` | `app_name` | 应用名/标题 |
| `website` / `url` | `url` | 网址（优先取 `url`，其次 `website`） |
| `username` | `username` | 账号 |
| `password` | `password` | 密码 |
| `notes` | `remark` | 备注 |
| `category` | `category` | 分类（为空时默认"其他"） |
| `otpAuth` | — | 2FA 信息，当前不导入，可写入 remark 提示 |

**注意**：1Password 旧版导出可能使用 ` notes`（带前导空格）作为字段名，解析时需 `strip()` 处理。

#### 实现方案

**Step 1 —— 格式检测**

在 `ManagerImportService.detect_format()` 中增加 1Password 识别逻辑：

```python
elif ext in ('csv', 'txt'):
    fl = first_line.lower()
    # 新增 1Password 检测
    if 'title' in fl and ('website' in fl or 'url' in fl) and 'username' in fl:
        return '1password_csv'
```

检测优先级应放在 LastPass 之前，因为 1Password 的 `title` + `username` 组合具有辨识度，而 `url` + `username` + `password` 也是 LastPass 的特征。实际可通过 `title` 字段的存在与否区分（LastPass 无 `title`，用 `name`）。

**Step 2 —— 解析器实现**

```python
@staticmethod
def _parse_1password_csv(file_path: str) -> List[Dict]:
    import csv
    accounts = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 处理旧版 1Password 字段名可能带前导空格的问题
            normalized = {k.strip().lower(): v for k, v in row.items()}
            url = normalized.get('url', '') or normalized.get('website', '')
            accounts.append({
                'app_name': normalized.get('title', ''),
                'url': url,
                'username': normalized.get('username', ''),
                'password': normalized.get('password', ''),
                'remark': normalized.get('notes', ''),
                'category': normalized.get('category', '') or '其他',
            })
    return accounts
```

**Step 3 —— UI 适配**

- `ui/import_dialog.py`：
  - 文件过滤器增加 `*.csv`（管理器模式已支持）
  - 下拉框说明文字从"支持 Bitwarden / LastPass"改为"支持 Bitwarden / LastPass / 1Password / KeePass"
- `ui/main_window.py` `_on_import_from_manager()` 第 4482 行错误提示同步更新

**Step 4 —— 边界处理**

| 场景 | 处理策略 |
|------|---------|
| 密码为空 | 保留空字符串导入（用户可在编辑弹窗补全） |
| title 为空 | `app_name` 设为 `"未命名"` |
| 同一 title + username 重复 | 走现有 `ImportDialog` 重复检测逻辑 |
| OTP 字段存在 | 追加到 remark：`"[1Password OTP] {otpAuth}"` |
| 大量数据（>1000 条） | 无特殊处理，Python csv 模块可胜任 |

**涉及文件**：
- `services/import_service.py`（新增解析器 + 检测逻辑）
- `ui/import_dialog.py`（提示文字更新）
- `ui/main_window.py`（错误提示更新）

**预计工作量**：~2 小时

---

### 2.2 KeePass XML 导入

#### 背景

KeePass（KeePass Password Safe）是开源密码管理器的标杆，其原生导出格式为 XML（`*.xml`，基于 KeePass 2.x 的 `KeePassFile`  schema）。许多企业和技术用户从 KeePass 迁移，支持 XML 导入可直接消费其完整数据结构。

#### KeePass XML 格式分析

KeePass 2.x XML 导出结构：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<KeePassFile>
  <Root>
    <Group>
      <Name>Internet</Name>
      <Entry>
        <String>
          <Key>Title</Key>
          <Value>GitHub</Value>
        </String>
        <String>
          <Key>UserName</Key>
          <Value>myuser</Value>
        </String>
        <String>
          <Key>Password</Key>
          <Value ProtectInMemory="True">mypassword</Value>
        </String>
        <String>
          <Key>URL</Key>
          <Value>https://github.com</Value>
        </String>
        <String>
          <Key>Notes</Key>
          <Value>个人开发账号</Value>
        </String>
      </Entry>
    </Group>
  </Root>
</KeePassFile>
```

关键特性：
- 数据以 `<Entry>` 为单位，嵌套在 `<Group>` 中
- 字段通过 `<String><Key>X</Key><Value>Y</Value></String>` 键值对表示
- 标准字段：`Title`、`UserName`、`Password`、`URL`、`Notes`
- 分组名 `<Group><Name>X</Name></Group>` 可作为 `category`
- KeePass 支持多层级 Group（Group 嵌套 Group），导入时取直接父 Group 名作为 `category`

#### 实现方案

**Step 1 —— 格式检测**

```python
@staticmethod
def detect_format(file_path: str) -> str:
    ext = file_path.lower().rsplit('.', 1)[-1] if '.' in file_path else ''
    with open(file_path, 'r', encoding='utf-8') as f:
        first_line = f.readline().strip()
    if ext == 'json':
        return 'bitwarden_json'
    elif ext == 'xml':
        # 检查 XML 根标签是否为 KeePassFile
        if first_line.startswith('<?xml'):
            # 读取更多内容确认
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read(2048)
            if '<KeePassFile>' in content:
                return 'keepass_xml'
        return 'unknown'
    elif ext in ('csv', 'txt'):
        # ... 现有逻辑 ...
```

**Step 2 —— 解析器实现**

使用 Python 标准库 `xml.etree.ElementTree`（无需第三方依赖）：

```python
@staticmethod
def _parse_keepass_xml(file_path: str) -> List[Dict]:
    import xml.etree.ElementTree as ET
    accounts = []
    tree = ET.parse(file_path)
    root = tree.getroot()

    def extract_entries(group_elem, parent_category="其他"):
        # 当前 Group 的名称
        category = parent_category
        name_elem = group_elem.find('Name')
        if name_elem is not None and name_elem.text:
            category = name_elem.text

        # 处理当前 Group 下的 Entry
        for entry in group_elem.findall('Entry'):
            strings = {}
            for string in entry.findall('String'):
                key = string.find('Key')
                value = string.find('Value')
                if key is not None and value is not None:
                    strings[key.text or ''] = value.text or ''

            title = strings.get('Title', '')
            if not title:
                continue  # 跳过无标题条目（KeePass 中可能存在元数据条目）

            accounts.append({
                'app_name': title,
                'url': strings.get('URL', ''),
                'username': strings.get('UserName', ''),
                'password': strings.get('Password', ''),
                'remark': strings.get('Notes', ''),
                'category': category or '其他',
            })

        # 递归处理子 Group
        for child_group in group_elem.findall('Group'):
            extract_entries(child_group, category)

    # 从 Root 开始遍历
    root_elem = root.find('Root')
    if root_elem is not None:
        for group in root_elem.findall('Group'):
            extract_entries(group)

    return accounts
```

**边界处理**：

| 场景 | 处理策略 |
|------|---------|
| 递归层级过深（>10） | Python 默认递归深度 1000，无需特殊处理 |
| Entry 无 Title | 跳过（KeePass 的回收站/元数据条目通常无 Title） |
| 密码带 `ProtectInMemory="True"` | `ElementTree` 正常读取 text，无需特殊处理 |
| URL 为空 | 保留空字符串 |
| 多层级 Group | 取直接父 Group 名作为 category（扁平化处理） |

**Step 3 —— UI 适配**

- `ui/import_dialog.py`：管理器模式文件过滤器增加 `*.xml`
- 提示文字同步更新

**涉及文件**：
- `services/import_service.py`（新增解析器 + 检测逻辑）
- `ui/import_dialog.py`（过滤器 + 提示文字更新）
- `ui/main_window.py`（错误提示更新）

**预计工作量**：~2 小时

---

## 3. Bug 修复计划

### 3.1 P0 — 阻塞性/稳定性问题

#### 3.1.1 AI 调用主线程阻塞（14 处 TODO）

##### 问题描述

全项目共 **14 处** `TODO(P0-3)` 标记，分布在 7 个文件中。所有位置均在主线程直接实例化 `OllamaClient` 并发起同步 HTTP 请求，Ollama 模型加载或推理耗时可达 30~60 秒，期间 UI 完全冻结无响应。

| # | 文件 | 行号 | 调用方法 |
|---|------|------|---------|
| 1 | `services/category_service.py` | 61 | `ollama.categorize()` |
| 2 | `services/category_service.py` | 130 | `ollama.categorize()` |
| 3 | `services/tools/utility_tools.py` | 24 | `ollama.generate()` |
| 4 | `services/tools/utility_tools.py` | 55 | `ollama.generate()` |
| 5 | `services/tools/search_tools.py` | 74 | `ollama.semantic_match()` |
| 6 | `services/tools/search_tools.py` | 103 | `ollama.semantic_match()` |
| 7 | `ui/dialogs/health_check_dialog.py` | 59 | `ollama.generate_stream()` |
| 8 | `ui/dialogs/health_check_dialog.py` | 906 | `ollama.generate_stream()` |
| 9 | `services/tag_service.py` | 137 | `ollama.generate()` |
| 10 | `services/assistant/action_mixin.py` | 295 | `BatchAddProcessor.parse_batch_text(..., ollama)` |
| 11 | `services/assistant/query_mixin.py` | 89 | `ollama.semantic_match()` |
| 12 | `services/assistant/query_mixin.py` | 159 | `ollama.parse_command()` |
| 13 | `services/assistant/query_mixin.py` | 335 | `ollama.generate_stream()` |
| 14 | `services/assistant/query_mixin.py` | 546 | `ollama` 工具选择（流式） |

##### 根因分析

项目中已存在完善的异步基础设施：
- `services/ai_service_manager.py` —— `AIServiceManager` 管理 `AIWorkerThread` 任务队列
- `services/ai_worker_thread.py` —— 后台线程执行 AI 调用，通过信号返回结果
- `AIServiceManager.submit_task(task_id, prompt, callback, stream=False)` 接口已就绪

但业务层完全未使用，形成"有路不走"的架构浪费。

##### 修复方案

**核心原则**：
1. **所有 AI 调用必须下沉到 `AIWorkerThread` 异步执行**
2. **主线程只处理 UI 更新（信号槽）**
3. **流式输出继续使用 `generate_stream()`，但必须在子线程中迭代，通过信号将 token 发回主线程**
4. **超时保持 300 秒（最低 5 分钟，不可降低）**

**非流式调用迁移模式（以 `category_service.py:61` 为例）**：

改造前：
```python
# TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行
ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=300)
ai_category = ollama.categorize(app_name, url)
```

改造后：
```python
from services.ai_service_manager import AIServiceManager

def _on_categorize_finished(self, task_id: str, result: str):
    self.pending_ai_category = result
    self._continue_add_account()  # 继续后续流程

def start_ai_categorize(self, app_name: str, url: str):
    prompt = f"请对应用'{app_name}'（网址：{url}）进行分类..."
    ai_manager = AIServiceManager.instance()
    ai_manager.submit_task(
        task_id=f"cat_{id(self)}",
        prompt=prompt,
        callback=self._on_categorize_finished,
        stream=False
    )
```

**流式调用迁移模式（以 `health_check_dialog.py` 为例）**：

流式输出无法直接走 `submit_task()`（其接口设计为返回完整结果），需在子线程中手动管理：

```python
from PyQt6.QtCore import QThread, pyqtSignal

class StreamWorker(QThread):
    token_received = pyqtSignal(str)
    finished_signal = pyqtSignal(str)

    def __init__(self, prompt: str, model: str):
        super().__init__()
        self.prompt = prompt
        self.model = model

    def run(self):
        ollama = OllamaClient(model=self.model, timeout=300)
        full_text = ""
        try:
            for token in ollama.generate_stream(self.prompt, temperature=0.5):
                full_text += token
                self.token_received.emit(token)
        except Exception as e:
            self.token_received.emit(f"\n[错误: {e}]")
        self.finished_signal.emit(full_text)

# UI 层使用
self.stream_worker = StreamWorker(prompt, model)
self.stream_worker.token_received.connect(self._append_token)
self.stream_worker.finished_signal.connect(self._on_stream_finished)
self.stream_worker.start()
```

**各文件具体迁移策略**：

| 文件 | 改造方式 | 特殊注意 |
|------|---------|---------|
| `services/category_service.py` | 两处的 `categorize()` 改为异步回调 | 上层调用方（`AccountDialog` 或 `main_window`）需适配为"发起-等待-继续"的异步模式 |
| `services/tools/utility_tools.py` | 两处的 `generate()` 改为异步 | 工具链返回结果给 AI 助手，需确保 AI 助手等待工具完成后再继续 |
| `services/tools/search_tools.py` | 两处的 `semantic_match()` 改为异步 | 语义搜索工具被 query_mixin 调用，query_mixin 本身也在改造 |
| `services/tag_service.py` | `generate()` 改为异步 | 标签生成是后台任务，可直接异步 |
| `ui/dialogs/health_check_dialog.py` | 两处的流式生成改为 `StreamWorker` | 对话框需显示"分析中..."动画，token 实时追加 |
| `services/assistant/action_mixin.py` | `parse_batch_text()` 参数中的 `ollama` 移除，内部自行异步调用 | `BatchAddProcessor` 需拆分为"解析（纯本地）+ AI 补全（异步）"两阶段 |
| `services/assistant/query_mixin.py` | 4 处：语义匹配、命令解析、流式输出、工具选择 | 这是改造最复杂的文件，query_mixin 是 AI 助车的查询中枢，需重新设计为基于信号的状态机 |

**query_mixin.py 状态机重构建议**：

当前 `query_mixin.py` 的查询处理是同步顺序执行：
1. 语义匹配 → 2. 命令解析 → 3. 执行动作/流式生成

改造为异步状态机：

```python
class QueryState(Enum):
    IDLE = 0
    SEMANTIC_MATCHING = 1
    COMMAND_PARSING = 2
    EXECUTING = 3
    STREAMING = 4
    DONE = 5

class QueryMixin:
    def process_query_async(self, query: str):
        self._query_state = QueryState.SEMANTIC_MATCHING
        self._submit_ai_task("semantic", prompt, self._on_semantic_done)

    def _on_semantic_done(self, task_id, result):
        self._semantic_result = result
        self._query_state = QueryState.COMMAND_PARSING
        self._submit_ai_task("parse", prompt, self._on_parse_done)

    def _on_parse_done(self, task_id, result):
        # ... 根据解析结果决定执行或流式输出
```

**涉及文件**（7 个文件，14 处）：
- `services/category_service.py`
- `services/tools/utility_tools.py`
- `services/tools/search_tools.py`
- `services/tag_service.py`
- `ui/dialogs/health_check_dialog.py`
- `services/assistant/action_mixin.py`
- `services/assistant/query_mixin.py`

**预计工作量**：2~3 天（query_mixin 的异步状态机重构占主要工作量）

---

#### 3.1.2 Repository search 全表加载

##### 问题描述

`core/repositories.py` 中 `AccountRepository.search()` 与 `URLRepository.search()` 已下沉到 SQL 层（`database.py:584`、`url_database.py:458`），使用 `LIKE` + `LIMIT 500` 实现，已优化。

但以下方法仍存在全表加载：

| 类 | 方法 | 问题代码 | 行号 |
|----|------|---------|------|
| `AccountRepository` | `filter_by_tags()` | `accounts = self.get_all()` | 217 |
| `AccountRepository` | `get_uncategorized()` | `accounts = self.get_all()` | 232 |
| `AccountRepository` | `resolve_filter_conditions()` | `accounts = self.get_all()` | 320 |
| `URLRepository` | `filter_by_tags()` | `urls = self.get_all()` | 395 |
| `URLRepository` | `get_uncategorized()` | `urls = self.get_all()` | 410 |
| `URLRepository` | `resolve_filter_conditions()` | `urls = self.get_all()` | 496 |

`get_all()` 会从 SQLite 读取全部记录并逐条解密，数据量 >1000 时内存和 CPU 开销剧增。

##### 修复方案

**方案 A：SQL 层过滤（推荐）**

在 `database.py` / `url_database.py` 中新增带条件的查询方法，避免全量加载：

```python
# core/database.py —— 新增方法

def get_accounts_by_tag(self, tag: str, limit: int = 500) -> List[Dict]:
    """SQL 层按标签筛选，避免全表加载"""
    with self._lock:
        # tags 是 JSON 字符串，如 '["支付", "理财"]'
        # 使用 JSON_CONTAINS (SQLite 3.38+) 或 LIKE 模糊匹配
        self.cursor.execute(
            "SELECT * FROM accounts WHERE tags LIKE ? ORDER BY app_name LIMIT ?",
            (f'%"{tag}"%', limit)
        )
        return [dict(row) for row in self.cursor.fetchall()]

def get_uncategorized_accounts(self, limit: int = 500) -> List[Dict]:
    """获取未分类账号（category == '其他' 或为空）"""
    with self._lock:
        self.cursor.execute(
            "SELECT * FROM accounts WHERE category = '其他' OR category = '' ORDER BY app_name LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in self.cursor.fetchall()]
```

Repository 层改为调用新方法：

```python
def filter_by_tags(self, tag: str) -> SearchResult:
    rows = self.db.get_accounts_by_tag(tag)
    matched = [Account.from_dict(self.db._decrypt_row(row)) for row in rows]
    ...
```

**注意**：`database.py` 的 `_decrypt_row()` 方法是否存在需确认。若不存在，新增一个仅解密指定字段的辅助方法。

**方案 B：Repository 层缓存（备选）**

若 SQL 层改造涉及 `resolve_filter_conditions()` 的复杂条件解析（多字段组合过滤），短期可在 Repository 层增加 LRU 缓存：

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def _get_all_cached(self) -> Tuple[Account, ...]:
    return tuple(self.get_all())
```

但缓存会引入数据一致性风险，仅作为临时缓解，长期仍应下沉到 SQL。

**涉及文件**：
- `core/database.py`（新增 SQL 层过滤方法）
- `core/url_database.py`（同上）
- `core/repositories.py`（6 个方法改为调用 SQL 层）

**预计工作量**：2~4 小时

---

#### 3.1.3 database.close() 未加锁

##### 问题描述

`docs/feature_inventory.md` 中标记此问题为"⚠️ 待修复"，但**实际代码中已修复**。

当前实现：
- `core/database.py:323`：`close()` 方法已使用 `with self._lock:`
- `core/url_database.py:162`：`close()` 方法已使用 `with self._lock:`

`docs/project_audit_fix_completion_2026-05-10.md` 已将 P0-3 标记为"✅ 已修复"。

##### 修复方案

**无需代码修改**，仅需文档同步：

1. 更新 `docs/feature_inventory.md`，将 `database.close() 未加锁` 的状态从"⚠️ 待修复"改为"✅ 已修复"
2. 若 `docs/project_research_report_2026-05-10.md` 中仍提及此问题，追加勘误说明

**预计工作量**：10 分钟

---

#### 3.1.4 restore_account() 解密失败崩溃 / 事务原子性破坏

##### 问题描述

**原始问题（解密失败崩溃）已修复**：`core/database.py:1116` 的 `restore_account()` 在 `json.loads()` 前检查了 `decrypted_json == '[解密失败]'`，若失败则返回 `None`。

**衍生问题（事务原子性破坏）未修复**：

```python
def restore_account(self, recycle_id: int) -> Optional[Dict]:
    with self._lock:
        # ... 获取回收站记录并解密 ...
        new_id = self.insert_account(account_data)  # ← 内部自行 _commit()
        # ... 如果后续 UPDATE recycle_bin 失败，account 已无法回滚 ...
        self.cursor.execute("UPDATE recycle_bin SET is_restored = 1 ...")
        self._commit()
```

`insert_account()` 内部会调用 `_commit()`，导致事务在 `restore_account()` 执行中途被提交。若后续 `UPDATE recycle_bin` 失败，已插入的 account 残留在 `accounts` 表中，造成数据不一致（账号恢复成功但回收站记录未标记为已恢复）。

##### 修复方案

**方案：提供「事务内插入」的私有方法**

```python
def _insert_account_without_commit(self, account_data: Dict) -> int:
    """在已有事务上下文中插入账号，不自行 commit"""
    encrypted = {
        'app_name': self._encrypt_field(account_data['app_name']),
        # ... 其他字段加密 ...
    }
    self.cursor.execute(
        "INSERT INTO accounts (app_name, ...) VALUES (?, ...)",
        tuple(encrypted.values())
    )
    return self.cursor.lastrowid

def restore_account(self, recycle_id: int) -> Optional[Dict]:
    with self._lock:
        try:
            # ... 获取并解密回收站记录 ...
            if decrypted_json == '[解密失败]':
                return None

            account_data = json.loads(decrypted_json)
            account_data.pop('id', None)
            # ... 清理时间戳字段 ...

            # 使用无 commit 版本插入
            new_id = self._insert_account_without_commit(account_data)

            self.cursor.execute(
                "UPDATE recycle_bin SET is_restored = 1, restored_at = CURRENT_TIMESTAMP WHERE id = ?",
                (recycle_id,)
            )
            self._commit()

            account_data['id'] = new_id
            return account_data
        except Exception as e:
            self.conn.rollback()
            logger.error("restore_account error: %s", e)
            return None
```

**额外检查**：搜索 `database.py` 中其他「事务嵌套调用 insert_account」的场景（如批量恢复），统一使用 `_insert_account_without_commit()`。

**涉及文件**：
- `core/database.py`

**预计工作量**：30 分钟

---

### 3.2 P1 — 性能/可靠性问题

#### 3.2.1 AI 聊天全量重绘卡顿

##### 问题描述

`ui/main_window.py:6316` 的 `_ai_update_chat_display()` 每次调用都遍历**整个对话历史**，将每条消息重新渲染为 HTML，然后 `setHtml()` 全量替换。

雪上加霜的是，流式输出时虽然用了 `insertHtml()` 增量追加，但设置了 **1 秒定时器** `_ai_refresh_timer`，每秒触发一次全量重建。对话历史较长时（20 条以上）CPU 开销显著。

`ui/ai_chat_renderer.py`（与 `ui/widgets/ai_chat_renderer.py` 代码重复）的 `markdown_to_html()` 每次渲染都重新获取 `ThemeManager.instance().colors`，并对每条消息执行 10+ 次正则替换。

##### 修复方案

**Step 1 —— 移除 1 秒定时器全量重建**

```python
# 改造前
self._ai_refresh_timer.start(1000)  # 每秒全量重建

# 改造后
# 仅在有结构变化（消息新增、折叠/展开、代码块复制状态变更）时局部更新
# 流式输出期间完全依赖 insertHtml() 增量追加，不触发全量重建
```

**Step 2 —— 实现「增量更新」策略**

定义三种更新级别：

| 级别 | 触发条件 | 操作 |
|------|---------|------|
| **Token 追加** | 流式输出收到新 token | `insertHtml()` 在末尾追加，不重建 |
| **消息追加** | 单条消息完成（assistant 结束） | `insertHtml()` 插入完整消息 HTML |
| **全量重建** | 模式切换、历史清空、主题切换 | `_ai_update_chat_display()` 全量重建 |

```python
def _ai_append_message(self, message_html: str):
    """在末尾追加一条完整消息（不使用 setHtml）"""
    cursor = self.result_area.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertHtml(message_html)
    self.result_area.setTextCursor(cursor)
    self.result_area.ensureCursorVisible()
```

**Step 3 —— 缓存已渲染的 HTML**

为每条消息增加缓存：

```python
class ChatMessage:
    def __init__(self, role, content):
        self.role = role
        self.content = content
        self._cached_html = None

    def get_html(self, renderer) -> str:
        if self._cached_html is None:
            self._cached_html = renderer.render(self)
        return self._cached_html

    def invalidate_cache(self):
        self._cached_html = None
```

仅当消息内容变化时（如编辑、重新生成）才 `invalidate_cache()`。

**Step 4 —— 合并重复的 ai_chat_renderer**

`ui/ai_chat_renderer.py` 与 `ui/widgets/ai_chat_renderer.py` 内容几乎相同。确认引用关系后删除其中一个，统一 import 路径。

**Step 5 —— Markdown 渲染优化**

```python
def markdown_to_html(self, text: str) -> str:
    colors = ThemeManager.instance().colors  # 只获取一次
    # ... 正则替换 ...
```

**涉及文件**：
- `ui/main_window.py`
- `ui/ai_chat_renderer.py`
- `ui/widgets/ai_chat_renderer.py`（删除或保留其一）

**预计工作量**：4 小时

---

#### 3.2.2 批量操作缺乏事务保护

##### 问题描述

三处高风险场景缺乏事务保护：

**场景 1：ImportDialog 文件导入（`ui/import_dialog.py:592`）**

```python
def on_import(self):
    for item in new_items:
        account = item.to_account()
        self.account_service.add_account(account)  # 逐条 commit
```

**场景 2：BatchAddProcessor AI 批量添加（`services/batch_add_processor.py:292`）**

```python
def _execute_batch_add(cls, items, repo):
    for item in items:
        new_id = repo.insert(item_data)  # 逐条 commit
```

**场景 3：类别批量删除（`ui/main_window.py:3049`）**

```python
def _execute_category_batch_delete(self):
    for category in self._selected_categories:
        self.account_service.delete_category(category)  # 逐个调用
```

##### 修复方案

**方案：使用 `with db.transaction()` 上下文管理器包裹**

项目已有成功范例：
- `main_window.py:3747` `_execute_batch_delete` 已使用 `with db.transaction()`
- `main_window.py:3805` `_execute_batch_categorize` 已使用 `with db.transaction()`

**ImportDialog 改造**：

```python
def on_import(self):
    new_items = [...]
    db = self.account_service.db  # 或直接获取 DatabaseManager 实例
    try:
        with db.transaction():  # 启动事务
            for item in new_items:
                account = item.to_account()
                # 绕过 add_account() 内部的 commit，直接调用 db.insert_account()
                db.insert_account(account.to_dict())
        # 事务成功，刷新 UI
        self._refresh_after_import()
    except Exception as e:
        logger.error("批量导入事务失败，已回滚: %s", e)
        QMessageBox.critical(self, "导入失败", f"导入过程中发生错误，所有变更已回滚。\n{e}")
```

**注意**：`account_service.add_account()` 内部会调用 `db.insert_account()` + `_commit()`。在事务模式下，需要：
- 方案 A：新增 `DatabaseManager.insert_account_no_commit()` 私有方法（见 3.1.4）
- 方案 B：`DatabaseManager` 支持嵌套事务或 `autocommit=False` 模式

**推荐方案 A**，因为 SQLite 不支持真正的嵌套事务（SAVEPOINT 虽可模拟，但改动面大）。

**BatchAddProcessor 改造**：

```python
def _execute_batch_add(cls, items, repo):
    db = repo.db
    success_count = 0
    try:
        with db.transaction():
            for item in items:
                item_data = cls._batch_item_to_dict(item, repo)
                db._insert_without_commit(item_data)  # 使用无 commit 版本
                success_count += 1
    except Exception as e:
        logger.error("批量添加事务失败: %s", e)
        # 全部回滚，success_count 不会被外部使用（事务失败时返回 0）
        return {"success": 0, "failed": len(items), "error": str(e)}
    return {"success": success_count, "failed": len(items) - success_count}
```

**类别批量删除改造**：

```python
def _execute_category_batch_delete(self):
    db = self.account_service.db
    try:
        with db.transaction():
            for category in self._selected_categories:
                if self.current_vault == 'accounts':
                    self.account_service._delete_category_no_commit(category)
                else:
                    self._url_service._delete_category_no_commit(category)
        self._refresh_category_list()
    except Exception as e:
        logger.error("批量删除类别失败: %s", e)
        QMessageBox.critical(self, "删除失败", "部分类别删除失败，所有变更已回滚。")
```

**涉及文件**：
- `ui/import_dialog.py`
- `services/batch_add_processor.py`
- `ui/main_window.py`
- `core/database.py` / `core/url_database.py`（可能需要新增 `_no_commit` 辅助方法）

**预计工作量**：2 小时

---

#### 3.2.3 其他 P1 问题（12 项汇总）

| # | 问题 | 文件 | 修复方案 | 预计工作量 |
|---|------|------|---------|-----------|
| 1 | **Excel Workbook 未关闭** | `services/import_service.py:349, 449` | `load_workbook` 后用 `try/finally: wb.close()` 或 `with` 语句 | 15 分钟 |
| 2 | **HTTP 连接未复用** | `ai/client_base.py:68, 128` | `OllamaClient` 初始化时创建 `requests.Session()`，所有 `post` 改为 `self.session.post()`，`__del__` 中 `session.close()` | 30 分钟 |
| 3 | **AccountService.search_accounts 全表加载** | `services/account_service.py:129` | 改为调用 `self.db.search_accounts()`（SQL 层已优化），不再 `get_all_accounts()` | 30 分钟 |
| 4 | **AccountService.get_all_accounts 无缓存** | `services/account_service.py:91` | 新增 `@lru_cache` 或基于信号的手动缓存（数据变更时 invalidate），短期可用 LRU 缓解 | 30 分钟 |
| 5 | **静默吞错：database.py 解密失败返回原值** | `core/database.py:247` | `except Exception:` 中增加 `logger.warning("解密失败，返回密文: %s", e)` | 10 分钟 |
| 6 | **静默吞错：database.py 多处异常无日志** | `core/database.py:635, 648` | 补充 `logger.warning` 记录异常信息和堆栈 | 15 分钟 |
| 7 | **静默吞错：url_database.py 多处异常无日志** | `core/url_database.py:528, 581, 821` | 补充 `logger.warning` 记录异常信息 | 15 分钟 |
| 8 | **静默吞错：url_service.py 异常 pass** | `services/url_service.py:166, 318` | 补充 `logger.warning` 记录异常信息 | 10 分钟 |
| 9 | **静默吞错：account_list_item.py 多处静默捕获** | `ui/widgets/account_list_item.py:130, 311...` | 区分「预期异常」（如网络失败）和「意外异常」，后者记录 `logger.error` | 30 分钟 |
| 10 | **静默吞错：url_list_item.py 多处静默捕获** | `ui/widgets/url_list_item.py:276, 295, 306` | 同上，补充日志 | 20 分钟 |
| 11 | **主窗口信号断开异常静默忽略** | `ui/main_window.py:5456, 5460, 5920, 5925` | 补充 `logger.debug` 记录断开失败的原因（通常是对象已销毁） | 15 分钟 |
| 12 | **ai_chat_renderer 代码重复** | `ui/ai_chat_renderer.py` vs `ui/widgets/ai_chat_renderer.py` | 确认所有 import 来源，删除冗余文件，统一路径 | 20 分钟 |

**预计总工作量**：~4 小时（12 项合计）

---

## 4. 测试覆盖补齐计划

### 4.1 当前测试现状

| 模块 | 测试文件 | 测试数量 | 覆盖率 |
|------|---------|---------|--------|
| `services/account_service.py` | `tests/test_account_service.py` | 6 | 基础 CRUD |
| `services/search_service.py` | `tests/test_search_service.py` | 4 | 精确/部分/拼音匹配 |
| `core/crypto.py` | `tests/test_crypto.py` | 8 | 加解密、密钥 |
| `models/` | `tests/test_id_type_consistency.py` | 4 | ID 类型一致性 |
| **总计** | **4 个测试文件** | **22** | **极低** |

**未测试核心模块**（33+ 个文件）：
- `services/`：`ai_assistant_service.py`、`ai_classification_service.py`、`ai_remark_service.py`、`ai_service_manager.py`、`ai_tools.py`、`ai_worker_thread.py`、`batch_add_processor.py`、`category_service.py`、`conversation_context.py`、`export_service.py`、`import_service.py`、`ocr_service.py`、`semantic_search_service.py`、`sync_service.py`、`tag_service.py`、`url_service.py`、以及 `assistant/` 和 `tools/` 子包（13 个）
- `core/`：`category_utils.py`、`clipboard.py`、`database.py`、`logger.py`、`password_generator.py`、`password_strength.py`、`pinyin.py`、`repositories.py`、`theme_manager.py`、`url_database.py`
- `ui/`：**全部未测试**（31 个文件）

### 4.2 补齐策略

#### 原则

1. **优先覆盖 data layer 和 service layer** —— UI 层测试成本高、收益低，后续可补充
2. **所有新功能必须附带测试** —— 1Password/KeePass 导入器、帮助弹窗等
3. **所有 Bug 修复必须附带回归测试** —— 防止复发
4. **使用 pytest + 内存数据库** —— 现有 `conftest.py` 已提供 `temp_db` fixture

#### 测试文件规划

| 新建测试文件 | 目标模块 | 测试用例设计 | 预计数量 |
|-------------|---------|-------------|---------|
| `tests/test_import_service.py` | `services/import_service.py` | ① 各格式检测（bitwarden_csv/json, lastpass_csv, 1password_csv, keepass_xml, unknown）<br>② 各解析器字段映射正确性<br>③ 边界：空文件、无标题行、特殊字符、大文件<br>④ ExcelParser / TextParser / MarkdownParser 基础解析 | 15 |
| `tests/test_database.py` | `core/database.py` | ① CRUD 基本操作<br>② 加密字段是否正确写入密文<br>③ 搜索（search_accounts）SQL 层过滤<br>④ 回收站（recycle_bin 插入/恢复/永久删除）<br>⑤ 事务回滚（insert + 异常回滚）<br>⑥ restore_account 解密失败返回 None<br>⑦ restore_account 事务原子性（mock insert_account 抛异常） | 12 |
| `tests/test_url_database.py` | `core/url_database.py` | ① URL 的 CRUD<br>② 搜索过滤<br>③ 回收站 | 6 |
| `tests/test_repositories.py` | `core/repositories.py` | ① AccountRepository 的 search/filter_by_tags/get_uncategorized<br>② URLRepository 同上<br>③ 验证 filter_by_tags 不走 get_all()（mock get_all 未调用） | 8 |
| `tests/test_category_service.py` | `services/category_service.py` | ① 分类提取<br>② 分类排序<br>③ AI 分类（mock OllamaClient） | 5 |
| `tests/test_tag_service.py` | `services/tag_service.py` | ① 标签 CRUD<br>② AI 标签生成（mock） | 4 |
| `tests/test_export_service.py` | `services/export_service.py` | ① 导出 Excel/CSV/JSON<br>② 加密备份导出/导入<br>③ 导出的敏感数据是否明文 | 6 |
| `tests/test_password_generator.py` | `core/password_generator.py` | ① 默认参数生成<br>② 自定义参数（长度、字符集）<br>③ 加密安全随机性验证（统计检验，或至少验证包含指定字符集） | 4 |
| `tests/test_password_strength.py` | `core/password_strength.py` | ① 各等级密码评分<br>② 边界：空密码、超长密码、全重复字符 | 4 |
| `tests/test_batch_add_processor.py` | `services/batch_add_processor.py` | ① 正常批量解析<br>② 事务保护验证（mock repo.insert 中途抛异常，验证无残留） | 4 |

**预计新增测试数量**：68 个

**预计工作量**：每项约 15~30 分钟，总计 ~2 天

### 4.3 测试基础设施增强

```python
# tests/conftest.py 新增 fixture

import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_ollama():
    """提供 mock 的 OllamaClient，用于隔离 AI 相关测试"""
    mock = MagicMock()
    mock.categorize.return_value = "开发工具"
    mock.generate.return_value = "这是一条 AI 生成的备注"
    mock.semantic_match.return_value = "匹配结果"
    mock.generate_stream.return_value = iter(["你好", "世界"])
    return mock

@pytest.fixture
def temp_vault_file(tmp_path):
    """提供临时加密备份文件路径"""
    return tmp_path / "test_backup.vault"
```

---

## 5. 用户使用说明（帮助系统）设计方案

### 5.1 设计目标

- **降低学习成本**：新用户首次打开软件即可了解核心功能
- **统一视觉风格**：复用「炽阳」帮助弹窗的设计语言（`LocalHelpDialog`），保持视觉一致性
- **上下文无关**：帮助文档涵盖全部功能，不局限于当前所在页面
- **离线可用**：所有帮助内容内嵌在代码中，无需联网

### 5.2 视觉设计规范（复用 LocalHelpDialog）

| 元素 | 规格 |
|------|------|
| 窗口尺寸 | 默认 640×720，最小 600×640 |
| 窗口标题 | "使用帮助" |
| Header | 顶部大标题 + 副标题 + 水平分割线 |
| 内容区 | `QScrollArea` 包裹，支持垂直滚动，水平滚动条隐藏 |
| 卡片样式 | `border-radius: 10px; border: 1px solid colors.border_subtle; background: colors.bg_primary` |
| 示例卡片 | 圆角卡片内显示示例语句，字号 13px |
| 小贴士卡片 | 独立圆角卡片，使用 bullet 列表，圆角 12px |
| 底部按钮 | 居中 "完成" 按钮，`border-radius: 17px`，宽 120px，高 34px |
| 颜色 | 全部从 `ThemeManager.instance().colors` 动态获取，适配暗色/亮色主题 |

### 5.3 内容结构设计

帮助文档按功能模块组织，共分为 **6 大章节**：

#### 章节 1：快速入门

```
🔰 欢迎使用 SecretManage
  └─ 什么是 SecretManage？（一句话简介 + 安全特性 badge）
  └─ 首次使用三步走
      ① 设置主密码（AES-256-GCM 加密）
      ② 添加第一条账号（点击「+ 新建账号」）
      ③ 体验 AI 助手「炽阳」（点击右侧 AI 面板）
  └─ 界面概览（配文字说明，标注：顶部工具栏、左侧分类树、中间列表区、右侧 AI 面板）
```

#### 章节 2：账号与网址管理

```
📁 账号库与网址库
  └─ 添加账号/网址（手动输入 vs 批量导入）
  └─ 编辑与删除（双击编辑、回收站恢复）
  └─ 分类与标签（级联分类、标签筛选、批量修改分类）
  └─ 收藏与排序（星标收藏、按名称/时间排序）
  └─ 一键复制（账号、密码、网址的复制按钮 + 剪贴板 20 秒自动清除说明）
```

#### 章节 3：导入与导出

```
📥 数据迁移
  └─ 支持的导入格式
      • Bitwarden（JSON / CSV）
      • LastPass（CSV）
      • 1Password（CSV）← 新功能
      • KeePass（XML）← 新功能
      • Excel（.xlsx / .xls）
      • Markdown / 文本
      • 加密备份（.vault）
  └─ 导出方式
      • Excel / CSV / JSON 明文导出（⚠️ 注意保管文件）
      • 加密备份导出（推荐用于定期备份）
```

#### 章节 4：AI 助手「炽阳」

```
🤖 炽阳 — 你的本地 AI 助手
  └─ Plan 模式（只读查询）
      • 语义搜索、条件筛选、分类统计、密码强度检测
  └─ Build 模式（确认后执行）
      • 批量新增、批量更新分类/标签、AI 生成备注
      • 智能整理、批量删除、生成强密码
  └─ 使用技巧
      • 首次使用发送任意消息完成「预热」
      • 支持上下文指代（「刚才找到的」「前面那些」）
      • Build 模式先展示预览表格，确认后才执行
```

#### 章节 5：安全与隐私

```
🔒 安全架构
  └─ 加密方式：AES-256-GCM + PBKDF2 密钥派生
  └─ 本地运行：AI 模型完全本地（Ollama），数据不上传云端
  └─ 剪贴板保护：密码复制后 20 秒自动清除
  └─ 健康检查：弱密码、重复密码、泄露风险检测
  └─ 密码生成器：内置 cryptographically secure 随机密码生成
```

#### 章节 6：常见问题（FAQ）

```
❓ 常见问题
  └─ Q: 忘记主密码怎么办？ → A: 主密码是加密唯一密钥，无法找回，请务必牢记。
  └─ Q: AI 助手响应慢/无响应？ → A: 首次使用需加载模型，请等待 30~60 秒；确保 Ollama 服务已启动。
  └─ Q: 如何备份数据？ → A: 使用「导出 → 加密备份」，生成 .vault 文件妥善保存。
  └─ Q: 导入时出现重复？ → A: 导入预览中会标记重复项，可选择跳过或覆盖。
  └─ Q: 支持多设备同步吗？ → A: 当前版本为纯本地应用，可通过手动复制 .vault 备份文件实现跨设备迁移。
```

### 5.4 实现方案

**Step 1 —— 新建帮助弹窗类**

```python
# ui/dialogs/help_dialog.py

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QFrame, QWidget
from PyQt6.QtCore import Qt
from core.theme_manager import ThemeManager

class HelpDialog(QDialog):
    """软件使用帮助对话框（复用 LocalHelpDialog 视觉风格）"""

    def __init__(self, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self.setWindowTitle("使用帮助")
        self.setMinimumSize(600, 640)
        self.resize(640, 720)

        # 整体布局复用 LocalHelpDialog 结构
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QWidget()
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(32, 24, 32, 16)
        h_layout.setSpacing(4)
        lbl_title = QLabel("使用帮助")
        lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 22px; font-weight: 600;")
        h_layout.addWidget(lbl_title)
        lbl_sub = QLabel("快速上手 SecretManage 本地密码保险箱")
        lbl_sub.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 14px;")
        h_layout.addWidget(lbl_sub)
        main_layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {colors.border_light};")
        main_layout.addWidget(sep)

        # ScrollArea + 内容
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(32, 20, 32, 12)
        c_layout.setSpacing(0)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ===== 章节 1：快速入门 =====
        self._add_section(c_layout, "🔰 快速入门", colors)
        self._add_paragraph(c_layout,
            "SecretManage 是一款基于 PyQt6 的本地密码管理器，所有数据均使用 AES-256-GCM "
            "加密存储在本地 SQLite 数据库中，AI 助手完全本地运行，数据不会上传任何云端服务器。",
            colors)
        self._add_subtitle(c_layout, "首次使用三步走", colors)
        steps = [
            ("① 设置主密码", "首次启动时会要求设置主密码，这是加密数据库的唯一密钥，请务必牢记。主密码无法找回。"),
            ("② 添加第一条账号", "点击顶部工具栏的「+ 新建账号」按钮，填写应用名、账号、密码等信息后保存。"),
            ("③ 体验 AI 助手", "点击右侧「炽阳」面板，发送任意消息完成模型预热，即可使用语义搜索、智能分类等功能。"),
        ]
        for title, desc in steps:
            self._add_feature_card(c_layout, title, desc, [], colors)

        # ===== 章节 2：账号与网址管理 =====
        self._add_section(c_layout, "📁 账号与网址管理", colors)
        features = [
            ("双库管理", "左侧导航栏可在「账号库」和「网址库」之间切换，账号库用于存储登录凭证，网址库用于收藏常用网站。", []),
            ("分类与标签", "支持级联分类（如「工作 > 开发工具」）和灵活标签。选中条目后右键可批量修改分类或添加标签。", []),
            ("一键复制", "列表每行右侧有三个图标按钮，分别用于复制网址、账号和密码。密码复制后，剪贴板将在 20 秒后自动清空。", []),
            ("收藏与排序", "点击条目左侧的星标可将其加入收藏。顶部工具栏可选择按名称、添加时间等维度排序。", []),
        ]
        for title, desc, ex in features:
            self._add_feature_card(c_layout, title, desc, ex, colors)

        # ===== 章节 3：导入与导出 =====
        self._add_section(c_layout, "📥 数据迁移", colors)
        self._add_paragraph(c_layout,
            "支持从主流密码管理器迁移数据，也可将数据导出为多种格式进行备份。",
            colors)
        import_formats = [
            "Bitwarden（JSON / CSV）", "LastPass（CSV）", "1Password（CSV）",
            "KeePass（XML）", "Excel（.xlsx / .xls）", "Markdown / 文本", "加密备份（.vault）"
        ]
        self._add_bullet_list(c_layout, "支持的导入格式：", import_formats, colors)

        export_notes = [
            "Excel / CSV / JSON 导出为明文格式，导出后请妥善保管文件。",
            "加密备份（.vault）使用与主密码相同的密钥加密，是最安全的备份方式。"
        ]
        self._add_bullet_list(c_layout, "导出注意事项：", export_notes, colors)

        # ===== 章节 4：AI 助手「炽阳」 =====
        self._add_section(c_layout, "🤖 AI 助手「炽阳」", colors)
        self._add_paragraph(c_layout,
            "炽阳基于本地 Ollama + gemma4:4b 模型运行，支持两种工作模式。",
            colors)

        # Plan badge
        plan_header = QHBoxLayout()
        plan_header.setSpacing(10)
        plan_badge = QLabel("Plan")
        plan_badge.setStyleSheet(f"color: {colors.accent_blue}; background-color: {colors.accent_blue_bg_light}; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;")
        plan_name = QLabel("规划模式（只读）")
        plan_name.setStyleSheet(f"color: {colors.text_primary}; font-size: 16px; font-weight: 600;")
        plan_header.addWidget(plan_badge)
        plan_header.addWidget(plan_name)
        plan_header.addStretch()
        c_layout.addLayout(plan_header)
        self._add_paragraph(c_layout,
            "仅查询和分析现有数据，不会修改、添加或删除任何内容。支持语义搜索、条件筛选、分类统计、密码强度检测。",
            colors)

        plan_examples = [
            "帮我找一下跟学习有关的账号",
            "列出分类是工作>开发工具的所有账号",
            "统计一下密码库里有多少条数据",
        ]
        self._add_example_card(c_layout, plan_examples, colors)
        c_layout.addSpacing(18)

        # Build badge
        build_header = QHBoxLayout()
        build_header.setSpacing(10)
        build_badge = QLabel("Build")
        build_badge.setStyleSheet(f"color: {colors.accent_orange_text}; background-color: {colors.accent_orange_bg}; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;")
        build_name = QLabel("构建模式（需确认）")
        build_name.setStyleSheet(f"color: {colors.text_primary}; font-size: 16px; font-weight: 600;")
        build_header.addWidget(build_badge)
        build_header.addWidget(build_name)
        build_header.addStretch()
        c_layout.addLayout(build_header)
        self._add_paragraph(c_layout,
            "执行增删改操作前会展示预览表格，经你确认后才会生效。支持批量新增、批量更新、AI 生成备注、智能整理、批量删除、生成强密码。",
            colors)

        build_examples = [
            "批量添加：B站 username1 pass1，知乎 username2 pass2",
            "把金融类的账号都改成金融与支付",
            "给刚才找到的账号都加上「重要」标签",
            "生成一个 16 位的强密码",
        ]
        self._add_example_card(c_layout, build_examples, colors)
        c_layout.addSpacing(18)

        # 小贴士
        tips = [
            "首次使用请发送任意消息完成「神经连接预热」，模型加载可能需要 30~60 秒。",
            "支持上下文对话，可用「刚才找到的」「前面那些」指代历史结果。",
            "Build 模式下所有操作先展示预览表格，可勾选后再确认执行。",
            "不确定操作是否安全时，先切到 Plan 模式询问。",
        ]
        self._add_tips_card(c_layout, "使用小贴士", tips, colors)

        # ===== 章节 5：安全与隐私 =====
        self._add_section(c_layout, "🔒 安全与隐私", colors)
        security_items = [
            ("加密存储", "采用 AES-256-GCM 对称加密 + PBKDF2 密钥派生，数据库文件无法被暴力破解。"),
            ("本地 AI", "Ollama 模型完全在本地 CPU/GPU 运行，对话内容和密码数据不会上传任何服务器。"),
            ("剪贴板保护", "密码复制后，系统会在 20 秒后自动清除剪贴板内容，防止密码残留。"),
            ("健康检查", "内置密码健康仪表盘，可检测弱密码、重复密码和已知泄露密码（HIBP k-anonymity）。"),
        ]
        for title, desc in security_items:
            self._add_feature_card(c_layout, title, desc, [], colors)

        # ===== 章节 6：常见问题 =====
        self._add_section(c_layout, "❓ 常见问题", colors)
        faqs = [
            ("忘记主密码怎么办？", "主密码是加密数据库的唯一密钥，没有任何后门可以找回。请务必牢记主密码，建议定期导出加密备份。"),
            ("AI 助手响应慢或无响应？", "首次使用需将模型加载到内存，请等待 30~60 秒。请确保 Ollama 服务已在后台运行（命令行执行 `ollama serve`）。"),
            ("如何备份数据？", "点击「导出」→「加密备份」，生成 .vault 文件。将该文件复制到安全位置（如 U 盘、网盘）即可实现备份。"),
            ("导入时出现重复？", "导入预览表格中会用红色标记与现有库重复的条目，你可以选择「跳过重复」或「覆盖现有」。"),
            ("支持多设备同步吗？", "当前版本为纯本地应用，不内置云同步。你可以通过手动复制 .vault 备份文件到另一台设备实现迁移。"),
        ]
        for q, a in faqs:
            self._add_faq_item(c_layout, q, a, colors)

        c_layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # Footer
        footer = QWidget()
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(32, 8, 32, 18)
        f_layout.addStretch()
        btn = QPushButton("完成")
        btn.setFixedSize(120, 34)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_orange_dark}; color: {colors.text_on_accent}; border: none;
                border-radius: 17px; font-size: 14px; font-weight: 500;
            }}
            QPushButton:hover {{ background-color: {colors.accent_orange_dark}; }}
            QPushButton:pressed {{ background-color: {colors.accent_orange_dark}; }}
        """)
        btn.clicked.connect(self.accept)
        f_layout.addWidget(btn)
        f_layout.addStretch()
        main_layout.addWidget(footer)

    # ---------- 辅助方法 ----------

    def _add_section(self, layout, title, colors):
        """添加章节大标题"""
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 18px; font-weight: 600; padding-top: 24px; padding-bottom: 12px;")
        layout.addWidget(lbl)

    def _add_subtitle(self, layout, title, colors):
        """添加小节标题"""
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500; padding-top: 8px; padding-bottom: 6px;")
        layout.addWidget(lbl)

    def _add_paragraph(self, layout, text, colors):
        """添加普通段落"""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.7; padding-bottom: 10px;")
        layout.addWidget(lbl)

    def _add_feature_card(self, layout, title, desc, examples, colors):
        """添加功能说明卡片"""
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500; padding-bottom: 4px; padding-top: 6px;")
        layout.addWidget(title_lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-bottom: 6px;")
        layout.addWidget(desc_lbl)

        if examples:
            self._add_example_card(layout, examples, colors)
        else:
            layout.addSpacing(8)

    def _add_example_card(self, layout, examples, colors):
        """添加示例语句卡片"""
        card = QWidget()
        card.setStyleSheet(f"""
            background-color: {colors.bg_primary};
            border-radius: 10px;
            border: 1px solid {colors.border_subtle};
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(6)
        for ex in examples:
            ex_lbl = QLabel(f'"{ex}"')
            ex_lbl.setWordWrap(True)
            ex_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.7;")
            card_layout.addWidget(ex_lbl)
        layout.addWidget(card)
        layout.addSpacing(14)

    def _add_bullet_list(self, layout, intro, items, colors):
        """添加 bullet 列表"""
        if intro:
            intro_lbl = QLabel(intro)
            intro_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; font-weight: 500; padding-top: 6px;")
            layout.addWidget(intro_lbl)
        for item in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(12, 2, 0, 2)
            dot = QLabel("\u2022")
            dot.setStyleSheet(f"color: {colors.text_disabled}; font-size: 14px;")
            dot.setAlignment(Qt.AlignmentFlag.AlignTop)
            txt = QLabel(item)
            txt.setWordWrap(True)
            txt.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.6;")
            row.addWidget(dot)
            row.addWidget(txt, 1)
            layout.addLayout(row)
        layout.addSpacing(8)

    def _add_tips_card(self, layout, title, tips, colors):
        """添加小贴士卡片"""
        card = QWidget()
        card.setStyleSheet(f"""
            background-color: {colors.bg_primary};
            border-radius: 12px;
            border: 1px solid {colors.border_subtle};
        """)
        tips_layout = QVBoxLayout(card)
        tips_layout.setContentsMargins(18, 16, 18, 16)
        tips_layout.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500;")
        tips_layout.addWidget(title_lbl)

        for tip in tips:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("\u2022")
            dot.setStyleSheet(f"color: {colors.text_disabled}; font-size: 14px;")
            dot.setAlignment(Qt.AlignmentFlag.AlignTop)
            txt = QLabel(tip)
            txt.setWordWrap(True)
            txt.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.6;")
            row.addWidget(dot)
            row.addWidget(txt, 1)
            tips_layout.addLayout(row)
        layout.addWidget(card)
        layout.addSpacing(18)

    def _add_faq_item(self, layout, question, answer, colors):
        """添加 FAQ 条目"""
        q_lbl = QLabel(f"Q: {question}")
        q_lbl.setWordWrap(True)
        q_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 14px; font-weight: 500; padding-top: 8px; padding-bottom: 2px;")
        layout.addWidget(q_lbl)

        a_lbl = QLabel(f"A: {answer}")
        a_lbl.setWordWrap(True)
        a_lbl.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.6; padding-bottom: 8px;")
        layout.addWidget(a_lbl)
```

**Step 2 —— 在主窗口添加帮助按钮**

```python
# ui/main_window.py 中合适位置（如顶部工具栏右侧）

from ui.dialogs.help_dialog import HelpDialog

# 在 _setup_toolbar() 或类似方法中添加
btn_help = QPushButton("?")
btn_help.setToolTip("使用帮助")
btn_help.setFixedSize(32, 32)
btn_help.setStyleSheet(f"""
    QPushButton {{
        background-color: {colors.bg_secondary};
        color: {colors.text_secondary};
        border: 1px solid {colors.border_subtle};
        border-radius: 16px;
        font-size: 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {colors.accent_blue_bg_light};
        color: {colors.accent_blue};
        border-color: {colors.accent_blue};
    }}
""")
btn_help.clicked.connect(self._on_show_help)
toolbar_layout.addWidget(btn_help)

def _on_show_help(self):
    dialog = HelpDialog(self)
    dialog.exec()
```

按钮设计为圆形「?」图标，hover 时变蓝，与整体工具栏风格协调。

**涉及文件**：
- 新建 `ui/dialogs/help_dialog.py`
- 修改 `ui/main_window.py`（添加按钮和槽函数）

**预计工作量**：~3 小时（含内容撰写、UI 调试、主题适配验证）

---

## 6. 实施排期与依赖关系

### 6.1 任务总览

| 阶段 | 任务 | 工作量 | 前置依赖 |
|------|------|--------|---------|
| **Phase 1** | 1Password CSV 导入 | 2h | 无 |
| | KeePass XML 导入 | 2h | 无 |
| | database.close() 文档同步 | 10min | 无 |
| | restore_account() 事务原子性 | 30min | 无 |
| **Phase 2** | Repository search 全表加载修复 | 4h | 无 |
| | 批量操作事务保护 | 2h | database.py 需先提供 `_no_commit` 方法 |
| | AI 聊天全量重绘优化 | 4h | 无 |
| **Phase 3** | AI 调用主线程阻塞（14 处） | 2~3 天 | Phase 2 完成（避免冲突） |
| | 帮助系统（HelpDialog） | 3h | 无 |
| **Phase 4** | 其他 12 项 P1 修复 | 4h | 无 |
| | 测试覆盖补齐（68 个新测试） | 2 天 | Phase 1~3 完成（测试覆盖新代码和修复） |

### 6.2 推荐执行顺序

```
Week 1
├── Day 1: Phase 1（功能补齐 + 小修复）
│   ├── 1Password CSV 导入
│   ├── KeePass XML 导入
│   ├── restore_account 事务修复
│   └── database.close 文档同步
│
├── Day 2: Phase 2（性能与稳定性）
│   ├── Repository 全表加载修复
│   ├── 批量操作事务保护
│   └── AI 聊天重绘优化
│
├── Day 3~4: Phase 3（核心架构）
│   ├── AI 主线程异步化（14 处）
│   └── 帮助系统 HelpDialog
│
└── Day 5: Phase 4（质量保障）
    ├── 其他 P1 修复
    └── 测试覆盖补齐
```

### 6.3 关键依赖关系

```
[P1] database.py _insert_account_without_commit()
    ├── [依赖方] restore_account() 事务修复
    ├── [依赖方] ImportDialog 批量导入事务保护
    └── [依赖方] BatchAddProcessor 事务保护

[P2] Repository SQL 层过滤方法
    └── [依赖方] repositories.py 6 个方法改造

[P3] AI 异步基础设施（AIServiceManager/AIWorkerThread）
    └── [依赖方] 14 处 TODO 改造
```

---

## 7. 风险与验收标准

### 7.1 风险清单

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| AI 异步化改造面大，可能引入回调地狱 | 🔴 高 | 使用 `QThread` + `pyqtSignal` 而非纯回调；分文件逐处改造，每处改造后运行现有功能验证 |
| query_mixin.py 状态机重构导致 AI 助手行为变化 | 🔴 高 | 保留原始同步方法（改名 `_sync_xxx`），异步方法通过单元测试覆盖所有状态流转后再删除旧方法 |
| 批量事务保护需新增 `_no_commit` 方法，改动 database.py 核心文件 | 🟡 中 | 新增方法不得修改现有 `insert_account()` 签名；新增测试验证事务回滚正确性 |
| 测试补齐工作量大，可能延期 | 🟡 中 | 按优先级分批：先 data layer（database/repositories），再 service layer，UI 测试最后 |
| KeePass XML 解析可能遇到非标准导出 | 🟢 低 | 使用 `xml.etree.ElementTree` 标准库，对缺失字段容错处理；无法解析时返回清晰错误提示 |

### 7.2 验收标准

| 维度 | 验收标准 | 验证方式 |
|------|---------|---------|
| **功能** | 1Password CSV 和 KeePass XML 可正确导入，字段映射无误 | 单元测试 + 手动测试真实导出文件 |
| **稳定性** | 14 处 AI 调用全部走异步，UI 在 AI 响应期间保持可交互 | 手动测试：触发 AI 分类/语义搜索/健康检查/AI 助手对话，界面不冻结 |
| **性能** | 对话历史 50 条时，流式输出无卡顿；`_ai_update_chat_display()` 仅在主题切换时调用 | 代码审查 + 手动测试长对话 |
| **数据安全** | 批量导入 100 条中途失败，数据库中无残留；restore_account 失败时 accounts 表无脏数据 | 单元测试模拟中途异常 |
| **质量** | 新增 68 个测试，核心模块（database、repositories、import_service、category_service、tag_service、export_service、batch_add_processor、password_generator、password_strength）均有测试覆盖 | `pytest tests/ -v` 输出 |
| **体验** | 主窗口存在「?」帮助按钮，点击弹出 HelpDialog，内容完整、滚动正常、主题适配 | 手动测试暗色/亮色主题 |

---

## 附录：代码修改文件汇总

| 文件 | 修改类型 | 关联任务 |
|------|---------|---------|
| `services/import_service.py` | 修改 + 新增方法 | 1Password/KeePass 导入 |
| `ui/import_dialog.py` | 修改 | 导入提示/过滤器更新 |
| `ui/main_window.py` | 修改 | 帮助按钮、错误提示、聊天重绘、批量删除事务 |
| `core/database.py` | 修改 + 新增方法 | restore_account 事务、批量导入 _no_commit 方法、Repository 过滤方法 |
| `core/url_database.py` | 修改 + 新增方法 | Repository 过滤方法 |
| `core/repositories.py` | 修改 | 全表加载修复 |
| `services/category_service.py` | 修改 | AI 异步化 |
| `services/tools/utility_tools.py` | 修改 | AI 异步化 |
| `services/tools/search_tools.py` | 修改 | AI 异步化 |
| `services/tag_service.py` | 修改 | AI 异步化 |
| `services/assistant/action_mixin.py` | 修改 | AI 异步化 |
| `services/assistant/query_mixin.py` | 修改（重构最大） | AI 异步化 |
| `ui/dialogs/health_check_dialog.py` | 修改 | AI 异步化（流式） |
| `ui/ai_chat_renderer.py` | 修改 | 聊天重绘优化 |
| `ui/widgets/ai_chat_renderer.py` | 删除 | 消除重复 |
| `ai/client_base.py` | 修改 | HTTP Session 复用 |
| `ui/widgets/account_list_item.py` | 修改 | 补充异常日志 |
| `ui/widgets/url_list_item.py` | 修改 | 补充异常日志 |
| `services/url_service.py` | 修改 | 补充异常日志 |
| `services/batch_add_processor.py` | 修改 | 事务保护 |
| `tests/*.py` | 新建 10 个测试文件 | 测试覆盖补齐 |
| `tests/conftest.py` | 修改 | mock  fixture |
| `ui/dialogs/help_dialog.py` | 新建 | 帮助系统 |
| `docs/feature_inventory.md` | 修改 | 文档同步 |

---

> **文档维护**：本文档随代码迭代持续更新。每完成一项任务，在对应章节追加 ✅ 标记和完成日期。
