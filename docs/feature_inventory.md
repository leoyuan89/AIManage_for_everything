# SecretManage 功能清单 —— 已实际实现功能对照表

> **文档日期**：2026-05-10
> **生成方式**：基于代码实际扫描，不做推测
> **用途**：防止开发过程中重复规划已完成功能，方便后续对照

---

## 目录

1. [v2.0 功能规划核对表](#一v20-功能规划核对表)
2. [Core 基础设施层](#二core-基础设施层)
3. [Models 数据模型层](#三models-数据模型层)
4. [Services 业务服务层](#四services-业务服务层)
5. [AI 客户端层](#五ai-客户端层)
6. [UI 用户界面层](#六ui-用户界面层)
7. [主程序与模板](#七主程序与模板)
8. [测试](#八测试)
9. [待确认/待完善项](#九待确认待完善项)

---

## 一、v2.0 功能规划核对表

> 来源：`docs/FEATURE_PLAN.md`（2026-05-07 制定，20 项功能）
> 核对结果：**20/20 项功能已全部实现**，无需重复开发。

| # | FEATURE_PLAN 功能 | 实际状态 | 代码位置 | 备注 |
|---|------------------|---------|---------|------|
| 1 | 密码生成器 | ✅ 已实现 | `core/password_generator.py` | `secrets` 模块，安全字符集，长度/字符类型配置 |
| 2 | 一键复制按钮 | ✅ 已实现 | `ui/widgets/account_list_item.py` | 网址/账号/密码三个复制按钮 + Toast 提示 |
| 3 | 密码健康仪表盘 | ✅ 已实现 | `ui/dialogs/health_check_dialog.py` | 弱密码/重复密码/**HIBP 泄露检测**/**AI 安全建议** |
| 4 | 撤销支持（60秒） | ✅ 已实现 | `ui/main_window.py` | `show_undo_banner()` + `Ctrl+Z` |
| 5 | 从其他密码管理器导入 | ✅ 已实现 | `services/import_service.py` `ManagerImportService` | **Bitwarden CSV/JSON**、**LastPass CSV** |
| 6 | 收藏功能 | ✅ 已实现 | `services/account_service.py` | `toggle_favorite()` + 分类树"⭐ 收藏" |
| 7 | 弹窗未保存提醒 | ✅ 已实现 | `ui/account_dialog.py` | `_is_dirty` 检测 + 确认对话框 |
| 8 | 搜索历史 + 最近使用 | ✅ 已实现 | `services/search_service.py` + `ui/main_window.py` | `_search_history`（10条）+ "🕐 最近使用"节点 |
| 9 | 剪贴板自动清除提示 | ✅ 已实现 | `core/clipboard.py` + `ui/main_window.py` | 20秒自动清除 + Toast 倒计时提示 |
| 10 | 密码强度即时建议 | ✅ 已实现 | `core/password_strength.py` | `evaluate_password_strength()` + `suggest_improvements()` |
| 11 | 密码历史 | ✅ 已实现 | `core/database.py` + `ui/account_dialog.py` | `password_history` 表 + 历史弹窗 |
| 12 | 批量分类 + 批量标签 | ✅ 已实现 | `ui/main_window.py` | `_execute_batch_categorize()` / `_execute_batch_tag()` |
| 13 | 高级搜索筛选器 | ✅ 已实现 | `services/search_service.py` + `ui/main_window.py` | `SearchFilter` + 筛选面板 UI |
| 14 | Bitwarden 兼容导出 | ✅ 已实现 | `services/export_service.py` | `export_bitwarden_csv()` + `ExportDialog` 格式选项 |
| 15 | 列表列自定义 | ✅ 已实现 | `ui/main_window.py` | `_toggle_column()` + `col_config` 持久化 |
| 16 | AI 安全建议 | ✅ 已实现 | `ui/dialogs/health_check_dialog.py` | `AiRecommendationThread` |
| 17 | 仪表盘统计页 | ✅ 已实现 | `ui/widgets/dashboard_widget.py` | 统计卡片/强度分布/重复密码/泄露检测/最近添加 |
| 18 | 紧凑视图模式 | ✅ 已实现 | `ui/main_window.py` + `ui/widgets/` | `_toggle_compact_view()` + 32px/56px 双高度 |
| 19 | 退出自动备份 | ✅ 已实现 | `ui/main_window.py` | `_auto_backup()` + `_cleanup_old_backups()` 保留5份 |
| 20 | 未保存提醒 | ✅ 已实现 | `ui/account_dialog.py` `ui/url_dialog.py` | `closeEvent` / `reject()` 中 dirty 检测 |

---

## 二、Core 基础设施层

### 2.1 `core/crypto.py` — 加密引擎

| 功能 | 方法/常量 | 代码行 |
|------|----------|--------|
| PBKDF2-HMAC-SHA256 密钥派生（600,000 迭代） | `_derive_key()` | L54 |
| AES-256-GCM 加密 | `encrypt()` | L73 |
| AES-256-GCM 解密 | `decrypt()` | L93 |
| 加密 → Base64 字符串 | `encrypt_to_string()` | L117 |
| Base64 字符串 → 解密 | `decrypt_from_string()` | L130 |
| HMAC 防时序攻击密码验证 | `verify_password()` | L143 |
| 更换主密码（重新生成盐值和密钥） | `change_password()` | L156 |
| SHA256 哈希（分类缓存用） | `hash_for_cache()` | L170 |

### 2.2 `core/database.py` — 密码库数据库管理器

**数据表：**

| 表名 | 用途 |
|------|------|
| `accounts` | 账号主表（敏感字段加密存储） |
| `category_cache` | AI 分类缓存（app_name_hash → category） |
| `config` | 通用配置键值对 |
| `snapshots` | 分类快照（用于回滚） |
| `audit_log` | AI 操作审计日志 |
| `recycle_bin` | 回收站（30天过期） |
| `category_order` | 分类自定义排序 |
| `vault_config` | 保险箱配置（session_version/iterations） |
| `password_history` | 密码修改历史（每个账号保留最近10条） |

**核心方法：**

| 功能 | 方法 | 代码行 |
|------|------|--------|
| 嵌套事务上下文管理器 | `_TransactionContext` | 开头 |
| 敏感字段透明加解密 | `_encrypt_field()` / `_decrypt_field()` | L225 |
| 数据库结构自动迁移 | `_migrate_database()` | L251 |
| 账号插入（自动加密） | `insert_account()` | L332 |
| 账号更新 | `update_account()` | L377 |
| 单字段更新（白名单保护） | `update_account_field()` | L419 |
| 账号查重 | `find_duplicate_account()` | L445 |
| SQL 层多关键词搜索（LIMIT 500） | `search_accounts()` | L491 |
| 分类重命名/删除/升级/重组 | `rename/delete/promote/reparent_category()` | L615 |
| 回收站软删除/恢复/永久删除/过期清理 | `soft_delete/restore/permanently_delete/cleanup_expired` | L1035 |
| 快照创建/读取/删除/过期清理 | `insert/get/delete/cleanup_old_snapshots()` | L1219 |
| 审计日志记录 | `insert_audit_log()` | L1000 |
| 泄露检测结果缓存 | `save_breach_results()` / `get_breach_results()` | L930 |

### 2.3 `core/url_database.py` — 网址库数据库管理器

| 功能 | 说明 |
|------|------|
| 数据表 | `urls`、`url_categories`、`category_order`、`url_recycle_bin`、`vault_config` |
| 自动列迁移 | `_ensure_columns()` 运行时自动添加缺失列 |
| 网址 CRUD | `insert/update/delete/get/search_url()` |
| 回收站 | 独立网址库回收站（与密码库隔离） |
| 分类管理 | 完整的重命名/删除/升级/重组 |
| 字段更新白名单 | `update_url_field()` 仅允许 title/url/category/tags/related_account_id/visit_count/ai_remark/remark |
| 泄露缓存 | `save_breach_results()` / `get_breach_results()` |

### 2.4 `core/theme_manager.py` — 主题管理

| 功能 | 方法 | 说明 |
|------|------|------|
| Light/Dark 双主题色板 | `ThemeColors` dataclass | 约 40 个颜色字段 |
| 单例模式（线程安全） | `instance()` | 双重检查锁定 |
| 应用级主题切换 | `apply_theme()` | 发射 `theme_changed` 信号 |
| 后台预加载另一主题 | `_preload_theme()` | 跳过 SVG 生成，切换无卡顿 |
| 35+ 图标映射 | `_ICON_MAP` | `qtawesome` 图标缓存 |
| 常用控件样式工厂 | `style_button_primary/danger()`、`style_bar/panel/input/scrollbar()` | |

### 2.5 其他 Core 模块

| 文件 | 功能 | 关键方法 |
|------|------|---------|
| `core/clipboard.py` | 剪贴板管理（20秒自动清除） | `copy_text()`、`clear()` |
| `core/password_generator.py` | 密码生成（`secrets` 模块） | `generate_password()` |
| `core/password_strength.py` | 密码强度评估 + 改进建议 | `evaluate_password_strength()`、`suggest_improvements()` |
| `core/repositories.py` | 仓库模式（Account/URL Repository + Factory） | `AccountRepository`、`URLRepository`、`RepositoryFactory` |
| `core/category_utils.py` | 分类路径解析/校验/树形构建 | `parse_category_path()`、`validate_category_name()`、`build_category_tree()` |
| `core/pinyin.py` | 中文转拼音首字母搜索 | `get_pinyin_initials()`、`match_pinyin()` |
| `core/logger.py` | 日志配置（控制台 INFO + 文件 DEBUG 按天轮转） | `setup_logging()` |
| `core/constants.py` | 全局常量（数据目录/数据库路径/备份目录等） | `DATA_DIR`、`VAULT_DB_PATH`、`BACKUP_DIR` 等 |

---

## 三、Models 数据模型层

| 文件 | 类 | 字段 | 方法 |
|------|-----|------|------|
| `models/account.py` | `Account` | id, app_name, url, username, password, category, tags, remark, ai_remark, security_level, is_favorite, last_password_change, created_at, updated_at | `get_tags_list()`、`from_dict()`、`to_dict()`、`mask_username()` |
| `models/url_item.py` | `URLItem` | id, title, url, category, tags, related_account_id, password, visit_count, ai_remark, remark, is_favorite, created_at, updated_at | `get_tags_list()`、`from_dict()`、`to_dict()` |

---

## 四、Services 业务服务层

### 4.1 数据服务

| 文件 | 类 | 核心功能 |
|------|-----|---------|
| `services/account_service.py` | `AccountService` | 账号 CRUD、分类管理（重命名/删除/升级/重组）、收藏、按首字母分组、搜索 |
| `services/url_service.py` | `URLService` | 网址 CRUD、分类管理、收藏、favicon 获取、关键词自动分类 |
| `services/category_service.py` | `CategoryService` | AI 智能分类缓存、规则分类兜底、批量分类未分类条目 |
| `services/tag_service.py` | `TagService` | 规则提取标签、AI 生成标签、标签验证与合并（去重，最多5个） |

### 4.2 导入导出

| 文件 | 类/函数 | 支持格式 |
|------|--------|---------|
| `services/import_service.py` | `MarkdownParser` | Markdown 表格格式、段落格式（## 标题分割） |
| `services/import_service.py` | `TextParser` | 等号/冒号分隔格式、位置推断格式 |
| `services/import_service.py` | `ExcelParser` | Excel `.xlsx/.xls`（首行表头映射） |
| `services/import_service.py` | `ManagerImportService` | **Bitwarden CSV**、**Bitwarden JSON**、**LastPass CSV** |
| `services/import_service.py` | `URLParser` | 文本（每行一个 URL）、Excel、**浏览器收藏夹 HTML**（Chrome/Edge/Firefox） |
| `services/export_service.py` | `ExportService` | **Excel**、**加密备份 .vault**、**Bitwarden CSV**、**HTML 书签**、URL Excel |

### 4.3 搜索

| 文件 | 类 | 功能 |
|------|-----|------|
| `services/search_service.py` | `SearchService` | 精确匹配、拼音匹配、`SearchFilter` 高级筛选（分类/日期/强度/URL/标签）、搜索历史（10条） |
| `services/semantic_search_service.py` | `SemanticSearchService` | ⚠️ 代码存在但标记为 DEPRECATED（gemma4:4b 不支持 `/api/embeddings`） |

### 4.4 AI 服务

| 文件 | 类 | 核心功能 |
|------|-----|---------|
| `services/ai_service_manager.py` | `AIServiceManager` | AI 服务单例管理器、任务队列提交、便捷异步接口（分类/备注/聊天/语义搜索/批量分类） |
| `services/ai_worker_thread.py` | `AIWorkerThread` | 后台工作线程、指数退避状态探测（30s→60s→120s）、任务队列（上限100）、优雅关闭 |
| `services/ai_assistant_service.py` | `AIAssistantService` | AI 助手主服务（History + Action + Query 三 Mixin） |
| `services/assistant/action_mixin.py` | `ActionMixin` | Build 模式操作预览、事务批量执行、审计日志 |
| `services/assistant/history_mixin.py` | `HistoryMixin` | Plan/Build 双模式对话历史管理 |
| `services/assistant/query_mixin.py` | `QueryMixin` | 语义查询、流式处理、**ReAct Tool Calling Agent（最多5轮）** |
| `services/ai_classification_service.py` | `AIClassificationService` | 预分析→提议→差异对比→应用/回滚、快照管理、启发式降级、分批处理（10条/批） |
| `services/ai_remark_service.py` | `AIRemarkService` | 异步备注生成（task_id）、同步备注生成（后台线程） |
| `services/conversation_context.py` | `ConversationContext` | 多轮对话上下文、自适应压缩、观察记录、**指代消解（ReferenceResolver）** |

### 4.5 AI 工具系统

| 文件 | 工具类 | 工具名 | 权限级别 |
|------|--------|--------|---------|
| `services/tools/search_tools.py` | `SemanticSearchAccountsTool` | `semantic_search_accounts` | READONLY |
| `services/tools/search_tools.py` | `SemanticSearchUrlsTool` | `semantic_search_urls` | READONLY |
| `services/tools/filter_tools.py` | `SemanticFilterAccountsTool` | `semantic_filter_accounts` | READONLY |
| `services/tools/filter_tools.py` | `SemanticFilterUrlsTool` | `semantic_filter_urls` | READONLY |
| `services/tools/batch_tools.py` | `BatchAddAccounts/UrlsTool` | `batch_add_accounts/urls` | PREVIEW |
| `services/tools/batch_tools.py` | `BatchUpdateAccounts/UrlsTool` | `batch_update_accounts/urls` | PREVIEW |
| `services/tools/batch_tools.py` | `BatchReorganizeAccounts/UrlsTool` | `batch_reorganize_accounts/urls` | PREVIEW |
| `services/tools/batch_tools.py` | `BatchAddRemarkAccounts/UrlsTool` | `batch_add_remark_accounts/urls` | PREVIEW |
| `services/tools/batch_tools.py` | `BatchAddTagsAccounts/UrlsTool` | `batch_add_tags_accounts/urls` | PREVIEW |
| `services/tools/batch_tools.py` | `BatchDeleteAccounts/UrlsTool` | `batch_delete_accounts/urls` | CONFIRM |
| `services/tools/classify_tools.py` | `SmartClassifyAccounts/UrlsTool` | `smart_classify_accounts/urls` | PREVIEW |
| `services/tools/merge_tools.py` | `SmartMergeDuplicateAccounts/UrlsTool` | `smart_merge_duplicate_accounts/urls` | PREVIEW |
| `services/tools/info_tools.py` | `GetAccount/UrlDetailTool` | `get_account/url_detail` | READONLY |
| `services/tools/info_tools.py` | `ListAllCategoriesTool` | `list_all_categories` | READONLY |
| `services/tools/info_tools.py` | `GetCategoryTreeTool` | `get_category_tree` | READONLY |
| `services/tools/info_tools.py` | `GetStatisticsTool` | `get_statistics` | READONLY |
| `services/tools/info_tools.py` | `GetRecentChangesTool` | `get_recent_changes` | READONLY |
| `services/tools/utility_tools.py` | `GenerateAccount/UrlRemarkTool` | `generate_account/url_remark` | READONLY |
| `services/tools/utility_tools.py` | `GeneratePasswordTool` | `generate_password` | READONLY |
| `services/tools/utility_tools.py` | `CheckPasswordStrengthTool` | `check_password_strength` | READONLY |

### 4.6 其他服务

| 文件 | 类 | 功能 |
|------|-----|------|
| `services/sync_service.py` | `SyncService` | 生成加密 PWA 离线 HTML 密包（单文件） |
| `services/batch_add_processor.py` | `BatchAddProcessor` | AI 批量文本解析、分块处理（4000字符/20条）、重复预检、分类校验 |
| `services/ocr_service.py` | `OCRService` | PaddleOCR 截图识别、智能字段提取（用户名/密码/网址/应用名）、图像预处理 |

---

## 五、AI 客户端层

| 文件 | 类 | 功能 |
|------|-----|------|
| `ai/client_base.py` | `OllamaClient` | 非流式生成、流式生成（失败降级）、结构化输出（`<think>`/`<result>`）、智能分类、多轮对话模拟 |
| `ai/client_semantic.py` | `SemanticClient` | 语义搜索、语义匹配、**本地降级匹配**（关键词+拼音+同义词+SequenceMatcher） |
| `ai/client_tools.py` | `ToolClient` | Tool Call JSON 决策生成、**五层 JSON 解析容错**、指令解析（`<思考>`/`<动作>`/`<回复>`）、正则提取兜底 |
| `ai/client_utils.py` | — | 括号深度计数 JSON 提取、**JSON 语法修复**（中文引号、未转义换行、末尾逗号等） |
| `ai/ollama_client.py` | `OllamaClient` | 聚合导出口，向后兼容便捷函数 |

---

## 六、UI 用户界面层

### 6.1 主窗口 `ui/main_window.py`

| 功能类别 | 具体功能 | 方法名 |
|---------|---------|--------|
| **全局快捷键** | 聚焦搜索框 | `_shortcut_focus_search()` |
| | 删除当前选中 | `_shortcut_delete_current()` |
| | Esc（退出选择/清空搜索/收起 AI 面板） | `_shortcut_escape()` |
| | 切换主题 | `_shortcut_toggle_theme()` |
| | 手动锁定 | `_shortcut_lock()` |
| | 撤销删除 | `_shortcut_undo()` |
| **库切换** | 密码库/网址库 Tab 切换 | `_on_vault_tab_changed()` |
| **分类管理** | 编辑模式（拖拽排序一级分类） | `_on_category_edit_toggle()` |
| | 批量删除模式（带复选框） | `_on_category_batch_delete_toggle()` |
| | 重组模式（跨层级拖拽） | `_on_category_reorganize_toggle()` |
| | DropZone 拖放（子类升为一级） | `_on_drop_zone_dropped()` |
| | 分类批量删除执行 | `_execute_category_batch_delete()` |
| **列表视图** | 紧凑视图/正常视图切换 | `_toggle_compact_view()` |
| | 列显示/隐藏自定义 | `_toggle_column()` |
| | 紧凑视图偏好持久化 | `_save/load_compact_preference()` |
| | 滚动位置保存/恢复 | `_save/restore_scroll_state()` |
| **选择模式** | 进入/退出批量选择 | `_enter/exit_selection_mode()` |
| | 全选/取消全选 | `_toggle_select_all()` |
| | 批量删除 | `_execute_batch_delete()` |
| | 批量分类 | `_execute_batch_categorize()` |
| | 批量标签 | `_execute_batch_tag()` |
| **撤销** | 显示撤销横幅（60秒倒计时） | `show_undo_banner()` |
| | 执行撤销恢复 | `_undo_delete()` |
| **搜索** | 执行搜索 | `on_search()` |
| | 显示搜索结果 | `_display_search_results()` |
| | 高级筛选面板（分类/日期/强度） | `_on_filter_toggle()`、`_on_apply_filter()`、`_on_clear_filter()` |
| **导入导出** | 批量导入（通用格式） | `on_batch_import()` |
| | 从其他管理器导入 | `_on_import_from_manager()` |
| | 导出（Excel/加密备份/CSV/HTML） | `on_export()` |
| **主题** | 应用主题 | `_apply_theme()` |
| | 主题切换回调（全组件重绘） | `_on_theme_changed()` |
| **AI 助手** | 展开/收起 AI 面板 | `on_ai_toggle_panel()` |
| | 发送/停止 AI 查询 | `_on_ai_send_or_stop()`、`_on_ai_stop_query()` |
| | 流式输出处理（thinking/result token） | `_on_thinking_token()`、`_on_result_token()` |
| | Build 模式预览确认/取消 | `_on_action_preview_confirmed()`、`_on_action_preview_cancelled()` |
| | ReAct 结果处理 | `_on_react_result()` |
| | ReAct 确认/取消 | `_on_react_preview_confirmed()`、`_on_react_preview_cancelled()` |
| | 清空对话历史 | `on_ai_clear_history()` |
| | 显示 AI 使用说明 | `on_ai_show_help()` |
| | 复制 AI 回复 | `_on_ai_copy_result()` |
| | 重新生成 | `_on_ai_regenerate()` |
| | 批量添加预览弹窗 | `_show_batch_add_dialog()` |
| | Markdown 渲染（代码块/列表/引用） | `_markdown_to_html()` |
| **会话安全** | 空闲定时器自动锁定 | `eventFilter()` |
| | 显示锁屏 | `show_lock_screen()` |
| | 解锁后回调 | `_on_unlocked()` |
| | 会话版本验证（检测密码修改） | `_verify_session()` |
| **同步/工具** | 同步到手机（PWA 密包） | `on_sync_to_mobile()` |
| | 健康检查对话框 | `on_health_check()` |
| | 回收站对话框 | `on_recycle_bin()` |
| | 仪表盘交互 | `_on_dashboard_action()` |
| **生命周期** | 关闭事件（自动备份+资源清理） | `closeEvent()` |
| | 自动备份数据库（保留5份） | `_auto_backup()` |
| | 清理旧备份 | `_cleanup_old_backups()` |
| **Toast 提示** | 复制成功浮动提示 | `show_copy_toast()` |
| **高亮** | AI 搜索结果高亮列表项 | `_ai_display_results_in_list()` |
| | 清除高亮 | `clear_account_highlight()` |
| **智能刷新** | 根据当前库/视图模式刷新 | `_smart_refresh()` |

### 6.2 对话框 `ui/dialogs/`

| 文件 | 功能 |
|------|------|
| `health_check_dialog.py` | 密码健康检查：弱密码检测、重复密码检测、**HIBP 泄露检测**、**AI 安全建议**、可点击跳转编辑 |
| `local_help_dialog.py` | AI 助手使用说明 |
| `password_generator_dialog.py` | 密码生成器设置弹窗（长度滑块、字符类型、实时预览） |

### 6.3 独立对话框（ui/ 根目录）

| 文件 | 功能 |
|------|------|
| `account_dialog.py` | 账号添加/编辑：手动输入 + **OCR 截图识别** + **AI 一级/二级分类** + 标签编辑 + **密码历史查看** + **AI 生成备注** + 密码生成器 + 强度评估 + dirty 检测 |
| `url_dialog.py` | 网址添加/编辑：AI 分类 + AI 标签 + AI 备注 + 密码生成器 + dirty 检测 |
| `ai_classify_dialog.py` | AI 分类确认：预分析→提议卡片→差异对比→应用/回滚、**快照管理** |
| `batch_add_preview_widget.py` | 批量添加预览：表格编辑、全选/反选、批量设分类、**AI 自动分类**、密码显示切换 |
| `export_dialog.py` | 导出对话框：范围选择、格式切换（Excel/加密备份/Bitwarden CSV/HTML）、自定义加密密码 |
| `import_dialog.py` | 导入对话框：普通导入/管理器导入切换、文件浏览、预览表格、全选/移除无效/删除选中行 |
| `lock_screen.py` | 锁屏遮罩：密码验证、**错误次数锁定冷却**、空闲定时器自动锁定 |
| `recycle_bin_dialog.py` | 回收站：密码库/网址库切换、加载条目（显示剩余天数）、恢复、永久删除、**双击查看解密详情**、清空 |
| `settings_dialog.py` | 设置：修改主密码、主题设置、AI 设置 |
| `tag_editor_dialog.py` | 标签编辑：添加/删除/**AI 智能生成标签** |

### 6.4 自定义 Widgets `ui/widgets/`

| 文件 | 功能 |
|------|------|
| `account_list_item.py` | 账号列表项：圆形图标、徽章、密码强度标签、分类标签、复制按钮（网址/账号/密码）、紧凑模式、选择模式复选框、主题响应 |
| `url_list_item.py` | 网址列表项：图标、标题、网址、分类、复制按钮、紧凑模式、选择模式 |
| `action_preview_widget.py` | 操作预览表格：动态列构建、勾选确认、单元格编辑、密码掩码 |
| `ai_chat_renderer.py` | AI 聊天渲染：欢迎语、用户消息、助手消息（思考过程折叠、代码高亮）、Markdown 转 HTML |
| `ai_input_edit.py` | AI 输入框：Enter 发送、Shift+Enter 换行 |
| `category_tree_widget.py` | 分类树：编辑模式（一级排序）、重组模式（跨层级拖拽）、自动滚动、DropZone |
| `dashboard_widget.py` | 仪表盘：统计卡片、快速操作、**密码强度环形图**、**重复密码检测**、**泄露检测结果**、最近添加列表 |

### 6.5 其他 UI 组件

| 文件 | 功能 |
|------|------|
| `ui/delegates/account_item_delegate.py` | 列表项绘制委托：自绘复选框、图标、收藏星标、分类标签、复制按钮、命中测试、紧凑模式 |
| `ui/models/account_list_model.py` | 列表数据模型：数据项设置、ID 查找行号、header 标记 |
| `ui/state/app_state.py` | 集中式状态管理：视图模式、当前库、AI 高亮 ID、选择模式、选中 ID 集合、会话版本、缓存脏标记、分类重载标记 |

---

## 七、主程序与模板

### 7.1 `main.py` — 启动流程

| 步骤 | 功能 |
|------|------|
| 1 | 启用 faulthandler（崩溃诊断） |
| 2 | Windows UTF-8 编码强制设置 |
| 3 | 初始化日志系统 |
| 4 | 创建 QApplication，设置应用名/版本 |
| 5 | 加载主题配置 |
| 6 | 初始化 ThemeManager |
| 7 | **首次启动**：SetupDialog → 设置主密码 → 创建 CryptoManager（600,000 迭代）→ 保存配置 → 创建数据库 |
| 8 | **非首次启动**：LoginDialog → 验证主密码（循环重试）→ **支持从备份恢复** |
| 9 | 初始化 AIServiceManager（后台探测 Ollama） |
| 10 | 创建并显示 MainWindow |

### 7.2 `templates/pwa_template.html` — PWA 离线密包

| 功能 | 说明 |
|------|------|
| iOS PWA 适配 | `apple-mobile-web-app-capable`、`viewport-fit=cover`、安全区适配 |
| 浏览器端解密 | Web Crypto API 实现 PBKDF2 + AES-GCM（600,000 迭代） |
| 锁屏界面 | 密码输入、显示/隐藏、生成时间/条目数信息、错误动画 |
| 双库浏览 | 底部 Tab 切换密码库/网址库 |
| 两级分类导航 | 一级分类网格 + 二级子分类网格、智能 emoji 图标匹配 |
| 条目列表 | 按拼音首字母分组（A-Z + #）、实时搜索、分类内筛选 |
| 详情页 | 用户名/密码（mask+切换）/网址/分类/标签/AI备注/备注/安全等级 |
| 复制功能 | 用户名、密码、网址一键复制 |
| 侧滑返回 | 完整状态机：idle→monitoring→activated→dragging→completing/cancelling |
| 响应式布局 | ≥430px 时网格变为 3 列 |

### 7.3 `prompts/classify_prompt.txt`

AI 助手对话指令模板，定义了：上下文记忆规则、权限限制声明、search 与 list 的严格区分、分类工具专用规则、数据范围提示、支持的 Actions 列表。

### 7.4 `scripts/migrate_category_separator.py`

数据库迁移脚本：将旧分类分隔符 `/` 替换为 `>`，含自动备份、事务保护、重复键合并、缓存清理。

---

## 八、测试

| 文件 | 用例数 | 测试内容 |
|------|--------|---------|
| `tests/conftest.py` | 2 fixtures | `temp_db`（临时 SQLite + CryptoManager）、`crypto` |
| `tests/test_account_service.py` | 6 | 添加/获取全部/按分类获取/更新/删除/密码加密验证 |
| `tests/test_crypto.py` | 8 | 加密解密往返/相同明文不同密文/空字符串/特殊字符/Base64往返/不同密钥/不同盐/相同盐复现 |
| `tests/test_id_type_consistency.py` | 4 | ID 为 int/集合比较/无 ID 为 None/不存在返回 None |
| `tests/test_search_service.py` | 4 | 精确匹配/部分匹配/无匹配/拼音匹配 |
| **总计** | **22** | |

---

## 九、待确认/待完善项

> 以下项在代码中有基础实现，但可能还需要确认是否完全达到预期效果：

| # | 项 | 说明 | 状态 |
|---|-----|------|------|
| 1 | **1Password CSV 导入** | `ManagerImportService` 目前只有 Bitwarden 和 LastPass，**没有 1Password 和 KeePass** | ❌ 未实现 |
| 2 | **KeePass XML 导入** | 同上 | ❌ 未实现 |
| 3 | **高级搜索筛选器 UI 完整度** | `SearchFilter` dataclass 和 `_on_apply_filter()` 存在，但需确认筛选面板是否已完整可用 | ⚠️ 待确认 |
| 4 | **AI 异步化 TODO** | 14 处 `TODO(P0-3)` 标注的同步调用尚未迁移到 `AIServiceManager.submit_task()` | ⚠️ 待修复 |
| 5 | **Repository search 全表加载** | `core/repositories.py` `search()` 方法仍全量加载到内存 | ⚠️ 待优化 |
| 6 | **database.close() 未加锁** | `close()` 未获取 `self._lock` | ⚠️ 待修复 |
| 7 | **restore_account() 解密失败崩溃** | 解密失败返回 `'[解密失败]'` 后 `json.loads()` 崩溃 | ⚠️ 待修复 |

---

> **使用说明**：
> 1. 后续规划新功能时，先查阅本文档确认是否已存在
> 2. 如需修改某项功能，按"代码位置"列直接定位
> 3. 本文档随代码更新而更新，修改功能后请同步更新此文档
