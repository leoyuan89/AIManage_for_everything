# Debug Journal — 问题排查记录

> 用途：记录项目中遇到的 Bug/问题、排查过程、根因与解决方案，供后续参考。
> 格式：按时间倒序，每次追加一条记录。

---

## 2026-05-07 | 主界面视图持久化：操作后自动跳回默认视图

### 现象
用户每次搜索或操作（编辑保存、删除）后，主界面自动回到默认的「全部」分类视图，导致用户需要反复重新搜索/筛选，体验极差。

### 排查过程
1. **定位根因**：`show_account_detail()` 和 `show_url_detail()` 在弹窗关闭后直接调用 `load_accounts()`/`load_urls()`，无条件重置为当前分类的默认视图
2. **同样问题**：`_execute_batch_delete()` 批量删除后也调用 `load_accounts()`/`load_urls()`
3. **搜索缓存污染**：`on_search()` 复用了 `_cached_accounts`（分类视图下仅含当前分类数据），导致在分类内搜索无结果
4. **新增条目无反馈**：`on_add_item()` 只是简单 `load_accounts()`，新增后不定位也不高亮

### 根因
- 缺少对当前「视图模式」（搜索/分类/AI高亮）的状态追踪
- 所有操作完成后的刷新逻辑都是无脑 `load_accounts()`，不区分用户当前所处的视图
- AccountDialog 新增账号时未捕获返回值，导致无法获取新条目 ID 进行高亮

### 解决方案
1. **新增 `_view_mode` 状态变量**（`'default'` / `'search'` / `'ai_highlight'`），在各入口方法中设置
2. **新增 `_smart_refresh()` 方法**：根据 `_view_mode` 智能刷新，搜索模式下重新执行搜索，AI高亮模式下重新应用筛选
3. **新增 `_reapply_ai_highlight()`**：数据变更后重新加载全量数据并应用当前 AI 高亮 ID 集合
4. **编辑/删除后**：`show_account_detail()`、`show_url_detail()`、`_execute_batch_delete()` 改用 `_smart_refresh()`
5. **新增条目后**：`on_add_item()` 切换至「全部」分类、清空搜索框和 AI 高亮，加载全量数据并高亮新条目
6. **搜索不再使用缓存**：`on_search()` 直接调用 `get_all_accounts()` 获取全量数据，不再复用分类过滤后的缓存
7. **AccountDialog 修复**：`on_save()` 新增时捕获 `add_account()` 返回的 ID 并赋值给 `self.account`

### 经验总结
- **视图状态需要显式管理**：不能默认「刷新=回默认」，用户当前的操作上下文是高价值状态
- **缓存复用需审慎**：`_cached_accounts` 在不同场景下含义不同（分类视图 vs 全量），搜索场景应直接用全量数据
- **新增/编辑操作应有视觉反馈**：用户需要知道自己操作的结果（高亮/定位），而不是刷新后面目全非

---

## 2026-05-07 | UI 主题系统重构：暗色主题适配 + 功能修复

### 背景
项目原有 200+ 处硬编码的浅色主题颜色值，暗色主题切换后界面丑陋不可用。用户要求全面改造主题系统，支持浅色/深色平滑切换。

### 改造范围
- **14 个文件**，+1670/-880 行
- 新建 `ThemeColors` 色板系统（40+ 颜色 Token）
- 新建 `ThemeManager` 单例（信号驱动主题切换）
- 集成 `qtawesome` 图标库
- 所有 UI 文件的硬编码颜色替换为主题 Token

### 排查过程

#### 1. 多次 `NameError: name 'colors' is not defined`
**现象**：主题改造用 agent 批量替换硬编码颜色，但 agent 在多处将 `colors = ThemeManager.instance().colors` 写入了 **f-string 内部**（变成 CSS 文本而非 Python 代码），导致运行时 NameError。

**根因**：agent 错误地将 Python 赋值语句放在了 f-string 的三引号内。静态扫描工具无法区分 f-string 内的文本和真正的 Python 代码。

**修复方法**：
- 编写静态扫描脚本，检测所有使用 `{colors.xxx}`（f-string 内）和 `colors.xxx`（Python 表达式）的方法
- 逐一手动修复，在所有引用 `colors` 的方法顶部添加真正的 `colors = ThemeManager.instance().colors`
- 共修复 **6 个方法**：`_display_search_results`, `_ai_display_results_in_list`, `set_preview_data`, `_fill_table`, `highlight_matched_accounts`, `_on_ai_mode_changed`

