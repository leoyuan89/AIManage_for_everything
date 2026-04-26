# 0426 二级分类（路径分隔符）详细实施规划

## 一、版本与目标

- **实施日期**：2026-04-26
- **目标**：将现有扁平分类升级为二级分类体系，使用 `>` 作为层级分隔符
- **约束**：
  - 最多支持二级（`主类>子类`），禁止三级
  - 数据零表结构变更，仅扩展 `category` 字段的语义
  - 并列概念用 `与` 替代 `/`
  - 分类名禁止包含 `/`、`>`、`·`

---

## 二、核心机制定义

| 符号/规则 | 语义 | 示例 |
|---|---|---|
| `>` | 层级分隔符（仅允许出现一次） | `工作>开发工具` |
| `与` | 并列概念连接词 | `金融与支付` |
| `/` | **禁止**出现在分类名中 | — |
| `·` | **禁止**出现在分类名中（旧数据清洗残留） | — |
| 一级分类 | 不含 `>` 的 category 值 | `学术与研究` |
| 二级分类 | 含一个 `>` 的 category 值 | `工作>开发工具` |

---

## 三、数据迁移（清洗脚本）

### 3.1 脚本信息

- **文件**：`scripts/migrate_category_separator.py`（新建）
- **执行时机**：代码升级前，**必须先执行**
- **作用范围**：用户数据目录下的生产数据库

### 3.2 执行步骤

1. **备份**：复制 `~/.local_password_vault/vault.db` 和 `urls.db` 为 `.backup.{timestamp}`
2. **扫描变更**：
   ```sql
   SELECT DISTINCT category FROM accounts WHERE category LIKE '%/%';
   SELECT DISTINCT category FROM urls WHERE category LIKE '%/%';
   ```
3. **替换**：将所有 `/` 替换为 `与`
   ```sql
   UPDATE accounts SET category = REPLACE(category, '/', '与') WHERE category LIKE '%/%';
   UPDATE urls SET category = REPLACE(category, '/', '与') WHERE category LIKE '%/%';
   ```
4. **清理缓存**：
   ```sql
   DELETE FROM category_cache;
   ```
5. **输出日志**：打印所有被修改的旧→新映射，供人工复核

### 3.3 异常处理

- 若替换后产生重复分类（如已有 `金融与支付` 和 `金融/支付`），合并数量并去重
- 脚本失败时不得修改原数据库，通过事务（BEGIN / COMMIT / ROLLBACK）保证原子性

---

## 四、改动总览

| 优先级 | 模块 | 涉及文件 | 改动目标 |
|---|---|---|---|
| P0 | 基础工具 | `core/category_utils.py`（新建） | 路径解析、校验、树构建等通用函数 |
| P0 | 数据清洗 | `scripts/migrate_category_separator.py`（新建） | 一次性替换旧数据中的 `/` |
| P0 | AI Prompt | `services/ai_tools.py` | 注入分类树上下文、约束输出格式为 `主类>子类` |
| P0 | AI Prompt | `services/batch_add_processor.py` | 同步更新分类示例和约束说明 |
| P1 | 分类服务 | `services/category_service.py` | 规则匹配返回完整路径；缓存兼容新格式 |
| P1 | 数据服务 | `services/account_service.py` | `get_by_category` 支持前缀匹配；新增 `get_category_tree` |
| P1 | 数据服务 | `services/url_service.py` | 同 `account_service.py` |
| P1 | 主界面 | `ui/main_window.py` | 侧边栏从 `QListWidget` 改 `QTreeWidget`，解析 `>` 建树 |
| P2 | 编辑弹窗 | `ui/account_dialog.py` | 分类选择器改为级联下拉（主类+子类） |
| P2 | 编辑弹窗 | `ui/url_dialog.py` | 同 `account_dialog.py` |
| P2 | AI 分类 | `ui/ai_classify_dialog.py` | 预览表格展示层级路径 |
| P2 | AI 助手 | `services/ai_assistant_service.py` | 分类相关工具（filter/reorganize/add）支持路径格式 |
| P2 | AI 助手 | `services/ai_classification_service.py` | 批量归类时注入分类树、解析路径 |
| P3 | 导出 | `services/export_service.py` | HTML 书签按 `>` 生成嵌套 `<H3>` 文件夹结构 |
| P3 | 导入 | `services/import_service.py` | HTML 书签导入时嵌套 `<H3>` 解析为 `>` 路径 |
| P3 | 导入导出 UI | `ui/export_dialog.py` | 分类选择器展示层级结构 |
| P3 | 导入导出 UI | `ui/import_dialog.py` | 分类映射支持层级展示 |
| P3 | 搜索 | `services/search_service.py` | 分类筛选支持前缀匹配 |

