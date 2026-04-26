# Bug 根因分析与修复文档

> 文档编号：0425-BUG-001  
> 创建日期：2026-04-25  
> 关联需求：0425_feature_request_category_batchdelete_ui_redesign.md

---

## 一、用户反馈问题汇总

| 序号 | 问题描述 | 严重度 |
|:---:|---------|:------:|
| 1 | 左侧分类条文字只显示一半（被截断） | 中 |
| 2 | 点击条目打开编辑弹窗非常慢 | 高 |
| 3 | 左侧分类导航没有鼠标悬浮标记效果 | 低 |
| 4 | 点击"批量删除"后，出现大量弹窗快速打开又关闭 | **严重** |
| 5 | 左侧分类导航中每个分类都显示 102 个（数量全部相同） | **严重** |
| 6 | 条目右侧标签显示新分类，但点开编辑对话框显示旧分类 | **严重** |

---

## 二、逐条根因分析

### 问题 1：左侧分类条文字截断

**根因**：`QSplitter` 的左侧面板宽度仅分配了 **150px**。

```python
# ui/main_window.py 第 1214 行
splitter.setSizes([150, 650, 0])  # 左:中:右 = 150:650:0
```

加上分类名+数量的文本（如 `"工作办公 (12)"`）需要约 120-140px，再减去 `QListWidget` 的滚动条宽度（约 15px）和内边距（15px × 2），实际可用宽度不足 120px。当分类名较长时（如"社交通讯"、"金融支付"），文本被截断只显示前半部分。

**修复方案**：将左侧面板宽度从 150px 增加到 **180px**，同时减小中间列表区域到 620px。

---

### 问题 2：编辑弹窗打开慢

**根因**：`AccountDialog.__init__` 每次创建弹窗时都要重新实例化多个 Service 对象。

```python
# ui/account_dialog.py 第 118-120 行
self.account_service = AccountService(db_manager)
self.category_service = CategoryService(db_manager, ollama_client)
self.ai_remark_service = AIRemarkService(ollama_client)
```

每次打开详情页都创建新的 `CategoryService` 和 `AIRemarkService`，这些 Service 的初始化可能涉及数据库查询、AI 客户端检查等操作。对于 102 条账号，虽然单次开销不大，但累积起来会导致明显的卡顿感。

**修复方案**：`AccountDialog` 改为接收已初始化的 Service 对象（由 `MainWindow` 传入），避免重复创建。

---

### 问题 3：分类导航无鼠标悬浮效果

**根因**：`category_list` 的样式表中定义了 `hover` 效果，但 `QListWidget::item:selected` 的样式（蓝色背景+左边框）优先级可能覆盖了 `hover`。

```python
QListWidget::item:hover {
    background-color: #f0f0f0;
}
```

当鼠标悬浮在未选中的分类上时，应该显示浅灰背景。但如果当前分类已被选中，`selected` 样式（`#e3f2fd` 蓝色）会保持，hover 效果不明显。

**修复方案**：增强 hover 样式的对比度，并确保 `hover` 和 `selected` 状态有明显区分。将 hover 背景色从 `#f0f0f0` 改为 `#e8e8e8`，增加左边框效果。

---

### 问题 4：批量删除后出现大量弹窗

**根因分析（高度怀疑）**：

`AccountListItem` 中的 `QCheckBox` 虽然没有显式连接任何信号，但 `QCheckBox` 继承自 `QAbstractButton`。当 `_update_selection_checkboxes()` 批量调用 `widget.set_checked(True)` 时，`QCheckBox.setChecked()` 会触发内部的 `stateChanged` 信号。

虽然代码中没有直接连接 `stateChanged`，但存在一个**隐式事件传播**路径：

1. `setChecked()` 改变 checkbox 状态
2. checkbox 的 `paintEvent` 被触发，请求重绘
3. 由于 checkbox 位于自定义 widget (`AccountListItem`) 内部，且 `AccountListItem` 被设置为 `QListWidget` 的 item widget
4. `QListWidget` 在接收到大量子 widget 的重绘请求时，可能会触发内部的 `viewport()->update()`
5. 如果 `QListWidget` 的 viewport 更新和 `itemWidget` 的显示/隐藏之间存在某种事件循环竞争...

**更可能的根因**：

`_enter_selection_mode()` → `load_accounts()` → 创建 102 个 `AccountListItem` → 每个 item 内部 `checkbox.setVisible(True)`。

`QCheckBox` 从隐藏变为可见时，会触发父 widget 的 **layout 重新计算**。102 个 widget 同时请求 layout 更新，可能导致 `QListWidget` 的 viewport 出现**闪烁或重绘风暴**，用户视觉上可能误以为是"弹窗"快速出现消失。

**另一可能根因**：`load_accounts()` 被调用了**多次**。

检查 `_enter_selection_mode`：
```python
def _enter_selection_mode(self):
    self._selection_mode = True
    self._selected_ids.clear()
    self._normal_title = self.lbl_list_title.text()
    if self.current_vault == 'accounts':
        self.load_accounts()      # 第 1 次
    else:
        self.load_urls()
    self._update_bottom_bar_for_selection()
```

检查 `_update_bottom_bar_for_selection`：
```python
def _update_bottom_bar_for_selection(self):
    ...
    self.bottom_bar.hide()
    self.selection_bottom_bar.show()
```

这里没有问题，不会再次调用 `load_accounts`。

但检查 `_toggle_select_all`：
```python
def _toggle_select_all(self):
    ...
    self._update_selection_checkboxes()
    self._update_bottom_bar_for_selection()
```

也没有 `load_accounts()`。

