# 更新日志 (CHANGELOG)

> 本地密码保险箱 AI Manage — 永久维护的版本更新日志
>
> 格式：时间倒序，按版本号分组。每个版本记录新增、优化、修复三类改动。

---

## [未发布] — 2026-05-15

### 修复
- **列表项复制按钮点击后弹窗问题**：`AccountListItem` / `URLListItem` 的 `mousePressEvent` 正确消费了复制按钮点击，但 `mouseReleaseEvent` 仍调用 `super()` 导致 release 事件传播到 `QListWidget`，触发 `itemClicked` 信号弹出详情弹窗。添加 `_press_handled` 标志位，复制按钮点击后在 `mouseReleaseEvent` 中拦截事件传播，彻底解决弹窗打开后复制按钮失效的问题
- **搜索历史未区分密码库/网址库**：搜索历史存储为单一扁平 JSON 列表，两个库共享同一份历史，且网址库搜索从未记录历史。将 `_search_history` 从 `List[str]` 重构为 `Dict[str, List[str]]`（按 `accounts` / `urls` 分区），所有历史方法添加 `vault_type` 参数；网址库搜索后显式记录历史；切换库时同步更新 QCompleter 补全列表；兼容旧格式自动迁移

---

## [未发布] — 2026-05-14

### 新增
- **列表项呼吸灯闪烁提示**：编辑/新增账号或网址保存成功后，对应列表项以淡蓝色柔和呼吸闪烁 2 秒（正弦波 alpha 0→40，2 秒内 2 次循环），直观提示用户刚刚操作的是哪一条目
- **日历年份快捷输入**：点击日历年份按钮不再弹出需要滚动很久的长列表菜单，改为弹出整数输入框直接输入年份（1900–2100），保持原月份并自动限制日期为该月最大天数

### 优化
- **筛选面板主题适配**：补全 `_reapply_styles` 和 `_on_filter_toggle` 中遗漏的 `lbl_filter_tags`、`filter_tags`、`btn_apply_filter`、`btn_clear_filter` 样式更新，确保 dark/light 主题切换后筛选面板所有控件颜色一致
- **日历导航栏布局稳定化**：为 prev/next/month/year 四个导航按钮设置固定/限制宽度（翻页按钮固定 32px，月份 70–90px，年份 55–70px），消除点击翻页或年份选择后的导航栏抖动偏移
- **日历样式完整主题化**：补充 `QCalendarWidget` 整体背景、`QToolButton` 背景边框 hover、`QAbstractItemView` 背景、`QMenu` 及选中项样式，消除主题切换后日历按钮显示为白色块的问题；隐藏左侧 ISO 周数列（`NoVerticalHeader`）
- **日历翻页按钮标识**：为 prev/next 按钮添加 `<` `>` 文字标识，避免无默认箭头图标时显示为空白块

### 修复
- **Service 层缓存未清除导致编辑保存后字段显示为空**：`MainWindow` 中 15+ 处数据变更路径（编辑保存、新增、分类调整、批量导入、收藏切换、回收站恢复等）仅设置 `_accounts_cache_dirty=True` 但未调用 `account_service.get_all_accounts.cache_clear()`，导致 `lru_cache` 返回旧数据。统一改为调用 `_invalidate_all_caches()` 同时清除 Service 层和 UI 层缓存。特别修复了 Dashboard 模式下 `_smart_refresh()` 直接 `return` 跳过缓存清除的问题
- **主题切换闪退（0xC0000409）**：
  - `SearchHistoryPanel` 缺少 `on_theme_changed()` 导致 `AttributeError`
  - `AccountListItem` / `UrlListItem` 的 `paintEvent` 中直接调用子控件 `move()/show()/hide()`，引发递归重绘栈溢出
  - `core/theme_manager.py` 中后台预加载线程与主线程对 `qt_material.set_icons_theme` 的 monkey patch 存在竞态条件，已加 `threading.Lock` 保护
  - `main.py` 缺少 `sys.excepthook` 全局异常钩子，信号槽中的未捕获异常直接闪退
  - `SettingsDialog` 重复连接 `theme_changed` 信号从未断开，造成内存泄漏
  - `MainWindow` 中 AI 筛选高亮时的样式表无限追加问题（改为直接设置而非追加）
- **日历主题切换不刷新**：`_fix_calendar_style` 有 `_calendar_style_applied` 缓存标志导致样式只应用一次，主题切换后重置该标志，确保下次打开日历应用新主题色

## [未发布] — 2026-05-13

### 新增
- **搜索历史面板（SearchHistoryPanel）**：空搜索框点击时显示最近搜索历史，pill 标签两列排列；支持浏览态（点击搜索）/删除态（管理→单条删除/清空全部→完成）两态切换；按密码库/网址库隔离历史记录；JSON 持久化到 `search_history.json`

### 优化
- **`SearchHistoryPanel` 稳定性重构**：设为 `Popup` 独立窗口 + `QTimer.singleShot` 延迟切换按钮可见性，彻底规避 PyQt6 + qt-material 环境下 `0xC0000409` 堆栈缓冲区溢出崩溃

### 修复
- **搜索历史面板 `0xC0000409` 崩溃**：修复 widget 层级冲突、事件循环中直接隐藏被点击按钮、启动时焦点自动触发显示等场景下的多重崩溃根因

---

## [未发布] — 2026-05-09

