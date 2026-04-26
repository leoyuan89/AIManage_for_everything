# 0425 代办任务文档 — AI原生数据治理架构落地计划

> 文档版本：v1.0
> 编写日期：2026-04-25
> 基线代码版本：当前主干（MVP 1-3 已实现，MVP 4 部分缺失）

---

## 一、需求变更与技术约束确认

### 1.1 搜索能力调整
| 原规划 | 当前决策 | 原因 |
|--------|----------|------|
| 独立语义搜索服务（SemanticSearchService） | ❌ **放弃** | gemma4:4b 不支持 `/api/embeddings`，独立向量索引无法工作 |
| Embedding 向量相似度计算 | ❌ **放弃** | 同上，无可用 Embedding API |
| 拼音精确搜索 | ✅ **保留** | 已有实现，需修复 `pinyin.py` 覆盖率问题 |
| AI 智慧推荐 | ✅ **保留并强化** | 通过 LLM `/api/generate` 做语义推理匹配，替代向量搜索 |

### 1.2 技术约束清单
1. **Ollama 模型**：`gemma4:4b`，仅支持 `/api/generate`，不支持 `/api/embeddings`
2. **上下文窗口**：约 32K，单次请求可承载 500 条账号摘要
3. **计算环境**：全部本地闭环，无云端依赖
4. **数据安全**：敏感字段（密码）在送入 LLM 前必须脱敏或排除

### 1.3 架构核心决策
- **"语义向量空间共享"** 在技术约束下重新定义为：**"共享同一套 LLM 语义推理能力"**
  - 分类引擎预分析 → LLM generate 做语义聚类
  - AI 助手 Plan 模式语义查询 → LLM generate 做语义匹配
  - 两者使用同一模型、同一 Prompt 策略、同一解析逻辑
- **放弃 `SemanticSearchService`**，相关代码标记为废弃，不再维护
- **分类缓存表 `category_cache`** 作为两模块的共享数据层，存储类别定义和命中统计

---

## 二、当前框架基线（已完成部分）

### 2.1 智能分类引擎（已有基础）
| 组件 | 状态 | 文件 |
|------|------|------|
| 预分析（只读） | ✅ 已有 | `ai_classification_service.py` |
| 类别提议数据结构 | ✅ 已有 | `CategoryProposal`（含 name/description/estimated_count/examples/conflicts/is_new） |
| 确认面板（卡片式） | ✅ 已有 | `ai_classify_dialog.py` `CategoryProposalCard` |
| 批量执行归类 | ✅ 已有 | `execute_classification()` 分批处理（每批10条） |
| 差异比对表格 | ✅ 已有 | `show_diff_view()` 表格展示 |
| 快照/回滚机制 | ⚠️ 内存级 | `create_snapshot()/rollback()`，仅存内存，重启丢失 |
| 启发式降级 | ✅ 已有 | `_heuristic_pre_analyze()/_heuristic_classify_item()` |
| 空库保护 | ✅ 已有 | `MIN_ITEMS_THRESHOLD = 5` |
| 24h 冷却 | ✅ 已有 | `COOLDOWN_SECONDS = 86400`，内存存储 |
| 低置信度标记 | ✅ 已有 | `LOW_CONFIDENCE_THRESHOLD = 0.6`，`is_low_confidence` 字段 |

### 2.2 双模式AI助手面板（已有基础）
| 组件 | 状态 | 文件 |
|------|------|------|
| Plan/Build Tab 切换 | ✅ 已有 | `main_window.py` 右侧面板 |
| 对话历史管理 | ✅ 已有 | `AIAssistantService._history`，上限 20 轮 |
| 自然语言指令解析 | ✅ 已有 | `ollama.parse_command()` |
| Action 执行框架 | ✅ 已有 | `execute_action()` 支持 6 种 action |
| 操作确认弹窗 | ✅ 已有 | `MainWindow` 中模态确认框 |
| AI 查询后台线程 | ✅ 已有 | `AIQueryThread(QThread)` |
| 数据库摘要构建 | ✅ 已有 | `build_db_summary()`，最多 500 条 |