---

## 五、分模块详细实现

### 5.1 core/category_utils.py（新建）

**目标**：为全项目提供统一的路径解析、校验、树构建工具，避免各模块重复实现。

**接口定义**：

```python
def parse_category_path(category: str) -> tuple[str, Optional[str]]:
    """
    解析分类路径。
    输入 "工作>开发工具" → ("工作", "开发工具")
    输入 "学术与研究"   → ("学术与研究", None)
    输入 "A>B>C"       → 抛出 ValueError（禁止三级）
    """

def validate_category_name(name: str) -> bool:
    """
    校验单级分类名是否合法。
    禁止包含 '/'> '·' 以及空白字符首尾。
    """

def format_category_path(parent: str, child: Optional[str] = None) -> str:
    """
    格式化路径。
    ("工作", "开发工具") → "工作>开发工具"
    ("学术与研究", None) → "学术与研究"
    """

def build_category_tree(categories: List[str]) -> dict:
    """
    将扁平分类列表构建为树形字典。
    
    输入：["工作", "工作>开发工具", "娱乐>游戏", "学术与研究"]
    输出：{
        "工作": {"children": {"开发工具"}, "has_direct_items": True},
        "娱乐": {"children": {"游戏"}, "has_direct_items": False},
        "学术与研究": {"children": set(), "has_direct_items": True}
    }
    """

def get_prefix_matcher(category: str) -> Callable[[str], bool]:
    """
    返回一个匹配函数，用于判断某条目的分类是否属于当前选中节点。
    选中 "工作" → 匹配 "工作" 和 "工作>开发工具"
    选中 "工作>开发工具" → 仅精确匹配
    """
```

**关联模块**：被 `services/account_service.py`、`services/url_service.py`、`ui/main_window.py`、`services/export_service.py`、`services/import_service.py` 等引用。

**注意事项**：
- 该模块为**纯工具函数**，无状态，不依赖数据库
- 所有涉及 `>` 的分割逻辑必须集中在此，禁止其他文件硬编码 `split('>')`

---

### 5.2 scripts/migrate_category_separator.py（新建）

**目标**：安全、原子化地完成旧数据迁移。

**实现细节**：

```python
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

def migrate():
    data_dir = Path.home() / '.local_password_vault'
    for db_name in ['vault.db', 'urls.db']:
        db_path = data_dir / db_name
        if not db_path.exists():
            continue
        
        # 1. 备份
        backup_path = db_path.with_suffix(f'.db.backup.{datetime.now():%Y%m%d_%H%M%S}')
        shutil.copy2(db_path, backup_path)
        
        conn = sqlite3.connect(db_path)
        try:
            conn.execute('BEGIN TRANSACTION')
            
            # 2. 扫描并记录变更
            cursor = conn.execute(
                "SELECT DISTINCT category FROM accounts WHERE category LIKE '%/%'"
            )
            changes = cursor.fetchall()
            
            # 3. 替换
            conn.execute(
                "UPDATE accounts SET category = REPLACE(category, '/', '与') "
                "WHERE category LIKE '%/%'"
            )
            # urls 表同理...
            
            # 4. 处理替换后的重复（如已有 "金融与支付" 和替换后的 "金融与支付"）
            # TODO: 合并逻辑
            
            # 5. 清理缓存
            conn.execute("DELETE FROM category_cache")
            
            conn.commit()
            print(f'[{db_name}] 迁移完成，变更记录：{changes}')
            
        except Exception as e:
            conn.rollback()
            print(f'[{db_name}] 迁移失败，已回滚：{e}')
            raise
        finally:
            conn.close()
```

