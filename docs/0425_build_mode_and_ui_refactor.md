# 0425 Build模式权限扩展与主界面重构 — 代办任务文档

> 文档版本：v1.0
> 编写日期：2026-04-25
> 基线代码版本：0425 迭代完成版（含分段输出、快照持久化、PWA同步、自动锁定等）

---

## 一、需求总览

本次迭代包含 **4 大模块**，其中 2 个为大型重构，2 个为中型功能升级：

| 模块 | 类型 | 工作量 | 优先级 |
|------|------|--------|--------|
| **Build 模式权限边界扩展** | 大型功能升级 | 高 | P0 |
| **密码库/网址库主界面合并重构** | 大型架构重构 | 高 | P0 |
| **AI 助手 UI 调整** | 小型修复 | 低 | P2 |
| **PWA 同步文件名修改** | 一行修改 | 低 | P2 |

---

## 二、模块一：Build 模式权限边界扩展（P0）

### 2.1 当前状态

| 能力 | 状态 |
|------|------|
| search / filter / list（只读） | ✅ Plan/Build 均支持 |
| reorganize（批量整理分类） | ✅ Build 模式支持，带 Action Preview + 事务 |
| add_remark（添加 AI 备注） | ✅ Build 模式支持，带 Action Preview + 事务 |
| delete（删除条目） | ❌ 未实现 |
| add（新增条目） | ❌ 未实现 |

当前 `VALID_ACTIONS = ['search', 'filter', 'list', 'reorganize', 'add_remark', 'explain']`

### 2.2 目标状态

`VALID_ACTIONS` 扩展为：
```python
VALID_ACTIONS = [
    'search', 'filter', 'list', 'explain',      # 只读
    'reorganize', 'add_remark',                 # 更新（已有）
    'delete',                                    # 删除（新增）
    'add'                                        # 创建（新增）
]
READONLY_ACTIONS = {'search', 'filter', 'list', 'explain'}
WRITE_ACTIONS = {'reorganize', 'add_remark', 'delete', 'add'}
```

---

### 2.3 任务清单：删除条目（delete）

#### T1-1 回收站数据模型设计

**新建表 `recycle_bin`**（主数据库 `vault.db` 中）：

```sql
CREATE TABLE IF NOT EXISTS recycle_bin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER NOT NULL,           -- 原条目 ID
    item_type TEXT NOT NULL,                -- 'account' | 'url'
    -- 加密存储原条目完整数据（JSON 序列化后加密）
    encrypted_data BLOB NOT NULL,
    -- 明文索引字段（用于回收站列表展示和搜索）
    app_name TEXT,                          -- 应用名/标题（明文，用于展示）
    username TEXT,                          -- 账号（脱敏后明文，如 138****1234）
    url TEXT,                               -- 网址（明文）
    category TEXT,                          -- 分类（明文）
    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,                   -- 自动清理时间（deleted_at + 30天）
    restored_at TIMESTAMP,                  -- 恢复时间（NULL 表示未恢复）
    is_restored INTEGER DEFAULT 0           -- 0=已删除, 1=已恢复, 2=已清理
);

-- 索引：加速过期查询和恢复查询
CREATE INDEX IF NOT EXISTS idx_recycle_expires 
    ON recycle_bin(expires_at) WHERE is_restored = 0;
CREATE INDEX IF NOT EXISTS idx_recycle_type 
    ON recycle_bin(item_type, is_restored);
```

**说明**：
- `encrypted_data` 存储原条目的完整 JSON（含密码等敏感字段），使用 `crypto_manager` 加密
- `app_name`/`username`/`url`/`category` 为明文索引字段，仅用于回收站列表展示，不存密码
- 软删除：原表数据物理删除，完整备份存入 `recycle_bin`
- 30 天自动清理：后台启动时检查 `expires_at < now()` 的记录并物理删除

#### T1-2 数据库操作层扩展

在 `core/database.py` `DatabaseManager` 中新增：