#### 2. 初始暗色主题不生效
**现象**：配置文件中 `theme: dark`，但启动后界面仍为浅色。通过设置切换却能正常工作。

**根因**：`ThemeManager.init_app()` 只调用了 `_apply_qt_material()` 应用 qt-material 样式，但**没有设置 `self._current` 和 `self._colors`**。导致 `setup_ui()` 读取 `ThemeManager.instance().colors` 时拿到的是默认 `LIGHT_COLORS`。

**修复**：`init_app()` 现在正确设置 `self._current = theme` 和 `self._colors = DARK/LIGHT_COLORS`。

#### 3. 设置弹窗主题切换延迟
**现象**：通过设置→主题设置切换主题后，主窗口不立即刷新，需再次打开设置才生效。

**根因**：主题切换信号链经过嵌套模态弹窗（SettingsDialog → ThemeSettingsDialog → QMessageBox），主窗口的 paint 事件被模态弹窗阻塞。

**修复**：
- `_apply_theme()` 中直接调用 `_reapply_styles()` + `repaint()` + `processEvents()`，不依赖信号异步传递
- `on_settings()` 在弹窗关闭后无条件执行 `_reapply_styles()`
- `SettingsDialog` 监听 `ThemeManager.theme_changed` 信号，实时更新自身按钮样式

#### 4. AI 匹配高亮不生效
**现象**：炽阳 AI 搜索结果中，匹配条目没有任何视觉高亮，与普通条目无法区分。

**排查**：尝试了多种方案均失败：
- `widget.setStyleSheet(background-color)` → 样式表正确替换但视觉无变化（QWidget 在 QListWidgetItem 中 CSS 背景不渲染）
- `widget.setPalette()` + `setAutoFillBackground(True)` → 同样不生效
- `item.setBackground()` → 无效（`setItemWidget()` 时 item 不绘制自己的背景）
- 红色极端测试 → 确认机制可行但子控件（图标、分类标签）的背景遮挡了父控件

**根因**：Qt 的 `setItemWidget()` 让 widget 完全接管 item 的绘制。widget 内的子控件（`icon_label`, `lbl_category`）有独立的不透明背景色，遮挡了父 widget 的背景。

**最终方案**：创建带高亮背景色的 `QWidget` 容器，将整个 `AccountListItem` 包裹其中，内部 widget 设为透明，子控件（分类标签）背景也透明化。这样容器背景色覆盖整条 item。

**颜色方案**：
- 浅色主题：`#BBDEFB`（中等蓝色，在白底上清晰可见）
- 深色主题：`#2A3D55`（蓝灰色，在黑底上清晰可见）

### 新增架构

```
ThemeManager (QObject 单例)
├── ThemeColors (40+ token 色板)
│   ├── LIGHT_COLORS  → Material Design 3 浅色
│   └── DARK_COLORS   → Material Design 3 深色
├── theme_changed 信号 → 驱动全局 UI 刷新
├── init_app()       → 启动时初始化
├── apply_theme()    → 运行时切换
├── get_icon()       → qtawesome 图标
└── style_*()        → 预设样式生成函数
```

### 经验总结
- **Agent 批量替换的陷阱**：agent 容易将代码写入 f-string 内部，静态检查工具可能漏检。必须编写针对性的验证脚本。
- **Qt 的 setItemWidget 机制**：使用 `setItemWidget` 后，item 完全不绘制自己的背景。高亮需在 widget 层实现。
- **QWidget CSS 背景**：QWidget（非 QFrame 子类）的 CSS `background-color` 在特定场景下不渲染，需配合 `setAutoFillBackground` 或使用容器包裹。
- **模态弹窗链**：嵌套模态弹窗会阻塞父窗口的事件处理，信号驱动方案不可靠时，应改为直接调用 + 弹窗关闭后兜底重绘。

---

## 2026-04-27 | QTreeWidget 自定义拖拽排序后条目被"吞掉"

### 现象
在分类导航栏编辑模式（排序模式）下，拖动一级分类或二级分类进行排序，drop 后被拖动的条目从 UI 上直接**消失**（被"吞掉"）。退出排序模式重新加载分类树后，条目又会正常显示，且顺序确实是调整后的结果——说明**数据层移动正确，仅 UI 层显示异常**。