### 2.3 待修复的已知 Bug（P0）
| Bug | 文件 | 修复工作量 |
|-----|------|-----------|
| `self.db.connection.commit()` → `self.db.conn.commit()` | `ui/settings_dialog.py:277` | 1 行 |
| 主界面搜索未调用 `SearchService.search()`，拼音/语义搜索失效 | `ui/main_window.py:on_search()` | 中等 |
| `SemanticSearchService` 未与主界面集成 | `services/semantic_search_service.py` | 废弃，改为移除调用 |
| `get_cached_category()` 重复 `return` | `core/database.py:339-340` | 1 行 |
| `update_account()` 未支持 `ai_remark`/`security_level`/`tags` | `core/database.py` | 小 |

---

## 三、模块一：智能分类引擎 — 差距分析与实现方案

### 3.1 差距矩阵

| 需求点 | 当前状态 | 差距描述 | 实现复杂度 |
|--------|----------|----------|-----------|
| **预分析输出《类别提议清单》** | ⚠️ 部分 | 已有 name/description/estimated_count/examples/conflicts，但缺少**与现有类别的合并建议**（如"建议合并至现有'金融'类"） | 低 |
| **确认面板：合并至现有类别** | ❌ 缺失 | 卡片上无"合并至现有类别"下拉选择器 | 中 |
| **确认面板：强制新建** | ❌ 缺失 | 无明确"强制新建"按钮/标记 | 低 |
| **确认面板：手动补充遗漏类别** | ❌ 缺失 | 无"添加自定义类别"输入框 | 低 |
| **批量归类：逐条推理主类别归属（单选策略）** | ⚠️ 接近 | 当前每批10条送入LLM，LLM内部已要求"每个条目只能选一个类别"。**无需改为逐条调用**（性能太差），保持分批但 Prompt 强化"强制单选"约束即可 | 低 |
| **跨域条目：主类别+建议标签** | ⚠️ 部分 | `_classify_batch()` 已返回 `suggested_tags`，但差异视图未展示标签，也未写入数据库 | 中 |
| **低置信度：落入"待整理"暂存区** | ❌ 缺失 | 当前仅标记 `is_low_confidence=True`，无"待整理"概念。需在差异视图中将低置信度条目归类到"待整理"分组，用户确认前不入主分类 | 中 |
| **差异视图：流向图（迁移路径可视化）** | ❌ 缺失 | 当前为表格，需增加**桑基图/流向图**或至少是**分组迁移卡片**（原类别→新类别的流向展示） | 高 |
| **差异视图：单条拖拽修正** | ❌ 缺失 | 当前仅有"撤销"按钮（改回原分类），不能拖拽修改为其他新类别 | 高 |
| **差异视图：批量采纳** | ⚠️ 部分 | "正式生效"按钮即批量采纳，但缺少**按类别批量采纳**（如"只采纳金融类的变更"） | 中 |
| **快照持久化（30天回滚）** | ❌ 缺失 | 仅存内存 `_snapshots` 列表。需**写入 SQLite 文件**（或 JSON 文件），支持程序重启后读取 | 中 |
| **回滚落库** | ❌ 缺失 | 当前 `rollback()` 只修改 `item.category` 内存对象，**未调用 `update_account()` 写入数据库** | 低 |

### 3.2 实现方案

#### 3.2.1 数据模型扩展
```python
# services/ai_classification_service.py

@dataclass
class CategoryProposal:
    """类别提议（扩展版）"""
    name: str
    description: str
    estimated_count: int
    examples: List[str] = field(default_factory=list)
    is_new: bool = True
    conflicts: List[str] = field(default_factory=list)
    # 新增字段
    merge_target: Optional[str] = None   # "合并至现有类别"的目标类别名
    force_new: bool = False              # 用户勾选"强制新建"
    source_items: List[int] = field(default_factory=list)

@dataclass
class ClassificationChange:
    """分类变更记录（扩展版）"""
    item_id: int
    item_name: str
    item_type: str
    old_category: str
    new_category: str
    confidence: float
    suggested_tags: List[str] = field(default_factory=list)
    is_low_confidence: bool = False
    # 新增字段
    is_pending: bool = False             # 是否在"待整理"暂存区
    user_override: bool = False          # 用户是否手动覆盖过
```

