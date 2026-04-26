# 2026-04-26 更新日志

## 一、今日工作总览

今日核心工作是 **ReAct Agent 改造收尾**、**GPU 重复调用修复**、**AI 助手使用方式改进** 以及 **左侧列表高亮恢复的根因排查**。经过多轮 debug，最终发现崩溃根因是一个极其隐蔽的**参数名不匹配**（`query` vs `query_text`），在 PyQt6 C 层交互中触发了 `STATUS_STACK_BUFFER_OVERRUN`。

---

## 二、功能增加与修复明细

### 1. GPU 重复调用修复（AI 核心）
- **位置**：`ai/ollama_client.py` + `services/ai_assistant_service.py`
- **现象**：Plan 模式下发送一条查询，GPU 出现两个峰值，AI 回复重复两次
- **根因**：
  1. `generate_tool_call()` 调用模型决定使用 `semantic_search_accounts` 工具
  2. `semantic_search_accounts` 工具**内部**又调用 `ollama.semantic_match()` → 第二次模型调用
  3. ReAct 循环继续第二轮 `generate_tool_call()` → 第三次模型调用
- **修复方案**：
  1. `semantic_match()` 改为**纯本地实现**（关键词匹配 + 拼音首字母匹配 + 同义词扩展 + 模糊匹配），不再调用 Ollama
  2. `process_react_query()` 中 READONLY 工具执行后直接返回 `done=True`，**不再进行第二轮循环**
- **结果**：Plan 模式下查账号只调用 **1 次**模型

### 2. 左侧列表高亮恢复（UI 交互）
- **位置**：`ui/main_window.py` → `_on_react_result()` / `_on_react_preview_confirmed()`
- **内容**：
  - ReAct `done` 分支：解析 `result.get('matched_ids')`，调用 `highlight_matched_accounts()` 高亮左侧匹配账号
  - Build 确认分支：执行完成后提取 `confirmed_items` 中的 ID，刷新列表并高亮显示所有受影响账号
- **崩溃排查**：
  - 现象：调用 `highlight_matched_accounts` 时进程崩溃，退出代码 `0xC0000409`
  - 排查过程：逐步注释代码、添加 debug print、替换为空函数，最终定位到参数名不匹配
  - 根因：`self.highlight_matched_accounts(matched_ids, query=q)` 中关键字参数名为 `query`，但方法签名为 `query_text: str = ""`。`TypeError` 在 PyQt6 C 层异常处理中触发了栈溢出
  - 修复：所有调用点改为 `query_text=`

### 3. AI 使用方式改进（UI + AI 核心）
- **位置**：`ui/main_window.py` + `services/ai_assistant_service.py`
- **内容**：
  - 欢迎语文案精简为"🦁🔥 密码库/网址库模式 → 炽阳已觉醒 → 你好，狮子座的主人 → ⚡ 首次同步提示"
  - Plan 模式拦截提示追加"并经你确认后可执行"
  - READONLY 结果格式化：反查匹配项名称，回复变为"找到 N 个相关结果：支付宝、微信、GitHub（共 N 个）"
  - `_continue_react_loop()` 上下文改进：从 `"[继续执行]"` 改为带 Observation 历史和原查询的丰富上下文

### 4. 线程安全修复（稳定性）
- **位置**：`ui/main_window.py` → `_on_ai_query_finished()` / `_on_react_result()`
- **内容**：
  - ReAct 模式下不在 `_on_ai_query_finished` 中提前断开信号和销毁线程，把清理工作交给 `_on_react_result`
  - `_on_react_result` 中使用 `deleteLater()` 安全延迟销毁 `AIQueryThread` 的 C++ 对象，避免在 `result_ready` 信号处理过程中直接回收

### 5. 旧代码审查报告（代码清理准备）
- **位置**：`services/ai_assistant_service.py` / `ai/ollama_client.py` / `services/semantic_search_service.py` 等
- **可立即安全删除**：
  - `ai/ollama_client.py` → `generate_with_think_result()`
  - `services/ai_assistant_service.py` → `semantic_query()`
  - `services/semantic_search_service.py` → **整个文件**
  - `ui/main_window.py` → `_run_stream()`, `_run_legacy()`
- **需连带清理的旧架构代码**：
  - `services/ai_assistant_service.py` → `process_query()`, `process_query_stream()`
  - `ai/ollama_client.py` → `parse_command()`
  - `services/ai_service_manager.py` → `parse_command_async()`, `semantic_search_async()`, `chat_async()`, `classify_batch_async()`

---

