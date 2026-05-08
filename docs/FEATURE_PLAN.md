# 功能提升实施计划

> 版本：v2.0 | 日期：2026-05-07 | 状态：待实施
>
> 基于代码审计和用户体验分析，计划实施 **20 项功能提升**，目标从"可用工具"提升为"桌面级专业密码管理器"。

---

## 一、优先级总览

| 优先级 | 数量 | 核心目标 | 预计工时 |
|--------|------|---------|---------|
| **P0 — 桌面级标配** | 4 | 补齐密码管理器基础能力 | 2 天 |
| **P1 — 竞争力提升** | 6 | 拉开与其他本地管理器的差距 | 1 周 |
| **P2 — 差异化亮点** | 6 | AI 能力 + 专业特性 | 2-3 周 |
| **P3 — 锦上添花** | 3 | 完善体验细节 | 1 周 |

---

## 二、前置条件

实施前需先完成：

1. **修复 SQL 注入风险**：`database.py:1004` `cleanup_old_snapshots` 使用 f-string 拼接 SQL，改为参数化查询
2. **提升 PBKDF2 迭代次数**：`crypto.py` 从 100,000 提升到 OWASP 推荐的 600,000（启动验证会慢约 0.5 秒，需告知用户）
3. **AI 分类 prompt 提取到独立文件**：`ai_assistant_service.py` 中 ~240 行硬编码的提示词字符串提取到 `prompts/classify_prompt.txt`，方便后续修改提示词内容，不改动内容本身（token 预算 32K 足够，无需额外控制）
4. **主窗口 closeEvent 补全**：断开 AI 信号、停止定时器，解决内存泄漏

---

## 三、P0 功能：桌面级标配（4 项）

### 3.1 密码生成器

**目标**：账号编辑弹窗内置密码生成器，一键生成强密码。

**实现要点**：
- 新建 `core/password_generator.py`，函数接口 `generate_password(length=16, upper=True, lower=True, digits=True, symbols=True)`
- 使用 Python `secrets` 模块（加密安全随机源，非 `random`）
- 特殊字符限定安全集合：`!@#$%^&*-_=+`，排除引号、反斜杠、反引号
- 生成器 UI：`account_dialog.py` 密码输入框右侧加"生成"按钮 + 齿轮图标（点击弹出配置面板）
- 配置面板：长度滑块（8-64），四个复选框（大写/小写/数字/符号），实时预览
- `url_dialog.py` 同步添加
- 生成后自动填充密码字段，同步触发密码强度评估

**涉及文件**：
- 新建 `core/password_generator.py`
- 修改 `ui/account_dialog.py`、`ui/url_dialog.py`

---

### 3.2 一键复制按钮

**目标**：列表每行右侧固定显示三个复制按钮（📋复制网址、👤复制账号、🔑复制密码），无需进入弹窗。

**实现要点**：
- 修改 `ui/widgets/account_list_item.py`：layout 最右侧添加三个 QPushButton 图标按钮
- 修改 `ui/widgets/url_list_item.py`：同理
- 按钮样式：24x24px 圆角图标，浅色背景，hover 变蓝
- 🔑 密码按钮：调用 `ClipboardManager.copy_text(password)`，20 秒后自动清除
- 👤 账号按钮：复制用户名
- 📋 URL 按钮：复制网址
- 点击后显示 toast：底部状态栏"✅ 密码已复制（20 秒后清除）"，倒计时刷新，清除后显示"🔒 剪贴板已清空"

**涉及文件**：
- 修改 `ui/widgets/account_list_item.py`、`ui/widgets/url_list_item.py`
- 修改 `ui/main_window.py`（toast 逻辑）

---

### 3.3 密码健康仪表盘

**目标**：一键检测所有存储密码的健康状况，报告弱密码、重复密码和泄露风险。

**实现要点**：
- 新建 `ui/dialogs/health_check_dialog.py`
- **弱密码检测**：复用 `evaluate_password_strength()` 对所有账号评分，标记"弱"和"中"
- **重复密码检测**：解密所有密码，计算哈希值，找出同一密码用于多个账号的组
- **泄露检测（HIBP k-anonymity）**：SHA-1 哈希 → 取前 5 位 → 请求 `https://api.pwnedpasswords.com/range/{前5位}` → 本地比对返回后缀 → 匹配则标记为泄露
  - 网络超时 5 秒，失败提示"网络不可用，跳过泄露检测"
  - 密码原文和完整哈希从未离开本地，只传前 5 位哈希前缀