#### 3.2.2 快照持久化方案
- **存储位置**：`~/.local_password_vault/snapshots/` 目录下，按 `snapshot_{id}.json` 存储
- **文件内容**：JSON 格式，包含 snapshot_id、created_at、item_type、changes、before_state
- **清理策略**：启动时加载全部快照，清理 30 天前的文件（与内存逻辑保持一致）
- **替代方案**：若担心文件碎片化，可存入 SQLite 的 `snapshots` 表（新建表）

**推荐**：新建 `snapshots` 表（与主库同文件，加密存储变更记录），更整洁且易于备份。

```sql
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    item_type TEXT NOT NULL,
    before_state BLOB NOT NULL,        -- JSON 加密存储
    changes BLOB NOT NULL              -- JSON 加密存储
);
```

#### 3.2.3 确认面板增强
- `CategoryProposalCard` 增加：
  - **"合并至现有"下拉框**：列出 `existing_categories`，选择后该提议标记为合并（不新建类别）
  - **"强制新建"复选框**：即使与现有类别冲突也强制创建
  - **"添加自定义类别"输入框**：在滚动区域底部，允许用户输入全新类别名并创建卡片
- 状态流转：
  - 提议卡片 → 用户编辑/弃用/合并/新建 → 生成 `approved_categories`（去重后的最终类别列表）→ 进入执行阶段

#### 3.2.4 差异视图增强（Diff View）
当前是简单表格，目标改为**分组迁移视图**：

```
┌─────────────────────────────────────────────────────────────┐
│  差异比对视图 — 共 23 条变更                                 │
├─────────────────────────────────────────────────────────────┤
│  ⚠️ 待整理（3条）  [一键确认] [批量编辑]                    │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐   │
│  │ 网易云音乐  │ ──→ │   待整理    │     │ [修正▼]     │   │
│  │ 置信度: 45% │     │             │     │ [编辑标签]  │   │
│  └─────────────┘     └─────────────┘     └─────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  金融（8条）  [采纳本组] [撤销本组]                         │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐   │
│  │  支付宝     │ ──→ │   金融      │     │ [撤销] [▼]  │   │
│  │  工商银行   │ ──→ │   金融      │     │ [撤销] [▼]  │   │
│  └─────────────┘     └─────────────┘     └─────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  社交（12条） [采纳本组] [撤销本组]                         │
│  ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

实现方式：
- 放弃纯表格，使用 **QScrollArea + 自定义 MigrationGroupWidget**
- 每组（原类别→新类别）一个分组卡片
- "待整理"组始终置顶，橙色高亮
- 单条修正：下拉框选择其他已批准的类别（或"待整理"）
- 批量采纳：每组顶部有"采纳本组"按钮

#### 3.2.5 回滚机制修复
- `rollback()` 方法在修改 `item.category` 后，**必须调用 `db.update_account()` 将变更写入数据库**
- 快照加载后，提供差异预览（回滚前后的对比），用户确认后再执行

---

## 四、模块二：双模式AI助手面板 — 差距分析与实现方案

### 4.1 差距矩阵

| 需求点 | 当前状态 | 差距描述 | 实现复杂度 |
|--------|----------|----------|-----------|
| **Plan 模式：只读隔离** | ⚠️ 部分 | 当前 `execute_action()` 中 `reorganize`/`add_remark` 仅返回建议不执行，但无明确的**模式级权限拦截**。需在 `Build` 模式时才允许生成写操作 Action | 中 |
| **Plan 模式：语义查询（LLM 推理匹配）** | ❌ 缺失 | 当前 `search` action 是本地内存关键词匹配。需改为：将 query + 全库摘要送入 LLM，让模型返回匹配 ID 列表和推理过程 | 中 |
| **左侧列表联动：自动筛选/高亮/折叠** | ❌ 缺失 | AI 助手返回匹配结果后，主窗口左侧账号列表无任何联动。需实现：匹配项高亮置顶、未命中项折叠/半透明 | 高 |
| **Build 模式：结构化操作预览（表格）** | ❌ 缺失 | 当前是简单确认弹窗（"是否执行？"）。需改为：在对话框中展示 **Action Preview 表格**（目标条目、原值、新值、影响范围） | 高 |
| **Build 模式：事务提交** | ❌ 缺失 | 当前无事务机制。批量更新时应使用 SQLite `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK` | 中 |
| **审计日志（Audit Log）** | ❌ 缺失 | 无变更记录。需新建 `audit_log` 表记录：时间、模式、用户query、AI解析的action、影响条目数、执行结果 | 中 |
| **流式输出：逐 Token 实时渲染** | ❌ 缺失 | 当前 `AIQueryThread` 返回完整 JSON 字符串后一次性显示。需改为：使用 `requests.stream=True` 逐 token 接收，通过 signal 实时传给 UI | 高 |
| **思考过程与最终结果分区** | ⚠️ 部分 | 数据模型已有 `thinking` 字段，但 UI 未分区展示（当前混在一起）。需拆分为上下两个区块 | 中 |
| **模式强提示（颜色/图标）** | ⚠️ 部分 | 已有 Tab 切换，但缺少颜色强提示。Plan 模式边框/标题栏应为蓝色，Build 模式应为橙色 | 低 |
| **上下文隔离：Build 操作意图不污染 Plan** | ❌ 缺失 | 当前 `_history` 是单一列表，模式切换后历史共享。需维护**两套独立历史**（或至少标记每条消息所属模式） | 中 |
| **Markdown 轻量渲染** | ❌ 缺失 | 当前使用 `setPlainText()` 纯文本显示。需支持粗体、代码块、列表等基础 Markdown | 中 |

### 4.2 实现方案

#### 4.2.1 Plan 模式语义查询实现

**核心思路**：用 LLM `/api/generate` 替代 Embedding 向量搜索。

```python
# ai/ollama_client.py 新增方法