### 修复
- **批量导入预览表格点击 checkbox 闪退**：`CategoryDelegate` 作为局部变量被 Python GC 回收后 Qt 访问悬空指针，改为保存为实例变量 `self._category_delegate`
- **`BatchItemTableModel.data()` 未捕获异常**：`_get_status_color()` 中 `status` 为 `None` 时 `startswith()` 在 Qt 回调中抛出 `AttributeError`，PyQt6 无法抛回 C++ 事件循环导致直接终止，增加空值保护和 `try/except` 兜底
- **`AccountListItem` 缺少 `_compact_mode` 初始化**：紧凑视图模式下触发 `AttributeError`
- **`_enter_selection_mode` 遗漏 `on_check_changed` 设置**：列表在非选择模式下加载后进入批量模式，checkbox 显示但无回调，勾选状态不同步
- **`services/sync_service.py` 密包非原子写入 + `ITERATIONS` 未注入**：改为临时文件 `os.replace()` 原子替换，并注入 `crypto_manager.iterations` 到 PWA 模板
- **`services/ai_assistant_service.py` Legacy Build 方法无事务**：`_execute_build_action_with_transaction_legacy` 添加 `with tx_db.transaction():` 包裹，并补充审计日志
- **全项目 `OllamaClient` 主线程阻塞**：所有直接实例化处添加 `timeout=30`，`ai_remark_service.py` 改为走 `AIServiceManager.generate_remark_async()` 异步队列
- **`core/repositories.py` 搜索全表加载**：`AccountRepository.search()` / `URLRepository.search()` 改为 SQL 层 `LIKE` 查询，避免全量解密加载
- **`core/database.py` 回收站脱敏逻辑不完整**：提取 `_mask_username()` 统一脱敏规则，邮箱/非邮箱统一处理
- **`ui/main_window.py` 日志级别不当**：13 处 `logger.info` 记录异常改为 `logger.exception`，4 处改为 `logger.error`
- **`core/crypto.py` 注释错误**：`ITERATIONS` 默认值注释从 100000 修正为 600000
- **`ui/main_window.py` UTF-8 BOM 污染**：去除文件头 BOM，修复工具链兼容性

### 优化
- **`main_window.py` 5 处列表项创建统一传入 `parent=self.account_list`**：`AccountListItem`/`URLListItem` 创建时杜绝裸窗口，消除批量模式下的白色弹窗闪现和 Qt 内部状态不稳定
- **批量操作点击条目非 checkbox 区域闪退**：`on_account_clicked` 中使用 `QApplication.widgetAt(QCursor.pos())` 判断点击位置，在 PyQt6 + qt-material + 复杂 widget 树环境下触发 `0xC0000409` 闪退。改用 `AccountListItem`/`URLListItem` 内部 `_checkbox_clicked` 标志位机制，弃用 `widgetAt`，实现点击条目任意位置均可勾选/取消勾选
- **`ui/main_window.py` AI 聊天全量重绘**：流式输出阶段改为增量 `_ai_append_token_html()` 追加，安全定时器降为 1 秒全量重建，显著降低长对话 CPU 占用
- **`core/password_strength.py` 硬编码颜色收敛 ThemeColors**：`evaluate_password_strength()` 仅返回语义标签，UI 层统一从 `ThemeManager.instance().colors` 动态取色
- **`services/ai_worker_thread.py` latency 实际测量**：任务执行前后记录 `time.perf_counter()` 差值，状态指标恢复意义
- **`services/ai_assistant_service.py` 清理无用 `inherited_ids`**：移除 `ReferenceResolver.resolve()` 的未使用返回值和 `tool_context` 中的传递
- **`ai/ollama_client.py` 移除未使用变量**：清理 `generate_tool_call` 中的 `tool_suffix_hint`

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

## [未发布] — 2026-05-13

### 新增
- **列表条目显示内容设置按钮**：在紧凑视图按钮旁新增 ⚙ 按钮，点击弹出菜单可勾选/取消勾选显示字段（首字母图标、应用名/网址标题、账号/网址地址、密码强度、分类标签、右箭头），配置按库独立持久化
- **Ctrl+M 批量选择模式快捷键**：快速进入 / 退出批量选择模式，与底部按钮等效
- **Ctrl+拖动多选**：进入批量选择模式后，按住 Ctrl 并在列表条目上拖动鼠标，经过的条目选中状态自动翻转（未选→选中，选中→未选），单次拖动内每个条目仅切换一次
- **批量操作后高亮**：批量分类 / 批量标签完成后，被修改的条目以蓝色背景置顶高亮显示，并显示操作横幅，避免直接回到默认列表导致无法感知修改结果
- **帮助文档快捷键一览**：新增「快捷键一览」卡片，以标签形式展示全部 10 个快捷键；更新批量操作提示为拖动框选说明
- **列设置图标**：`assets/icons/icon_settings.svg`（滑块风格，与现有图标统一）

### 优化
- **列表项字体精细化**：标题字体 14px→13px，副标题字体 11px→10px，副标题行高 16px→18px，解决 56px 高度下文字底部截断问题
- **`elidedText` 截断可靠性**：标题/网址/账号的 `elidedText` 计算从 `QFontMetrics(font)` 改为 `painter.fontMetrics()`，确保截断宽度与绘制字体度量完全一致

### 修复
- **副标题（用户名/网址）字体过大被截断**：11px 字体在 16px 行高内溢出，改为 10px + 18px 行高
- **标题截断可能失效**：`QFontMetrics(title_font)` 与 `painter.setFont(title_font)` 后的实际度量存在细微差异，改用 `painter.fontMetrics()` 后统一

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