### 排查过程
1. **初始实现**：在 `dropEvent` 中手动 `invisibleRootItem().takeChild()` + `insertChild()` 移动顶层 item → **item 消失**
2. **改用高级 API**：换成 `QTreeWidget` 级 API `takeTopLevelItem()` + `insertTopLevelItem()` → **仍然消失**
3. **怀疑 model 刷新**：`dropEvent` 末尾加 `viewport().update()` → **仍然消失**
4. **核心发现**：问题不在移动 API 本身，而在 `event.accept()`。调用 `event.accept()` 后，Qt drag/drop 框架认为 drop 已被处理，会在 drag 结束阶段执行内部清理（selection model 更新、drag state 释放等）。此时若手动移除了 item，Qt 内部保存的 model index / item 指针变为**悬空引用**，清理逻辑访问失效引用导致 item 被异常删除或隐藏。
5. **验证方案**：`event.ignore()` 拒绝 Qt 默认处理 + `QTimer.singleShot(0, ...)` 延迟到下一事件循环再手动移动 → **正常**

### 根因
`QTreeWidget` 在 `InternalMove` 拖拽模式下，`dropEvent` 中调用 `event.accept()` 会触发 Qt 内部的 drag 结束清理流程。该流程依赖 drop 前保存的 item model index 和指针状态。若此时手动 `takeTopLevelItem` 移除了 item，Qt 内部的引用失效，清理阶段的 undefined behavior 导致 item 从 view 中被异常移除（数据仍在，但不可见）。

### 解决方案
在 `dropEvent` 中：
1. **拒绝 Qt 默认处理**：`event.ignore()` —— 告知 Qt "此 drop 未被处理"，阻止其执行任何内部 drag 清理逻辑
2. **延迟手动移动**：`QTimer.singleShot(0, do_move)` —— 将 `takeTopLevelItem`/`insertTopLevelItem` 或 `takeChild`/`insertChild` 推迟到**下一事件循环**，确保 Qt drag 状态完全结束后才操作 item，彻底避免状态冲突

```python
def dropEvent(self, event):
    # ... 位置计算与规则校验 ...
    
    event.ignore()  # 关键：拒绝 Qt 默认 drop 清理
    
    # 延迟到下一帧执行移动
    def do_move():
        old_row = self.indexOfTopLevelItem(source_item)
        taken = self.takeTopLevelItem(old_row)
        self.insertTopLevelItem(target_row, taken)
        self.setCurrentItem(taken)
    
    QTimer.singleShot(0, do_move)
```

### 经验总结
- 覆盖 Qt 的 `dropEvent` 做手动拖拽排序时，`event.accept()` 不只是"接受 drop"那么简单，它会触发一整套 drag 结束清理流程
- 当手动操作 item（`takeChild`/`insertChild`）与 Qt 内部 drag 状态冲突时，`event.ignore()` + 延迟执行是可靠方案
- `QTreeWidget` 的 `InternalMove` 默认行为和手动干预混用时极易产生悬空引用问题，最佳实践是**要么完全交给 Qt 默认处理，要么完全接管并拒绝默认处理**

---

## 2026-04-27 | AIHelpDialog 点击后闪退（0xC0000409）

### 现象
在 `ui/main_window.py` 中新增 `AIHelpDialog(QDialog)` 使用说明对话框，点击"炽阳"标题后程序直接闪退，Windows 退出码 `-1073740791 (0xC0000409)`，即 **STATUS_STACK_BUFFER_OVERRUN**（栈缓冲区溢出）。

### 排查过程
1. **验证基础组件**：空 `QDialog` + 样式表 → 正常
2. **逐步加组件**：+ `QScrollArea` + 20个 `QLabel` → 正常
3. **加复杂结构**：+ objectName 样式表卡片 + HBox 嵌套 → 正常
4. **完整结构复刻**：把所有功能卡片、分隔线、小贴士全部内联构建 → 正常
5. **测试相同 objectName**：10个卡片共用同一个 objectName `"helpCard"` → 正常
6. **测试模块级类**：调用文件顶部定义的 `AIHelpDialog(self).exec()` → **闪退**
7. **测试局部类**：把完整代码包成 `on_ai_show_help` 方法内的局部类 → **正常**

### 根因
`main_window.py` 是一个 **5000+ 行**的大文件，包含庞大的 `MainWindow` 类、qt-material 全局样式表、大量信号/槽和自定义组件。在这个文件的**模块级作用域**中定义一个继承 `QDialog` 的子类 `AIHelpDialog`，会和文件内的其他代码（极可能是 qt-material 样式表引擎在超大模块上下文中的解析/计算逻辑）产生某种深层冲突，导致 Qt 内部栈溢出。

独立测试脚本（把同样代码放在单独小文件中）完全正常，证明**代码逻辑本身无问题**，问题仅在**定义位置/上下文**。

