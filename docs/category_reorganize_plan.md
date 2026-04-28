# 分类重组拖拽功能 — 实现计划

## 需求概述
在分类树标题栏新增"重组"按钮，点击后进入重组模式，支持通过拖拽改变分类层级关系。

## 界面设计
- 标题栏新增"重组"按钮，样式与"排序"一致（蓝底白字），位于"排序"和"删除"之间
- 点击"重组"后，按钮变为"✓"，提示"完成"
- 重组模式下，分类树最上方显示特殊条目："📌 将类别拖至此处成为一级类别"
- 所有一级和二级类别显示拖拽手柄 ☰

## 拖拽规则

| 源类别 | 目标位置 | 结果 | 是否允许 |
|---|---|---|---|
| 二级 | "成为一级"区域 | 变为一级（调用 promote_category） | ✅ |
| 二级 | 一级节点上（OnItem） | 变为该一级下的二级 | ✅ |
| 一级（无子类） | 一级节点上（OnItem） | 变为该一级下的二级 | ✅ |
| 一级（有子类） | 一级节点上（OnItem） | 禁止（避免产生三级） | ❌ |
| 任何 | 二级节点上（OnItem） | 禁止（不存在三级） | ❌ |
| 任何 | 节点之间（Above/Below） | 同级排序 | ✅ |
| "全部"或"成为一级" | 任何位置 | 禁止 | ❌ |

## 数据变更逻辑

### 二级 → 一级
- `其他>学习` → `学习`
- 调用已有的 `promote_category`

### 二级 → 其他一级下
- `其他>学习` 拖到 `系统` 下 → `系统>学习`
- 精确匹配更新 `UPDATE SET category='系统>学习' WHERE category='其他>学习'`

### 一级（无子类）→ 其他一级下
- `代码算法` 拖到 `其他` 下 → `其他>代码算法`
- 精确匹配更新

### 同级排序
- 拖到 Above/Below → 只调整顺序，不改变路径
- 保存排序到 category_order

## 涉及文件

### 1. ui/main_window.py
- 标题栏新增 `btn_category_reorganize` 按钮
- 新增 `_category_reorganize_mode` 状态标志
- 新增 `_on_category_reorganize_toggle()` 方法
- 修改 `_reload_categories()`：重组模式下显示特殊条目
- 修改 `CategoryTreeWidget`：
  - 新增 `_reorganize_mode` 标志和 `set_reorganize_mode()`
  - 重写 `dragMoveEvent`：实现重组拖拽规则
  - 重写 `dropEvent`：处理重组释放，计算新路径，弹出确认，更新数据库

### 2. core/database.py
- 新增 `reparent_category(old_path: str, new_path: str) -> int`
- 精确匹配更新 `accounts` 表
- 更新 `category_order` 表：删除 old_path，插入 new_path（复用 sort_index）

### 3. core/url_database.py
- 同上，操作 `urls` 表

### 4. services/account_service.py
- 新增 `reparent_category(old_path: str, new_parent: str) -> bool`
- 根据 old_path 和 new_parent 计算 new_path
- 调用 db.reparent_category

### 5. services/url_service.py
- 同上

## 模式互斥
- 重组模式、排序模式、批量删除模式三者互斥
- 进入任一模式时，自动退出其他模式

## 确认对话框
- 拖拽释放后，弹出确认对话框显示变更预览：
  - `"确定将「{旧路径}」移动到「{新路径}」吗？"`
- 用户确认后才执行数据库更新
