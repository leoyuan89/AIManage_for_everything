# 0426 阶段项目全景文档

> 用途：涵盖所有已实现模块、核心函数位置及架构设计，用于后续快速定位与迭代。  
> 日期：2026-04-26  
> 版本：v1.0

---

## 一、项目概述

**本地密码保险箱** —— 基于 PyQt6 的密码管理软件，集成本地 Ollama（gemma4:4b）进行智能分类、语义搜索、AI 助手对话、OCR 截图导入等功能。

### 1.1 技术栈

| 层级 | 技术 |
|------|------|
| UI 框架 | PyQt6 6.11.0 |
| 加密 | `cryptography`（PBKDF2-HMAC-SHA256 + AES-256-GCM） |
| 数据库 | SQLite（双库：vault.db + vault_urls.db） |
| AI 引擎 | Ollama（gemma4:4b，仅支持 `/api/generate`） |
| 主题 | qt-material（light_blue / dark_blue） |
| OCR | PaddleOCR |
| 导出 | openpyxl（Excel）、自定义加密备份（.vault）、PWA 密包（.html） |

### 1.2 数据目录

```
~/.local_password_vault/
├── vault.db          # 加密账号库
├── vault_urls.db     # 明文网址库
└── config.json       # salt + theme + AI 配置
```

---

## 二、目录结构与模块清单

```
secretmanage/
├── main.py                    # 程序入口（SetupDialog → LoginDialog → MainWindow）
├── requirements.txt           # 依赖清单
│
├── core/                      # 核心基础设施层
│   ├── crypto.py              # 加密引擎（CryptoManager）
│   ├── database.py            # 主数据库（DatabaseManager）— vault.db
│   ├── url_database.py        # 网址数据库（URLDatabaseManager）— vault_urls.db
│   ├── repositories.py        # Repository 模式统一数据层抽象
│   ├── pinyin.py              # 拼音首字母转换（PinyinConverter）
│   ├── theme_manager.py       # qt-material 主题加载（apply_theme_to_app）
│   ├── clipboard.py           # 剪贴板工具
│   └── password_strength.py   # 密码强度检测
│
├── models/                    # 数据模型层
│   ├── account.py             # Account 数据类
│   └── url_item.py            # URLItem 数据类
│
├── services/                  # 业务逻辑层（Service）
│   ├── ai_service_manager.py      # AI 服务唯一入口（单例 + 后台线程）
│   ├── ai_worker_thread.py        # AI 后台工作线程（任务队列 + 状态探测）
│   ├── ai_assistant_service.py    # 炽阳 AI 助手核心（Plan/Build 双模式）
│   ├── ai_classification_service.py  # AI 智能分类引擎（预分析 → 差异预览 → 生效/回滚）
│   ├── ai_remark_service.py       # AI 一句话备注生成
│   ├── batch_add_processor.py     # 批量导入处理器（文本分块 → AI 解析 → 去重预检）
│   ├── search_service.py          # 同步搜索（精确 + 拼音匹配）
│   ├── semantic_search_service.py # ⚠️ 已废弃（gemma4:4b 不支持 embeddings API）
│   ├── ocr_service.py             # PaddleOCR 截图识别与字段提取
│   ├── conversation_context.py    # 多轮对话上下文管理与指代消解
│   ├── account_service.py         # 账号业务服务（CRUD + 分类管理）
│   ├── url_service.py             # 网址业务服务（CRUD + 分类管理）
│   ├── category_service.py        # 分类服务（缓存 + 规则匹配）
│   ├── tag_service.py             # 标签服务（预定义标签库 + 关键词提取）
│   ├── export_service.py          # 导出服务（Excel / 加密备份 .vault）
│   ├── import_service.py          # 导入服务（.md / .txt / .xlsx）
│   └── sync_service.py            # PWA 同步包生成（加密 HTML 单文件）
│
├── ai/                        # AI HTTP 客户端层
│   └── ollama_client.py       # OllamaClient（generate / stream / categorize / semantic_match / parse_command）
│
├── ui/                        # UI 表现层（PyQt6 Widgets）
│   ├── main_window.py             # 主窗口（3920行，三栏布局 + 炽阳面板 + 搜索 + 字母导航）
│   ├── account_dialog.py          # 账号添加/编辑弹窗（手动输入 + OCR + AI 分类/备注）
│   ├── url_dialog.py              # 网址添加/编辑弹窗
│   ├── ai_classify_dialog.py      # AI 智能分类对话框（完整分类流程）
│   ├── batch_add_preview_widget.py  # 批量导入预览组件（表格 + 勾选 + 批量改分类）
│   ├── import_dialog.py           # 批量导入对话框（调用 import_service）
│   ├── export_dialog.py           # 导出对话框（Excel / 加密备份）
│   ├── settings_dialog.py         # 设置主界面（改密码 / 主题 / AI 助手设置）
│   ├── lock_screen.py             # 锁定屏幕 + 空闲检测（IdleTimer）
│   ├── recycle_bin_dialog.py      # 回收站管理（恢复 / 永久删除 / 清空）
│   └── tag_editor_dialog.py       # 标签编辑器
│
└── docs/                      # 项目文档
```