- 报告 UI：顶部总览卡片（总账号数/弱密码数/重复组数/泄露数）→ 三项分类列表 → 底部 AI 安全建议
- 每项可点击跳转编辑弹窗
- 入口：主窗口底部工具栏加"🔒 密码健康"按钮

**涉及文件**：
- 新建 `ui/dialogs/health_check_dialog.py`
- 修改 `ui/main_window.py`（按钮入口）

---

### 3.4 撤销支持（60 秒）

**目标**：批量删除后显示 60 秒撤销横幅，可一键恢复被删条目。

**实现要点**：
- 数据库层已有 snapshots 表，删除前调用 `db.create_snapshot(type="batch_delete", data=被删条目的完整 JSON)`
- 删除后在列表顶部显示横幅："已删除 N 个条目至回收站  [撤销] [✕]"
- 撤销按钮：从 snapshots 表读取最近快照，逐条恢复 insert，删除快照记录
- 60 秒后横幅自动消失（QTimer），快照保留直到撤销或软件关闭
- `Ctrl+Z` 快捷键在批量删除后直接触发撤销

**涉及文件**：
- 修改 `ui/main_window.py`（撤销横幅 + Ctrl+Z）
- 修改 `core/database.py`（完善快照恢复方法）

---

## 四、P1 功能：竞争力提升（6 项）

### 4.1 从其他密码管理器导入

**目标**：支持从 Bitwarden、LastPass、1Password、KeePass 导入数据。

**实现要点**：
- 新建 `services/import_service.py`，包含各格式解析器
- **Bitwarden CSV**：`name,url,username,password,notes,folder` → folder 映射为分类
- **Bitwarden JSON**：items 数组，含 login 对象
- **LastPass CSV**：`url,username,password,name,extra,grouping` → grouping 映射为分类
- **1Password CSV**：自动检测列标题自适应映射
- **KeePass XML**：解析 Entry 节点
- 导入前自动检测格式（扩展名 + 内容特征），显示预览弹窗（可取消勾选、可选目标分类）
- 入口：主窗口底部工具栏"导入"下拉菜单 → "从其他管理器导入"

**涉及文件**：
- 新建 `services/import_service.py`
- 新建 `ui/dialogs/import_preview_dialog.py`
- 修改 `ui/main_window.py`（入口按钮）

---

### 4.2 收藏功能

**目标**：左侧分类树顶部新增"⭐ 收藏"项，常用账号可一键访问。

**实现要点**：
- 数据库：`accounts` 表和 `urls` 表各新增 `is_favorite INTEGER DEFAULT 0` 字段
- `account_service` / `url_service` 新增 `toggle_favorite(id)` 和 `get_favorites()` 方法
- 分类树顶部插入"⭐ 收藏"项（排在"全部"前面），点击只显示已收藏条目
- 列表项右键菜单："添加到收藏"/"取消收藏"
- `AccountListItem` / `URLListItem` 左上角显示 ⭐ 标识
- "收藏"分类下扁平列表，不支持子分类

**涉及文件**：
- 修改 `core/database.py`（schema migration）
- 修改 `services/account_service.py`、`services/url_service.py`
- 修改 `ui/main_window.py`（分类树 + 右键菜单 + 列表渲染）
- 修改 `ui/widgets/account_list_item.py`（星标显示）

---

### 4.3 弹窗未保存提醒

**目标**：编辑弹窗关闭时若存在未保存修改，弹出确认对话框防止数据丢失。

**实现要点**：
- `AccountDialog` 和 `URLEditDialog` 维护 `_is_dirty` 标志
- 任意字段变化时设置 `_is_dirty = True`
- 重写 `closeEvent` / `reject()`：若 `_is_dirty=True`，弹窗"有未保存的修改，是否保存？[保存] [不保存] [取消]"
- 新增模式（`is_edit_mode=False`）初始不标记为 dirty，实际输入后才标记

**涉及文件**：
- 修改 `ui/account_dialog.py`、`ui/url_dialog.py`

---

### 4.4 搜索历史 + 最近使用

**目标**：搜索框下拉显示历史搜索词，分类树增加"最近使用"项。

**实现要点**：
- `SearchService` 已有 `_search_history`（最多 10 条），直接暴露到 UI
- 搜索框获得焦点时弹出下拉列表（QCompleter 自定义），点击即搜索
- 历史按时间倒序，重复关键词去重
- 分类树新增"🕐 最近使用"项（排在"收藏"之后），读取 `get_recent_accounts()`（已存在于 account_service）
- "最近使用"显示最近修改/查看的 20 个条目