```python
def soft_delete_account(self, account_id: int, account_data: dict) -> bool:
    """将账号移入回收站（软删除）"""
    # 1. 将 account_data 序列化为 JSON，加密后存入 recycle_bin
    # 2. 提取 app_name/username/url/category 作为明文索引（username 需脱敏）
    # 3. 计算 expires_at = now + 30 days
    # 4. 从 accounts 表物理删除该记录
    # 5. 返回是否成功

def get_recycle_bin_items(self, item_type: str = None, 
                          include_expired: bool = False) -> List[Dict]:
    """获取回收站条目列表"""

def restore_account(self, recycle_id: int) -> Optional[Dict]:
    """从回收站恢复账号到 accounts 表"""
    # 1. 从 recycle_bin 读取 encrypted_data
    # 2. 解密后反序列化为 account_data
    # 3. 插入 accounts 表（生成新 ID 或尝试保留原 ID）
    # 4. 标记 recycle_bin 记录为已恢复
    # 5. 返回恢复后的账号数据

def cleanup_expired_recycle_bin(self, days: int = 30) -> int:
    """清理超过保留期的回收站条目，返回清理数量"""
```

在 `core/url_database.py` `URLDatabaseManager` 中新增对应的 `soft_delete_url` / `restore_url` 方法（或统一由主库的 `recycle_bin` 管理两种类型）。

**决策**：统一使用主数据库的 `recycle_bin` 表管理两种类型的软删除，通过 `item_type` 区分。这样恢复时可以根据类型路由到正确的表。

#### T1-3 AI 解析层：delete 意图识别

**修改 `ai/ollama_client.py` `parse_command()` 的 Prompt**：

在原有 action 列表中增加 `delete`：
```
- delete: 删除条目，params={"target_ids": [1, 2, 3], "query_description": "删掉所有分类为未整理的网址", "item_type": "account|url"}
```

**要求模型输出**：
```json
{
  "action": "delete",
  "params": {
    "target_ids": [1, 2, 3],
    "query_description": "删掉所有分类为未整理的网址",
    "item_type": "account"
  }
}
```

**如果用户描述模糊**（如"删掉刚才添加的"），模型应返回 `target_ids: []` + `query_description`，由本地代码根据上下文（时间戳最近添加的）补全。

#### T1-4 Build 模式：delete 的 Action Preview

**`services/ai_assistant_service.py` `build_action_preview()` 扩展 delete 分支**：

```python
elif action == 'delete':
    target_ids = params.get('target_ids', [])
    item_type = params.get('item_type', 'account')
    
    for tid in target_ids:
        acc = account_map.get(tid)  # 或 url_map
        if acc:
            preview_items.append({
                "target_id": tid,
                "item_type": item_type,
                "app_name": acc.app_name,
                "username": acc.mask_username(),  # 脱敏
                "category": acc.category,
                "impact": f"将从{item_type}库中删除，移入回收站保留30天"
            })
```

**UI 预览表格列**：应用名/网址 | 账号（脱敏） | 分类 | 影响说明 | 删除类型

#### T1-5 Build 模式：delete 的事务执行

**`execute_build_action_with_transaction()` 扩展 delete 分支**：

```python
elif action_type == 'delete':
    for item in executable_items:
        target_id = item['target_id']
        item_type = item.get('item_type', 'account')
        
        # 1. 读取原条目完整数据
        if item_type == 'account':
            original = db.get_account_by_id(target_id)
            db.soft_delete_account(target_id, original)
        else:
            original = url_db.get_url_by_id(target_id)
            db.soft_delete_url(target_id, original)
        
        affected_ids.append(target_id)
```

**审计日志**：记录 `parsed_action='delete'`，`affected_ids` 包含被删条目 ID。

#### T1-6 回收站 UI 入口

**方案 A（推荐）**：在主界面底部工具栏增加"回收站"按钮，点击弹出回收站对话框。

**方案 B**：在设置对话框中增加回收站管理页。

**回收站对话框功能**：
- 列表展示：应用名/网址、分类、删除时间、剩余保留天数
- 操作：恢复（单条/批量）、永久删除、清空回收站
- 筛选：按类型（账号/网址）、按分类、按时间范围

---

### 2.4 任务清单：新增条目（add）

#### T2-1 AI 解析层：add 意图识别与实体抽取

**修改 `ai/ollama_client.py` `parse_command()` 的 Prompt**：