---

## 三、核心模块详细定位

### 3.1 启动与认证流程

| 功能 | 文件 | 核心类/函数 | 行号 |
|------|------|------------|------|
| 程序入口 | `main.py` | `main()` | L220-334 |
| 首次运行设置主密码 | `main.py` | `SetupDialog` | L31-134 |
| 登录验证（循环） | `main.py` | `LoginDialog` | L136-218 |
| 主题初始化 | `main.py` | `main()` 中 theme loading | L234-245 |
| AI Service Manager 初始化 | `main.py` | `AIServiceManager.instance()` | L331 |

### 3.2 加密引擎（core/crypto.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 密钥派生 + 加解密 | `CryptoManager` | L13-142 |
| 加密 → Base64 字符串 | `encrypt_to_string(plaintext)` | L52-53 |
| 解密 Base64 字符串 | `decrypt_from_string(ciphertext_str)` | L55-56 |
| SHA256 缓存哈希 | `hash_for_cache(text)` | L58-60 |
| 盐值自动生成 | `__init__(master_password, salt=None)` | L30-33 |

**加密参数**：`SALT_LENGTH=32`, `KEY_LENGTH=32`, `NONCE_LENGTH=12`, `ITERATIONS=100000`

### 3.3 数据库层（双库架构）

#### 3.3.1 主库 vault.db（core/database.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 主数据库管理器 | `DatabaseManager` | L13-811 |
| 透明字段加解密 | `_encrypt_field` / `_decrypt_field` | L149-164 |
| 插入账号 | `insert_account` | L202-241 |
| 更新账号 | `update_account` | L243-286 |
| 删除账号 | `delete_account` | L288-328 |
| 软删除（回收站） | `soft_delete_account` | L553-584 |
| 恢复账号（生成新 ID） | `restore_account` | L638-670 |
| 审计日志 | `insert_audit_log` | L519-549 |
| 分类排序 | `get_category_orders` / `save_category_orders` | L391-407 |

**表结构**：`accounts`, `category_cache`, `config`, `snapshots`, `audit_log`, `recycle_bin`, `category_order`

#### 3.3.2 网址库 vault_urls.db（core/url_database.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 网址数据库管理器 | `URLDatabaseManager` | L10-386 |
| 插入网址 | `insert_url` | L100-135 |
| 更新网址 | `update_url` | L137-172 |
| 删除网址 | `delete_url` | L174-196 |
| 分类排序 | `get_category_orders` / `save_category_orders` | L302-318 |

**表结构**：`urls`, `url_categories`, `category_order`

#### 3.3.3 Repository 统一抽象（core/repositories.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 抽象基类 | `VaultRepository` | L79-163 |
| 密码库实现 | `AccountRepository` | L167-344 |
| 网址库实现 | `URLRepository` | L349-531 |
| 单例工厂 | `RepositoryFactory` | L536-553 |
| 批量导入中间格式 | `BatchItem` | L34-63 |

**字段权限**：
- `AccountRepository.ALLOWED_FIELDS = {'category', 'remark', 'ai_remark', 'tags'}`
- `URLRepository.ALLOWED_FIELDS = {'category', 'remark', 'ai_remark', 'tags', 'title', 'url'}`

### 3.4 AI 服务架构

#### 3.4.1 服务管理器入口（services/ai_service_manager.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 单例管理器 | `AIServiceManager` | L30-149 |
| 获取单例 | `instance()` | L38-46 |
| 毫秒级状态查询 | `get_state()` → `AIStateSnapshot` | L64-71 |
| 任务提交（异步） | `submit_task(task_type, payload)` | L100-117 |
| 便捷接口 | `categorize_async`, `generate_remark_async`, `chat_async`, `parse_command_async`, `semantic_search_async`, `classify_batch_async` | L119-149 |

#### 3.4.2 后台工作线程（services/ai_worker_thread.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| AI 状态枚举 | `AIStatus` | L21-26 |
| 状态快照 | `AIStateSnapshot` | L28-44 |
| 线程安全缓存 | `AIStateCache` | L47-60 |
| 任务类型枚举 | `AITaskType` | L63-70 |
| 工作线程主类 | `AIWorkerThread` | L79-350 |
| 主循环 | `run()` | L100-145 |
| Ollama 状态探测 | `_do_probe()` | L210-245 |
| 任务分发处理 | `_process_task()` | L247-296 |

**探测策略**：指数退避 `BACKOFF_INTERVALS = [30, 60, 120, 120]`, `MAX_PROBE_INTERVAL = 300`