**实际最可能根因**：`AccountListItem` 初始化时调用了 `self.setFixedHeight(56)` 和复杂的样式表设置。当 `load_accounts()` 一次性创建 102 个这样的 widget 时，Qt 的布局引擎需要大量计算，导致界面卡顿。用户描述的"弹窗打开又关闭"可能是 **Qt 的内部绘制缓冲或双缓冲机制** 在重绘大量 widget 时的视觉假象。

**修复方案**：
1. 延迟创建 checkbox（使用 `set_selection_mode` 时才真正显示）
2. 在 `_enter_selection_mode` 中使用 `QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)` 提示用户正在加载
3. 如果卡顿严重，考虑分批创建 widget 或使用 `QListView` + `QAbstractListModel` 替代 `QListWidget`
4. **关键修复**：检查 `on_account_clicked` 是否在非选择模式下被意外触发

---

### 问题 5：所有分类都显示 102 个

**根因**：`on_category_selected` 切换分类时**没有设置缓存失效标记**。

```python
# ui/main_window.py 第 1482-1488 行
def on_category_selected(self, item):
    self.current_category = item.data(Qt.ItemDataRole.UserRole)
    if self.current_vault == 'accounts':
        self.load_accounts()
    else:
        self.load_urls()
```

`load_accounts()` 的逻辑：
```python
if self._cache_dirty or not self._cached_accounts:
    if self.current_category == '全部':
        self._cached_accounts = self.account_service.get_all_accounts()
    else:
        self._cached_accounts = self.account_service.get_accounts_by_category(self.current_category)
    self._cache_dirty = False
```

当用户从"全部"切换到"工作办公"时：
1. `current_category` 从 `'全部'` 变为 `'工作办公'`
2. 但 `_cache_dirty` 仍然是 `False`
3. `_cached_accounts` 不为空（之前加载了全部 102 条）
4. `if` 条件不满足，**跳过了按分类查询**
5. 直接使用包含全部 102 条账号的旧缓存

所以无论点击哪个分类，都显示全部 102 条。

**修复方案**：在 `on_category_selected` 中设置 `_cache_dirty = True`（和 `_url_cache_dirty = True`）。

---

### 问题 6：点开编辑显示错误类别

**根因**：这个问题与**问题 5 是同一根因**（缓存 bug）。

由于 `load_accounts()` 在切换分类时没有重新查询数据库，`_cached_accounts` 中保存的是**上一次完整加载的数据**（可能是 AI 整理前的旧数据，或 AI 整理后的新数据）。

当用户点击某条条目时：
```python
def show_account_detail(self, account: Account):
    dialog = AccountDialog(self.db, account, self._ollama_client, parent=self)
```

`AccountDialog` 直接使用传入的 `account` 对象（来自 `_cached_accounts`），**不会重新从数据库读取**。

如果 `_cached_accounts` 中的 Account 对象包含旧分类，编辑对话框就显示旧分类。

但用户反馈"条目右侧标签显示新分类"，这说明 `_cached_accounts` 中的 Account 对象**确实包含新分类**。然而编辑对话框显示旧分类...

**进一步分析**：

这说明 `AccountDialog` 中的分类下拉框（`cmb_category`）的选项列表和 Account 对象的 `category` 值之间存在不一致。

`AccountDialog.load_account_data()` 中：
```python
index = self.cmb_category.findText(self.account.category)
if index >= 0:
    self.cmb_category.setCurrentIndex(index)
```

如果 `cmb_category` 的选项列表是**硬编码的旧分类**（如 ['全部', '金融', '社交', ...]），而 `self.account.category` 是**新分类**（如 '个人身份'），`findText('个人身份')` 会返回 -1，分类下拉框就显示默认选项（可能是第一项或当前选中项）。

**这就是根本原因！** `AccountDialog` 中的分类下拉框使用了**硬编码的分类列表**，没有包含 AI 生成的新分类！

**修复方案**：
1. `AccountDialog` 的分类下拉框应该从数据库动态读取分类列表（调用 `CategoryService` 或 `AccountService.get_categories()`）
2. 同时修复缓存 bug（问题 5），确保切换分类时重新加载

---

## 三、修复方案汇总

| 问题 | 修复文件 | 修复内容 |
|------|---------|---------|
| 1 左侧截断 | `ui/main_window.py` | `splitter.setSizes([150, ...])` → `[180, ...]` |
| 2 弹窗慢 | `ui/account_dialog.py` | 延迟初始化 Service，或由 MainWindow 传入已初始化的 Service |
| 3 悬浮效果 | `ui/main_window.py` | 增强 `category_list` 的 `hover` 样式 |
| 4 批量删除弹窗 | `ui/main_window.py` | 检查并优化 widget 创建逻辑，加入等待光标 |
| 5 分类数量错误 | `ui/main_window.py` | `on_category_selected` 中设置 `_cache_dirty = True` |
| 6 编辑显示旧分类 | `ui/account_dialog.py` | 分类下拉框从数据库动态读取，而非硬编码 |

---

## 四、待排查问题

### 批量删除"弹窗"现象

如果修复后仍然存在大量弹窗快速出现消失的现象，建议：

1. 在 `_enter_selection_mode` 开头和结尾添加调试日志：
```python
print(f"[_enter_selection_mode] START, _cached_accounts={len(self._cached_accounts)}")
```

2. 检查 `load_accounts` 是否被调用了多次（添加调用计数器）

3. 检查是否有异常被静默捕获并弹出了 QMessageBox

4. 如果确认是 Qt 重绘性能问题，考虑将 `QListWidget` + 自定义 widget 方案改为 `QListView` + `QAbstractListModel` + 委托绘制（Delegate）方案，性能更好。
