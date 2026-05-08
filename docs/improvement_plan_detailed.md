# 遗留问题详细改进计划

> 生成日期：2026-05-08
> 优先级：P3（后续迭代）

---

## 一、模块拆分：`main_window.py`（6971 行）

### 现状
`ui/main_window.py` 承担导航、列表、搜索、AI面板、设置、导入导出、主题切换、分类管理等几乎所有 UI 逻辑，近 7000 行，维护困难。

### 拆分方案

```
ui/
├── main_window.py          # 框架 + 导航 + 信号路由（目标 < 1500 行）
├── panels/
│   ├── search_panel.py     # 搜索框 + 筛选面板 + 搜索结果
│   ├── ai_panel.py         # AI 助手侧边栏
│   ├── category_panel.py   # 左侧分类树
│   └── list_panel.py       # 账号/网址列表 + 字母导航
├── controllers/
│   ├── theme_controller.py # 主题切换 + _reapply_styles
│   ├── import_export_controller.py
│   └── settings_controller.py
└── dialogs/                # 已有，保持不变
```

### 具体拆分步骤

| 步骤 | 内容 | 预计工作量 |
|------|------|-----------|
| 1 | 提取 `SearchPanel` 类（搜索框、筛选面板、AI筛选横幅） | 4h |
| 2 | 提取 `AIPanel` 类（AI 侧边栏、聊天历史、输入框） | 4h |
| 3 | 提取 `CategoryPanel` 类（分类树、拖拽、批量操作） | 3h |
| 4 | 提取 `AccountListPanel` 类（列表、选择模式、字母导航） | 4h |
| 5 | 提取 `ThemeController`（主题切换、样式刷新） | 2h |
| 6 | `main_window.py` 改为组合上述组件 | 3h |

### 注意事项
- 保持信号/槽连接不变，避免破坏现有交互逻辑
- 先复制代码到新文件，再在原文件中删除，逐步验证
- 每个组件提取后运行完整功能测试

---

## 二、提取公共基类：`database.py` / `url_database.py`

### 现状
两个数据库管理器中，分类排序、重命名、升级、删除等逻辑几乎完全一致：
- `get_category_orders` / `save_category_orders`
- `rename_category` / `rename_category_order`
- `promote_category`
- `reparent_category`
- `delete_category`

### 重构方案

```python
# core/base_database.py
from abc import ABC, abstractmethod
import threading
import sqlite3

class BaseDatabaseManager(ABC):
    """数据库管理器抽象基类，提供分类管理和线程安全"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.conn = None
        self.cursor = None
        self._connect()
    
    # === 线程安全包装 ===
    def _execute(self, sql, params=()):
        with self._lock:
            self.cursor.execute(sql, params)
            self.conn.commit()
    
    def _fetchall(self, sql, params=()):
        with self._lock:
            self.cursor.execute(sql, params)
            return self.cursor.fetchall()
    
    # === 分类管理（通用实现）===
    def get_category_orders(self) -> dict:
        # 统一实现...
    
    def save_category_orders(self, orders: dict):
        # 统一实现...
    
    def rename_category(self, old_name: str, new_name: str) -> bool:
        # 统一实现...
    
    def promote_category(self, path: str) -> bool:
        # 统一实现...
    
    def reparent_category(self, old_path: str, new_path: str) -> bool:
        # 统一实现...
    
    def delete_category(self, path: str) -> bool:
        # 统一实现...
    
    @abstractmethod
    def _create_tables(self):
        """子类实现建表逻辑"""
        pass
```

### 迁移步骤

| 步骤 | 内容 | 预计工作量 |
|------|------|-----------|
| 1 | 创建 `core/base_database.py`，迁移分类管理方法 | 3h |
| 2 | `DatabaseManager` 继承 `BaseDatabaseManager` | 2h |
| 3 | `URLDatabaseManager` 继承 `BaseDatabaseManager` | 2h |
| 4 | 运行 account_service / url_service 测试验证 | 2h |

---

## 三、硬编码路径集中管理

### 现状
`.local_password_vault` 分布在至少 7 个文件、15+ 处：
- `main.py`
- `ui/main_window.py`
- `services/semantic_search_service.py`
- `scripts/migrate_category_separator.py`
- `_test_init.py`

### 方案

```python
# core/constants.py
from pathlib import Path

APP_NAME = "LocalPasswordVault"
DATA_DIR = Path.home() / '.local_password_vault'
CONFIG_FILE = DATA_DIR / 'config.json'
DB_FILE = DATA_DIR / 'vault.db'
URL_DB_FILE = DATA_DIR / 'url_vault.db'
SNAPSHOT_DIR = DATA_DIR / 'snapshots'
RECYCLE_BIN_DAYS = 30

# 确保目录存在
def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
```

### 迁移步骤

| 步骤 | 内容 | 预计工作量 |
|------|------|-----------|
| 1 | 创建 `core/constants.py` | 30min |
| 2 | 逐个文件替换硬编码路径 | 2h |
| 3 | 验证所有文件路径引用正确 | 1h |

---

## 四、头像颜色数组主题化

### 现状
`account_list_item.py` 和 `url_list_item.py` 使用 15 个高饱和度 Material 色：
```python
colors = ['#E57373', '#F06292', '#BA68C8', '#9575CD', '#7986CB',
          '#64B5F6', '#4FC3F7', '#4DD0E1', '#4DB6AC', '#81C784',
          '#AED581', '#DCE775', '#FFF176', '#FFD54F', '#FFB74D']
```

### 方案

在 `ThemeColors` 中新增 `icon_palette` 字段：

