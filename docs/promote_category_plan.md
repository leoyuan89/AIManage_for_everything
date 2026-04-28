# 二级分类升级为一级分类 — 实现计划

## 需求
右键二级分类节点时，增加"⬆️ 升级为一级"选项。
例如：`其他>学习` → `学习`（所有该分类下的条目 category 从 `其他>学习` 改为 `学习`）。

## 冲突处理
如果目标一级分类名（如 `学习`）已存在，提示用户并拒绝升级。

## 涉及文件

### 1. core/database.py
新增 `promote_category(old_path: str) -> bool`：
- 解析 `new_name = old_path.split('>')[1]`
- 检查 `category_order` 表中是否已有 `new_name`
- 更新 `accounts` 表：`UPDATE accounts SET category = ? WHERE category = ?`
- 更新 `category_order` 表：删除 `old_path` 记录，插入 `new_name`（sort_index 复用旧值或给 max+1）
- 返回 True/False

### 2. core/url_database.py
同上，操作 `urls` 表。

### 3. services/account_service.py
新增 `promote_category(self, category_path: str) -> bool`：
- 调用 `self.db.promote_category(category_path)`

### 4. services/url_service.py
同上。

### 5. ui/main_window.py
在 `_on_category_context_menu` 中：
- `is_parent_node == False`（二级节点）时，菜单增加 `action_promote = menu.addAction("⬆️ 升级为一级")`
- 点击后：
  1. `child_name = category.split('>', 1)[1]`
  2. 获取现有所有一级分类名（从 tree_data.keys() 或 get_categories()）
  3. 如果 `child_name` 已存在于一级分类中，警告并返回
  4. 调用 service.promote_category(category)
  5. `_reload_categories()`、`_cache_dirty = True`、刷新列表