**关联模块**：独立脚本，不引用业务代码，仅操作 SQLite。

**注意事项**：
- 必须先在测试库验证后再执行生产库
- 输出变更日志供用户人工确认

---

### 5.3 services/ai_tools.py

**目标**：让 AI 理解并输出 `主类>子类` 格式的分类路径。

**改动点 1：分类 Prompt 模板（约 line 262 附近）**

原 Prompt 中分类相关描述（如 `社交/金融/邮箱/游戏/工作/其他`）需全部替换。

新 Prompt 结构：
```
你是一名密码管理软件的分类专家。

【当前分类体系】（动态注入）
{category_tree_text}

【输出规则】
1. 输出格式必须是 `主类>子类`，最多二级。例如：`工作>开发工具`、`娱乐>游戏`
2. 如果某个条目只属于一个大类、不需要细分，可只输出主类，如 `学术与研究`
3. 优先匹配【当前分类体系】中已有的路径
4. 如需新建子类，确保主类已存在于体系中；如需新建主类，直接输出主类名
5. 分类名禁止包含 `/`、`>`、`·` 三个符号
6. 并列概念用"与"连接，如 `金融与支付`、`工具与系统`
7. 禁止输出三级及以上路径（如 `A>B>C` 是非法的）

请直接输出分类路径，不要解释。
```

**动态注入实现**：
- 在调用 AI 分类前，先通过 `CategoryService.get_all_categories()` 获取当前所有分类
- 用 `core/category_utils.build_category_tree()` 构建树
- 将树格式化为文本注入 Prompt

**改动点 2：输出后校验（新增函数）**

```python
def sanitize_ai_category(ai_output: str, existing_categories: List[str]) -> str:
    """
    校验并修正 AI 输出的分类路径。
    """
    # 1. 去除首尾空白
    cleaned = ai_output.strip()
    
    # 2. 检查非法字符
    if any(c in cleaned for c in ['/', '·']):
        # 替换为 '-'
        cleaned = cleaned.replace('/', '-').replace('·', '-')
    
    # 3. 检查是否超过二级
    if cleaned.count('>') > 1:
        # 截断为二级
        parts = cleaned.split('>')
        cleaned = f"{parts[0]}>{parts[1]}"
    
    # 4. 检查 '> ' 或 ' >' 等不规范格式
    cleaned = '>'.join(p.strip() for p in cleaned.split('>'))
    
    return cleaned
```

**关联模块**：
- 依赖 `core/category_utils` 的 `build_category_tree`
- 被 `services/ai_classification_service.py`、`services/ai_assistant_service.py`、`services/batch_add_processor.py` 调用

**注意事项**：
- 分类树注入会增加 Prompt 长度，需关注 token 消耗（gemma4:4b 上下文够大，一般没问题）
- 如果分类数量极多（>50 个），可只注入一级分类列表，不展开子类

---

### 5.4 services/batch_add_processor.py

**目标**：批量添加的 Prompt 示例同步支持新格式。

**改动点**：

line 104 和 line 131 附近，JSON 示例中的 `category` 字段注释和示例值：

原：
```json
"category": "分类（可选，如金融/社交/工作等）"
```

改为：
```json
"category": "分类路径（可选，如 工作>开发工具、金融与支付、学术与研究）"
```

**关联模块**：被 `ui/batch_add_...` 调用，改动量极小。

---

### 5.5 services/category_service.py

**目标**：规则匹配和缓存机制兼容新格式。

**改动点 1：`_rule_based_categorize`**

当前返回 `Optional[str]`（单级分类名），现在需返回完整路径。