### 解决方案
将对话框实现为 `on_ai_show_help` **方法内的局部类**（`LocalHelpDialog`），完全隔离在方法作用域中，不再在模块级定义。局部类不会和 `main_window.py` 中的全局代码产生任何冲突，经测试稳定可靠。

### 经验总结
- **0xC0000409** 在 PyQt 中不只是 `pyqtSignal(dict)` 的问题，大文件中的模块级类定义 + 复杂全局样式表也可能触发
- 当代码逻辑本身正确、独立测试通过、但嵌入大文件就崩溃时，优先考虑**作用域隔离**（局部类、内联实现、或拆分到独立文件）
- QWidget 样式表避免使用 `QWidget { ... }` 全局选择器，应使用 `#objectName` 限定，防止 cascade 到子控件

---

## 2026-04-28 | 网址分类任务 212→143 数据丢失

### 现象
对「编程学习与工具」分类下的212个网址执行智能细分二级子类，最终只有143个条目完成分类赋值，剩余60个条目被**静默丢弃**。日志中仅记录了8条SKIP重复ID，无其他异常或错误。

### 排查过程
1. **排除截断可能**：`done_reason='stop'` 而非 `'length'`，且 `gen_tokens=4790` 远未达 `num_predict=16384` 上限 → **不是被截断**
2. **检查JSON解析**：`smart_classify_urls` 工具内无 `JSON parse failed` 日志 → **解析成功**
3. **检查工具执行逻辑**：遍历 `data.items()` 生成预览项，仅处理模型返回的ID。代码**未对比输入ID集合 vs 输出ID集合**，未返回的ID直接静默丢弃
4. **分析prompt内容**：`SmartClassifyUrlsTool` 上传了 `ID+标题+网址+分类`，其中网址URL被截断40字符仍占大量token。212条网址prompt达18681字符/10360 token，4B模型面对如此大规模重复性输出任务容易"偷懒"遗漏
5. **发现 `_extract_json_object_robust` 正则隐患**：代码块提取使用 `\{[\s\S]*?\}` 非贪婪匹配，遇到嵌套JSON时可能提前在第一个 `}` 截断

### 根因
1. **大模型一次性处理数据量过载**：prompt塞入212条全部信息，4B小模型生成过程中主动停止，遗漏约60个条目
2. **代码无遗漏兜底**：`SmartClassifyUrlsTool` / `SmartClassifyAccountsTool` 均未检测「模型未返回的ID」，导致遗漏条目静默丢失
3. **prompt冗余**：上传了网址URL（对用户分类决策无价值），浪费大量token

### 解决方案
1. **精简prompt**（`services/ai_tools.py`）：
   - `SmartClassifyUrlsTool`：去掉网址URL，改为上传 `ID+标题+分类+备注+AI备注`
   - `SmartClassifyAccountsTool`：补充 `AI备注`，去掉空备注字段以节省token
2. **精简 db_summary**（`services/ai_assistant_service.py`）：
   - `build_db_summary`（网址库）：去掉 `网址` 列，改为 `ID|标题|分类|备注|AI备注`
   - `semantic_query`（网址库）：去掉URL，改为上传标题/分类/标签/备注/AI备注
3. **精简语义搜索摘要**（`services/ai_tools.py`）：
   - `_build_urls_summary`：去掉URL，改为上传标题/分类/标签/备注/AI备注
4. **添加遗漏检测**（`services/ai_tools.py`）：
   - 生成预览后，计算 `input_ids - seen_ids`，找出模型未返回的ID
   - `force_subclass` 模式下归入 `主类>未分类`，非细分模式归入 `其他`
   - 打印 `MISSING` 日志提示用户
5. **修复 `_extract_json_object_robust` 正则bug**（`ai/ollama_client.py`）：
   - 将 `\{[\s\S]*?\}` 非贪婪提取改为提取代码块全部内容，再用括号深度计数找完整JSON对象

### 经验总结
- **大模型不是万能的**：4B参数模型面对200+条目的全量分类任务，单次prompt极易遗漏。代码必须自己做「输入输出ID对齐检查」
- **prompt即成本**：每条冗余字段（如URL）都会增加模型负担。只上传对决策真正有价值的字段
- **静默丢弃是最危险的bug**：比崩溃更隐蔽，用户可能在很久后才发现数据不完整
- **db_summary 是更大的隐患**：`build_db_summary` 上传了500条带URL的数据（`max_items=500`），比工具内部prompt更膨胀，是第一轮决策调用prompt达3万字符的元凶

---