增加 `add` action：
```
- add: 新增条目，params={"item_type": "account|url", "fields": {"app_name": "B站", "username": "abc@qq.com", "password": "123456", "url": "https://www.bilibili.com", "category": "视频", "remark": "", "tags": []}}
```

**实体抽取 Prompt 设计**：
```
用户说："帮我添加一个B站账号，用户名是abc@qq.com，密码是123456，分类选视频"

请从用户输入中抽取以下字段：
- app_name: 应用名称（如"B站"→"哔哩哔哩"或保留"B站"）
- username: 账号
- password: 密码
- url: 网址（如果用户输入中包含 http/https 或域名后缀，识别为网址）
- category: 分类（如果用户未指定，返回空字符串）
- remark: 备注（用户未提及则空）
- tags: 标签列表（用户未提及则空数组）
- item_type: "account" 或 "url"（如果包含密码或明确说是"账号"，则为 account；如果只有网址和标题，则为 url）

如果关键字段缺失（如缺少 password 且 item_type=account），请在 response 中主动询问用户补全，不要直接返回空值。
```

**模型返回格式**：
```json
{
  "action": "add",
  "params": {
    "item_type": "account",
    "fields": {
      "app_name": "哔哩哔哩",
      "username": "abc@qq.com",
      "password": "123456",
      "url": "https://www.bilibili.com",
      "category": "视频",
      "remark": "",
      "tags": []
    },
    "missing_fields": []  // 如果无缺项则为空
  }
}
```

#### T2-2 缺项追问机制

**`services/ai_assistant_service.py` `process_query()` 中增加缺项检测**：

```python
if action == 'add':
    fields = params.get('fields', {})
    item_type = params.get('item_type', 'account')
    missing = []
    
    if item_type == 'account':
        if not fields.get('app_name'): missing.append('应用名称')
        if not fields.get('username'): missing.append('账号')
        if not fields.get('password'): missing.append('密码')
    elif item_type == 'url':
        if not fields.get('title'): missing.append('标题')
        if not fields.get('url'): missing.append('网址')
    
    if missing:
        result['response'] = f"请补充以下信息：{', '.join(missing)}"
        result['action'] = 'explain'  # 降级为 explain，等待用户补全
        result['params'] = {'pending_add': params}  # 保存已抽取的字段
```

**追问上下文保持**：如果用户下一条回复是补全信息，系统应合并 `pending_add` 中的字段与新抽取的字段，然后再次检查缺项。

#### T2-3 新增预览卡片（Add Preview Widget）

**新建 `ui/add_preview_dialog.py`（或复用 `ActionPreviewWidget`）**：

预览卡片展示内容：
```
┌────────────────────────────────────────────┐
│ 📋 新增条目预览                              │
├────────────────────────────────────────────┤
│ 应用名: 哔哩哔哩                             │
│ 账号:   abc@qq.com                           │
│ 密码:   ••••••                               │
│ 网址:   https://www.bilibili.com             │
│ 分类:   视频                                 │
│ 备注:   （无）                               │
│ 标签:   （无）                               │
├────────────────────────────────────────────┤
│ 目标库: 密码库                               │
├────────────────────────────────────────────┤
│        [取消]  [确认入库]                    │
└────────────────────────────────────────────┘
```

**`services/ai_assistant_service.py` `build_action_preview()` 扩展 add 分支**：

```python
elif action == 'add':
    fields = params.get('fields', {})
    item_type = params.get('item_type', 'account')
    preview_items.append({
        "type": "add",
        "item_type": item_type,
        "fields": fields,
        "impact": f"新增到{item_type}库"
    })
```

#### T2-4 新增事务执行

**`execute_build_action_with_transaction()` 扩展 add 分支**：

```python
elif action_type == 'add':
    for item in executable_items:
        fields = item['fields']
        item_type = item.get('item_type', 'account')
        
        if item_type == 'account':
            account = Account(
                app_name=fields.get('app_name', ''),
                username=fields.get('username', ''),
                password=fields.get('password', ''),
                url=fields.get('url', ''),
                category=fields.get('category', '其他'),
                remark=fields.get('remark', ''),
                tags=json.dumps(fields.get('tags', []), ensure_ascii=False)
            )
            new_id = db.insert_account(account.to_dict())
        else:
            url_item = URLItem(
                title=fields.get('title', ''),
                url=fields.get('url', ''),
                category=fields.get('category', '其他'),
                tags=json.dumps(fields.get('tags', []), ensure_ascii=False)
            )
            new_id = url_db.insert_url(url_item.to_dict())
        
        affected_ids.append(new_id)
```