#### 3.4.3 Ollama HTTP 客户端（ai/ollama_client.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| HTTP 客户端 | `OllamaClient` | L11-634 |
| 非流式生成 | `generate(prompt, temperature, num_predict)` | L34-73 |
| 流式生成 | `generate_stream` | L75-127 |
| 智能分类 | `categorize` | L162-201 |
| 语义匹配 | `semantic_match` | L309-389 |
| 指令解析 | `parse_command` | L417-507 |
| JSON 提取（容错） | `_extract_command` | L550-634 |

**上下文长度**：`num_ctx=32768`

#### 3.4.4 炽阳 AI 助手（services/ai_assistant_service.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 对话消息 | `ConversationMessage` | L16-24 |
| AI 助手核心服务 | `AIAssistantService` | L26-1094 |
| 有效动作列表 | `VALID_ACTIONS` | L30-32 |
| 只读/写操作权限 | `READONLY_ACTIONS` / `WRITE_ACTIONS` | L34-38 |
| 构建数据库摘要 | `build_db_summary` | L51-133 |
| 主查询入口（Plan） | `process_query` | L201-363 |
| 流式处理入口 | `process_query_stream` | L365-566 |
| 生成操作预览（Build） | `build_action_preview` | L610-760 |
| Plan 模式执行 | `execute_action` | L762-897 |
| Build 模式事务执行 | `execute_build_action_with_transaction` | L899-1000+ |

**指令解析结果结构**：
```python
result = {
    "success": True,
    "thinking": "...",
    "action": "search|filter|list|reorganize|add_remark|delete|add|explain",
    "params": {...},
    "response": "...",
    "semantic_result": {"matched_ids": [...], "reasoning": "...", "confidence_scores": {}},
    "error": ""
}
```

#### 3.4.5 多轮对话上下文（services/conversation_context.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 单轮快照 | `TurnSnapshot` | L13-22 |
| 对话上下文管理 | `ConversationContext` | L25-114 |
| 指代消解器 | `ReferenceResolver` | L117-166 |

**配置**：`max_turns=6`, `idle_timeout=300`（秒）

#### 3.4.6 AI 智能分类（services/ai_classification_service.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 类别提议 | `CategoryProposal` | L18-30 |
| 单条变更记录 | `ClassificationChange` | L33-45 |
| 分类前快照 | `ClassificationSnapshot` | L47-55 |
| 分类引擎 | `AIClassificationService` | L57-732 |
| 预分析（提议分类体系） | `pre_analyze_accounts` / `pre_analyze_urls` | L87-267 |
| 执行分类（分批处理） | `execute_classification` | L269-314 |
| 创建快照 | `create_snapshot` | L316-355 |
| 回滚 | `rollback` | L357-418 |

#### 3.4.7 AI 备注生成（services/ai_remark_service.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 备注生成服务 | `AIRemarkService` | L5-71 |
| 生成一句话备注 | `generate_ai_remark(app_name, url, category)` | L17-71 |

#### 3.4.8 批量导入处理器（services/batch_add_processor.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 批量导入处理器 | `BatchAddProcessor` | L12-306 |
| 文本分块 | `chunk_text(text)` | L26-50 |
| AI 解析 | `parse_batch_text(text, vault_type, ollama_client)` | L53-79 |
| 预检转换 | `prepare_batch_items(parsed_items, repo)` | L168-179 |
| 执行导入 | `execute_batch_add(batch_items, repo)` | L304-306 |

**约束**：`MAX_BATCH_CHARS = 4000`, `MAX_BATCH_ITEMS = 20`

### 3.5 搜索服务

#### 3.5.1 同步搜索（services/search_service.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 搜索结果 | `SearchResult` | L16-22 |
| 搜索服务 | `SearchService` | L24-227 |
| 主搜索入口 | `search(query, accounts)` | L38-101 |
| 精确匹配 | `_exact_match` | L117-154 |
| 拼音匹配 | `_pinyin_match` | L156-171 |
| 语义搜索候选 | `get_remaining_for_semantic` | L103-115 |

**字段权重**：`app_name(1.0) > username(0.9) > url(0.8) > remark(0.7) > tags(0.75) > category(0.6)`

#### 3.5.2 语义搜索（已废弃）

- **文件**：`services/semantic_search_service.py`
- **状态**：⚠️ DEPRECATED（gemma4:4b 不支持 `/api/embeddings` API）
- **替代**：`ai/ollama_client.py::semantic_match()`（基于 `/api/generate` 的文本推理）

### 3.6 OCR 服务（services/ocr_service.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| OCR 服务 | `OCRService` | L19-328 |
| 图片识别 | `recognize_image(image_path)` | L33-71 |
| 提取账号字段 | `extract_account_fields(image_path)` | L73-252 |
| 图片预处理 | `preprocess_image` | L295-328 |

