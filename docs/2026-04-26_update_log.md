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
