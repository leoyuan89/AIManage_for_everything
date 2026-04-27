# Debug Journal — 问题排查记录

> 用途：记录项目中遇到的 Bug/问题、排查过程、根因与解决方案，供后续参考。
> 格式：按时间倒序，每次追加一条记录。

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