**预处理**：缩放至 1920px、转 RGB

### 3.7 业务服务层

#### 3.7.1 账号服务（services/account_service.py）

| 功能 | 类/函数 |
|------|---------|
| 账号 CRUD | `add_account`, `update_account`, `delete_account`, `get_account`, `get_all_accounts` |
| 分类管理 | `get_categories`, `add_category`, `rename_category`, `delete_category`, `get_accounts_by_category` |
| 搜索 | `search_accounts` |

#### 3.7.2 网址服务（services/url_service.py）

| 功能 | 类/函数 |
|------|---------|
| 网址 CRUD | `add_url`, `update_url`, `delete_url`, `get_url`, `get_all_urls` |
| 分类管理 | `get_categories`, `add_category`, `rename_category`, `delete_category`, `get_urls_by_category` |
| 搜索 | `search_urls` |

**默认分类**：`['全部', '开发工具', '云服务', '社交平台', '学习资源', '娱乐', '购物', '其他']`

#### 3.7.3 分类服务（services/category_service.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 分类服务 | `CategoryService` | L9-203 |
| 获取分类（缓存优先） | `get_category` | L23-72 |
| 规则匹配 | `_rule_based_categorize` | L74-122 |
| AI 分类 | `_ai_categorize` | L124-161 |

**默认分类**：`['社交', '金融', '邮箱', '游戏', '工作', '其他']`

#### 3.7.4 标签服务（services/tag_service.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 标签服务 | `TagService` | L9-183 |
| 生成标签 | `generate_tags` | L29-65 |
| 关键词提取 | `_extract_tags_from_name` | L67-97 |

#### 3.7.5 导出/导入服务

| 功能 | 文件 | 核心类 |
|------|------|--------|
| Excel 导出 | `services/export_service.py` | `ExportService` |
| 加密备份导出 | `services/export_service.py` | `export_encrypted_backup` |
| 批量导入 | `services/import_service.py` | `ImportService` + `ImportItem` |
| PWA 密包生成 | `services/sync_service.py` | `SyncService.generate_pwa_package` |

### 3.8 UI 层（主窗口与对话框）

#### 3.8.1 主窗口（ui/main_window.py，3920 行）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| AI 查询后台线程 | `AIQueryThread` | L39-219 |
| 分段发射模式 | `_run_segmented` | L84-151 |
| 流式模式 | `_run_stream` | L153-211 |
| 账号列表项 | `AccountListItem` | L221-483 |
| 网址列表项 | `URLListItem` | L221-483（内部处理） |
| Build 模式操作预览 | `ActionPreviewWidget` | L485-710 |
| 主窗口 | `MainWindow` | L712-3920 |
| 初始化 UI | `setup_ui` | L814-1568 |
| 字母导航条 | `_build_alpha_nav` | L1570-1602 |
| 加载账号 | `load_accounts` | L1643-1693 |
| 加载网址 | `load_urls` | L1944-1993 |
| 重载分类导航 | `_reload_categories` | L1731-1805 |
| 库切换 | `_on_vault_tab_changed` | L1694-1730 |
| AI 发送消息 | `on_ai_send_message` | L3068-3143 |
| AI 查询完成回调 | `_on_ai_query_finished` | L3145-3372 |
| 高亮匹配条目 | `highlight_matched_accounts` | L3561-3658 |
| 批量选择模式 | `_enter_selection_mode` / `_exit_selection_mode` | L2154-2184 |
| 分类排序编辑 | `_on_category_edit_toggle` / `_save_category_order` | 在 `_reload_categories` 内 |
| 分类批量删除 | `_on_category_batch_delete_toggle` / `_execute_category_batch_delete` | 在 `_reload_categories` 内 |
| 锁定界面 | `show_lock_screen` / `_setup_session_security` | L3784-3839 |
| 同步到手机 | `on_sync_to_mobile` | L3841-3894 |
| 回收站 | `on_recycle_bin` | L3896-3914 |

**三栏 Splitter 尺寸**：`[230, 570, 0]`（左|中|右，AI 面板默认收起）

#### 3.8.2 账号对话框（ui/account_dialog.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| OCR 后台线程 | `OCRWorker` | L40-65 |
| 自定义下拉框 | `PopupComboBox` | L67-248 |
| 两端对齐标签 | `JustifyLabel` | L251-301 |
| 账号对话框 | `AccountDialog` | L303-1244 |
| 手动输入页 | `setup_manual_tab` | L475-668 |
| OCR 截图页 | `setup_ocr_tab` | L670-779 |
| AI 分类 | `on_ai_categorize` | L799-812 |
| AI 生成备注 | `on_ai_generate_remark` | L638-643 |
| AI 任务结果分发 | `_on_ai_task_finished` / `_on_ai_task_failed` | L814-830 |
| 应用 OCR 结果 | `on_apply_ocr_result` | L925-975 |
| 编辑模式回填 | `load_account_data` | L977-999 |