```python
def _rule_based_categorize(self, app_name: str, url: str = "") -> Optional[str]:
    # ... 原有规则匹配逻辑 ...
    
    # 原返回：return '工作'
    # 新返回：return '工作>开发工具'  或  '工作'
    
    # 具体规则细化：
    if 'github' in app_lower or 'gitlab' in app_lower:
        return '工作>开发工具'
    if 'figma' in app_lower or 'sketch' in app_lower:
        return '工作>设计'
    # 无法细分的返回一级
    if '飞书' in app_lower or '钉钉' in app_lower:
        return '工作'
```

**改动点 2：`get_all_categories`**

该方法当前返回扁平列表，**保持现状**。它返回的字符串列表中可能含 `>`，这是正常且符合预期的。

**改动点 3：`cache_category` / `get_cached_category`**

缓存的键值对格式不变：
- key: 应用名哈希
- value: `工作>开发工具`（完整路径）

无需改动，但需确认缓存表字段长度足够（通常 `TEXT` 无限制）。

**关联模块**：
- 被 `services/account_service.py`（间接通过 AI 分类）调用
- 依赖 `core/category_utils.parse_category_path` 做路径解析（如果需要）

---

### 5.6 services/account_service.py & services/url_service.py

**目标**：分类查询支持「前缀匹配」和「树形结构获取」。

#### 5.6.1 新增方法 `get_category_tree()`

```python
def get_category_tree(self) -> dict:
    """
    获取分类树，用于 UI 级联选择和 AI 分类树注入。
    """
    from core.category_utils import build_category_tree
    cats = self.get_categories()
    # 过滤掉 '全部'
    return build_category_tree([c for c in cats if c != '全部'])
```

#### 5.6.2 修改 `get_accounts_by_category()`（关键）

```python
def get_accounts_by_category(self, category: str) -> List[Account]:
    """
    按分类查询账号。
    如果 category 不含 '>'，视为父节点，返回该父节点下所有条目（含直接条目和子类条目）。
    如果含 '>'，精确匹配。
    """
    all_accounts = self.get_all_accounts()
    
    if '>' not in category:
        # 父节点：匹配精确等于，或以 "category>" 开头
        return [a for a in all_accounts 
                if a.category == category or a.category.startswith(f"{category}>")]
    else:
        # 子节点：精确匹配
        return [a for a in all_accounts if a.category == category]
```

**说明**：
- 当前 `get_all_accounts()` 返回的是 `Account` 对象列表（内存中过滤）
- 如果未来数据量大，可改为 SQL 层过滤：`WHERE category = ? OR category LIKE ?||'>%'`
- 但目前保持服务层过滤，侵入性最小

**关联模块**：
- `get_category_tree()` 被 `ui/account_dialog.py`、`ui/main_window.py`、`services/ai_tools.py` 调用
- `get_accounts_by_category()` 被 `ui/main_window.py`、`services/search_service.py` 调用

---

### 5.7 ui/main_window.py（改动最大）

**目标**：分类侧边栏从扁平列表升级为树形结构。

#### 5.7.1 控件替换

将分类侧边栏从 `QListWidget` 改为 `QTreeWidget`：

```python
# 原
self.category_list = QListWidget()

# 新
self.category_tree = QTreeWidget()
self.category_tree.setHeaderHidden(True)
self.category_tree.setColumnCount(1)
```

#### 5.7.2 构建树形数据（`_refresh_category_sidebar`）