**注意**：新增操作也需要写入审计日志，并更新分类缓存（如果分类是新的）。

#### T2-5 智能分类建议（add 时）

新增条目时，如果用户未指定分类或分类为"其他"，自动调用 `CategoryService.get_category()` 进行 AI 智能分类。

---

### 2.5 任务清单：统一安全边界与审计强化

#### T3-1 所有写操作强制 Action Preview

当前写操作（reorganize, add_remark, delete, add）在执行前必须通过 `build_action_preview()` 生成预览，并经用户确认。

**已有的防护**：
- ✅ `reorganize` / `add_remark` 有预览
- ❌ `delete` 需新增预览
- ❌ `add` 需新增预览

**`MainWindow._on_ai_query_finished()` 中统一处理**：

```python
WRITE_ACTIONS = {'reorganize', 'add_remark', 'delete', 'add'}

if action in WRITE_ACTIONS:
    # 统一生成预览
    preview = self.ai_assistant.build_action_preview(action, params, self._cached_accounts)
    self._show_action_preview(preview, action, params, query)
```

#### T3-2 审计日志增强

当前 `audit_log` 表已支持记录写操作。需要确保 `delete` 和 `add` 的操作也正确写入：

- `delete`：`parsed_action='delete'`，`affected_ids` 为被删条目 ID 列表
- `add`：`parsed_action='add'`，`affected_ids` 为新增条目 ID 列表

#### T3-3 Build 模式 UI 强提示强化

**当前状态**：
- Build 模式 Tab 文字为橙色
- 顶部有橙色横幅

**需要增强**：
1. **顶部权限横幅文字更醒目**：
   ```
   🔧 构建模式 — 可执行写操作（整理 / 备注 / 删除 / 新增）
   ⚠️ 所有操作需经你确认后才会生效
   ```
2. **发送按钮颜色变化**：Build 模式下发送按钮变为橙色（当前可能已是）
3. **模式切换时的确认弹窗**：从 Plan 切换到 Build 时，弹出提示：
   ```
   切换到 Build 模式后，AI 可以执行删除、新增等写操作。
   所有操作在执行前都会要求你确认，是否继续？
   ```
4. **Build 模式下输入框 placeholder 提示**：
   ```
   Build 模式：可以执行增删改操作，所有变更需确认后生效
   ```

---

## 三、模块二：密码库/网址库主界面合并重构（P0）

### 3.1 当前状态

| 组件 | 当前行为 |
|------|----------|
| 密码库 | 主窗口左侧分类导航 + 中间账号列表 |
| 网址库 | 独立弹窗 `URLManagerDialog`，有自己的搜索、分类、列表 |
| 切换方式 | 底部工具栏"网址管理"按钮 → 弹出模态对话框 |

**问题**：
- 网址库是独立弹窗，与主窗口割裂
- 搜索、AI 助手、分类导航无法复用
- 用户体验不连贯

### 3.2 目标状态

**主界面增加"库切换 Tab"**：

```
┌─────────────────────────────────────────────────────────────┐
│  [🔍 搜索框...]  [密码库 ●] [网址库 ○]  [+] 添加  [⚙] 设置   │
├──────────┬───────────────────────────────────────────┬──────┤
│          │                                           │      │
│  📁 分类  │   A                                       │ 炽阳  │
│  ────────│   ┌─────────────────────────────────┐     │      │
│  ○ 全部  │   │ 支付宝         138****1234      │     │      │
│  ● 金融  │   │  alipay.com                     │     │      │
│  ○ 社交  │   └─────────────────────────────────┘     │      │
│          │                                           │      │
├──────────┴───────────────────────────────────────────┴──────┤
│  [🔒 锁定]  [📤 导出]  [📱 同步]  [🗑 回收站]               │
└─────────────────────────────────────────────────────────────┘
```