```python
# core/theme_manager.py
@dataclass
class ThemeColors:
    # ... 现有字段 ...
    icon_palette: list[str]  # 头像循环配色

LIGHT_COLORS = ThemeColors(
    # ... 现有字段 ...
    icon_palette=['#E57373', '#F06292', '#BA68C8', '#9575CD', '#7986CB',
                  '#64B5F6', '#4FC3F7', '#4DD0E1', '#4DB6AC', '#81C784',
                  '#AED581', '#FFB74D', '#FF8A65', '#E0E0E0', '#BDBDBD']
)

DARK_COLORS = ThemeColors(
    # ... 现有字段 ...
    icon_palette=['#5C3A3A', '#5A3A4A', '#4A3A5C', '#3A3A5C', '#3A4A5C',
                  '#3A5C6E', '#3A6E5C', '#5C6E3A', '#6E5C3A', '#6E3A3A',
                  '#5C5C5C', '#4A4A4A', '#3A3A3A', '#2E2E2E', '#252525']
    # 或使用降低饱和度的同一色系
)
```

### 修改文件
- `core/theme_manager.py`：新增字段
- `ui/widgets/account_list_item.py`：改用 `colors.icon_palette`
- `ui/widgets/url_list_item.py`：改用 `colors.icon_palette`

---

## 五、`password_strength.py` 收敛到 ThemeColors

### 现状
`core/password_strength.py` 返回硬编码颜色：
```python
def evaluate_password_strength(password: str) -> dict:
    # ...
    return {
        'score': score,
        'label': label,
        'color': '#f44336',  # 硬编码
        'bg_color': '#FFEBEE',  # 硬编码
        'feedback': [...]
    }
```

### 方案

方案 A（推荐）：`evaluate_password_strength` 只返回语义标签，不返回颜色
```python
def evaluate_password_strength(password: str) -> dict:
    return {
        'score': score,
        'label': label,
        'feedback': [...]
    }

# UI 层统一使用 _get_strength_color(label) 获取颜色
```

方案 B：接收 `ThemeColors` 参数
```python
def evaluate_password_strength(password: str, colors: ThemeColors = None) -> dict:
    if colors is None:
        colors = ThemeManager.instance().colors
    return {
        'score': score,
        'label': label,
        'color': color_map[label],  # 从 colors 获取
        'bg_color': bg_map[label],
    }
```

### 影响范围
- `core/password_strength.py`
- `ui/account_dialog.py`（已部分修复，需移除 `result['color']` 引用）
- `ui/widgets/account_list_item.py`（已修复）
- `ui/widgets/dashboard_widget.py`（已修复）

---

## 六、测试覆盖补充

### 当前测试
- `test_account_service.py`
- `test_crypto.py`
- `test_id_type_consistency.py`
- `test_search_service.py`

### 需要补充的测试

#### P0：数据库线程安全测试
```python
# tests/test_database_thread_safety.py
import threading
import time

def test_concurrent_reads_and_writes(temp_db):
    """多线程并发读写不应导致异常或数据损坏"""
    errors = []
    
    def writer():
        try:
            for i in range(50):
                temp_db.add_account(f"app_{i}", "u", "p", "cat")
        except Exception as e:
            errors.append(e)
    
    def reader():
        try:
            for _ in range(50):
                temp_db.get_all_accounts()
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)
    
    threads = [threading.Thread(target=writer) for _ in range(2)] + \
              [threading.Thread(target=reader) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    assert len(errors) == 0, f"并发错误: {errors}"
```

#### P1：泄露检测子线程测试
```python
# tests/test_breach_check_thread.py
from unittest.mock import patch, MagicMock

def test_breach_check_interrupt():
    """线程中断应安全退出，不崩溃"""
    thread = _BreachCheckThread(['password'], {'password': [1]})
    thread.start()
    thread.requestInterruption()
    thread.wait(5000)
    assert not thread.isRunning()

def test_breach_check_parallel():
    """并行查询结果应与串行一致"""
    # 使用 mock 响应验证
```

#### P2：主题切换测试
```python
# tests/test_theme_switch.py
def test_theme_switch_does_not_crash(app, main_window):
    ThemeManager.instance().apply_theme('dark')
    QApplication.processEvents()
    ThemeManager.instance().apply_theme('light')
    QApplication.processEvents()
    # 断言无异常
```

---

## 七、其他建议

### 7.1 泄露检测网络预检（已在本轮修复错误提示，预检可后续增强）
在 `_run_breach_check` 启动线程前，增加 DNS 预检：
```python
def _pre_check_network(self):
    import socket
    try:
        sock = socket.create_connection(("api.pwnedpasswords.com", 443), timeout=3)
        sock.close()
        return True
    except Exception:
        return False
```

### 7.2 泄露检测结果本地缓存
建立 SQLite 缓存表，缓存前缀查询结果（TTL 7 天）：
```sql
CREATE TABLE breach_cache (
    prefix TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.3 `clipboard.py` 改用 `QTimer`
当前使用 `threading.Timer`，在 PyQt 应用中建议统一使用 `QTimer`：
```python
from PyQt6.QtCore import QTimer

class ClipboardManager(QObject):
    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._clear_password)
```

---

## 实施优先级建议

| 阶段 | 内容 | 预计总工时 | 收益 |
|------|------|-----------|------|
| **第一阶段** | 硬编码路径集中化 + password_strength 颜色收敛 | 4h | 高（低侵入、易维护） |
| **第二阶段** | database/url_database 公共基类提取 | 8h | 高（消除重复代码） |
| **第三阶段** | 头像颜色主题化 + 测试补充 | 6h | 中（视觉一致性） |
| **第四阶段** | main_window.py 模块拆分 | 20h | 高（长期维护） |