```python
def _refresh_category_sidebar(self):
    self.category_tree.clear()
    
    # 获取当前模式的分类树
    if self.current_vault_type == 'accounts':
        tree_data = self.account_service.get_category_tree()
    else:
        tree_data = self.url_service.get_category_tree()
    
    # 添加"全部"节点
    root_all = QTreeWidgetItem(self.category_tree)
    root_all.setText(0, f"全部 ({self._get_total_count()})")
    root_all.setData(0, Qt.ItemDataRole.UserRole, "全部")
    
    # 添加一级节点
    for parent_name, info in sorted(tree_data.items()):
        # 计算该父节点下的总条目数（含子类）
        count = self._get_category_count(parent_name)
        
        parent_item = QTreeWidgetItem(self.category_tree)
        parent_item.setText(0, f"{parent_name} ({count})")
        parent_item.setData(0, Qt.ItemDataRole.UserRole, parent_name)
        
        # 如果有子类，添加子节点
        for child_name in sorted(info['children']):
            full_path = f"{parent_name}>{child_name}"
            child_count = self._get_category_count(full_path)
            
            child_item = QTreeWidgetItem(parent_item)
            child_item.setText(0, f"{child_name} ({child_count})")
            child_item.setData(0, Qt.ItemDataRole.UserRole, full_path)
        
        # 如果该父节点有直接的条目（不含子类的），可选择在父节点本身显示
        # 或添加一个虚拟的"（未分类）"子节点
```

#### 5.7.3 点击事件（`_on_category_clicked`）

```python
def _on_category_clicked(self, item, column):
    category = item.data(0, Qt.ItemDataRole.UserRole)
    
    if category == "全部":
        items = self.account_service.get_all_accounts()
    else:
        items = self.account_service.get_accounts_by_category(category)
    
    self._refresh_item_list(items)
```

#### 5.7.4 右键菜单

右键点击树节点时：
- 一级节点：显示「新建子类」、「重命名」、「删除」（删除需确认是否合并子类）
- 二级节点：显示「重命名」、「删除」
- 空白处：显示「新建一级分类」

重命名逻辑：
- 重命名一级节点 `工作` → 需批量修改所有 `工作` 和 `工作>xxx` 的前缀
- 重命名二级节点 `工作>开发工具` → 只修改精确匹配的记录

#### 5.7.5 样式与交互

- 父节点默认展开（或记忆用户的上次展开状态）
- 选中子节点时，父节点高亮（但不选中）
- 数量统计实时更新

**关联模块**：
- 依赖 `services/account_service.get_category_tree()` / `url_service.get_category_tree()`
- 依赖 `services/account_service.get_accounts_by_category()` / `url_service.get_accounts_by_category()`
- 依赖 `core/category_utils`

**注意事项**：
- `QTreeWidget` 的选中态和 `QListWidget` 不同，需确保复选框全选逻辑兼容
- 树形控件的数据绑定通过 `UserRole` 存储完整路径，展示文本仅用于显示

---

### 5.8 ui/account_dialog.py & ui/url_dialog.py

**目标**：分类选择器支持级联选择或路径输入。

#### 5.8.1 UI 布局改动

将原有的单一下拉框（或文本输入）改为：

```
分类：
[主类下拉框 ▼]  >  [子类下拉框 ▼]  [或输入新子类]
```

#### 5.8.2 加载主类

```python
def _load_categories(self):
    tree = self.account_service.get_category_tree()
    self.cmb_parent.clear()
    self.cmb_parent.addItem("请选择")
    self.cmb_parent.addItems(sorted(tree.keys()))
    
    # 如果有预设值（编辑模式）
    if self.account and self.account.category:
        from core.category_utils import parse_category_path
        parent, child = parse_category_path(self.account.category)
        self.cmb_parent.setCurrentText(parent)
        if child:
            self.cmb_child.setCurrentText(child)
```

#### 5.8.3 主类联动子类

```python
def _on_parent_changed(self, parent_name):
    self.cmb_child.clear()
    self.cmb_child.addItem("")  # 空表示无子类（一级分类）
    self.cmb_child.setEditable(True)
    
    tree = self.account_service.get_category_tree()
    if parent_name in tree:
        for child in sorted(tree[parent_name]['children']):
            self.cmb_child.addItem(child)
```

#### 5.8.4 保存时校验与组装

```python
from core.category_utils import validate_category_name, format_category_path

parent = self.cmb_parent.currentText().strip()
child = self.cmb_child.currentText().strip()

if not parent or parent == "请选择":
    QMessageBox.warning(self, "验证失败", "请选择主分类")
    return

if not validate_category_name(parent):
    QMessageBox.warning(self, "验证失败", f"主分类名不能包含 / > ·")
    return

if child and not validate_category_name(child):
    QMessageBox.warning(self, "验证失败", f"子分类名不能包含 / > ·")
    return

category = format_category_path(parent, child if child else None)
account.category = category
```