#### 3.8.3 网址对话框（ui/url_dialog.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 网址编辑对话框 | `URLEditDialog` | L19-420 |
| AI 分类 | `on_ai_categorize` | L263-274 |
| AI 生成标签/备注 | `on_ai_generate_tags` / `on_ai_generate_remark` | L276-305 |
| 保存 | `on_save` | L349-389 |
| 删除（软删除） | `on_delete` | L391-410 |

#### 3.8.4 AI 智能分类对话框（ui/ai_classify_dialog.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 预分析后台线程 | `PreAnalysisWorker` | L24-49 |
| 分类执行线程 | `ClassificationWorker` | L51-84 |
| 快照选择对话框 | `SnapshotSelectionDialog` | L86-157 |
| 迁移分组组件 | `MigrationGroupWidget` | L159-311 |
| 类别提议卡片 | `CategoryProposalCard` | L313-441 |
| 智能分类对话框 | `AIClassifyDialog` | L444-852 |
| 启动预分析 | `start_pre_analysis` | L574-588 |
| 显示提议 | `show_proposals` | L606-661 |
| 执行下一步 | `on_next_clicked` | L690-725 |
| 差异视图 | `show_diff_view` | L748-794 |
| 生效 | `on_apply_clicked` | L796-825 |
| 回滚 | `on_rollback_clicked` | L827-842 |

#### 3.8.5 批量导入预览（ui/batch_add_preview_widget.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 分类下拉委托 | `CategoryDelegate` | L20-43 |
| 表格模型 | `BatchItemTableModel` | L45-235 |
| 预览组件 | `BatchAddPreviewWidget` | L237-436 |
| 设置数据 | `set_items` | L303-323 |
| 批量修改分类 | `_on_batch_category` | L355-369 |
| 智能推断分类 | `_on_auto_classify` | L383-426 |

#### 3.8.6 设置对话框（ui/settings_dialog.py）

| 功能 | 类/函数 | 行号 |
|------|---------|------|
| 修改主密码对话框 | `ChangePasswordDialog` | L34-251 |
| 修改密码核心逻辑 | `_do_change_password` | L180-250 |
| 主题设置对话框 | `ThemeSettingsDialog` | L253-377 |
| AI 助手设置 | `AIAssistantSettingsDialog` | L379-498 |
| 设置主界面 | `SettingsDialog` | L501-634 |

#### 3.8.7 其他 UI 组件

| 功能 | 文件 | 核心类 |
|------|------|--------|
| 导入对话框 | `ui/import_dialog.py` | `ImportDialog` |
| 导出对话框 | `ui/export_dialog.py` | `ExportDialog` |
| 锁定屏幕 | `ui/lock_screen.py` | `LockScreen` + `IdleTimer`（5分钟空闲锁定） |
| 回收站对话框 | `ui/recycle_bin_dialog.py` | `RecycleBinDialog` |
| 标签编辑器 | `ui/tag_editor_dialog.py` | `TagEditorDialog` |

---

## 四、架构设计

### 4.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                        UI 层 (ui/)                           │
│  MainWindow · AccountDialog · URLEditDialog · AIClassifyDialog│
│  BatchAddPreviewWidget · SettingsDialog · LockScreen · ...   │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                     业务逻辑层 (services/)                    │
│  AIAssistantService · AIClassificationService · SearchService │
│  AccountService · URLService · ExportService · ImportService  │
│  AIServiceManager（单例入口）· AIWorkerThread（后台线程）      │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                     数据访问层 (core/)                        │
│  RepositoryFactory（单例工厂）                                │
│  ├─ AccountRepository ──→ DatabaseManager（vault.db）        │
│  └─ URLRepository ──────→ URLDatabaseManager（vault_urls.db）│
│  CryptoManager · PinyinConverter · ThemeManager · ...        │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                      外部服务层                               │
│  Ollama（/api/generate）· PaddleOCR · qt-material            │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 AI 交互架构

