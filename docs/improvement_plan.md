# 改进计划

> 版本：v1.0 | 日期：2026-05-07
> 
> 基于对当前代码库（~6000 行 `main_window.py`）的全面审查，识别出架构、性能、体验三个层面的改进方向，按优先级排列。

---

## 一、架构拆分：`main_window.py` 模块化

### 现状

`ui/main_window.py` ~6000 行，混杂以下职责：

- UI 构建（2400+ 行）：`setup_ui()` 及其子方法构建整个主窗口布局
- 列表渲染（600+ 行）：`AccountListItem`、`URLListItem`、`load_accounts()`、`load_urls()`、`_display_search_results()`、`highlight_matched_accounts()`
- AI 面板（1200+ 行）：消息发送、聊天渲染、Build/ReAct 模式、AI 工具调用确认
- 状态管理（散落各处）：`_view_mode`、`_selection_mode`、`_highlight_matched_ids`、`_cache_dirty`、`_react_state` 等 20+ 个状态变量
- 业务协调（800+ 行）：分类操作、批量删除、导入导出、回收站

**问题**：任一改动需要翻阅数千行找上下文，极易引入回归 bug。

### 目标

每个模块单一职责，模块间通过明确的接口（信号/槽 或 方法调用）通信，最终 `MainWindow` 只做顶层编排。

### 拆分方案

```
ui/
├── main_window.py          # ~800 行：仅做顶层窗口 + 模块组装编排
├── widgets/
│   ├── account_list_item.py   # AccountListItem widget（~150 行）
│   ├── url_list_item.py       # URLListItem widget（~100 行）
│   └── ai_filter_banner.py    # AI 筛选横幅 widget（~60 行）
├── panels/
│   ├── list_panel.py          # 列表视图面板：构建列表、搜索、高亮、选择模式（~800 行）
│   ├── category_panel.py      # 分类侧边栏：树形控件、拖拽、右键菜单、批量操作（~600 行）
│   ├── ai_panel.py            # AI 对话面板：消息渲染、状态机（Build/ReAct）、工具确认（~1000 行）
│   └── bottom_bar.py          # 底部操作栏：正常模式/选择模式切换（~200 行）
├── state/
│   └── app_state.py           # 集中状态管理：view_mode、selection、vault、cache 标记（~150 行）
├── coordinators/
│   ├── account_coordinator.py # 账号操作协调：增删改查、分类切换、搜索触发（~400 行）
│   └── url_coordinator.py     # 网址操作协调（~300 行）
└── dialogs/                   # 保持不变（已有独立文件）
    ├── account_dialog.py
    ├── url_dialog.py
    └── ...
```

### 模块职责与接口

#### `AppState` — 集中状态管理
```
职责：
- 维护所有视图/模式状态变量（view_mode, selection_mode, current_vault, current_category 等）
- 缓存管理（mark_dirty, is_dirty, get_cached）
- 发射状态变更信号，驱动 UI 更新

关键信号：
- view_mode_changed(str)
- vault_changed(str)
- category_changed(str)
- selection_mode_changed(bool)
```

#### `ListPanel` — 列表视图
```
职责：
- 构建/管理 QListWidget（后续改造为 QListView + Model）
- 渲染三种视图：默认分类列表、搜索结果、AI 高亮
- 响应 AppState 信号自动切换视图
- 管理滚动位置、选择模式 checkbox

输入：
- AppState.view_mode_changed → 切换渲染模式
- Coordinator 提供数据

输出：
- item_clicked(account/url) → 触发 Coordinator 打开编辑
- selection_changed(selected_ids) → 更新底部栏
```

#### `AiPanel` — AI 对话面板
```
职责：
- 对话历史渲染（Markdown → HTML）
- Build/ReAct 状态机
- AI 工具调用结果确认弹窗
- 思考过程展开/折叠

输入：
- 用户输入文本
- AI 流式响应

输出：
- execute_action(action, params) → 触发 Coordinator 执行
- highlight_requested(ids) → 触发 ListPanel 高亮
```

#### `Coordinator` — 操作协调器
```
职责：
- 作为各面板之间的中介，不直接操作 UI
- 处理增删改查的业务流程
- 批量操作（导入导出、批量删除）
- 调用 Service 层，更新 AppState，触发面板刷新

关键流程（以编辑账号为例）：
1. ListPanel.item_clicked → Coordinator.show_detail(account)
2. Coordinator 打开 AccountDialog（modal）
3. 用户保存 → dialog.accept()
4. Coordinator 调用 account_service.update_account()
5. Coordinator 调用 app_state.mark_cache_dirty()
6. Coordinator 调用 list_panel.smart_refresh()
```

### 实施步骤