**关联模块**：
- 依赖 `services/account_service.get_category_tree()`
- 依赖 `core/category_utils`

**注意事项**：
- 子类下拉框需设为可编辑（`setEditable(True)`），允许用户创建新的子类
- 如果用户手动输入了已存在的子类名，应自动匹配下拉项而非创建重复

---

### 5.9 ui/ai_classify_dialog.py

**目标**：AI 分类预览正确展示层级路径。

**改动点**：
- 预览表格的"分类"列直接显示 AI 返回的完整路径（如 `工作>开发工具`）
- 无需额外解析，但需校验路径合法性（调用 `core.category_utils.validate_category_name` 对每一级分别校验）
- 确认后写入数据库的值即为完整路径

**关联模块**：依赖 `core/category_utils`。

---

### 5.10 services/ai_assistant_service.py

**目标**：AI 助手在对话中操作分类时，支持路径格式。

#### 5.10.1 工具定义更新

**filter 工具**：
```
- filter: 按分类/标签筛选，params={"category": "工作"} 或 {"category": "工作>开发工具"}
```

**reorganize 工具**：
```
- reorganize: 建议重新整理分类，params={"changes": [{"target_id": 1, "field": "category", "new_value": "工作>开发工具", "reason": "..."}]}
```

**add 工具**：
```
- add: 新增条目，params={"item_type": "account|url", "fields": {"app_name": "B站", "category": "娱乐>视频"}}
```

#### 5.10.2 新增工具 get_category_tree

```
- get_category_tree: 获取当前分类树结构，params={"item_type": "account|url"}
  返回示例：{"工作": ["开发工具", "设计"], "娱乐": ["游戏", "视频"], "学术与研究": []}
```

**实现**：
```python
def tool_get_category_tree(self, item_type: str) -> dict:
    if item_type == 'account':
        tree = self.account_service.get_category_tree()
    else:
        tree = self.url_service.get_category_tree()
    # 转为 AI 易读的格式
    return {k: sorted(v['children']) for k, v in tree.items()}
```

**关联模块**：被 AI 助手对话流程调用，改动量中等。

---

### 5.11 services/ai_classification_service.py

**目标**：批量归类时注入分类树上下文。

**改动点**：
- 在调用 AI 分类前，先获取当前分类树并格式化为文本
- 将分类树文本拼入 Prompt
- 接收 AI 返回后，调用 `core.category_utils.parse_category_path` 解析并校验

**关联模块**：依赖 `services/category_service`、`core/category_utils`。

---

### 5.12 services/export_service.py

**目标**：HTML 书签导出支持嵌套文件夹。

#### 5.12.1 export_urls_to_html 重构

当前实现（按 category 扁平分组）：
```python
categories = {}
for item in urls:
    cat = item.category or '其他'
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(item)
```

新实现（按层级嵌套）：
```python
from core.category_utils import parse_category_path

def _build_nested_groups(urls):
    """构建二级嵌套结构"""
    groups = {}  # {parent: {'direct': [], 'children': {child: []}}}
    
    for item in urls:
        parent, child = parse_category_path(item.category or '其他')
        if parent not in groups:
            groups[parent] = {'direct': [], 'children': {}}
        if child:
            if child not in groups[parent]['children']:
                groups[parent]['children'][child] = []
            groups[parent]['children'][child].append(item)
        else:
            groups[parent]['direct'].append(item)
    
    return groups

# HTML 生成
groups = _build_nested_groups(urls)
for parent_name, data in groups.items():
    lines.append(f'<DT><H3 ADD_DATE="{ts}">{html.escape(parent_name)}</H3>')
    lines.append('<DL><p>')
    
    # 父节点直接条目
    for item in data['direct']:
        lines.append(f'<DT><A HREF="{html.escape(item.url)}">{html.escape(item.title)}</A>')
    
    # 子节点文件夹
    for child_name, child_items in data['children'].items():
        lines.append(f'<DT><H3 ADD_DATE="{ts}">{html.escape(child_name)}</H3>')
        lines.append('<DL><p>')
        for item in child_items:
            lines.append(f'<DT><A HREF="{html.escape(item.url)}">{html.escape(item.title)}</A>')
        lines.append('</DL><p>')
    
    lines.append('</DL><p>')
```