def semantic_match(self, query: str, items_summary: List[Dict]) -> Dict:
    """
    语义匹配：根据用户自然语言描述，从条目列表中找出最相关的条目。
    
    Args:
        query: 用户查询，如"我的游戏账号"、"支付相关的"
        items_summary: 条目摘要列表，每条包含 id, app_name, category, tags, remark
        
    Returns:
        {
            "matched_ids": [1, 5, 12],
            "reasoning": "用户想找游戏账号，匹配到 Steam、Epic、暴雪战网...",
            "confidence_scores": {"1": 0.95, "5": 0.88, "12": 0.72}
        }
    """
```

Prompt 设计：
```
用户正在密码管理软件中搜索账号，他说："{query}"

软件中存储的账号列表如下（每行格式：ID | 应用名 | 分类 | 标签 | 备注）：
{items_summary}

请从列表中找出用户可能想找的应用。
返回 JSON 格式：
{
  "matched_ids": [匹配的ID列表],
  "reasoning": "你的推理过程（中文）",
  "confidence_scores": {"ID": 置信度(0-1)}
}

规则：
1. 只返回列表中确实存在的 ID
2. 如果没有匹配的，返回空数组
3. confidence > 0.6 才纳入结果
4. 只输出 JSON，不要其他解释
```

**左侧列表联动机制**：
1. Plan 模式下，用户输入 query → `AIAssistantService` 调用 `semantic_match()`
2. 返回 matched_ids 后，通过 signal 通知 `MainWindow`
3. `MainWindow` 左侧列表执行：
   - **匹配项**：高亮边框（蓝色）、置顶显示、展开详情
   - **未匹配项**：透明度降至 40%、折叠为"其他条目（X条）"
   - 顶部显示横幅："AI 找到 5 个相关账号，推理：{reasoning}"
4. 用户点击"清除筛选"或发送新 query 时恢复默认视图

#### 4.2.2 Build 模式结构化操作预览

**执行流程改造**：
```
用户输入自然语言指令（Build模式）
    ↓
LLM 解析为 action + params（当前已有）
    ↓
【新增】生成 Action Preview（操作预览）
    - 在右侧对话框中渲染一个表格 Widget
    - 表格列：目标条目 | 字段 | 原值 | 新值 | 影响范围
    - 底部显示"影响 12 条记录，不可撤销"
    ↓
用户点击"确认执行" / "取消"
    ↓
【新增】事务包装
    BEGIN TRANSACTION
    逐条执行数据库更新
    COMMIT（成功）/ ROLLBACK（失败）
    ↓
【新增】写入审计日志
    INSERT INTO audit_log (...)
    ↓
