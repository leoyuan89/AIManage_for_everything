# 更新日志 (CHANGELOG)

> 本地密码保险箱 AI Manage — 永久维护的版本更新日志
>
> 格式：时间倒序，按版本号分组。每个版本记录新增、优化、修复三类改动。

---

## [未发布] — 2026-05-09

### 修复
- **批量导入预览表格点击 checkbox 闪退**：`CategoryDelegate` 作为局部变量被 Python GC 回收后 Qt 访问悬空指针，改为保存为实例变量 `self._category_delegate`
- **`BatchItemTableModel.data()` 未捕获异常**：`_get_status_color()` 中 `status` 为 `None` 时 `startswith()` 在 Qt 回调中抛出 `AttributeError`，PyQt6 无法抛回 C++ 事件循环导致直接终止，增加空值保护和 `try/except` 兜底
- **`AccountListItem` 缺少 `_compact_mode` 初始化**：紧凑视图模式下触发 `AttributeError`
- **`_enter_selection_mode` 遗漏 `on_check_changed` 设置**：列表在非选择模式下加载后进入批量模式，checkbox 显示但无回调，勾选状态不同步

### 优化
- **`main_window.py` 5 处列表项创建统一传入 `parent=self.account_list`**：`AccountListItem`/`URLListItem` 创建时杜绝裸窗口，消除批量模式下的白色弹窗闪现和 Qt 内部状态不稳定
- **批量操作点击条目非 checkbox 区域闪退**：`on_account_clicked` 中使用 `QApplication.widgetAt(QCursor.pos())` 判断点击位置，在 PyQt6 + qt-material + 复杂 widget 树环境下触发 `0xC0000409` 闪退。改用 `AccountListItem`/`URLListItem` 内部 `_checkbox_clicked` 标志位机制，弃用 `widgetAt`，实现点击条目任意位置均可勾选/取消勾选

## [未发布] — 2026-05-07

### 新增
- **键盘快捷键**：`Ctrl+F` 聚焦搜索 / `Ctrl+N` 新建 / `Delete` 删除当前 / `Escape` 三级退出(选择模式→清除搜索→关闭AI面板) / `Ctrl+D` 切换主题 / `Ctrl+L` 锁定 / `Ctrl+1/2` 切换密码库/网址库
- **日志系统**：`core/logger.py` 统一日志管理，日志写入 `~/.local_password_vault/app.log` 按天轮转保留7天。全项目 20+ 文件 `print()` → `logger.*()` 替换
- **基础测试体系**：`tests/` 目录，22 个单元测试覆盖 crypto、account_service、search_service、ID 一致性
- **密码会话校验**：修改主密码后 `session_version` 递增，敏感操作（查看密码、导出、设置）前校验，不匹配则弹出锁屏
- **AppState 状态管理类**：`ui/state/app_state.py`，集中管理 view_mode/vault/category/selection/highlight/cache 状态 + 信号驱动
- **SmartRefreshWidget 虚拟滚动原型**：为后续 QListView + Model/Delegate 迁移预留

### 优化
- **视图持久化**：编辑/删除/批量删除后不再自动跳回默认视图，保持在搜索/分类/AI高亮视图
- **_reload_categories() 条件调用**：编辑保存时仅分类变化才重建分类树，减少无效刷新
- **ID 类型统一**：`_highlight_matched_ids` 从 `set of str` 统一为 `set of int`，消除 3 处 ID 类型转换
- **滚动位置保持**：`_smart_refresh()` 内建 `try/finally` 确保操作后滚动位置恢复
- **新增条目高亮**：新增账号/网址后自动切至「全部」并高亮新条目
- **代码拆分**：`AccountListItem` 和 `URLListItem` 提取到 `ui/widgets/`，main_window 减 266 行

### 修复
- 搜索在分类视图下结果为空（缓存被分类过滤污染），改为搜索直接获取全量数据
- `highlight_matched_accounts` 中未匹配条目 CSS 静默无效（f-string 缺失），导致灰色效果未生效
- `_reapply_ai_highlight()` 缓存 dirty 标记未清除
- 缺失 `_thinking_is_redundant()` 方法导致运行时 `AttributeError`
- 6 处 AI 聊天 HTML 颜色 f-string 前缀缺失
- `AccountDialog.on_save()` 新增时未捕获返回值导致新条目 ID 丢失

---

## v1.2 — 2026-05-07

### 修复
- **主界面视图持久化**：操作（编辑/删除/批量删除）后不再自动跳回默认视图，保持在当前搜索/分类视图

---

## v1.1 — 2026-05-07

### 新增
- **UI 主题系统重构**：新建 `ThemeColors` 色板（40+ Token）和 `ThemeManager` 信号驱动单例，支持浅色/深色平滑切换。涉及 14 个文件，+1670/-880 行
- **qtawesome 图标库集成**

### 修复
- 暗色主题初始不生效（`init_app` 未设置 `_current` 和 `_colors`）
- 设置弹窗主题切换延迟（模态弹窗链阻塞 paint 事件）
- AI 匹配高亮不生效（`setItemWidget` 后 item 不绘制背景，改用容器包裹）
- 6 处 `NameError: name 'colors' is not defined`（f-string 内误写赋值语句）

### 优化
- 搜索支持备注字段匹配

---

## v1.0 — 2026-04-28

### 新增
- 密码库 + 网址库双库管理
- 二级分类体系 + AI 智能细分
- AI 助手（炽阳）：Plan/Build/ReAct 三种模式
- Ollama + Gemma4:4b 本地 AI 集成
- 密码加密存储（cryptography）
- 拼音搜索
- 批量导入/导出（Excel）
- 回收站（30 天软删除）
- 锁定屏幕（10 分钟空闲自动锁）
- 分类树拖拽排序

### 修复
- ReAct 操作确认后 AI 误解重复执行（添加 `_react_state = IDLE` 结束循环）
- AI 智能分类 212→143 数据丢失（prompt 过载 + 无遗漏检测，精简 prompt + 添加遗漏兜底）
- 分类树拖拽后条目"被吞掉"（`event.accept()` 与 `takeTopLevelItem` 冲突，改用 `event.ignore()` + 延迟执行）
- `AIHelpDialog` 点击闪退 0xC0000409（大文件模块级类定义与 qt-material 冲突，改用局部类隔离）
- 分类名不能包含 `/、>、·` 校验缺失
- `_extract_json_object_robust` 正则非贪婪匹配提前截断嵌套 JSON

### 优化
- 二级分类支持升级为一级分类
- 分类树拖拽时视口自动滚动
- 网址分类 prompt 精简（去掉冗余 URL 字段）
- 迭代自纠正循环 + 同步到手机增强