```
┌──────────────┐     submit_task()      ┌──────────────────┐
│   UI 组件     │ ────────────────────→ │ AIServiceManager │
│ (MainWindow)  │  ← state_changed       │    （单例）       │
│               │  ← task_finished       │                  │
│               │  ← task_failed         │  ┌────────────┐  │
└──────────────┘                        │  │ AIStateCache│  │
                                        │  │ (QMutex)   │  │
                                        │  └────────────┘  │
                                        └────────┬─────────┘
                                                 │ start()
                                                 ↓
                                        ┌──────────────────┐
                                        │  AIWorkerThread   │
                                        │  （后台线程）      │
                                        │                  │
                                        │  ┌────────────┐  │
                                        │  │ 任务队列    │  │
                                        │  │ (deque)    │  │
                                        │  └────────────┘  │
                                        │                  │
                                        │  ┌────────────┐  │
                                        │  │ 状态探测循环 │  │
                                        │  │ 指数退避    │  │
                                        │  │ 30→60→120s  │  │
                                        │  └────────────┘  │
                                        └────────┬─────────┘
                                                 │
                              ┌──────────────────┼──────────────────┐
                              ↓                  ↓                  ↓
                       ┌──────────┐      ┌──────────┐      ┌──────────┐
                       │ categorize│      │ semantic │      │  chat/   │
                       │          │      │ _match   │      │ classify │
                       └──────────┘      └──────────┘      └──────────┘
                              ↓                  ↓                  ↓
                       ┌──────────────────────────────────────────────┐
                       │        ai/ollama_client.py                    │
                       │         OllamaClient                           │
                       │   generate() / generate_stream()               │
                       │   categorize() / semantic_match()              │
                       │   parse_command()                              │
                       └──────────────────────────────────────────────┘
                              ↓
                       ┌──────────────┐
                       │ Ollama HTTP  │
                       │ /api/generate │
                       └──────────────┘
```

### 4.3 双库数据流

```
              密码库（accounts）                    网址库（urls）
                  vault.db                           vault_urls.db
                     ↑                                    ↑
        ┌────────────┴────────────┐          ┌───────────┴───────────┐
        │   DatabaseManager       │          │  URLDatabaseManager   │
        │  （字段级 AES-256-GCM）  │          │      （明文）          │
        │                         │          │                       │
        │  accounts               │          │  urls                 │
        │  recycle_bin            │          │  url_categories       │
        │  category_order         │          │  category_order       │
        │  snapshots              │          └───────────────────────┘
        │  audit_log              │                    ↑
        └─────────────────────────┘                    │
                     ↑                                 │
        ┌────────────┴────────────┐                    │
        │   AccountRepository     │    ← RepositoryFactory →    URLRepository
        │   ALLOWED_FIELDS        │         （单例工厂）          ALLOWED_FIELDS
        │   {category, remark,    │                              {category, remark,
        │    ai_remark, tags}     │                               ai_remark, tags,
        │                         │                               title, url}
        └─────────────────────────┘
                     ↑
        ┌────────────┴────────────┐
        │  AccountService / AI    │
        │  AssistantService / ... │
        └─────────────────────────┘
```

### 4.4 启动流程

```
main.py
  │
  ├─→ QApplication 创建
  ├─→ 主题加载（qt-material light_blue / dark_blue）
  ├─→ 判断 vault.db 存在性
  │     ├─ 不存在 → SetupDialog（设置主密码 ≥ 6 位）
  │     │            → 创建 salt → 创建 CryptoManager → 创建 vault.db
  │     └─ 存在 → LoginDialog（循环验证主密码）
  │                  → 尝试解密数据库首条记录校验
  ├─→ DatabaseManager 初始化
  ├─→ URLDatabaseManager 初始化
  ├─→ RepositoryFactory 注册 AccountRepository + URLRepository
  ├─→ AIServiceManager.instance() 初始化（后台线程自动探测 Ollama）
  └─→ MainWindow 显示
```

### 4.5 搜索链路

```
用户输入搜索词
     │
     ↓
┌──────────────┐
│ SearchService │
│   .search()   │
└──────┬───────┘
       │
       ├─→ 精确匹配（_exact_match）
       │     字段权重：app_name > username > url > remark > tags > category
       │
       └─→ 无结果且查询为字母时 → 拼音匹配（_pinyin_match）
             ↓
       core/pinyin.py::PinyinConverter
```

### 4.6 双模式安全架构（AI 助手）