**涉及文件**：
- 修改 `ui/main_window.py`（搜索下拉 + 分类树）
- 修改 `services/search_service.py`（暴露历史）

---

### 4.5 剪贴板自动清除提示

**目标**：复制密码后显示倒计时提示，清除时再次通知用户。

**实现要点**：
- 复制密码后底部状态栏显示："✅ 密码已复制（20 秒后自动清除）"
- QTimer 每秒刷新倒计时："（15 秒）"→"（14 秒）"→...
- 清除时显示："🔒 剪贴板已清空"，3 秒后消失
- 配置项 `clipboard_clear_delay` 加入 config.json（默认 20 秒）
- 用户再次复制前若清除计时未到，重置计时器

**涉及文件**：
- 修改 `ui/main_window.py`（toast 逻辑）
- 修改 `core/clipboard.py`（可配置延迟）
- 修改 `main.py`（config 加载）

---

### 4.6 密码强度即时建议

**目标**：编辑密码时实时给出具体的强度改进建议，不只是"弱/中/强"标签。

**实现要点**：
- `password_strength_utils.py` 新增 `suggest_improvements(password)` 函数
- 规则检测：长度 < 8 → "增加到 8 位以上"；无大写 → "添加大写字母"；无数字 → "添加数字"；连续字符 → "避免 abc/123 等连续字符"；常见密码 → "避免常见弱密码"
- 密码框下方新增 QLabel，显示 2-3 条建议（红色文字，11pt）
- 每次文本变化触发评估 + 建议
- 强度达到"强"或"极强"时建议区变绿"✅ 密码强度良好"

**涉及文件**：
- 修改 `core/password_strength_utils.py`（新增 `suggest_improvements`）
- 修改 `ui/account_dialog.py`（建议区 UI）

---

## 五、P2 功能：差异化亮点（6 项）

### 5.1 密码历史

**目标**：修改账号密码时保留旧密码加密记录，防止新密码登录失败后无法找回。

**实现要点**：
- 数据库新建 `password_history` 表：`id, account_id, encrypted_password, changed_at`
- `account_dialog.on_save()` 中：编辑模式 + 密码变化时，将旧密码加密插入 history
- 密码框旁增加"密码历史"按钮（🕐 图标），点击弹出子对话框
- 子对话框：日期时间列表 + 密码（点击解密显示 + 一键复制）
- 每个账号保留最近 10 条历史，超出自删最旧
- 删除账号时级联删除其密码历史

**涉及文件**：
- 修改 `core/database.py`（新建表 + CRUD 方法）
- 修改 `ui/account_dialog.py`（按钮 + 历史弹窗）
- 修改 `services/account_service.py`（历史操作封装）

---

### 5.2 批量分类 + 批量标签

**目标**：多选条目后支持批量修改分类和标签。

**实现要点**：
- 选择模式下底部操作栏增加"批量分类"和"批量标签"两个按钮
- **批量分类**：弹出分类选择器 → 更新所有选中条目的分类
- **批量标签**：弹出标签对话框，可选择"添加标签"或"移除标签"模式
- 操作前确认对话框显示影响条目数
- 完成后刷新列表 + reload_categories
- URL 库同步支持

**涉及文件**：
- 修改 `ui/main_window.py`（底部操作栏 + 处理逻辑）

---

### 5.3 高级搜索筛选器

**目标**：搜索框下方增加可折叠筛选面板，按分类、日期、密码强度、标签组合筛选。

**实现要点**：
- 搜索框下方新增折叠面板（QWidget + 展开/收起箭头），默认收起
- 筛选条件：
  - 分类下拉框（多选）
  - 创建/修改日期范围（两个 QDateEdit）
  - 密码强度（弱/中/强/极强 四选一）
  - 有无 URL 复选框
  - 标签关键词输入框
- 定义 `SearchFilter` dataclass → `SearchService.search_advanced(query, filter)`
- 搜索结果显示生效筛选标签（如"筛选：社交 · 弱密码"）
- 筛选条件保存到 config.json，下次恢复
- URL 库同步支持（强度筛选不适用于 URL）

**涉及文件**：
- 修改 `ui/main_window.py`（筛选面板 UI + 逻辑）
- 修改 `services/search_service.py`（新增 `search_advanced`）