**交互规则**：
- 顶部增加 "密码库" / "网址库" 两个 Tab 按钮（或切换按钮组）
- 点击切换时：
  - 左侧分类导航更新为当前库的分类列表
  - 中间列表清空并加载当前库的条目
  - 搜索框 placeholder 更新
  - 右侧 AI 助手保持通用（可查询当前库的条目）
- 底部"添加"按钮根据当前库弹出不同的对话框（`AccountDialog` 或 `URLEditDialog`）
- 底部"导出"按钮根据当前库导出不同格式

### 3.3 任务清单

#### T4-1 主界面顶部增加库切换 Tab

**修改 `ui/main_window.py` `setup_ui()`**：

在顶部工具栏增加库切换按钮组：

```python
self.tab_group = QButtonGroup(self)
btn_vault_accounts = QPushButton("密码库")
btn_vault_urls = QPushButton("网址库")
btn_vault_accounts.setCheckable(True)
btn_vault_urls.setCheckable(True)
btn_vault_accounts.setChecked(True)
self.tab_group.addButton(btn_vault_accounts, 0)
self.tab_group.addButton(btn_vault_urls, 1)
self.tab_group.buttonClicked.connect(self._on_vault_tab_changed)
```

#### T4-2 当前库状态管理

**在 `MainWindow` 中新增状态**：

```python
self.current_vault = 'accounts'  # 'accounts' | 'urls'
self._cached_urls = []           # 网址缓存
self._url_cache_dirty = True
self.url_service = URLService(url_db_manager)
```

**`_on_vault_tab_changed(tab_id)`**：
- 更新 `self.current_vault`
- 调用 `self.load_accounts()` 或 `self.load_urls()`
- 更新左侧分类导航
- 更新底部按钮状态

#### T4-3 分类导航动态切换

**左侧分类导航根据当前库显示不同分类**：

```python
CATEGORIES_ACCOUNTS = ['全部', '金融', '社交', '邮箱', '游戏', '工作', '其他']
CATEGORIES_URLS = ['全部', '开发工具', '云平台', '社交媒体', '学习', '娱乐', '其他']
```

**`load_categories()` 方法**：根据 `self.current_vault` 加载对应的分类列表。

#### T4-4 列表区域动态切换

**中间列表根据当前库显示不同内容**：

- `accounts` 模式：显示 `AccountListItem`，支持展开查看密码
- `urls` 模式：显示 `URLListItem`，支持点击跳转、复制网址

**`load_accounts()` / `load_urls()` 方法**：
- 清空 `self.account_list`
- 根据当前分类筛选
- 加载对应的数据并渲染列表项

#### T4-5 搜索功能通用化

**搜索框根据当前库搜索不同内容**：

```python
def on_search(self):
    if self.current_vault == 'accounts':
        # 调用 SearchService.search()
        ...
    else:
        # 调用 URLService.search_urls()
        ...
```

#### T4-6 底部按钮行为适配

| 按钮 | accounts 模式 | urls 模式 |
|------|--------------|-----------|
| 添加 | 打开 `AccountDialog` | 打开 `URLEditDialog` |
| 导出 | 导出 Excel / .vault | 导出 .txt / .xlsx |
| AI整理 | `AIClassifyDialog` (account) | `AIClassifyDialog` (url) |

#### T4-7 移除独立的 URLManagerDialog

- `on_url_manager()` 方法改为切换到 `urls` 模式
- `URLManagerDialog` 文件保留但标记为废弃（或删除）
- `ui/url_manager_dialog.py` 中的 `URLListItem` 和 `URLEditDialog` 类迁移到 `ui/main_window.py` 或新建 `ui/url_components.py`

#### T4-8 AI 助手适配双库

**AI 助手的 `build_db_summary()` 需要根据当前库构建不同的摘要**：

```python
def build_db_summary(self, accounts=None, urls=None, vault_type='accounts'):
    if vault_type == 'accounts':
        # 原有逻辑
    else:
        # 构建网址库摘要
```

**`MainWindow.on_ai_send_message()` 传递当前库的上下文**：

```python
if self.current_vault == 'accounts':
    context = self._cached_accounts
else:
    context = self._cached_urls
```

---

