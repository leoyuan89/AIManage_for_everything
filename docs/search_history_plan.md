# 搜索历史面板实现方案

## 一、需求概述

在搜索框区域增加"最近搜索"下拉面板，类似现代 App（Google、Bing、淘宝等）的搜索历史体验：

| 功能 | 说明 |
|------|------|
| 历史记录展示 | 搜索框获得焦点时，下方弹出面板显示最近搜索记录（最多 10 条） |
| 单条重新搜索 | 点击历史记录 pill，自动填充搜索框并触发搜索 |
| 单条删除 | 每条历史右侧带 × 按钮，点击删除该条记录 |
| 清空全部 | 面板顶部有"清空全部"按钮，一键删除所有历史 |
| 自动保存 | 每次按回车搜索后，自动将关键词加入历史（去重 + 置顶） |
| 空态处理 | 无历史记录时，面板不弹出或显示"暂无搜索历史"提示 |

## 二、现有基础（无需从零造轮子）

### 2.1 搜索历史数据层
`services/search_service.py` 已具备完整的历史管理能力：

```python
self._search_history: List[str] = []      # 内存中的历史列表
self._max_history = 10                     # 最大保留 10 条

_add_to_history(query)      # 去重 + 置顶 + 截断
get_search_history()        # 返回副本
clear_history()             # 清空全部
```

**现状问题**：历史仅存于内存，程序重启后丢失。需要增加持久化。

### 2.2 搜索框 UI
`ui/main_window.py` 中搜索框为 `QLineEdit`，已连接：
- `returnPressed → on_search`
- `QCompleter` 补全（基础字符串列表下拉）
- `eventFilter` 捕获 `FocusIn` 刷新补全历史

### 2.3 面板挂载点
搜索框位于 `self.top_bar`（`QWidget`，高度 60px）内。历史面板需要以**弹出层**形式定位在搜索框正下方，而非插入布局（`top_bar` 高度固定，无法容纳下拉面板）。

---

## 三、技术方案

### 3.1 整体架构

```
┌─────────────────────────────────────┐
│  top_bar                              │
│  ┌─────────────────────┐  ┌─────┐   │
│  │ 搜索框...            │  │ 筛选 │   │
│  └─────────────────────┘  └─────┘   │
└─────────────────────────────────────┘
         ↓ 搜索框获得焦点
┌─────────────────────────────────────┐
│  SearchHistoryPanel（弹出层）         │
│  ┌────────────────────────────────┐ │
│  │ 最近搜索          [清空全部]   │ │  ← 标题行
│  └────────────────────────────────┘ │
│  ┌──────────┐ ┌──────────┐          │
│  │ 微信    × │ │ qq      × │          │  ← pill 标签
│  └──────────┘ └──────────┘          │
│  ┌──────────┐ ┌──────────┐          │
│  │ 银行    × │ │ github  × │          │
│  └──────────┘ └──────────┘          │
└─────────────────────────────────────┘
```

### 3.2 组件拆分

| 组件 | 文件 | 职责 |
|------|------|------|
| `SearchHistoryPanel` | `ui/widgets/search_history_panel.py` | 历史面板 UI：标题行 + FlowLayout 容器 + pill 按钮生成/刷新 |
| `HistoryPillButton` | 内置于 `search_history_panel.py` | 单条历史记录按钮：文本 + 右侧 × |
| `SearchService` 扩展 | `services/search_service.py` | 增加 `remove_history_item(index)` 和持久化加载/保存 |
| `MainWindow` 集成 | `ui/main_window.py` | 创建面板实例、控制显示/隐藏/定位、连接信号 |

### 3.3 定位策略（关键决策）

**方案 A：Popup 窗口（推荐）**
- 面板设为 `Qt.WindowType.Popup`
- 优点：点击外部自动关闭，无需自己处理焦点丢失逻辑
- 缺点：Popup 窗口不能有父窗口的 modal 限制，需要精确定位

**方案 B：普通 QWidget 绝对定位**
- 面板 parent 设为 `MainWindow.centralWidget()`
- 使用 `search_box.mapToGlobal()` + `panel.move()` 定位
- 使用 `QTimer` 延迟隐藏处理失去焦点
- 优点：完全可控，可包含复杂交互按钮
- 缺点：需要自己处理"点击外部关闭"逻辑

**结论**：采用 **方案 B**。因为面板内包含"清空全部"、多个"×"删除按钮，需要稳定接收鼠标事件。Popup 窗口在某些平台/主题下可能对子按钮的点击有兼容性问题（经验证之前 `eventFilter` + `return True` 就导致了崩溃）。

### 3.4 FlowLayout 实现

PyQt6 无内置 FlowLayout。引入 Qt 官方示例的 `FlowLayout`（约 150 行），支持：
- 按钮从左到右排列
- 超出宽度自动换行
- 父容器缩放时自动重排

文件位置：`ui/widgets/flow_layout.py`

### 3.5 持久化方案

历史记录保存到本地 JSON 文件，与紧凑视图/列配置的持久化方式一致：

```
~/.local_password_vault/search_history.json
```