1. **先抽 `AppState`**：提取所有状态变量到一个独立类，各模块通过依赖注入引用
2. **平行迁移面板**：`ListPanel` → `CategoryPanel` → `AiPanel` → `BottomBar`，每步保持功能不变
3. **引入 Coordinator**：把 `show_account_detail`、`on_add_item`、`_execute_batch_delete` 等业务流程抽到 Coordinator
4. **最后瘦身 `MainWindow`**：只保留窗口级逻辑（标题栏、菜单、lock screen、模块组装）

---

## 二、测试体系搭建

### 目标

核心业务逻辑（Service 层、Coordinator 层）有自动化测试保护，每次改动可快速验证。

### 方案

```
tests/
├── conftest.py                 # pytest fixtures：临时 SQLite、加密密钥
├── services/
│   ├── test_account_service.py # CRUD、密码加密解密、分类过滤
│   ├── test_url_service.py     # CRUD、搜索
│   ├── test_search_service.py  # 精确/拼音匹配
│   └── test_crypto.py          # 加密解密正确性
├── state/
│   └── test_app_state.py       # 状态切换、信号发射
├── coordinators/
│   └── test_account_coordinator.py  # 业务流程（mock UI 面板）
└── ui/                         # 可选：GUI 测试
    └── test_list_panel.py      # Model 数据正确性
```

### 策略

| 层级 | 覆盖方式 | 框架 | 优先级 |
|------|---------|------|--------|
| Service 层 | 单元测试 | pytest + sqlite :memory: | 高 |
| Crypto 层 | 单元测试 | pytest | 高 |
| Coordinator 层 | 集成测试（mock UI） | pytest + unittest.mock | 中 |
| State 层 | 单元测试 | pytest | 中 |
| UI 层 | 手动 / smoke test | — | 低 |

### 实施步骤

1. 安装 `pytest`、`pytest-cov`
2. 在 `conftest.py` 中创建 `DatabaseManager` 的 in-memory fixture（不依赖真实文件）
3. 先写 `test_crypto.py`（最独立），再写 `test_account_service.py`
4. CI 集成：`pytest --cov=services --cov=core`

---

## 三、列表性能：QListWidget → QListView + Model/Delegate

### 现状

每次刷新（`load_accounts()` / `on_search()` / `highlight_matched_accounts()`）都执行：

```python
self.account_list.clear()
for item in data:
    widget = AccountListItem(item)     # 创建完整 widget
    list_item = QListWidgetItem()
    self.account_list.setItemWidget(list_item, widget)  # 子 widget 挂载
```

**问题**：200 个条目 = 200 个 widget 对象常驻内存，每次重建触发 200 次 layout/paint。`setUpdatesEnabled(False)` 只是临时缓解。

### 目标

列表在 500+ 条目时滚动流畅，切换视图无感知延迟。

### 方案：QListView + QAbstractListModel + QStyledItemDelegate

#### 核心概念

- **`QAbstractListModel`**：纯数据层，不持有 widget。`rowCount()` 返回条数，`data()` 返回每行的角色数据
- **`QStyledItemDelegate`**：渲染层，Paint 方式绘制每行，而不是创建 widget。只有可见行才会触发 `paint()`
- **虚拟滚动**：Qt 自动管理，不可见的行不绘制、不占用资源

#### 数据模型设计

```python
class AccountListModel(QAbstractListModel):
    # 自定义 DataRole
    AppNameRole = Qt.UserRole + 1
    UsernameRole = Qt.UserRole + 2
    CategoryRole = Qt.UserRole + 3
    SecurityLevelRole = Qt.UserRole + 4
    BadgesRole = Qt.UserRole + 5
    MatchedRole = Qt.UserRole + 6      # AI 高亮标记
    OriginalDataRole = Qt.UserRole + 100  # 原始 Account 对象

    def __init__(self):
        self._items = []          # [(account, badges, is_matched), ...]
        self._section_headers = {}  # {row: "搜索结果"}  分区标题

    def set_items(self, items, view_mode='default'):
        """更新数据并通知 View"""
        self.beginResetModel()
        self._items = items
        self._view_mode = view_mode
        self.endResetModel()
```

#### Delegate 绘制方案

```python
class AccountItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # 1. 读取 model 各角色数据
        app_name = index.data(AppNameRole)
        username = index.data(UsernameRole)
        category = index.data(CategoryRole)
        is_matched = index.data(MatchedRole)

        # 2. 绘制背景（高亮/普通/搜索分区标题）
        # 3. 绘制圆形首字母图标（QPainter.drawEllipse + drawText）
        # 4. 绘制文字（QPainter.drawText）
        # 5. 绘制徽章（小圆角矩形 + 文字）
        # 6. 绘制分类标签
```

**注意**：Delegate 的 `paint()` 用 `QPainter` 直接绘制，不需要创建子 widget。首字母图标、圆角徽章、分类标签都通过 `QPainter` 绘制，性能远高于 widget 树。

