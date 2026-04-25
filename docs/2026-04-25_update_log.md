# 2026-04-25 更新日志

## 一、今日工作总览

今日主要围绕 **AI 助手（炽阳）Build 模式稳定性提升**、**UI 交互体验优化**、**数据一致性修复** 以及 **关键闪退问题排查** 四大方向展开，共涉及 13 项功能新增/修复。其中，最后的 `0xC0000409` 启动闪退问题是今日排查工作的核心，已彻底定位并修复。

---

## 二、功能增加与修复明细

### 1. 移除同步阻塞按钮（UI 优化）
- **位置**：`ui/main_window.py`
- **内容**：删除"一键整理"和"批量分类"两个同步调用 Ollama 的按钮
- **原因**：这两个按钮在主线程直接调用 `requests.post`，会阻塞 UI 数十秒，导致窗口无响应，体验极差。AI 操作统一通过 Build 模式的预览-确认流程完成

### 2. 嵌套 JSON 解析修复（AI 核心）
- **位置**：`ai/ollama_client.py`
- **内容**：新增 `_extract_json_after_marker()` 方法
- **技术细节**：
  - 旧方案使用正则 `.*?` 提取 JSON，遇到 `params` 中嵌套对象（如 `"changes": [{...}]`）时会被截断，导致解析失败
  - 新方案使用**括号深度计数**（`depth` 变量）配合字符串遍历，完整提取嵌套的 `{}` 和 `[]`
  - 同时正确处理字符串内部的转义引号 `"` 和转义字符 `\`

### 3. 假事务修复（数据层）
- **位置**：`services/ai_assistant_service.py`
- **内容**：`execute_build_action_with_transaction()` 方法
- **技术细节**：
  - 底层 DAO（`AccountRepository` / `URLRepository`）已使用 SQLite 的 `autocommit` 模式，外层手动包裹 `BEGIN/COMMIT/ROLLBACK` 形成"假事务"
  - 修复方案：去掉外层事务，改为**逐条独立执行**，每条操作后记录成功/失败，避免单条失败导致整个事务回滚的迷惑行为

### 4. 账号新增键名兼容（数据层）
- **位置**：`core/repositories.py`
- **内容**：`AccountRepository.insert()` 和 `check_duplicate()`
- **技术细节**：同时兼容两套键名——AI 返回的 `app`/`account` 和数据库模型的 `app_name`/`username`，避免批量新增时因键名不匹配导致数据丢失

### 5. Delete 二次确认修复（业务逻辑）
- **位置**：`ui/main_window.py`
- **内容**：Build 模式执行 `delete` 操作时，`_force=True` 的判断逻辑
- **修复前**：`_force=True` 时错误落入 `add` 分支
- **修复后**：`_force=True` 时正确执行删除逻辑（软删除，移入回收站）

### 6. 双库缓存修复（业务逻辑）
- **位置**：`ui/main_window.py` → `_on_action_preview_confirmed()`
- **内容**：根据当前所在的库（`current_vault`）动态传入正确的缓存数据
- **修复前**：无论当前在密码库还是网址库，都传入 `_cached_accounts`
- **修复后**：`accounts` 库传入 `_cached_accounts`，`urls` 库传入 `_cached_urls`

### 7. 预览与执行一致性（AI 核心）
- **位置**：`ui/main_window.py` → `_on_ai_query_finished()`
- **内容**：Plan 模式和 Build 模式下，统一调用 `build_action_preview()` 生成预览，再将预览结果传给 `ActionPreviewWidget`
- **意义**：确保"预览即执行"，用户看到的变更列表与实际执行的操作完全一致

### 8. 列表刷新修复（UI 交互）
- **位置**：`ui/main_window.py`
- **内容**：Build 模式执行成功后
- **修复前**：仅刷新账号列表，分类导航不刷新
- **修复后**：根据 `current_vault` 刷新对应列表 **+** 调用 `_reload_categories()` 更新左侧分类导航

### 9. Plan 模式高亮状态清理（UI 交互）
- **位置**：`ui/main_window.py` → `load_accounts()` / `load_urls()`
- **内容**：
  - 列表加载开头恢复 `lbl_list_title.show()`，避免高亮模式下标题被隐藏后无法恢复
  - 执行成功后调用 `clear_account_highlight()`，清除蓝色高亮和筛选横幅

### 10. 预览表格可勾选（UI 交互）
- **位置**：`ui/main_window.py` → `ActionPreviewWidget`
- **内容**：
  - 预览表格每行第一列增加复选框（`QCheckBox`）
  - 默认全选，底部实时更新勾选计数（`checked/total`）
  - 确认执行时只执行被勾选的条目
  - 按钮加宽：取消 80px，确认 110px

### 11. 去掉所有 `[:20]` 截断限制（UI 交互）
- **位置**：`ui/main_window.py` → `ActionPreviewWidget`
- **内容**：预览表格和横幅文字不再截断为 20 字符，完整显示应用名、分类名等信息

### 12. AI 查询语义摘要（AI 核心）
- **位置**：`services/ai_assistant_service.py`
- **内容**：
  - Prompt 增加 `<query_summary>` 标签，要求 AI 用一句话提炼用户查询意图
  - 横幅文字优先显示 AI 提炼的摘要，而非原始查询字符串
  - 提升用户对 AI 理解程度的感知

### 13. 启动闪退修复 `0xC0000409`（关键修复）
- **位置**：`ui/main_window.py` → `ActionPreviewWidget.setup_ui()`
- **现象**：输入密码后、主界面出现时立即闪退，退出代码 `-1073740791 (0xC0000409)` —— `STATUS_STACK_BUFFER_OVERRUN`（C++ 层栈缓冲区溢出）
- **根因分析**：
  1. `setup_ui()` 中先连接了信号：`self.table.itemChanged.connect(self._on_item_check_changed)`
  2. 随后调用 `self._fill_table()` 填充表格
  3. `_fill_table()` 为第一列的 `QTableWidgetItem` 设置 `cell.setCheckState(Qt.CheckState.Checked)`
  4. `setCheckState()` 立即触发 `itemChanged` 信号 → 调用 `_on_item_check_changed()`
  5. `_on_item_check_changed()` 中访问 `self.lbl_scope.setText(...)`
  6. **但此时 `self.lbl_scope` 尚未被创建**，导致 Python `AttributeError`
  7. 在 PyQt6 的信号/槽机制中，该异常破坏了 Qt C++ 内部状态，后续 `QTableWidget.setItem()` 调用触发 C++ 层栈溢出，进程直接崩溃
- **修复方案**：
  - 将 `self.lbl_scope` 的创建提前到 `_fill_table()` 之前
  - 先创建空文本的 `QLabel`，连接信号并填充表格后，再调用 `setText()` 设置实际内容
- **验证**：修复后程序可正常启动，完整加载 139 条账号记录，无异常退出

---

## 三、涉及文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `ai/ollama_client.py` | 修改 | 新增 `_extract_json_after_marker` |
| `core/repositories.py` | 修改 | `insert` / `check_duplicate` 键名兼容 |
| `services/ai_assistant_service.py` | 修改 | 假事务改逐条执行、语义摘要 |
| `services/batch_add_processor.py` | 修改 | 键名兼容 `_batch_item_to_dict` |
| `ui/main_window.py` | 大量修改 | UI 交互、Build 模式、预览勾选、闪退修复等 |
| `docs/2026-04-25_update_log.md` | 新增 | 本文档 |

---

## 四、遗留待验证项

- [ ] 网址库 Plan 模式搜索 fallback 清除矛盾文案
- [ ] 网址库匹配列表 UI 标签显示"匹配"徽章