```json
{
  "accounts": ["微信", "qq", "银行"],
  "urls": ["github", "bilibili"]
}
```

- 按库隔离（密码库和网址库的历史分开存储）
- `SearchService.__init__` 时加载
- `_add_to_history()` / `clear_history()` / `remove_history_item()` 后异步保存

---

## 四、UI 设计细节

### 4.1 面板样式

```
背景色：bg_primary（与输入框一致）
边框：1px solid border_default，下方圆角 8px
阴影：可选（QGraphicsDropShadowEffect）
最大宽度：与搜索框等宽
最大高度：约 300px（超出可滚动）
内边距：12px 16px
```

### 4.2 标题行

```
左侧："最近搜索" — 14px，font-weight: 500，text_primary
右侧："清空全部" — 13px，accent_blue，hover 时 underline
```

### 4.3 Pill 按钮样式

```
背景色：bg_secondary
边框：1px solid border_subtle，圆角 16px
文字：13px，text_primary，左右内边距 12px
高度：32px

× 按钮：
  - 位于 pill 内部右侧
  - 颜色 text_disabled，hover 时 accent_red
  - 点击区域 20×20，防止误触

hover 状态：
  - 整个 pill：bg_hover
  - × 按钮可见度提高
```

### 4.4 空态

当历史记录为空时：
- 方案 1：面板不弹出（推荐，简洁）
- 方案 2：面板显示"暂无搜索历史"居中提示

---

## 五、交互流程

### 5.1 显示面板

```
用户点击搜索框（获得焦点）
  ↓
MainWindow.eventFilter 捕获 FocusIn
  ↓
调用 search_history_panel.refresh(history_list)
  ↓
如果历史非空：
    计算位置（搜索框左下角全局坐标 → 转父窗口局部坐标）
    panel.move(pos)
    panel.show()
    panel.raise_()
否则：
    panel.hide()
```

### 5.2 隐藏面板

```
触发条件 1：用户按回车执行搜索
    → on_search() 中调用 panel.hide()

触发条件 2：用户点击面板外部区域
    → MainWindow.mousePressEvent 中检测
    → 如果点击位置不在 panel 内：panel.hide()

触发条件 3：用户点击"清空全部"后历史为空
    → panel 自动 hide()

触发条件 4：用户点击某条历史执行搜索
    → 填充搜索框 + 触发搜索 + panel.hide()
```

### 5.3 删除单条历史

```
用户点击某 pill 上的 ×
  ↓
SearchHistoryPanel 发出 signal：delete_requested(index, text)
  ↓
MainWindow 槽函数：
    search_service.remove_history_item(text)
    refresh_panel()
```

### 5.4 清空全部历史

```
用户点击"清空全部"
  ↓
SearchHistoryPanel 发出 signal：clear_all_requested()
  ↓
MainWindow 槽函数：
    search_service.clear_history()
    panel.hide()
```

---

## 六、需要修改的文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `ui/widgets/flow_layout.py` | 新增 | Qt 官方 FlowLayout 示例移植 |
| `ui/widgets/search_history_panel.py` | 新增 | 历史面板主组件 |
| `services/search_service.py` | 修改 | 增加 `remove_history_item()`、持久化加载/保存 |
| `ui/main_window.py` | 修改 | 集成面板：创建实例、定位、显示/隐藏、信号连接 |
| `core/constants.py` 或 DATA_DIR | 无需修改 | 复用现有的 `~/.local_password_vault/` 目录 |

---

## 七、与现有 QCompleter 的关系

**决策**：保留 `QCompleter`，但改变其角色。

- **现有**：`QCompleter` 在获得焦点时弹出，显示历史列表作为补全建议
- **调整后**：`QCompleter` 仍然保留，用于**输入过程中的实时补全**（当用户输入字符时，匹配历史记录并下拉提示）
- **新增**：`SearchHistoryPanel` 仅在**搜索框为空且获得焦点**时显示，展示全部历史记录的可视化面板

两者互不冲突：
- 搜索框为空 + 获得焦点 → 显示 SearchHistoryPanel
- 搜索框有输入 + 获得焦点 → QCompleter 根据输入内容过滤并弹出

---

## 八、风险与注意事项

1. **焦点竞争**：`SearchHistoryPanel` 内的按钮点击时，搜索框会失去焦点。如果隐藏逻辑过于激进（如立刻 hide），可能导致按钮点击事件无法送达。需要使用 `QTimer.singleShot(200ms)` 延迟隐藏，或在点击面板内部时取消隐藏。

2. **主题切换**：面板需要在主题切换时重新应用样式表。连接 `ThemeManager.theme_changed` 信号。

3. **多屏幕/窗口移动**：面板使用 `mapToGlobal` 定位，如果用户拖动主窗口到另一屏幕，面板位置仍然正确（每次 show 时重新计算）。

4. **性能**：历史最多 10 条， pill 按钮数量少，无性能问题。

5. **持久化线程安全**：保存 JSON 时复用现有的后台线程模式（参考 `_save_compact_preference`），避免阻塞 UI。