#### 选择模式处理

`QListView` 配合 model 通过 `Qt.ItemIsUserCheckable` 角色原生支持 checkbox，无需单独 `QCheckBox` widget。

#### 预期收益

| 指标 | 当前 QListWidget | 改造后 QListView | 
|------|-----------------|-----------------|
| 200 条目内存 | ~200 widget 对象 | ~0 widget 对象（仅 paint）|
| 刷新耗时 | 150-300ms | 10-30ms |
| 滚动流畅度 | 卡顿 | 60fps |

### 实施步骤

1. 新建 `AccountListModel(QAbstractListModel)` 和 `AccountItemDelegate(QStyledItemDelegate)`
2. 在 `ListPanel` 中添加 `QListView` 替代 `QListWidget`
3. 先实现默认分类视图渲染，验证功能
4. 逐步支持搜索结果视图（分区标题行）
5. 逐步支持 AI 高亮视图（matched/unmatched 分组 + 彩色背景）
6. 最后替换 `URLListItem` 为 URL 版本的 Model/Delegate

### 风险与兼容

- **Delegate paint 开发复杂度高**：每个视觉元素（圆角图标、徽章、渐变背景）都需要手写 `QPainter` 代码。建议先用 prototype 验证视觉效果，确认满意后再全量迁移
- **交互（hover、click）**：Delegate 的 `editorEvent()` 可处理鼠标悬停高亮、点击，但不如 widget 的 signal/slot 直观
- **过渡期方案**：保留 `QListWidget` 的 `AccountListItem`，新增 `QListView` 方案，通过开关切换，验证稳定后再删除旧代码

---

## 四、`_reload_categories()` 调用优化

### 现状

几乎每次操作后都无条件调用 `_reload_categories()`，包括：
- 编辑账号内容（不改分类）
- 保存账号（分类未变）
- 批量删除

**问题**：`_reload_categories()` 从数据库全量读取分类树并重建 widget，条目多时也有开销。大部分操作不改变分类，属于无效刷新。

### 方案

在 `_reload_categories()` 调用点加判断：只有分类结构真正可能变化时才调用。

| 操作场景 | 需要 `_reload_categories()` | 原因 |
|---------|---------------------------|------|
| 编辑条目（分类未变） | ❌ | 分类树结构不变 |
| 编辑条目（分类变了） | ✅ | 新旧分类条目数变化需更新 |
| 删除条目 | ✅ | 条目数变化 |
| 新增条目 | ✅ | 条目数变化 + 可能引入新分类 |
| 重命名/删除分类 | ✅ | 结构变化 |
| 回收站恢复 | ✅ | 条目数变化 |
| 批量导入 | ✅ | 大量条目变化 |
| 主题切换 | ❌ | 仅视觉刷新，可单独调用分类树样式更新 |

### 实施

1. 在 `AppState` 中添加 `_categories_need_reload` 标记
2. `_smart_refresh()` 末尾根据标记决定是否调用 `_reload_categories()`
3. 各操作 point 按上表设置标记
4. 分类数变化单独走轻量级 `category_tree.update_counts()`（仅更新括号内数字，不重建树）

---

## 五、滚动位置在 `_smart_refresh()` 中保持

### 现状

`show_account_detail()` 有 `_save_scroll_state()` / `_restore_scroll_state()` 包裹，但 `_smart_refresh()` 里没有。

### 方案

将滚动保存/恢复逻辑内置到 `_smart_refresh()` 中：

1. 进入时调用 `_save_scroll_state()` 记录当前 `scrollbar.value()`
2. 执行刷新
3. 退出时调用 `_restore_scroll_state()` 恢复滚动位置

**注意**：搜索结果和 AI 高亮视图的内容变化后，原来的精确滚动位置可能不准确（条目顺序/数量变了）。此时退化为**恢复到最接近的可见区域**而非精确像素位置。更优的方案是定位到当前选中的条目或保留第一个可见条目的锚点。

---

## 六、键盘快捷键

### 方案

在 `MainWindow` 中注册全局快捷键（仅在窗口获得焦点时生效）：

| 快捷键 | 功能 | 实现 |
|--------|------|------|
| `Ctrl+F` | 聚焦搜索框 | `self.search_box.setFocus()` + `selectAll()` |
| `Ctrl+N` | 新建条目 | 触发 `on_add_item()` |
| `Ctrl+E` | 编辑选中条目 | 触发当前列表第一个可见/选中条目的编辑 |
| `Delete` | 删除选中条目 | 进入选择模式并选中当前条目，弹出确认 |
| `Ctrl+A` | 全选（选择模式下） | `selectAll()` |
| `Escape` | 退出选择模式 / 清除搜索 / 关闭 AI 面板 | 三级优先级 |
| `Ctrl+D` | 切换暗色/浅色主题 | `ThemeManager.apply_theme(toggle)` |
| `Ctrl+L` | 锁定屏幕 | `show_lock_screen()` |
| `Ctrl+1` | 切换到密码库 | `_on_vault_tab_changed(0)` |
| `Ctrl+2` | 切换到网址库 | `_on_vault_tab_changed(1)` |