## 四、模块三：AI 助手 UI 调整（P2）

### T5-1 AI 面板初始宽度与最大宽度增大

**当前值**：
```python
self.ai_panel.setMaximumWidth(400)   # 展开时最大 400
self.ai_panel.setMinimumWidth(300)   # 展开时最小 300
splitter.setSizes([150, 750, 0])     # 左:中:右 = 150:750:0
```

**修改目标**：
```python
self.ai_panel.setMaximumWidth(600)   # 最大 600
self.ai_panel.setMinimumWidth(400)   # 最小 400
splitter.setSizes([150, 650, 0])     # 左:中:右 = 150:650:0
```

### T5-2 清空按钮宽度增大

**当前值**：
```python
btn_ai_clear.setFixedHeight(28)
btn_ai_clear.setFixedWidth(50)   # 太窄，"清空"两字显示不全
```

**修改目标**：
```python
btn_ai_clear.setFixedHeight(28)
btn_ai_clear.setFixedWidth(80)   # 足够显示"清空"二字
```

---

## 五、模块四：PWA 同步文件名修改（P2）

### T6-1 修改默认导出文件名

**文件**：`ui/main_window.py` `on_sync_to_mobile()`

**当前代码**：
```python
default_name = f"vault_{datetime.now().strftime('%Y%m%d')}.html"
```

**修改目标**：
```python
default_name = "leopassword.html"
```

---

## 六、实现顺序建议

### 第一轮（1-2天）：P2 修复 + PWA 文件名
- T5-1 AI 面板宽度调整
- T5-2 清空按钮宽度
- T6-1 PWA 文件名修改

### 第二轮（3-5天）：Build 模式 delete + add
- T1-1 回收站表设计
- T1-2 数据库软删除/恢复方法
- T1-3 delete 意图识别（Prompt 修改）
- T1-4 delete Action Preview
- T1-5 delete 事务执行
- T2-1 add 意图识别与实体抽取
- T2-2 缺项追问机制
- T2-3 add 预览卡片
- T2-4 add 事务执行
- T3-1 统一 Action Preview 流程
- T3-2 审计日志增强
- T3-3 Build 模式 UI 强提示

### 第三轮（3-5天）：主界面合并重构
- T4-1 顶部库切换 Tab
- T4-2 当前库状态管理
- T4-3 分类导航动态切换
- T4-4 列表区域动态切换
- T4-5 搜索功能通用化
- T4-6 底部按钮行为适配
- T4-7 移除独立 URLManagerDialog
- T4-8 AI 助手适配双库

### 第四轮（1-2天）：回收站 UI + 测试
- T1-6 回收站 UI 入口
- 全链路测试

---

## 七、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| delete 软删除的加密数据占用空间 | 中 | 30 天自动清理 + 用户可手动清空回收站 |
| add 自然语言实体抽取不准确 | 高 | 缺项追问机制 + 表单预览确认 |
| 主界面重构引入回归 Bug | 高 | 分步重构，每次只改一个组件；保留旧代码做 fallback |
| 双库切换时 AI 助手上下文混乱 | 中 | `build_db_summary` 根据当前库动态构建 |
| delete 误删恢复时 ID 冲突 | 低 | 恢复时生成新 ID，原 ID 不保留 |

---

## 八、待确认问题

1. **回收站条目恢复时的 ID 处理**：是否保留原 ID 还是生成新 ID？
   - 保留原 ID：如果原 ID 已被新条目占用会冲突
   - 生成新 ID：更安全，但关联数据（如相关网址的 `related_account_id`）会断开
   - **建议**：生成新 ID，恢复时显示提示"已恢复，新 ID 为 xxx"

2. **网址库的分类体系**：是否与密码库共用一套分类？
   - 当前 `account_service.py` 和 `url_service.py` 的分类列表不同
   - **建议**：保持独立分类体系，但在 AI 分类时统一使用 7 个大类

3. **add 操作时 AI 分类的触发时机**：
   - 用户输入后即时分类（可能延迟）
   - 或用户确认后后台异步分类
   - **建议**：用户确认后后台异步分类，避免阻塞 UI

---

*本文档基于当前代码基线（0425 迭代版）编写，随开发进度动态更新。*