```
┌─────────────────────────────────────────────────────────────┐
│                        Plan 模式（只读）                       │
│  • search / filter / list / explain                          │
│  • 直接执行，联动左侧列表高亮                                  │
│  •  reorganize / add_remark / delete / add → 仅返回建议文本    │
│  • 右侧回复末尾附加提示："切换到 Build 模式并经你确认后可执行"   │
└─────────────────────────────────────────────────────────────┘
                              ↓ 用户主动切换
┌─────────────────────────────────────────────────────────────┐
│                       Build 模式（可写）                       │
│  • 安全操作（search/filter/list）→ 直接执行                    │
│  • 写操作（reorganize/add_remark/delete/add）                  │
│    → build_action_preview() 生成结构化预览                     │
│    → ActionPreviewWidget 显示（用户可勾选/取消）                │
│    → 用户确认 → execute_build_action_with_transaction()        │
│    → 逐条执行 + audit_log 审计日志                             │
│    → delete > 50 条需二次确认                                   │
│  • batch_add_account / batch_add_url                          │
│    → BatchAddPreviewWidget 预览 → 确认导入                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 五、关键设计模式与约定

### 5.1 单例模式

| 类 | 文件 | 获取方式 |
|----|------|---------|
| `AIServiceManager` | `services/ai_service_manager.py` | `AIServiceManager.instance()` |
| `RepositoryFactory` | `core/repositories.py` | `RepositoryFactory.get_repository(vault_type)` |

### 5.2 后台线程模式

| 线程类 | 用途 | 所在文件 |
|--------|------|---------|
| `AIWorkerThread` | AI 任务队列 + 状态探测 | `services/ai_worker_thread.py` |
| `AIQueryThread` | AI 助手查询（避免 GPU 阻塞 UI） | `ui/main_window.py` L39-219 |
| `OCRWorker` | PaddleOCR 识别 | `ui/account_dialog.py` L40-65 |
| `PreAnalysisWorker` | AI 分类预分析 | `ui/ai_classify_dialog.py` L24-49 |
| `ClassificationWorker` | AI 分类执行 | `ui/ai_classify_dialog.py` L51-84 |

### 5.3 缓存策略

| 缓存对象 | 所在类 | 脏标记 | 触发刷新条件 |
|----------|--------|--------|-------------|
| `_cached_accounts` | `MainWindow` | `_cache_dirty` | 增删改、分类变更、切换分类 |
| `_cached_urls` | `MainWindow` | `_url_cache_dirty` | 增删改、分类变更、切换分类 |

### 5.4 信号-槽机制（关键信号）

| 信号 | 发射方 | 接收方 | 用途 |
|------|--------|--------|------|
| `state_changed(AIStateSnapshot)` | `AIServiceManager` | `MainWindow._on_ai_state_changed` | AI 状态更新底部栏 |
| `task_finished(task_id, result)` | `AIServiceManager` | `AccountDialog._on_ai_task_finished` | AI 分类/备注结果 |
| `task_failed(task_id, error)` | `AIServiceManager` | `AccountDialog._on_ai_task_failed` | AI 任务失败 |
| `result_ready(str)` | `AIQueryThread` | `MainWindow._on_ai_query_finished` | AI 助手查询完成 |
| `thinking_token(str)` | `AIQueryThread` | `MainWindow._on_thinking_token` | 思考过程流式输出 |
| `result_token(str)` | `AIQueryThread` | `MainWindow._on_result_token` | 结果分段输出 |

### 5.5 加密备份格式（.vault 文件）

```
第一行：salt（Base64）
第二行：加密数据（Base64 封装的 AES-256-GCM 密文）
```

导入时使用用户输入的密码 + 文件中的 salt 创建 `CryptoManager` 解密。

---

## 六、快速定位索引（按功能找代码）

### 6.1 账号管理

| 功能 | 文件 | 函数/类 |
|------|------|---------|
| 添加账号 | `ui/account_dialog.py` | `AccountDialog` |
| 编辑账号 | `ui/account_dialog.py` | `load_account_data` |
| 删除账号（软删除） | `core/database.py` | `soft_delete_account` |
| 批量删除 | `ui/main_window.py` | `_execute_batch_delete` |
| 回收站恢复 | `core/database.py` | `restore_account` |
| 账号列表展示 | `ui/main_window.py` | `load_accounts`, `AccountListItem` |

### 6.2 网址管理

| 功能 | 文件 | 函数/类 |
|------|------|---------|
| 添加/编辑网址 | `ui/url_dialog.py` | `URLEditDialog` |
| 网址列表展示 | `ui/main_window.py` | `load_urls`, `URLListItem` |
| 网址删除 | `ui/url_dialog.py` | `on_delete` |

### 6.3 分类管理

| 功能 | 文件 | 函数/类 |
|------|------|---------|
| 获取分类列表 | `services/account_service.py` | `get_categories` |
| 新增分类 | `services/account_service.py` / `url_service.py` | `add_category` |
| 重命名分类 | `services/account_service.py` / `url_service.py` | `rename_category` |
| 删除分类（条目移至"其他"） | `services/account_service.py` / `url_service.py` | `delete_category` |
| 分类自定义排序 | `core/database.py` / `url_database.py` | `save_category_orders` |
| 拖拽排序 UI | `ui/main_window.py` | `_reload_categories`（编辑模式） |
| 批量删除分类 UI | `ui/main_window.py` | `_on_category_batch_delete_toggle` |

### 6.4 AI 功能

| 功能 | 文件 | 函数/类 |
|------|------|---------|
| AI 智能分类（预分析） | `services/ai_classification_service.py` | `pre_analyze_accounts` |
| AI 智能分类（执行） | `services/ai_classification_service.py` | `execute_classification` |
| AI 智能分类（UI） | `ui/ai_classify_dialog.py` | `AIClassifyDialog` |
| AI 助手对话 | `services/ai_assistant_service.py` | `AIAssistantService` |
| AI 助手面板 | `ui/main_window.py` | `on_ai_send_message`, `_on_ai_query_finished` |
| AI 生成备注 | `services/ai_remark_service.py` | `generate_ai_remark` |
| 批量导入（AI 解析） | `services/batch_add_processor.py` | `parse_batch_text` |
| 语义匹配 | `ai/ollama_client.py` | `semantic_match` |
| OCR 截图导入 | `services/ocr_service.py` | `extract_account_fields` |

### 6.5 搜索

| 功能 | 文件 | 函数/类 |
|------|------|---------|
| 精确搜索 | `services/search_service.py` | `_exact_match` |
| 拼音搜索 | `services/search_service.py` | `_pinyin_match` |
| 语义搜索 | `ai/ollama_client.py` | `semantic_match` |
| 搜索 UI | `ui/main_window.py` | `on_search` |
| 高亮结果 | `ui/main_window.py` | `highlight_matched_accounts` |
| 字母导航 | `ui/main_window.py` | `_build_alpha_nav` |

### 6.6 导入导出

| 功能 | 文件 | 函数/类 |
|------|------|---------|
| Excel 导出 | `services/export_service.py` | `export_to_excel` |
| 加密备份导出 | `services/export_service.py` | `export_encrypted_backup` |
| Excel/文本导入 | `services/import_service.py` | `ImportService` |
| 批量导入预览 | `ui/batch_add_preview_widget.py` | `BatchAddPreviewWidget` |
| PWA 同步包 | `services/sync_service.py` | `generate_pwa_package` |

### 6.7 安全

| 功能 | 文件 | 函数/类 |
|------|------|---------|
| 加密引擎 | `core/crypto.py` | `CryptoManager` |
| 修改主密码 | `ui/settings_dialog.py` | `ChangePasswordDialog._do_change_password` |
| 锁定屏幕 | `ui/lock_screen.py` | `LockScreen` |
| 空闲检测 | `ui/lock_screen.py` | `IdleTimer`（5分钟） |
| 审计日志 | `core/database.py` | `insert_audit_log` |

---

## 七、已知问题与注意事项

### 7.1 代码体积

- **`ui/main_window.py` 长达 3920 行**：AI 面板与列表交互逻辑集中，后续维护需拆分（可考虑提取 `AIChatPanel`, `AccountListPanel`, `CategorySidebar` 等子组件）。

### 7.2 废弃模块

- **`services/semantic_search_service.py` 已废弃**：gemma4:4b 不支持 `/api/embeddings` API，新代码禁止引用。语义匹配请使用 `ai/ollama_client.py::semantic_match()`。

### 7.3 稳定性风险

- **BatchAddProcessor JSON 稳定性**：模型偶发输出非标准 JSON，依赖 `_parse_json_response`（`ollama_client.py::_extract_command`）的容错解析（括号深度计数法）。
- **PopupComboBox 跨平台兼容性**：`ui/account_dialog.py` 中自定义 `QWidget` 模拟下拉框，使用 `Qt.WindowType.Popup` + `QListWidget` 完全自绘，已解决原生 `QComboBox` 的展开延迟/遮挡问题，但需关注不同平台 Popup 行为差异。

### 7.4 内存安全

- **流式输出安全保护**：`MainWindow._on_thinking_token` 和 `_on_result_token` 中均检查 `_ai_query_running` 标志，查询结束后丢弃延迟到达的 token，防止 `0xC0000409`（STATUS_STACK_BUFFER_OVERRUN）崩溃。
- **信号断开机制**：`_on_ai_query_finished` 中立即断开 `thinking_token` 和 `result_token` 信号连接，并释放线程引用。

### 7.5 数据一致性

- **网址删除的双库操作**：网址软删除需先备份到主库回收站（`db.soft_delete_url`），再删除网址表记录（`_url_db.delete_url`），两处操作需保持一致。
- **分类排序持久化**：`category_order` 表独立维护，分类增删改后需调用 `_reload_categories()` 刷新 UI 和缓存。

---

## 八、后续迭代建议

1. **拆分 main_window.py**：将 AI 面板、列表区域、分类导航、底部工具栏分别提取为独立 QWidget 子类。
2. **semantic_search_service.py 清理**：确认无其他模块引用后可删除，或保留作为注释说明。
3. **PopupComboBox 提取**：若其他对话框也需要自定义下拉框，可提取为 `ui/components/popup_combo_box.py`。
4. **AI 流式输出优化**：当前为"先获取完整结果再分段发射"，未来可考虑真正的流式生成（需配合 `OllamaClient.generate_stream`）。
5. **单元测试覆盖**：核心业务逻辑（`ai_assistant_service.py`, `batch_add_processor.py`, `crypto.py`）建议补充单元测试。

---

*文档结束。如有模块更新，请及时同步本文档。*