---

### 5.4 Bitwarden 兼容导出

**目标**：导出格式新增 Bitwarden CSV，方便迁移数据。

**实现要点**：
- `ExportDialog` 新增"Bitwarden CSV (.csv)"格式选项
- Bitwarden CSV 列：`name, url, username, password, notes, folder`
- 字段映射：`app_name→name, url→url, username→username, password→password(需解密), remark→notes, category→folder`
- URL 库导出同理

**涉及文件**：
- 修改 `ui/export_dialog.py`
- 修改 `services/export_service.py`

---

### 5.5 列表列自定义

**目标**：列表顶部右键菜单可勾选显示/隐藏各信息列。

**实现要点**：
- 列表标题栏右键菜单：复选框含应用名、账号（脱敏）、密码强度、分类标签、更新时间
- 配置存储：config.json 中 `list_columns` 项，记录每列可见状态
- `AccountListItem` / `URLListItem` 根据配置动态隐藏/显示子控件
- 应用名始终可见（不可隐藏）
- 密码库和网址库各自独立保存列配置

**涉及文件**：
- 修改 `ui/main_window.py`（右键菜单 + 配置加载）
- 修改 `ui/widgets/account_list_item.py`、`ui/widgets/url_list_item.py`
- 修改 `main.py`（config 加载）

---

### 5.6 AI 安全建议

**目标**：健康检测报告中，对弱密码和重复密码给出 AI 驱动的总体改进建议。

**实现要点**：
- 健康检测完成后，收集问题列表（问题类型 + 涉及应用名/分类，不传密码原文）
- 发送给本地 AI（Ollama）请求生成 3-5 条总体安全建议
- 建议显示在健康报告底部，markdown 渲染
- AI 不可用时回退到通用规则建议

**涉及文件**：
- 修改 `ui/dialogs/health_check_dialog.py`

---

## 六、P3 功能：锦上添花（3 项）

### 6.1 仪表盘统计页

**目标**：新增"首页"视图，展示密码库整体统计信息。

**实现要点**：
- 分类树顶部新增"🏠 首页"项，点击渲染仪表盘视图（而非账号列表）
- 仪表盘内容（QPainter 自定义绘制，不依赖外部图表库）：
  - (1) 顶部概览卡片：总条目数 / 密码库 / 网址库 / 本周新增（4 个卡片横向排列）
  - (2) 密码强度环形饼图（`QPainter.drawPie`），四色区分弱/中/强/极强
  - (3) 分类分布横向柱状图：Top 5 分类 + "其他"
  - (4) 最近添加列表：最近 5 条新增条目（可点击跳转编辑）
- 数据进入首页时计算一次，切换到其他视图时保留缓存
- URL 库切换时仪表盘自动切换为网址库统计

**涉及文件**：
- 新建 `ui/widgets/dashboard_widget.py`
- 修改 `ui/main_window.py`（分类树 + 视图切换）

---

### 6.2 紧凑视图模式

**目标**：提供紧凑列表视图，行高缩小、隐藏图标，适合条目多时快速浏览。

**实现要点**：
- 列表顶部标题栏右侧新增视图切换按钮（列表图标 / 紧凑图标）
- **标准模式**：56px 行高，图标 + 应用名 + 脱敏账号 + 分类标签 + 复制按钮
- **紧凑模式**：32px 行高，隐藏圆形图标，应用名 + 账号并排，字号缩小，分类变纯文字
- 切换通过 `set_compact_mode(enabled)` 方法实现
- 切换时重建列表，保持视图模式（搜索/分类/AI 高亮）
- 配置存储到 config.json，下次启动恢复
- 密码库和网址库各自独立保存视图偏好

**涉及文件**：
- 修改 `ui/main_window.py`（切换按钮 + 重建逻辑）
- 修改 `ui/widgets/account_list_item.py`、`ui/widgets/url_list_item.py`

---

### 6.3 退出自动备份

**目标**：每次正常退出时自动备份数据库文件，保留最近 5 份备份。

**实现要点**：
- 主窗口 `closeEvent` 中增加备份逻辑
- 备份目录：`~/.local_password_vault/backups/`
- 备份文件命名：`vault_backup_YYYYMMDD_HHMMSS.db`
- 分别备份 `vault.db`（密码库）和 `vault_urls.db`（网址库）
- 保留策略：每次备份后删除超过 5 份的最旧备份
- 登录界面增加"从备份恢复"按钮：选择备份文件 → 覆盖当前数据库 → 提示重启
- 使用 `shutil.copy2()` 保留文件时间戳