**Excel 导出**：分类列直接显示完整路径（如 `工作>开发工具`），**无需改动**。

**关联模块**：依赖 `core/category_utils.parse_category_path`。

---

### 5.13 services/import_service.py

**目标**：浏览器 HTML 书签导入时，嵌套文件夹解析为 `>` 路径。

#### 5.13.1 _parse_bookmark_node 递归解析

```python
def _parse_bookmark_node(node, parent_path=""):
    """递归解析 HTML 书签节点"""
    from bs4 import BeautifulSoup
    
    h3 = node.find('h3')
    if h3:
        folder_name = h3.get_text(strip=True)
        # 校验文件夹名（浏览器导出可能含非法字符）
        folder_name = folder_name.replace('/', '与').replace('>', '-').replace('·', '-')
        
        current_path = f"{parent_path}>{folder_name}" if parent_path else folder_name
        
        dl = node.find('dl', recursive=False)
        if dl:
            for dt in dl.find_all('dt', recursive=False):
                a_tag = dt.find('a')
                if a_tag:
                    # 叶子节点：网址书签
                    url = a_tag.get('href', '')
                    title = a_tag.get_text(strip=True)
                    yield {
                        'title': title,
                        'url': url,
                        'category': current_path,  # 完整路径
                        'tags': []
                    }
                else:
                    # 嵌套文件夹
                    yield from _parse_bookmark_node(dt, current_path)
```

**注意事项**：
- HTML 书签可能超过二级嵌套，但我们的体系最多支持二级
- 超过二级的路径（如 `A>B>C`）需截断或合并：可把 `B>C` 作为子类名（但含 `>` 非法），因此建议超过二级时，将深层路径用 `-` 连接为子类名：`A>B-C-D`
- 更简单的方案：遇到三级时，只取前两级，忽略更深层

**关联模块**：被 `ui/import_dialog.py` 调用。

---

### 5.14 ui/export_dialog.py & ui/import_dialog.py

**目标**：分类选择器展示层级。

#### 5.14.1 export_dialog.py

分类下拉框（指定分类导出时）：
- 当前为扁平列表
- 改为树形下拉或级联选择
- 由于 `QComboBox` 不支持树形，可简化为：
  - 第一级选主类，第二级选子类（类似 account_dialog 的级联下拉）
  - 或在下拉框中缩进显示：`工作`、`  ├── 开发工具`

推荐采用**级联下拉**方案（与 account_dialog 保持一致）。

#### 5.14.2 import_dialog.py

分类映射表格中，目标分类列支持下拉选择（级联），允许映射到一级或二级分类。

**关联模块**：依赖 `services/account_service.get_category_tree()` / `url_service.get_category_tree()`。

---

### 5.15 services/search_service.py

**目标**：分类筛选支持前缀匹配。

**改动点**：

```python
def filter_by_category(self, items, category: str):
    """按分类筛选，支持父节点前缀匹配"""
    from core.category_utils import get_prefix_matcher
    matcher = get_prefix_matcher(category)
    return [item for item in items if matcher(item.category)]
```

**关联模块**：被 `ui/main_window.py` 搜索逻辑调用。

---

## 六、文件间依赖关系

```
core/category_utils.py (新建)
    ├── services/account_service.py
    │       └── ui/main_window.py
    │       └── ui/account_dialog.py
    │       └── ui/export_dialog.py
    │       └── services/search_service.py
    ├── services/url_service.py
    │       └── ui/main_window.py
    │       └── ui/url_dialog.py
    │       └── ui/export_dialog.py
    ├── services/category_service.py
    │       └── services/ai_tools.py
    ├── services/export_service.py
    ├── services/import_service.py
    └── ui/import_dialog.py

services/ai_tools.py
    ├── services/ai_classification_service.py
    ├── services/ai_assistant_service.py
    └── services/batch_add_processor.py

scripts/migrate_category_separator.py
    └── （独立运行，不依赖业务代码）
```