刷新左侧列表，显示操作结果
```

**Action Preview Widget 设计**：
使用 `QTableWidget` 或自定义 `ActionPreviewWidget` 嵌入到对话气泡中：

```
┌────────────────────────────────────────────┐
│ 🤖 我将执行以下操作：                        │
├────────────────────────────────────────────┤
│ 目标           字段      原值      新值      │
├────────────────────────────────────────────┤
│ 支付宝         分类      其他  →  金融       │
│ 工商银行       分类      其他  →  金融       │
│ 网易云音乐     标签      []    →  [音乐]     │
├────────────────────────────────────────────┤
│ 影响范围：3条记录 | 操作类型：批量更新       │
│ ⚠️ 此操作不可撤销                           │
├────────────────────────────────────────────┤
│        [取消]  [确认执行]                    │
└────────────────────────────────────────────┘
```

#### 4.2.3 流式输出改造

**当前问题**：`AIQueryThread` 调用 `ollama.parse_command()`，等待完整响应后通过 `pyqtSignal(str)` 一次性返回 JSON。

**目标**：逐 token 实时渲染思考过程和最终结果。

**技术方案**：
1. `ollama_client.py` 新增 `generate_stream()` 方法，使用 `requests.post(stream=True)`
2. `AIQueryThread` 改造为双 signal：
   - `thinking_token(str)`：逐 token 传递思考过程
   - `result_token(str)`：逐 token 传递最终结果
   - `finished(dict)`：完整解析后的 JSON
3. `MainWindow` 右侧对话框拆分为两个 `QTextEdit`：
   - 上方 `thinking_area`（灰色背景，等宽字体）：实时渲染思考过程
   - 下方 `result_area`（白色背景）：实时渲染最终结果
4. 流式渲染结束后，在结果区下方显示"复制"、"重新生成"按钮

**思考过程与最终结果的区分**：
- 依赖模型输出格式。可在 Prompt 中强制要求：
  ```
  请先输出你的思考过程（以 <think> 开始，</think> 结束），
  然后输出最终回复（以 <result> 开始，</result> 结束）。
  ```
- UI 层解析 token 流，遇到 `<think>` 切换到 thinking_area，遇到 `<result>` 切换到 result_area

#### 4.2.4 模式隔离与强提示

**上下文隔离**：
```python
# AIAssistantService
self._history_plan: List[ConversationMessage] = []   # Plan 模式历史
self._history_build: List[ConversationMessage] = []  # Build 模式历史

def process_query(self, query: str, mode: str, ...):
    history = self._history_plan if mode == 'plan' else self._history_build
    # ... 使用对应历史
```

**视觉强提示**：
- Plan 模式：右侧面板边框 2px 蓝色 (`#2196F3`)，Tab 图标为 🔍/💬，标题"炽阳助手 — 规划模式"
- Build 模式：右侧面板边框 2px 橙色 (`#FF9800`)，Tab 图标为 🔧/⚡，标题"炽阳助手 — 构建模式"
- 模式切换时，面板顶部显示横幅提示（3秒后淡出）

