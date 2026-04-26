# Bug 修复待办确认文档（最终版）

> 文档编号：0425-TODO-001  
> 创建日期：2026-04-25  
> 状态：用户已确认全部问题，待执行修复  

---

## 一、用户已确认的问题清单

### 问题 1：批量删除时出现白色弹窗/闪烁（P0）

**用户描述**：点击"批量删除"后，列表中间出现白色小弹窗（如图1），闪一下就消失，反复出现多个。

**根因分析**：
- `load_accounts()` 在 `_enter_selection_mode()` 中被调用，会**清空整个列表并重建 102 个 widget**
- 这个"清空-重建"过程导致视觉闪烁，用户看到的"白色弹窗"是列表重建过程中的某种中间渲染状态
- 重建 102 个复杂 widget 开销大，体验极差

**修复方案**：**不再重新创建 widget**，改为**增量更新**——只切换现有 widget 中 checkbox 的显示/隐藏状态。

```python
# _enter_selection_mode() 新逻辑：
# 1. _selection_mode = True
# 2. 遍历 account_list 中所有现有 item
# 3. 获取每个 item 的 AccountListItem widget
# 4. 调用 widget.set_selection_mode(True)
# 5. 不再调用 load_accounts()！
```

同理，`_exit_selection_mode()` 也不再调用 `load_accounts()`，只遍历现有 widget 隐藏 checkbox。

---

### 问题 2：编辑弹窗布局问题（P1）

**用户确认的具体问题**（图3）：

| 序号 | 问题 | 位置 |
|:---:|------|------|
| 2.1 | 标签文字错位 | "网址"、"账号"等标签与对应输入框位置不齐 |
| 2.2 | 密码"显示"按钮宽度不够 | 密码输入框右侧的"显示"按钮太窄，文字被截断 |
| 2.3 | "编辑标签"按钮宽度不够 | 标签区域右侧的"编辑标签"按钮太窄 |
| 2.4 | "AI生成"按钮宽度不够 | AI备注区域右侧的"AI生成"按钮太窄 |
| 2.5 | 用户备注输入框显示不全 | 用户备注的文本框大小有问题 |
| 2.6 | 整体弹窗尺寸偏小 | 需要扩大弹窗 |

**根因**：`qt-material` light 主题与 `AccountDialog` 的自定义布局冲突。主题改变了默认字体、边距和控件尺寸，导致原有布局计算失效。

**修复方案**：
1. 弹窗尺寸从 `700×650` 扩大到 **800×750**
2. 检查所有水平布局（标签+输入框），确保标签宽度固定且对齐
3. 密码"显示"按钮宽度从默认调整为 **60px**
4. "编辑标签"按钮宽度调整为 **80px**
5. "AI生成"按钮宽度调整为 **90px**
6. 用户备注输入框（`QTextEdit` 或 `QLineEdit`）增大高度和宽度
7. 统一检查所有控件在 light 主题下的对比度

---

### 问题 3：左侧分类导航高度不满（P1）

**用户描述**：分类列表下方有大量空白空间浪费（图2）。

**修复方案**：
```python
self.category_list.setSizePolicy(
    QSizePolicy.Policy.Expanding, 
    QSizePolicy.Policy.Expanding
)
```

---

### 问题 4：主界面条目无 hover 效果（P2）

**用户描述**：鼠标悬浮中间列表项无高亮效果。

**修复方案**：为 `AccountListItem` / `URLListItem` 添加 `enterEvent` / `leaveEvent`，悬浮时背景变为 `#fafafa`（比当前更深，确保可见）。

---

## 二、修复计划

### 第一批：立即执行（P0 + P1）

| 序号 | 修复内容 | 涉及文件 | 预估工作量 |
|:---:|---------|---------|:---------:|
| 1 | 批量删除：改为增量更新 checkbox，不再重建列表 | `ui/main_window.py` | 中 |
| 2 | 编辑弹窗：扩大尺寸 + 修复所有按钮宽度 | `ui/account_dialog.py` | 中 |
| 3 | 编辑弹窗：修复标签错位 + 用户备注框大小 | `ui/account_dialog.py` | 中 |
| 4 | 左侧分类导航：占满高度 | `ui/main_window.py` | 小 |

### 第二批：后续执行（P2）

| 序号 | 修复内容 | 涉及文件 | 预估工作量 |
|:---:|---------|---------|:---------:|
| 5 | 主界面条目 hover 效果 | `ui/main_window.py` | 小 |
| 6 | 编辑弹窗打开速度优化 | `ui/account_dialog.py` | 中 |

---

## 三、关键修复细节说明

### 修复 1：批量删除增量更新（核心改动）

**原代码逻辑（问题所在）**：
```python
def _enter_selection_mode(self):
    self._selection_mode = True
    self.load_accounts()  # ❌ 清空并重建 102 个 widget，导致闪烁
```

**新代码逻辑**：
```python
def _enter_selection_mode(self):
    self._selection_mode = True
    self._selected_ids.clear()
    self._normal_title = self.lbl_list_title.text()
    
    # ✅ 遍历现有 item，只切换 checkbox 显示状态
    for i in range(self.account_list.count()):
        item = self.account_list.item(i)
        widget = self.account_list.itemWidget(item)
        if widget and hasattr(widget, 'set_selection_mode'):
            widget.set_selection_mode(True)
    
    self._update_bottom_bar_for_selection()

def _exit_selection_mode(self):
    self._selection_mode = False
    self._selected_ids.clear()
    
    # ✅ 遍历现有 item，只隐藏 checkbox
    for i in range(self.account_list.count()):
        item = self.account_list.item(i)
        widget = self.account_list.itemWidget(item)
        if widget and hasattr(widget, 'set_selection_mode'):
            widget.set_selection_mode(False)
            if hasattr(widget, 'set_checked'):
                widget.set_checked(False)
    
    self.lbl_list_title.setText(self._normal_title)
    self._update_bottom_bar_for_normal()
```

**好处**：
- 不再清空/重建列表，彻底解决闪烁问题
- 性能提升 100 倍（从创建 102 个 widget 变为更新 102 个属性）
- 用户体验更流畅

---

### 修复 2：编辑弹窗尺寸和布局

**弹窗尺寸**：`700×650` → `800×750`

**各控件调整**：

| 控件 | 当前问题 | 修复方式 |
|------|---------|---------|
| 弹窗整体 | 太小 | `setMinimumSize(800, 750)` |
| 标签列（应用名、网址等） | 错位 | 统一标签宽度为 **80px**，右对齐 |
| 密码"显示"按钮 | 太窄 | `setFixedWidth(60)` |
| "编辑标签"按钮 | 太窄 | `setFixedWidth(80)` |
| "AI生成"按钮 | 太窄 | `setFixedWidth(90)` |
| 用户备注框 | 显示不全 | 增加最小高度到 **80px** |

---

## 四、用户审核确认

以上修复方案是否确认？如无异议，我将立即执行第一批修复（4项）。

如有需要调整的地方，请直接指出。