**关键依赖说明**：
- `core/category_utils.py` 是**底层基石**，所有涉及分类解析/校验/建树的地方都必须引用它
- `services/account_service.py` 和 `services/url_service.py` 的 `get_category_tree()` 是**UI 和 AI 的数据源**
- `services/ai_tools.py` 的 Prompt 模板是**AI 行为的总开关**

---

## 七、校验标准

### 7.1 数据层校验

| 校验项 | 通过标准 |
|---|---|
| 数据清洗完成 | `SELECT COUNT(*) FROM accounts WHERE category LIKE '%/%'` 返回 0 |
| 非法字符检查 | `SELECT DISTINCT category FROM accounts WHERE category REGEXP '[/·]'` 返回空集 |
| 三级路径检查 | 无 `category` 含两个及以上 `>` |

### 7.2 AI 层校验

| 校验项 | 通过标准 |
|---|---|
| AI 分类输出格式 | 连续测试 20 个不同应用，AI 输出均符合 `主类>子类` 或 `主类`，无 `/`、无 `·`、无三级 |
| 分类树注入 | AI 能根据已有分类树推荐已有子类，而非重复创建同义分类 |
| 兜底行为 | 当应用无法归类时，AI 输出一级分类（如 `其他`），而非空值或乱码 |

### 7.3 UI 层校验

| 校验项 | 通过标准 |
|---|---|
| 侧边栏展示 | `QTreeWidget` 正确展示为树形，父节点可展开/收起，二级节点缩进显示 |
| 数量统计 | 父节点数量 = 直接属于该父类的条目 + 所有子类条目之和；子节点数量精确匹配 |
| 点击父节点 | 列表区显示所有属于该父类的条目（含子类） |
| 点击子节点 | 列表区仅显示精确匹配的条目 |
| 编辑弹窗级联 | 选择主类后，子类下拉框自动加载已有子类；子类可手动输入创建新分类 |
| 输入校验 | 用户输入含 `/`、`>`、`·` 的分类名时，弹窗阻止保存并提示 |

### 7.4 导入导出校验

| 校验项 | 通过标准 |
|---|---|
| HTML 导出 | Chrome 导入后，书签管理器中展示为嵌套文件夹，层级与软件内一致 |
| HTML 导入 | Chrome 导出的嵌套书签导入后，`category` 字段正确解析为 `>` 路径 |
| Excel 导出 | 分类列显示完整路径（如 `工作>开发工具`） |
| Vault 备份 | 加密备份/恢复后，含 `>` 的分类路径完整保留，无截断或转义 |

### 7.5 回归校验

| 校验项 | 通过标准 |
|---|---|
| 旧数据兼容 | 不含 `>` 的旧分类（如 `学术与研究`）在树中作为一级节点正常展示 |
| 搜索筛选 | 搜索+分类筛选组合使用时，结果正确（前缀匹配生效） |
| 批量添加 | 批量添加账号/网址时，AI 建议的分类路径正确写入数据库 |
| 缓存失效 | 分类变更后，AI 分类缓存正确失效或更新 |

---

## 八、回退方案

1. **数据回退**：执行清洗脚本前已自动生成 `.backup.{timestamp}` 文件，若升级失败，直接覆盖还原数据库即可
2. **代码回退**：所有改动通过 Git 管理，可一键回退到升级前版本（旧代码对含 `>` 的 category 值按普通字符串处理，不会崩溃，只是展示为扁平文本）
3. **AI 回退**：若 AI 频繁输出非法格式，可在 `sanitize_ai_category` 中强制降级为仅输出一级分类，关闭二级功能

---

**文档状态**：规划完成，待用户确认后按 Phase 分批实施。