**涉及文件**：
- 修改 `ui/main_window.py`（closeEvent）
- 修改 `ui/lock_screen.py` 或 `main.py`（登录界面恢复按钮）

---

## 七、实施顺序

按依赖关系和影响排序（`[P]` 标注可并行项）：

| 天次 | 功能 | 依赖 |
|------|------|------|
| **第 1 天** | `[P]` 前置修复（SQL 注入、PBKDF2、closeEvent）<br>`[P]` 密码生成器<br>`[P]` 一键复制按钮 | 无依赖，三个可并行 |
| **第 2 天** | 剪贴板 toast 提示<br>未保存提醒<br>收藏功能 | toast 依赖复制按钮 |
| **第 3 天** | `[P]` 密码历史<br>`[P]` 搜索历史 + 最近使用<br>`[P]` 密码强度建议 | 无依赖，三个可并行 |
| **第 4 天** | 密码健康仪表盘（含 HIBP）<br>AI 安全建议 | 依赖密码生成器/强度评估 |
| **第 5 天** | `[P]` 撤销支持<br>`[P]` 列表列自定义<br>`[P]` 紧凑视图 | 无依赖 |
| **第 6 天** | `[P]` 高级搜索筛选器<br>`[P]` 批量分类 + 批量标签 | 无依赖 |
| **第 7 天** | `[P]` 从其他管理器导入<br>`[P]` Bitwarden 导出<br>`[P]` 仪表盘统计页 | 三个可并行 |
| **第 8 天** | 退出自动备份<br>全面测试 + Bug 修复 | 无依赖 |

---

## 八、并行开发策略

若使用多 Agent 并行开发，按文件归属分组避免冲突：

| Agent | 负责文件 | 功能 | 冲突风险 |
|-------|---------|------|---------|
| **A** | `core/password_generator.py`（新建）+ `ui/account_dialog.py`（小改） | 密码生成器 | 低 |
| **B** | `ui/widgets/account_list_item.py` + `ui/widgets/url_list_item.py` + `ui/main_window.py`（小改） | 一键复制 + toast | 与 A 无冲突 |
| **C** | `core/database.py` + `services/account_service.py` + `ui/account_dialog.py` | 密码历史 + 收藏 | account_dialog 与 A 冲突，需错开 |
| **D** | `ui/dialogs/health_check_dialog.py`（新建）+ `ui/main_window.py`（入口） | 密码健康仪表盘 | main_window 与 B 需协调 |
| **E** | `services/import_service.py`（新建）+ `ui/main_window.py`（入口） | 从其他管理器导入 | main_window 与 B/D 需协调 |
| **F** | `ui/export_dialog.py` + `services/export_service.py` | Bitwarden 导出 | 无冲突 |
| **G** | `ui/widgets/dashboard_widget.py`（新建）+ `ui/main_window.py`（入口） | 仪表盘 | main_window 与 B/D/E 需协调 |

**建议**：所有 Agent 先完成各自独立文件的创建/修改，最后统一协调修改 `main_window.py` 中的入口按钮和菜单注册。

---

## 九、风险与注意事项

- PBKDF2 迭代从 100K 提升到 600K 会使启动验证变慢约 0.5-1 秒，需要提前告知用户
- HIBP 泄露检测需要网络请求，首次使用时需确认网络可用性
- 密码历史表存储加密后的旧密码，安全性与当前密码存储等同
- 从其他管理器导入时分类映射可能不精确（不同管理器分类结构不同），需提供预览让用户手动调整
- `main_window.py` 当前约 5700 行，多次并行修改入口需注意合并冲突
- 所有数据库结构变更（收藏、密码历史）需做 schema migration，不能直接覆盖现有数据
- AI prompt 提取到独立文件时不改动内容，单纯从代码中移到 `prompts/` 目录方便编辑
- Token 预算 32K 足够（Gemma4:4b 上下文窗口充足），无需额外管控

---

## 十、验收标准

- 所有 20 项功能在浅色/深色两种主题下视觉效果正常
- 22 个现有单元测试全部通过，无回归 bug
- 新增功能的核心逻辑有对应的单元测试覆盖
- 密码库和网址库双库所有功能行为一致
- 视图持久化（搜索/分类/AI 高亮）在新增功能操作后仍保持