### 实施

```python
# 在 MainWindow.setup_ui() 末尾注册
shortcuts = [
    (QKeySequence("Ctrl+F"), self._focus_search),
    (QKeySequence("Ctrl+N"), self.on_add_item),
    (QKeySequence("Delete"), self._delete_current),
    (QKeySequence("Escape"), self._handle_escape),
    # ...
]
for key_seq, slot in shortcuts:
    QShortcut(key_seq, self).activated.connect(slot)
```

---

## 七、ID 类型统一

### 现状

- `_highlight_matched_ids`: `set` of `str`（来自 `{str(m) for m in matched_ids}`）
- `_selected_ids`: `set` of `int`
- `_execute_batch_delete()`: 遍历 `int(id)`
- `highlight_matched_accounts()`: `str(getattr(item, 'id', None)) in self._highlight_matched_ids`

每次对比都需要 `int()` ↔ `str()` 转换，且 LLM 返回的 ID 可能是字符串。

### 方案

1. **内部统一使用 `int`**：`_highlight_matched_ids` 改为 `set` of `int`
2. **在外层统一转换**：`highlight_matched_accounts()` 入口处一次性 `{int(m) for m in matched_ids}`，处理 LLM 可能返回的字符串 ID
3. **比较时不再转换**：`item.id in self._highlight_matched_ids`

---

## 八、异常处理规范化

### 现状

```python
except Exception as e:
    print(f"[Module] Error: {e}")
```

问题：静默吞异常，生产环境用户看不到，排查困难。

### 方案

1. **引入日志模块**：`import logging`，替代 `print()`
   ```python
   logger = logging.getLogger(__name__)
   logger.exception("Failed to delete account %s", account_id)
   ```

2. **分级处理**：
   | 异常类型 | 处理方式 |
   |---------|---------|
   | 数据库操作失败 | 弹出 `QMessageBox.critical()` + 记录日志 |
   | AI 调用超时/失败 | 弹出轻提示（状态栏）+ 记录日志 |
   | 加密/解密失败 | 弹出 `QMessageBox.critical()` + 建议检查密码 |
   | 非关键 UI 更新失败 | 仅记录日志，不打断用户 |

3. **日志输出**：开发环境输出到 console，生产环境写入 `~/.local_password_vault/app.log`，按天轮转

---

## 九、修改主密码后的会话校验

### 现状

用户在设置中修改主密码后，当前已解锁的 session 仍可正常操作。理论上旧密码持有者（若之前解锁后离开）仍可操作加密数据。

### 方案

1. **修改密码时**：生成新的密钥派生盐值（salt），用新密码重新加密所有数据
2. **设置会话版本号**：`AppState` 中维护 `session_version`，每次改密码后递增
3. **操作前校验**：敏感操作（查看密码明文、导出）前检查 `session_version` 是否匹配
4. **不匹配时**：弹出重新验证对话框，要求输入当前主密码

### 实施

1. `CryptoManager` 增加 `change_password(old_pwd, new_pwd)` 方法：用旧密码解密数据密钥 → 用新密码重新加密 → 更新 salt
2. 数据库 `vault_config` 表增加 `session_version` 字段
3. 每次启动/解锁时读取 `session_version` 存入 `AppState`
4. `AccountDialog` / `ExportDialog` 显示密码明文前校验 `session_version`

---

## 实施优先级建议

| 优先级 | 改进项 | 理由 |
|--------|-------|------|
| 🔴 P0 | 滚动位置保持（五） | 当前版本 `_smart_refresh()` 回退 bug，影响体验 |
| 🔴 P0 | ID 类型统一（七） | 当前已有不一致，可能引发隐蔽 bug |
| 🟡 P1 | `_reload_categories()` 优化（四） | 减少无效刷新，改动小收益大 |
| 🟡 P1 | 键盘快捷键（六） | 用户体验提升明显，实现简单 |
| 🟡 P1 | 异常处理（八） | 提高可维护性和问题排查效率 |
| 🟢 P2 | 架构拆分（一） | 大工程，需分步实施，建议在功能稳定后进行 |
| 🟢 P2 | 测试体系（二） | 挂载在架构拆分之后，先有清晰模块边界再写测试 |
| 🔵 P3 | QListWidget → QListView（三） | 性能提升显著但开发成本高，Delegate paint 复杂 |
| 🔵 P3 | 密码会话校验（九） | 安全增强，暂时风险较低可延后 |
