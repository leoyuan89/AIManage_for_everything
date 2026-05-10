# SecretManage 项目全面调研报告

> **报告日期**：2026-05-10
> **调研范围**：全项目（`ui/`、`services/`、`core/`、`ai/`、`models/`、`templates/`、`main.py`、`tests/`）
> **调研方式**：静态代码分析 + AST 扫描 + 历史报告交叉比对 + 多模块深度审查
> **参考文档**：`docs/comprehensive_audit_report_2026-05-09.md`、`docs/comprehensive_optimization_report_2026-05-09.md`、`docs/project_comprehensive_audit_report_2026-05-10.md`、`docs/FEATURE_PLAN.md`、`docs/debug_journal.md`、`docs/improvement_plan.md`

---

## 目录

1. [执行摘要](#一执行摘要)
2. [项目现状总览](#二项目现状总览)
3. [现有问题深度分析](#三现有问题深度分析)
4. [用户体验优化建议](#四用户体验优化建议)
5. [新功能开发建议](#五新功能开发建议)
6. [技术债务与架构改进](#六技术债务与架构改进)
7. [实施路线图](#七实施路线图)
8. [附录：风险矩阵](#附录风险矩阵)

---

## 一、执行摘要

本项目是一款基于 **PyQt6** 的桌面密码管理软件，集成了本地 AI（Ollama + Gemma4:4b）进行智能分类、语义搜索和 AI 助手对话。采用 **AES-256-GCM** 加密存储敏感数据，支持双库管理（密码库 + 网址库），具备 Material Design 主题切换能力。

**核心结论**：

- **架构基础扎实**：分层清晰（core → models → services → ui），加密方案符合 OWASP 2023 标准，AI 基础设施（AIWorkerThread、AIServiceManager）设计完善
- **严重问题未决**：4 项 P0 遗留问题 + 5 项新增 Critical 问题，涉及 AI 主线程阻塞、数据库竞态、数据完整性风险
- **测试覆盖极低**：22 个现有测试仅覆盖 crypto、account_service、search_service，大量核心模块零测试
- **功能规划丰富**：FEATURE_PLAN.md 已规划 20 项 v2.0 功能提升，但尚未启动实施
- **代码规模膨胀**：`main_window.py` 达 7,274 行，`ai_tools.py` 达 2,200 行，维护成本急剧上升

**建议优先级**：
1. **本周**：修复全部 P0 + Critical 问题（9 项）
2. **两周内**：修复 P1 问题（15 项）+ 启动 FEATURE_PLAN 中 P0 功能
3. **下月**：补齐核心模块测试 + 拆分超大模块
4. **Q3**：全面落地 v2.0 功能提升计划

---

## 二、项目现状总览

### 2.1 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                         UI 层                                │
│  main_window.py (7,274 行) | dialogs/ | widgets/ | delegates/│
├─────────────────────────────────────────────────────────────┤
│                      Services 层                             │
│  AI Assistant (ReAct Agent) | Classification | Search | Sync │
│  Account/URL Service | Export/Import | Tools Registry        │
├─────────────────────────────────────────────────────────────┤
│                        AI 层                                 │
│  OllamaClient (HTTP) | Semantic Search | Tool Calling | Utils│
├─────────────────────────────────────────────────────────────┤
│                      Core 基础设施                            │
│  Crypto (PBKDF2+AES-GCM) | Database (SQLite) | ThemeManager │
│  Repository Pattern | Clipboard | Logger | Password Utils    │
├─────────────────────────────────────────────────────────────┤
│                      Data 层                                 │
│  Account Model | URLItem Model | vault.db | vault_urls.db    │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心指标

| 指标 | 数值 | 评价 |
|------|------|------|
| 总代码行数 | ~35,000 行 | 中等规模桌面应用 |
| Python 文件数 | 80+ | 模块划分较细 |
| 最大单文件 | main_window.py (7,274 行) | ⚠️ 严重超标 |
| 测试用例 | 22 个 | ⚠️ 覆盖率极低 |
| 测试通过率 | 100% | ✅ |
| AI 超时设置 | 300 秒 | ✅ 符合 AGENTS.md 要求 |
| PBKDF2 迭代 | 600,000 | ✅ OWASP 2023 标准 |

### 2.3 已实现的关键能力

| 能力 | 状态 | 说明 |
|------|------|------|
| 本地加密存储 | ✅ 成熟 | PBKDF2 + AES-256-GCM，密钥管理规范 |
| 双库管理 | ✅ 成熟 | 密码库（加密）+ 网址库（明文） |
| 主题切换 | ✅ 成熟 | Light/Dark + qt-material，动态响应 |
| AI 助手对话 | ✅ 可用 | ReAct Agent + Tool Calling，最多 5 轮 |
| 智能分类 | ✅ 可用 | 预分析 → 确认 → 执行 → 预览 → 生效/回滚 |
| 语义搜索 | ✅ 可用 | AI 语义匹配 + 本地关键词降级 |
| 导入/导出 | ✅ 可用 | Excel、加密备份、HTML 书签 |
| PWA 同步 | ✅ 可用 | 离线密包，已修复迭代次数注入 |
| 回收站 | ✅ 可用 | 30 天过期，支持恢复 |
| 撤销删除 | ✅ 可用 | 60 秒倒计时撤销横幅 |
| 密码生成器 | ✅ 已实现 | secrets 模块，安全字符集 |
| 收藏功能 | ✅ 已实现 | ⭐ 标识 + 分类树入口 |
| 紧凑视图 | ✅ 已实现 | 32px/56px 双高度 |
| 仪表盘 | ✅ 已实现 | QPainter 自绘统计页 |
| OCR 导入 | ✅ 可用 | PaddleOCR 截图识别 |
| 剪贴板安全 | ✅ 可用 | 20 秒自动清除 |
| 密码历史 | ✅ 已实现 | 最近 10 条旧密码 |

---

## 三、现有问题深度分析

### 3.1 严重问题（P0 / Critical）— 必须立即修复

#### 🔴 P0-1: AI 服务层全面绕过异步 Worker，主线程直接阻塞

| 项目 | 内容 |
|------|------|
| **影响文件** | `services/ai_assistant_service.py`、`services/ai_classification_service.py`、`services/ai_remark_service.py`、`services/tools/search_tools.py`、`services/tools/utility_tools.py`、`ui/dialogs/health_check_dialog.py` |
| **根因** | 业务层代码仍然直接实例化 `OllamaClient` 并执行同步 HTTP 请求，`AIWorkerThread` / `AIServiceManager` 的完善队列机制被完全架空 |
| **后果** | Ollama 模型加载或推理时（首次加载可达 30~60 秒）UI 完全冻结；`timeout=300` 时请求可能长期挂起 |
| **代码标记** | 全项目 14 处 `TODO(P0-3)` 标注此问题 |
| **修复工作量** | 2~3 天 |
| **修复方案** | 1. 所有 AI 调用统一收敛到 `AIServiceManager.submit_task()`；2. 流式输出由 Worker 线程通过信号回传；3. 主线程仅负责 UI 更新 |

> **现状矛盾**：`AIWorkerThread` 基础设施非常完善（队列、状态探测、指数退避、优雅关闭），但业务层完全未使用，形成**"有路不走"的架构浪费**。

#### 🔴 P0-2: Repository `search()` 全表加载到内存过滤

| 项目 | 内容 |
|------|------|
| **影响文件** | `core/repositories.py` |
| **根因** | `AccountRepository.search()` 和 `URLRepository.search()` 均先调用 `self.get_all()` 加载整张表到内存，再做 Python 层面的字符串包含匹配 |
| **后果** | 数据量增大时（>1000 条）内存和 CPU 开销剧增；每次搜索都触发全量解密 |
| **修复工作量** | 2~4 小时 |
| **修复方案** | 将搜索逻辑下沉到 SQL 层，使用 `LIKE` 多条件 + 索引；短期增加 `LIMIT 500` |

#### 🔴 P0-3: `database.close()` 未加锁保护

| 项目 | 内容 |
|------|------|
| **影响文件** | `core/database.py` |
| **根因** | `close()` 方法读写 `self.conn` 和 `self.cursor` 时未获取 `self._lock` |
| **后果** | 多线程环境下，`close()` 与正在执行的查询产生竞态，可能导致 `sqlite3.ProgrammingError` 或段错误 |
| **修复工作量** | 30 分钟 |
| **修复方案** | 在 `close()` 方法内添加 `with self._lock:` 包裹全部操作 |

#### 🔴 P0-4: `restore_account()` 解密失败导致 `JSONDecodeError`

| 项目 | 内容 |
|------|------|
| **影响文件** | `core/database.py` |
| **根因** | 回收站恢复时，`_decrypt_field()` 返回 `'[解密失败]'`，紧接着调用 `json.loads()` 会抛出 `JSONDecodeError` |
| **后果** | 回收站中任何一条解密失败的条目，都会阻断整个恢复流程，导致条目**永久丢失** |
| **修复工作量** | 30 分钟 |
| **修复方案** | 在 `json.loads()` 前检查是否为 `'[解密失败]'`，若是则跳过该条目 |

#### 🔴 C1 (新增 Critical): `sync_service` 属性访问无保护

| 项目 | 内容 |
|------|------|
| **影响文件** | `services/sync_service.py` |
| **根因** | 访问 `crypto_manager.iterations` 前未验证属性存在性 |
| **后果** | `AttributeError` 导致密包生成中断 |
| **修复工作量** | 15 分钟 |

#### 🔴 C2 (新增 Critical): 明文密码短暂暴露于内存/临时文件

| 项目 | 内容 |
|------|------|
| **影响文件** | `services/sync_service.py` |
| **根因** | 序列化阶段将原始密码放入 payload dict，写入 `.tmp` 临时文件后再加密 |
| **后果** | 进程崩溃或内存转储时明文密码可被提取；临时文件写入中断后可能残留 |
| **修复工作量** | 2 小时 |
| **修复方案** | 在序列化阶段即对敏感字段加密，或确保临时文件在异常时立即清理 |

#### 🔴 C3 (新增 Critical): `_rename_parent_category()` 直接操作裸连接

| 项目 | 内容 |
|------|------|
| **影响文件** | `ui/main_window.py` |
| **根因** | 直接访问 `self.db.conn.cursor()` 和 `conn.commit()`，完全绕过 `self.db._lock`；表名通过 f-string 拼接 |
| **后果** | 与其他 DB 操作产生竞态；f-string 拼接存在注入面 |
| **修复工作量** | 1 小时 |

#### 🔴 C4 (新增 Critical): `_sanitize_classified_category()` 逻辑缺陷

| 项目 | 内容 |
|------|------|
| **影响文件** | `services/ai_classification_service.py` |
| **根因** | `child` 验证失败后，`parent` 变量直接用作 fallback，可能返回 `"编程>"` 等不完整分类名 |
| **后果** | 数据库中写入格式错误的分类名，导致分类树解析异常 |
| **修复工作量** | 30 分钟 |

#### 🔴 C5 (新增 Critical): `rollback()` 未校验 `item_type` 一致性

| 项目 | 内容 |
|------|------|
| **影响文件** | `services/ai_classification_service.py` |
| **根因** | 恢复快照时未检查快照中的 `item_type` 是否与传入的 `items` 类型一致 |
| **后果** | 可能将网址数据写回账号表，造成数据损坏 |
| **修复工作量** | 30 分钟 |

### 3.2 高优先级问题（P1 / High）— 两周内修复

| # | 问题 | 影响文件 | 风险 | 工作量 |
|---|------|---------|------|--------|
| P1-1 | AI 聊天区域全量 `setHtml` 重绘 | `ui/main_window.py` | 长对话卡顿（>20 轮时每次 50~200ms） | 4 小时 |
| P1-2 | `password_strength` 硬编码颜色 | `core/password_strength.py` | 暗黑主题不协调 | 1 小时 |
| P1-3 | `_update_state_post_task` latency 始终为 0 | `services/ai_worker_thread.py` | 监控指标失效 | 30 分钟 |
| P1-4 | `inherited_ids` 计算后未使用 | `services/ai_assistant_service.py` | 代码异味 + 上下文膨胀 | 30 分钟 |
| P1-5 | `generate_tool_call` 未使用变量 | `ai/ollama_client.py` | 代码异味 | 15 分钟 |
| P1-6 | `generate_stream` 连接/读取超时共用 300s | `ai/ollama_client.py` | 服务不可用时挂起 5 分钟 | 30 分钟 |
| P1-7 | `generate()` 未处理 HTTP 503/429 | `ai/ollama_client.py` | 用户体验差 | 1 小时 |
| P1-8 | `generate_with_think_result()` 贪婪正则过度匹配 | `ai/ollama_client.py` | 内容截断 | 1 小时 |
| P1-9 | `pre_analyze_*()` 声明截断但未实现 | `services/ai_classification_service.py` | 大库 prompt 超限 | 30 分钟 |
| P1-10 | `_classify_batch()` 发送备注至 LLM | `services/ai_classification_service.py` | 隐私风险 | 30 分钟 |
| P1-11 | `build_db_summary()` 忽略参数 | `services/ai_assistant_service.py` | 双重加载 | 30 分钟 |
| P1-12 | 批量操作缺乏事务保护 | `ui/main_window.py` | 数据不一致 | 2 小时 |
| P1-13 | `check_duplicate()` 全表扫描 | `core/repositories.py` | 性能差 | 1 小时 |
| P1-14 | `update_field()` 读取-修改-写入竞态 | `core/repositories.py` | 数据覆盖 | 2 小时 |
| P1-15 | `update_url_field()` 映射脆弱 | `core/url_database.py` | 数据错乱 | 1 小时 |

### 3.3 中低优先级问题（P2 / P3）— 纳入后续迭代

| # | 问题 | 影响文件 | 工作量 |
|---|------|---------|--------|
| P2-1 | 日志级别不当（大量 `info` 记录异常） | `ui/main_window.py` | 30 分钟 |
| P2-2 | `crypto.py` 注释与实际不符 | `core/crypto.py` | 5 分钟 |
| P2-3 | `main_window.py` UTF-8 BOM 污染 | `ui/main_window.py` | 5 分钟 |
| P2-4 | `soft_delete_account` 脱敏不完整 | `core/database.py` | 30 分钟 |
| P2-5 | 数据库缺少上下文管理器 | `core/database.py`, `url_database.py` | 2 小时 |
| P2-6 | `get_cached_category()` 多余 commit | `core/database.py` | 15 分钟 |
| P2-7 | `restore_url()` 重复 commit | `core/url_database.py` | 15 分钟 |
| P2-8 | `_TransactionContext` commit 失败无回滚 | `core/database.py` | 30 分钟 |
| P2-9 | `get_password_history()` 无访问控制 | `core/database.py` | 30 分钟 |
| P2-10 | `_shortcut_toggle_theme()` 属性错误 | `ui/main_window.py` | 15 分钟 |
| P2-11 | `_on_ai_query_finished()` 竞态条件 | `ui/main_window.py` | 1 小时 |
| P2-12 | `_ai_append_token_html()` 未转义单引号 | `ui/main_window.py` | 15 分钟 |
| P2-13 | `categorize()` 静默吞异常 | `ai/ollama_client.py` | 30 分钟 |
| P2-14 | `ThemeManager.get_icon()` 未缓存 | `core/theme_manager.py` | 30 分钟 |
| P2-15 | `RepositoryFactory` 实例永不清理 | `core/repositories.py` | 30 分钟 |
| P3-1 | 拆分超大模块（main_window.py 等） | 多文件 | 1~2 天/模块 |
| P3-2 | QListWidget → QListView 迁移 | `ui/main_window.py` | 2~3 天 |
| P3-3 | 测试覆盖补齐 | `tests/` | 2~3 天 |
| P3-4 | 硬编码路径集中化 | 多文件 | 2 小时 |
| P3-5 | PWA 测试模式移除 | `templates/pwa_template.html` | 30 分钟 |
| P3-6 | 密包元数据加密 | `services/sync_service.py` | 2 小时 |

### 3.4 安全专项审查

#### ✅ 已修复的安全问题（20 项）

| # | 问题 | 修复方式 |
|---|------|---------|
| 1 | `verify_password()` 时序攻击风险 | `hmac.compare_digest()` |
| 2 | `_decrypt_field()` 返回原始密文 | 返回 `'[解密失败]'` |
| 3 | SQLite 多线程无锁 | `threading.RLock()` + `_TransactionContext` |
| 4 | AI Worker 队列无界 | `MAX_QUEUE_SIZE = 100` |
| 5 | ThemeManager 单例非线程安全 | 双重检查锁定 |
| 6 | Logger 重复追加 handler | `if not root_logger.handlers:` |
| 7 | PWA 迭代次数不匹配 | `{{ITERATIONS}}` 模板注入 |
| 8 | 密包非原子写入 | `.tmp` + `os.replace()` |
| 9 | `escapeJs` 转义不完整 | 补充 `"`、`<`、`>`、`&` |
| 10 | 网址库密码字段未序列化 | `_serialize_urls()` 添加 `password` |
| 11 | `PopupComboBox` 内存泄漏 | `deleteLater()` |
| 12 | Undo Banner 定时器泄漏 | `stop()` / `deleteLater()` |
| 13 | `ClipboardManager` 线程不安全 | `threading.Lock()` |
| 14 | `AIClassifyDialog` 强制终止线程 | `requestInterruption()` + `wait()` |
| 15 | `update_url_field()` SQL 拼接 | 预编译 SQL 映射表 |
| 16 | 裸 `except:` 吞异常 | AST 扫描清理 |
| 17 | `ai_classification_service` NameError | 预初始化变量 |
| 18 | `record_history` 参数无效 | 添加 `if record_history:` |
| 19 | `_fix_json` 中文引号替换 | `\u201c` 替换为 `"` |
| 20 | `generate_stream` 降级丢失异常 | `raise ... from stream_e` |

#### ⚠️ 仍存在的安全问题（9 项）

| # | 问题 | 严重程度 | 说明 |
|---|------|---------|------|
| 1 | `find_duplicate_account` 因随机 nonce 永远失效 | 🔴 高 | AES-GCM 随机 nonce 导致相同明文加密结果不同，重复检测功能完全失效 |
| 2 | `soft_delete_account` 非原子操作 | 🔴 高 | 回收站插入与原表删除非事务保护 |
| 3 | `restore_account` 破坏事务原子性 | 🔴 高 | 调用 `insert_account()` 内部提前 commit |
| 4 | 明文密码短暂暴露（sync_service） | 🔴 高 | 序列化到临时文件前未加密 |
| 5 | `_rename_parent_category` 裸连接操作 | 🔴 高 | 绕过 `_lock`，f-string 拼接表名 |
| 6 | `toggle_favorite` 绕过封装层 | 🟡 中 | 直接操作 `db.cursor` 和 `db.conn` |
| 7 | `PRAGMA foreign_keys` 未启用 | 🟡 中 | 外键级联删除不生效 |
| 8 | `_decrypt_field_safe` 可能暴露密文 | 🟡 中 | 解密失败时返回原值 |
| 9 | 服务层无输入验证 | 🟡 中 | `app_name`、`password` 可为任意长度 |

---

## 四、用户体验优化建议

### 4.1 交互流畅性优化

| # | 优化项 | 现状问题 | 优化方案 | 预期效果 |
|---|--------|---------|---------|---------|
| 1 | **AI 响应速度感知** | Ollama 首次加载模型时 UI 冻结 30~60 秒 | 添加"AI 正在思考..."加载动画 + 进度指示 | 用户明确知道等待原因，焦虑感降低 |
| 2 | **搜索响应速度** | 全表加载 + 全量解密，大数据量时卡顿 | 实现 SQL 层搜索 + 分页加载 | 1000+ 条数据搜索 < 200ms |
| 3 | **列表滚动流畅度** | QListWidget + 200 个 widget 对象常驻内存 | 待 QListView + Delegate 方案稳定后迁移 | 滚动达到 60fps |
| 4 | **AI 聊天区域重绘** | 每次全量 `setHtml`，长对话时滚动跳动 | 流式阶段改用 `QTextCursor` 局部插入 | 长对话无卡顿 |
| 5 | **主题切换延迟** | 全量样式重建，深色主题初始不生效 | 预加载另一主题样式表缓存 | 切换无感知 |

### 4.2 界面一致性优化

| # | 优化项 | 现状问题 | 优化方案 | 涉及文件 |
|---|--------|---------|---------|---------|
| 1 | **密码强度颜色主题化** | 硬编码 `#f44336`/`#4CAF50`，暗黑主题不协调 | 返回语义标签，UI 层从 ThemeColors 取色 | `core/password_strength.py`, UI 层 |
| 2 | **样式字符串集中化** | 200+ 处 `f"background-color: {colors.xxx}"` 散落 | ThemeManager 提供 `get_button_style()` 等工厂方法 | `core/theme_manager.py`, 全 UI |
| 3 | **头像颜色主题化** | Material 硬编码 15 色数组 | 从 ThemeColors 动态生成 | `ui/widgets/` |
| 4 | **Tab 顺序优化** | 无 `setTabOrder` 调用 | 为 AccountDialog 等复杂表单配置 Tab 顺序 | `ui/account_dialog.py` |
| 5 | **无障碍支持** | 无 `setAccessibleName`/`Description` | 为核心控件添加辅助属性 | 全 UI |

### 4.3 错误处理与反馈优化

| # | 优化项 | 现状问题 | 优化方案 |
|---|--------|---------|---------|
| 1 | **AI 错误分类提示** | 503/429 被归为通用异常 | 明确提示"模型加载中"/"请求过于频繁" |
| 2 | **批量操作进度反馈** | 大批量操作时无进度指示 | 添加 `QProgressDialog` 或进度条 |
| 3 | **网络超时友好提示** | 连接超时时挂起 5 分钟 | 连接超时 10 秒 + 友好重试提示 |
| 4 | **日志级别统一** | 大量异常场景使用 `logger.info` | 统一为 `logger.error`/`logger.exception` |
| 5 | **JSON 解析失败降级** | AI 返回非法 JSON 时 UI 线程崩溃 | `json.loads` 包 `try/except`，显示友好错误 |

### 4.4 性能优化

| # | 优化项 | 现状 | 目标 | 方案 |
|---|--------|------|------|------|
| 1 | **搜索性能** | O(n) 全量加载 | O(log n) 索引搜索 | SQL 层 `LIKE` + `LIMIT` |
| 2 | **重复检测** | 全表扫描 + 密文比较 | O(1) 哈希查询 | 新增 `hash_for_cache` 字段 |
| 3 | **分类重命名** | N+1 更新 + 全量解密 | 单条 SQL 批量更新 | 下沉到 database 层 |
| 4 | **图标缓存** | 每次新建 QIcon | 复用缓存 | `functools.lru_cache` |
| 5 | **历史记录截断** | `_max_history = 20` 未执行 | 实际限制 20 条 | 追加时检查长度并移除旧条目 |

---

## 五、新功能开发建议

### 5.1 高价值功能（建议优先实施）

基于 FEATURE_PLAN.md 已有规划，结合用户实际场景，以下功能优先级最高：

#### 🌟 F1: 从其他密码管理器导入

| 项目 | 内容 |
|------|------|
| **目标** | 支持从 Bitwarden、LastPass、1Password、KeePass 导入数据 |
| **价值** | 降低用户迁移成本，是密码管理器的核心竞争力功能 |
| **技术方案** | 新建 `services/import_service.py`，各格式独立解析器 + 自动格式检测 |
| **工作量** | 2~3 天 |
| **依赖** | 无 |

#### 🌟 F2: 高级搜索筛选器

| 项目 | 内容 |
|------|------|
| **目标** | 搜索框下方增加可折叠筛选面板，按分类、日期、密码强度、标签组合筛选 |
| **价值** | 大数据量时精准定位，提升查找效率 |
| **技术方案** | `SearchFilter` dataclass + `SearchService.search_advanced()` + 条件持久化到 config.json |
| **工作量** | 1~2 天 |
| **依赖** | 无 |

#### 🌟 F3: 密码健康仪表盘增强

| 项目 | 内容 |
|------|------|
| **目标** | 弱密码、重复密码、泄露风险（HIBP k-anonymity）一键检测 |
| **现状** | 基础框架已存在（`ui/dialogs/health_check_dialog.py`） |
| **增强项** | 1. HIBP 泄露检测（SHA-1 前 5 位查询）；2. AI 安全建议（Ollama 生成改进建议）；3. 一键修复引导 |
| **工作量** | 2 天 |
| **依赖** | 无 |

#### 🌟 F4: 列表列自定义

| 项目 | 内容 |
|------|------|
| **目标** | 列表顶部右键菜单可勾选显示/隐藏各信息列 |
| **价值** | 用户可按需定制信息密度 |
| **技术方案** | `list_columns` 配置项 + `AccountListItem`/`URLListItem` 动态隐藏子控件 |
| **工作量** | 1 天 |
| **依赖** | 无 |

### 5.2 中等价值功能（建议次批实施）

| # | 功能 | 说明 | 工作量 | 依赖 |
|---|------|------|--------|------|
| F5 | **Bitwarden 兼容导出** | 新增 Bitwarden CSV 格式选项 | 4 小时 | 无 |
| F6 | **批量分类 + 批量标签** | 多选条目后批量修改分类和标签 | 1 天 | 无 |
| F7 | **搜索历史 + 最近使用** | 搜索框下拉历史词，分类树"最近使用"项 | 1 天 | 无 |
| F8 | **密码强度即时建议** | 编辑时实时给出具体改进建议 | 4 小时 | 无 |
| F9 | **剪贴板倒计时提示** | 复制后状态栏显示倒计时，清除时通知 | 4 小时 | 无 |
| F10 | **弹窗未保存提醒** | 编辑弹窗关闭时 dirty 检测 | 4 小时 | 无 |

### 5.3 创新差异化功能（长期规划）

| # | 功能 | 说明 | 工作量 | 技术挑战 |
|---|------|------|--------|---------|
| F11 | **AI 自动密码审计** | AI 定期分析密码库，主动推送安全建议 | 3~5 天 | 需要定时任务框架 |
| F12 | **智能分类自学习** | 根据用户手动调整，AI 学习用户分类偏好 | 5~7 天 | 需要本地模型微调能力 |
| F13 | **跨设备同步（局域网）** | 同一局域网内多设备实时同步 | 5~7 天 | 需要 P2P 或局域网发现协议 |
| F14 | **浏览器扩展集成** | Chrome/Firefox 扩展，自动填充密码 | 7~10 天 | 需要 Native Messaging 协议 |
| F15 | **TOTP/2FA 支持** | 集成 TOTP 生成器，支持双因素认证 | 3~5 天 | 需要 OTP 算法实现 |
| F16 | **密码共享（加密链接）** | 生成有时效性的加密分享链接 | 3~5 天 | 需要非对称加密 + 链接管理 |
| F17 | **生物识别解锁** | 支持 Windows Hello / Touch ID | 2~3 天 | 需要平台特定 API 调用 |
| F18 | **数据变更历史** | 记录所有增删改操作，支持按时间点恢复 | 5~7 天 | 需要完整审计日志系统 |

---

## 六、技术债务与架构改进

### 6.1 模块拆分计划

| 文件 | 当前行数 | 拆分方案 | 预计工作量 |
|------|---------|---------|-----------|
| `ui/main_window.py` | 7,274 行 | 拆分为 `panels/`（AI 面板、列表区域、工具栏）+ `controllers/`（事件处理、状态管理） | 2~3 天 |
| `services/ai_tools.py` | ~2,200 行 | 按工具类别拆分至 `services/tools/` 下已存在的各模块 | 1~2 天 |
| `services/ai_assistant_service.py` | ~1,700 行 | 拆分为对话管理、ReAct 引擎、工具执行器三个独立模块 | 1~2 天 |
| `ai/ollama_client.py` | ~1,163 行 | 拆分为基础客户端、流式处理、工具调用、语义搜索四个模块 | 1 天 |
| `ui/account_dialog.py` | ~1,686 行 | 提取 `OCRWorker`、`PasswordHistoryDialog`、`PopupComboBox` 为独立模块 | 4 小时 |

### 6.2 数据库层改进

| # | 改进项 | 说明 | 工作量 |
|---|--------|------|--------|
| 1 | **提取 `BaseDatabaseManager`** | `database.py` 和 `url_database.py` 大量重复逻辑抽象为基类 | 1 天 |
| 2 | **启用外键约束** | `PRAGMA foreign_keys = ON` | 15 分钟 |
| 3 | **重复检测修复** | 新增 `app_name_hash`、`username_hash` 字段用于重复查询 | 2 小时 |
| 4 | **事务保护全覆盖** | `soft_delete`、`restore`、批量操作全部纳入事务 | 4 小时 |
| 5 | **上下文管理器** | 实现 `with DatabaseManager(...) as db:` | 2 小时 |

### 6.3 AI 架构改进

| # | 改进项 | 说明 | 工作量 |
|---|--------|------|--------|
| 1 | **全面异步化** | 所有 AI 调用统一走 `AIServiceManager.submit_task()` | 2~3 天 |
| 2 | **HTTP 重试机制** | `urllib3.util.retry.Retry` 适配器 | 2 小时 |
| 3 | **Prompt 注入防护** | 用户输入严格过滤/转义 | 2 小时 |
| 4 | **响应 latency 真实测量** | `time.perf_counter()` 差值 | 30 分钟 |
| 5 | **Token 预算管控** | 大库场景下自动截断 prompt | 2 小时 |

### 6.4 测试体系完善

| 模块 | 当前测试 | 目标覆盖 | 优先级 | 预计工作量 |
|------|---------|---------|--------|-----------|
| `core/database.py` | 无 | 事务回滚、解密失败、并发读写 | 高 | 4 小时 |
| `core/url_database.py` | 无 | 回收站恢复、字段更新 | 高 | 3 小时 |
| `services/sync_service.py` | 无 | 模板注入、加密一致性、原子写入 | 高 | 4 小时 |
| `services/ai_worker_thread.py` | 无 | 队列行为、超时、优雅关闭 | 高 | 4 小时 |
| `ai/ollama_client.py` | 无 | JSON 修复、降级、语义匹配 | 中 | 4 小时 |
| `services/ai_assistant_service.py` | 无 | ReAct 状态机、事务执行 | 中 | 6 小时 |
| `core/theme_manager.py` | 无 | 单例、信号、主题切换 | 低 | 2 小时 |
| UI 层 | 无 | smoke test（pytest-qt） | 低 | 1 天 |

---

## 七、实施路线图

### 7.1 第一阶段：紧急修复（第 1~2 周）

**目标**：消除所有 P0 + Critical 问题，确保软件稳定可靠

| 天次 | 任务 | 涉及文件 | 工作量 |
|------|------|---------|--------|
| Day 1 | 修复 `database.close()` 未加锁 | `core/database.py` | 30 分钟 |
| Day 1 | 修复 `restore_account()` 解密失败崩溃 | `core/database.py` | 30 分钟 |
| Day 1 | 修复 `sync_service` 属性访问 + ITERATIONS 注入 | `services/sync_service.py` | 30 分钟 |
| Day 1 | 修复 `_sanitize_classified_category()` 逻辑缺陷 | `services/ai_classification_service.py` | 30 分钟 |
| Day 1 | 修复 `rollback()` 未校验 item_type | `services/ai_classification_service.py` | 30 分钟 |
| Day 2 | 修复 `_rename_parent_category()` 裸连接 | `ui/main_window.py` | 1 小时 |
| Day 2 | 修复 `sync_service` 明文密码暴露 | `services/sync_service.py` | 2 小时 |
| Day 3~5 | AI 调用全面异步化（P0-1） | `services/ai_*.py`, `ai/ollama_client.py` | 2~3 天 |
| Day 6 | 修复 Repository `search()` 全表加载 | `core/repositories.py` | 4 小时 |
| Day 7 | 全面测试 + Bug 修复 | 全项目 | 1 天 |

### 7.2 第二阶段：体验优化（第 3~4 周）

**目标**：修复 P1 问题，启动 FEATURE_PLAN 中 P0 功能

| 天次 | 任务 | 涉及文件 | 工作量 |
|------|------|---------|--------|
| Day 8 | 修复 AI 聊天全量重绘 | `ui/main_window.py` | 4 小时 |
| Day 8 | 修复 `password_strength` 硬编码颜色 | `core/password_strength.py` | 1 小时 |
| Day 9 | 修复 OllamaClient 超时 + 503/429 | `ai/ollama_client.py` | 2 小时 |
| Day 9 | 修复批量操作缺乏事务 | `ui/main_window.py` | 2 小时 |
| Day 10 | 修复 `check_duplicate()` 全表扫描 + `update_field()` 竞态 | `core/repositories.py` | 3 小时 |
| Day 11 | 修复 `pre_analyze_*()` 截断 + 备注隐私 | `services/ai_classification_service.py` | 1 小时 |
| Day 12~13 | 实施功能：从其他管理器导入 | `services/import_service.py` | 2 天 |
| Day 14 | 全面测试 + Bug 修复 | 全项目 | 1 天 |

### 7.3 第三阶段：功能扩展（第 5~8 周）

**目标**：落地 FEATURE_PLAN 中 P1 + P2 功能

| 周次 | 任务 | 工作量 |
|------|------|--------|
| Week 5 | 高级搜索筛选器 + 列表列自定义 | 3 天 |
| Week 6 | 密码健康仪表盘增强（HIBP + AI 建议） | 3 天 |
| Week 7 | 批量分类/标签 + 搜索历史/最近使用 | 3 天 |
| Week 8 | Bitwarden 导出 + 密码强度即时建议 | 2 天 |

### 7.4 第四阶段：架构升级（第 9~12 周）

**目标**：拆分超大模块，补齐测试，引入创新功能

| 周次 | 任务 | 工作量 |
|------|------|--------|
| Week 9~10 | 拆分 `main_window.py` + `ai_tools.py` + `ollama_client.py` | 1~2 周 |
| Week 10~11 | 补齐核心模块测试（database、sync_service、ai_worker_thread） | 1 周 |
| Week 11~12 | 引入创新功能（TOTP / 生物识别 / 浏览器扩展调研） | 1~2 周 |

---

## 附录：风险矩阵

### A. 业务风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| AI 主线程阻塞导致用户流失 | 高 | 高 | 立即实施异步化改造 |
| 大数据量时搜索/分类操作卡顿 | 高 | 中 | SQL 层搜索 + 分批处理 |
| 回收站恢复失败导致数据丢失 | 中 | 高 | 修复 `restore_account()` 异常处理 |
| 批量操作中断导致数据不一致 | 中 | 高 | 添加事务保护 |

### B. 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| QListView 迁移触发崩溃 | 中 | 中 | 充分隔离测试后再集成 |
| AI 异步化改造引入新 Bug | 中 | 中 | 小步快跑，每处修改单独测试 |
| 模块拆分导致合并冲突 | 低 | 低 | 按文件归属分组，协调入口修改 |
| PWA 测试模式安全隐患 | 低 | 中 | 生产构建流程移除测试模式 |

### C. 进度风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| AI 异步化工作量低估 | 中 | 高 | 预留 1 周缓冲时间 |
| 新功能开发分散修复精力 | 中 | 中 | 严格执行"先修复后开发"原则 |
| 测试覆盖补齐耗时超预期 | 中 | 低 | 优先覆盖核心模块，UI 测试延后 |

---

> **报告总结**：本项目具备扎实的技术基础和清晰的功能规划，但存在 9 项严重问题必须立即处理。建议按照"紧急修复 → 体验优化 → 功能扩展 → 架构升级"四阶段推进，预计 12 周内可将项目从"可用工具"提升为"桌面级专业密码管理器"。
>
> **下一步行动**：建议优先启动第一阶段紧急修复，特别是 AI 异步化改造（P0-1）和数据库安全修复（P0-3/P0-4），这两项对用户体验和数据安全影响最大。