## 三、涉及文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `ai/ollama_client.py` | 修改 | `semantic_match()` 改为本地实现 |
| `services/ai_assistant_service.py` | 修改 | READONLY 直接返回、结果格式化、Plan 拦截提示 |
| `ui/main_window.py` | 修改 | 欢迎语、ReAct 状态机、线程安全、高亮恢复、参数名修复 |
| `docs/2026-04-26_update_log.md` | 新增 | 本文档 |

---

## 四、遗留待验证项

- [ ] Build 模式下预览确认后左侧高亮受影响账号
- [ ] 旧代码清理（待用户确认后执行）


---

## 五、下午追加修复：AI 分类细分功能完整闭环

### 6. AI 分类细分功能完整修复（核心功能闭环）

#### 6.1 工具调用决策层修复
- **位置**：`ai/ollama_client.py` → `generate_tool_call()`
- **问题**：AI 将"细分二级子类"识别为 `direct_answer` 而非调用 `smart_classify_accounts`
- **修复**：Prompt 中新增明确规则 + 单轮示例：
  - 规则 3：用户要求"分类、细分、细分二级子类、整理分类、重组分类" → **必须调用** `smart_classify_accounts`/`smart_classify_urls`
  - 示例：`"给教育与学习细分二级子类"` → `tool: "smart_classify_accounts"`

#### 6.2 局部操作数据隔离修复
- **位置**：`services/ai_assistant_service.py` → `process_react_query()`
- **问题 1**：`conversation_context` 缓存了全局 `db_summary`（140 条），局部操作时仍使用缓存的全量数据
- **修复 1**：局部操作（`scope_hint` 非空）时直接构建局部 `db_summary`，**不存入缓存**
- **问题 2**：`tool_context` 缺少 `"query"` 键，`SmartClassifyAccountsTool` 中 `user_query` 永远是默认值
- **修复 2**：`tool_context` 中增加 `"query": enhanced_query`

#### 6.3 数据筛选增强（父节点匹配）
- **位置**：`services/ai_assistant_service.py` → `_filter_items_by_query()`
- **问题**：第一次细分后所有账号变为二级路径，`categories` 集合中无一级分类名，第二次查询匹配失败
- **修复**：增加父节点匹配逻辑：
  ```python
  elif '>' in cat:
      parent = cat.split('>')[0].strip()
      if parent in query:
          matched_cats.append(parent)
  ```

#### 6.4 分类工具 Prompt 全面改造
- **位置**：`services/ai_tools.py` → `SmartClassifyAccountsTool` + `SmartClassifyUrlsTool`
- **改造内容**：
  1. **提取一级分类列表**：写入 Prompt，明确告知 AI 子类名不能和一级分类重名
  2. **`force_subclass` 模式专用规则**：检测到"细分/二级/子类/子分类"关键词时，使用完全不同的输出规则：
     - 每个类别名**必须**是二级路径 `主类>子类`
     - **绝对禁止**输出一级分类
     - 必须根据应用名/备注尽可能细分，不允许偷懒
     - 增加具体输出示例
  3. **规则 3 优化**：从"所有账号当前分类都是 X"改为"这些账号都属于 X 分类体系（有些可能已有二级子类，有些可能仍是一级）"，避免误导 AI
  4. **规则 11 新增**：【绝对禁止】更改一级分类，主类必须是推断出的 `main_category`

#### 6.5 代码层兜底校验
- **位置**：`services/ai_tools.py`
- **一级分类兜底**：`force_subclass=True` 时，AI 返回一级分类（无 `>`）→ 自动修正为 `主类>其他`
- **主类错误兜底**：`force_subclass=True` 时，AI 返回错误主类（如 `一般与其他>考试`）→ 自动修正为正确主类（如 `教育与学习>考试`）
- **ID 去重**：AI 可能把同一 ID 分到多个分类 → `seen_ids` 集合去重，保留第一次出现的分类

#### 6.6 AI 查询数据源修复
- **位置**：`ui/main_window.py`
- **问题**：AI 查询复用 `_cached_accounts`，用户点击侧边栏分类后缓存被污染（只剩 7 条）
- **修复**：AI 查询时**强制使用全部数据**，不受 UI 筛选状态影响

---

## 六、更新后涉及文件清单（追加）

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `ai/ollama_client.py` | 修改 | `generate_tool_call()` Prompt 强化，细分必须调用工具 |
| `services/ai_assistant_service.py` | 修改 | 局部操作缓存隔离、父节点匹配、tool_context 传 query |
| `services/ai_tools.py` | 修改 | 分类工具 Prompt 全面改造 + 代码层三级兜底 |
| `ui/main_window.py` | 修改 | AI 查询强制使用全部数据 |