#### 4.2.5 审计日志表设计

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    mode TEXT NOT NULL,               -- 'plan' | 'build'
    user_query TEXT NOT NULL,         -- 用户原始输入
    parsed_action TEXT,               -- AI 解析的 action
    parsed_params BLOB,               -- JSON 加密存储参数
    affected_count INTEGER DEFAULT 0, -- 影响条目数
    affected_ids BLOB,                -- JSON 加密的条目ID列表
    result TEXT,                      -- 'success' | 'cancelled' | 'error'
    error_message TEXT,               -- 错误信息
    transaction_id TEXT               -- 事务ID（Build模式有）
);
```

---

## 五、共享基础设施与联动机制

### 5.1 放弃 SemanticSearchService

- `services/semantic_search_service.py` 标记为 **废弃（DEPRECATED）**
- 主界面中移除 `SemanticSearchService` 的初始化代码
- `settings_dialog.py` 中的"AI增强搜索"开关保留，但含义改为："启用 AI 智慧推荐（Plan 模式语义查询）"

### 5.2 分类缓存作为共享数据层

- 分类引擎整理后的新类别，通过 `category_cache` 表共享给搜索和AI助手
- `AIAssistantService.build_db_summary()` 构建摘要时，读取 `category_cache` 中的类别定义作为上下文

### 5.3 拼音搜索修复

- `core/pinyin.py` 的 `PINYIN_MAP` 仅覆盖约 100 个常用汉字，需扩展或替换
- **推荐方案**：引入 `pypinyin` 库（pip install pypinyin），替换硬编码映射表
- 若不引入新依赖，则需将常用汉字映射表扩展至至少 3000 字（工作量较大，不推荐）

---

## 六、0425 代办任务清单

### P0 — 阻塞性（必须首先完成）

| # | 任务 | 模块 | 文件 | 工作量 | 备注 |
|---|------|------|------|--------|------|
| 1 | 修复 `settings_dialog.py` 数据库引用错误 | Bug修复 | `ui/settings_dialog.py:277` | 1行 | `connection` → `conn` |
| 2 | 修复 `get_cached_category()` 重复 return | Bug修复 | `core/database.py:339-340` | 1行 | 删除多余 return |
| 3 | 修复主界面搜索未调用 SearchService | Bug修复 | `ui/main_window.py:on_search()` | 中 | 接入 `SearchService.search()`，恢复拼音搜索 |
| 4 | 修复 `update_account()` 缺失字段支持 | Bug修复 | `core/database.py` | 小 | 增加 `ai_remark`/`security_level`/`tags`/`last_password_change` |
| 5 | 移除 SemanticSearchService 主界面集成引用 | 架构清理 | `ui/main_window.py` | 小 | 避免初始化未使用的服务 |

### P1 — 智能分类引擎核心增强

| # | 任务 | 模块 | 文件 | 工作量 | 备注 |
|---|------|------|------|--------|------|
| 6 | 快照持久化：新建 `snapshots` 表 + 读写方法 | 分类引擎 | `core/database.py` + `services/ai_classification_service.py` | 中 | 替代内存存储 |
| 7 | 修复回滚机制：修改后调用 `update_account()` 落库 | 分类引擎 | `services/ai_classification_service.py` | 小 | 当前只改内存 |
| 8 | 确认面板增强：添加"合并至现有"下拉框 | 分类引擎 UI | `ui/ai_classify_dialog.py` `CategoryProposalCard` | 中 | 每卡片一个下拉框 |
| 9 | 确认面板增强：添加"手动补充类别"输入框 | 分类引擎 UI | `ui/ai_classify_dialog.py` | 小 | 滚动区域底部 |
| 10 | 差异视图：低置信度条目归入"待整理"分组 | 分类引擎 UI | `ui/ai_classify_dialog.py` `show_diff_view()` | 中 | 置顶橙色分组 |
| 11 | 差异视图：单条修正下拉框（可改为其他类别） | 分类引擎 UI | `ui/ai_classify_dialog.py` | 中 | 替代简单的"撤销"按钮 |
| 12 | 差异视图：按类别批量采纳按钮 | 分类引擎 UI | `ui/ai_classify_dialog.py` | 小 | 每组顶部添加 |

### P2 — AI 助手面板双模式改造

| # | 任务 | 模块 | 文件 | 工作量 | 备注 |
|---|------|------|------|--------|------|
| 13 | Plan 模式语义查询：`ollama.semantic_match()` 方法 | AI助手 | `ai/ollama_client.py` | 中 | LLM 推理匹配替代向量搜索 |
| 14 | Plan 模式语义查询：左侧列表联动（高亮/置顶/折叠） | AI助手 UI | `ui/main_window.py` | 高 | 信号驱动列表刷新 |
| 15 | Build 模式权限隔离：模式级 action 过滤 | AI助手 | `services/ai_assistant_service.py` | 中 | Plan 模式禁止写操作 action |
| 16 | Build 模式：结构化操作预览 Widget | AI助手 UI | `ui/main_window.py`（新增 ActionPreviewWidget） | 高 | 表格形式展示目标/原值/新值 |
| 17 | Build 模式：事务提交包装 | AI助手 | `services/ai_assistant_service.py` + `core/database.py` | 中 | SQLite BEGIN/COMMIT/ROLLBACK |
| 18 | 审计日志：新建 `audit_log` 表 + 写入逻辑 | AI助手 | `core/database.py` + `services/ai_assistant_service.py` | 中 | 记录每次 Build 模式操作 |
| 19 | 流式输出：`generate_stream()` + 双 signal | AI助手 | `ai/ollama_client.py` + `ui/main_window.py` `AIQueryThread` | 高 | 逐 token 实时渲染 |
| 20 | 思考/结果分区 UI | AI助手 UI | `ui/main_window.py` | 中 | 上下两个 QTextEdit |
| 21 | 模式强提示：颜色边框 + 图标 + 标题 | AI助手 UI | `ui/main_window.py` | 低 | Plan蓝/Build橙 |
| 22 | 上下文隔离：两套独立对话历史 | AI助手 | `services/ai_assistant_service.py` | 中 | `_history_plan` / `_history_build` |
| 23 | Markdown 轻量渲染 | AI助手 UI | `ui/main_window.py` | 中 | 粗体、代码块、列表 |

### P3 — 体验优化与性能

| # | 任务 | 模块 | 文件 | 工作量 | 备注 |
|---|------|------|------|--------|------|
| 24 | 拼音搜索：`pypinyin` 替换硬编码映射 | 搜索 | `core/pinyin.py` | 小 | `pip install pypinyin` |
| 25 | 导入标签丢失修复 | 导入 | `services/import_service.py` | 小 | `ImportItem.to_account()` 传递 tags |
| 26 | 批量归类 Prompt 强化：强制单选 + 标签建议 | 分类引擎 | `services/ai_classification_service.py` | 低 | 优化 `_classify_batch()` prompt |
| 27 | 冷却时间持久化 | 分类引擎 | `services/ai_classification_service.py` | 小 | 存入 config 表或文件 |
| 28 | 快照选择对话框（回滚时让用户选择） | 分类引擎 UI | `ui/ai_classify_dialog.py` | 中 | 列表展示历史快照 |

### P4 — 原 MVP 4 功能（降级优先级）

| # | 任务 | 模块 | 文件 | 工作量 | 备注 |
|---|------|------|------|--------|------|
| 29 | 自动锁定与会话安全 | 安全 | 新建 `ui/lock_screen.py` | 高 | 5分钟无操作锁定，遮罩+密码验证 |
| 30 | PWA 同步到手机（加密 HTML） | 同步 | 新建 `services/sync_service.py` + `templates/pwa_template.html` | 高 | MVP 4 核心功能 |
| 31 | 主题切换（qt-material） | UI | `main.py` + `ui/settings_dialog.py` | 小 | 启用 `use_qt_material`，添加设置选项 |
| 32 | 密码强度评估 UI 展示 | UI | `ui/account_dialog.py` + `ui/main_window.py` | 小 | 已有字段，只需展示 |
| 33 | AI 一句话备注生成与展示 | AI助手 | `services/ai_assistant_service.py` + `ui/main_window.py` | 中 | 已有字段，需生成逻辑 |

---

## 七、推荐实施顺序（迭代计划）

### 第一轮（1-2天）：Bug 修复 + 基础稳固
- 任务 1~5（P0 Bug 修复）
- 任务 24（拼音库替换）
- 任务 25（导入标签修复）

### 第二轮（2-3天）：智能分类引擎增强
- 任务 6~7（快照持久化 + 回滚落库）
- 任务 8~9（确认面板增强）
- 任务 10~12（差异视图增强：待整理 + 单条修正 + 批量采纳）
- 任务 26~27（Prompt 优化 + 冷却持久化）

### 第三轮（3-5天）：AI 助手双模式改造（核心难点）
- 任务 13~14（Plan 模式语义查询 + 左侧联动）
- 任务 19~20（流式输出 + 分区 UI）
- 任务 15（权限隔离）
- 任务 16~17（操作预览 + 事务提交）
- 任务 18（审计日志）
- 任务 21~23（模式强提示 + 上下文隔离 + Markdown）

### 第四轮（2-3天）：MVP 4 收尾
- 任务 29~33（按优先级挑选）

---

## 八、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 流式输出导致 UI 卡顿 | 高 | 控制 token 刷新频率（每 50ms 批量刷新一次），或使用 `QTimer` 节流 |
| Plan 模式语义查询延迟高（全库摘要过大） | 中 | 限制摘要条目数（200条），对大数据库先做本地关键词预过滤 |
| 事务提交中 LLM 操作部分失败 | 中 | 纯本地操作（SQLite）纳入事务，LLM 调用在事务外完成，只把结果写入事务 |
| 差异视图分组过多导致性能问题 | 低 | 分组数量理论上限为类别数（<20），无性能风险 |

---

*本文档基于当前代码基线与 0425 需求文档编制，随开发进度动态更新。*
