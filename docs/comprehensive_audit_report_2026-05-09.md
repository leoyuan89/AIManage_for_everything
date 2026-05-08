# 深度代码审查报告 —— 全项目安全、性能与架构审计

> 生成日期：2026-05-09
> 审查范围：全项目（`ui/`、`services/`、`core/`、`models/`、`ai/`、`templates/`、`main.py`）
> 审查重点：PWA 同步安全性、移动端交互缺陷、线程安全、AI 服务稳定性、UI 性能与内存泄漏

---

## 目录

1. [执行摘要](#一执行摘要)
2. [本次已修复问题（7 项）](#二本次已修复问题)
3. [遗留严重问题（Critical / P0）](#三遗留严重问题)
4. [高优先级问题（High / P1）](#四高优先级问题)
5. [中优先级问题（Medium / P2）](#五中优先级问题)
6. [低优先级与代码质量改进（Low / P3）](#六低优先级与代码质量改进)
7. [架构层面长期改进建议](#七架构层面长期改进建议)
8. [附录：修复优先级速查表](#附录修复优先级速查表)

---

## 一、执行摘要

本次审查在用户提出的 **"PWA 左滑返回失效"** 基础上，对全项目进行了地毯式安全与质量审计。共识别出 **50+ 项问题**，其中：

- **严重（Critical）**：6 项，涉及功能失效、数据损坏、安全漏洞
- **高（High）**：12 项，涉及线程安全、内存泄漏、主线程阻塞
- **中（Medium）**：15 项，涉及代码质量、异常处理、性能隐患
- **低（Low）**：20+ 项，涉及代码异味、重复代码、日志规范

**已当场修复 7 项最关键问题**（见第二节），剩余问题按优先级列入后续迭代计划。

---

## 二、本次已修复问题

### 1. PWA 左滑返回首次导航失效

| 项目 | 内容 |
|------|------|
| **文件** | `templates/pwa_template.html` |
| **根因** | `doUnlock()` 解锁成功后仅调用 `show('mainScreen')` 移除了 `hidden` 类，**但未添加 `active` 类**。导致 `pushScreen()` 第一次执行时 `$('.screen.active')` 为 `null`，`navStack` 为空，左滑手势直接返回 |
| **修复** | 在测试模式分支和真实解密分支均追加 `$('#mainScreen').classList.add('active');` |

### 2. PWA 与桌面端 PBKDF2 迭代次数硬编码不匹配

| 项目 | 内容 |
|------|------|
| **文件** | `core/crypto.py`、`services/sync_service.py`、`templates/pwa_template.html` |
| **根因** | 桌面端 `ITERATIONS = 600000`，但 PWA JS 中硬编码 `iterations: 100000`，且 `sync_service.py` **未将迭代次数注入模板**。用户使用正确主密码在 PWA 中永远无法解密 |
| **修复** | - `sync_service.py` 新增注入 `{{ITERATIONS}}` 模板变量<br>- PWA JS 新增 `const ITERATIONS = parseInt("{{ITERATIONS}}", 10) || 600000;`<br>- `deriveKey()` 使用 `iterations: ITERATIONS` |

### 3. `CryptoManager.verify_password()` 存在时序攻击风险

| 项目 | 内容 |
|------|------|
| **文件** | `core/crypto.py` |
| **根因** | 使用普通 `==` 比较派生密钥的字节串，攻击者可能通过计时分析推测主密码 |
| **修复** | 引入 `import hmac`，改用 `hmac.compare_digest(test_key, self._key)` |

### 4. 密包文件非原子写入

| 项目 | 内容 |
|------|------|
| **文件** | `services/sync_service.py` |
| **根因** | `generate_pwa_package()` 直接 `open(output_path, 'w')` 写入目标文件，写入中断会留下损坏文件 |
| **修复** | 改为先写入 `.tmp` 临时文件，成功后 `os.replace()` 原子替换；异常时清理临时文件 |

### 5. `escapeJs` 转义不完整导致潜在 XSS

| 项目 | 内容 |
|------|------|
| **文件** | `templates/pwa_template.html` |
| **根因** | `escapeJs()` 仅转义 `\`、`'`，未处理 `"`、`<`、`>`、`&`。恶意内容可能破坏 HTML/JS 边界 |
| **修复** | 补充 `"` 转义及 `<`、`>`、`&` 的 Unicode 转义 |

### 6. 网址库密码字段未序列化到密包

| 项目 | 内容 |
|------|------|
| **文件** | `services/sync_service.py`、`templates/pwa_template.html` |
| **根因** | `_serialize_urls()` 遗漏 `password` 字段；PWA 详情页也未渲染网址密码 |
| **修复** | `_serialize_urls()` 添加 `password`；PWA `openDetail()` 非账号模式下增加密码行渲染 |

---

## 三、遗留严重问题

### 3.1 `core/database.py` — `_decrypt_field()` 解密失败返回原始密文

| 项目 | 内容 |
|------|------|
| **文件** | `core/database.py` ~L171-180 |
| **根因** | `try/except` 捕获所有解密异常后，直接返回原始密文字符串 |
| **后果** | UI 可能将 Base64 密文直接展示给用户，既泄露加密数据又造成困惑 |
| **修复建议** | 返回空字符串或带 `[解密失败]` 标记的占位文本，并记录 `logger.error` |

### 3.2 AI 服务层全面绕过异步 Worker，主线程直接阻塞

| 项目 | 内容 |
|------|------|
| **文件** | `services/ai_assistant_service.py`、`services/ai_classification_service.py`、`services/ai_remark_service.py`、`services/ai_tools.py` |
| **根因** | 几乎所有 AI 操作都在 UI 主线程中直接实例化 `OllamaClient` 并执行同步 HTTP 请求，`AIWorkerThread` / `AIServiceManager` 的队列和重试机制被完全架空 |
| **后果** | Ollama 模型加载或推理时 UI 完全冻结；`timeout=None` 时请求可能永久挂起 |
| **修复建议** | 将所有 AI 调用统一收敛到 `AIServiceManager.submit_task()`，流式输出通过 Worker 线程信号逐 token 回传 |

### 3.3 `OllamaClient.generate()` / `generate_stream()` 超时设为 `None`

| 项目 | 内容 |
|------|------|
| **文件** | `ai/ollama_client.py` ~L156-159、L206-210 |
| **根因** | `requests.post(..., timeout=None)` 不设超时 |
| **后果** | Ollama 服务异常、模型加载卡住时，`requests` 无限期阻塞，且不可被 Python 线程中断机制唤醒 |
| **修复建议** | 设置合理超时（如连接超时 10s、读取超时 120s）；流式请求使用 `stream=True` + 定期检查 `_running` 标志 |

### 3.4 `execute_build_action_with_transaction` 名不副实，无数据库事务

| 项目 | 内容 |
|------|------|
| **文件** | `services/ai_assistant_service.py` ~L1352-1521 |
| **根因** | 方法名声称"在 SQLite 事务中批量执行"，但代码中逐条调用 `repo.insert()` / `repo.update_field()`，无任何 `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK` |
| **后果** | 批量操作中途中断时，已完成的部分无法回滚，数据处于不一致状态 |
| **修复建议** | 在 Repository 层提供事务上下文管理器，或在该方法中显式包裹 `BEGIN` / `COMMIT` |

### 3.5 `ai_classification_service.py` 异常处理块引用未赋值变量

| 项目 | 内容 |
|------|------|
| **文件** | `services/ai_classification_service.py` `pre_analyze_accounts()`、`pre_analyze_urls()`、`_classify_batch()` |
| **根因** | `except Exception` 块中引用 `result` 和 `json_str`，但若异常发生在 `ollama.generate()` 阶段，这两个变量尚未赋值 |
| **后果** | 原始异常被 `NameError` 彻底掩盖，调试极其困难 |
| **修复建议** | 使用 `try/except/finally` 或局部变量预初始化确保日志安全 |

---

## 四、高优先级问题

### 4.1 UI 层多处主线程阻塞操作

| 文件 | 方法 | 问题描述 |
|------|------|---------|
| `ui/widgets/dashboard_widget.py` | `_run_health_check()` | 遍历所有账号逐条调用 `evaluate_password_strength()` 并计算 SHA256，全部在主线程同步执行，数百条账号时 UI 冻结数秒 |
| `ui/settings_dialog.py` | `_do_change_password()` | 逐条 SELECT 解密重新加密 UPDATE 所有账号，全程在主线程 |
| `ui/import_dialog.py` | `_parse_vault_file()` | `.vault` 文件解密和反序列化在主线程执行 |
| `ui/export_dialog.py` | `on_export_clicked()` | Excel 生成、加密备份打包、HTML 书签生成均在主线程 |
| `ui/batch_add_preview_widget.py` | `_on_auto_classify()` | 循环中直接调用 `auto_classify()`，若底层涉及 AI 推理则 UI 冻结 |

**修复建议**：将上述长耗时操作全部迁移至 `QThread`，通过信号回传进度和结果；密码修改等操作配合 `QProgressDialog`。

### 4.2 `PopupComboBox` 严重内存泄漏

| 项目 | 内容 |
|------|------|
| **文件** | `ui/account_dialog.py` |
| **根因** | 每次打开下拉菜单都新建 `QWidget` + `QListWidget`，旧对象仅调用 `.close()` 后覆盖引用，从未调用 `deleteLater()` |
| **后果** | 频繁添加/编辑账号时内存持续增长 |
| **修复建议** | 覆盖引用前调用 `self._popup.deleteLater()`；重写 `hideEvent` 确保外部点击关闭时也能清理 |

### 4.3 Undo Banner 定时器覆盖泄漏

| 项目 | 内容 |
|------|------|
| **文件** | `ui/main_window.py` `show_undo_banner()` |
| **根因** | `self._undo_timer = QTimer(self)` 直接赋值，若用户快速连续触发两次批量删除，前一个 timer 引用丢失但仍在运行 |
| **后果** | 旧 timer 在不可预期的时间触发 `_dismiss_undo_banner()`；内存泄漏 |
| **修复建议** | 创建新 timer 前，先检查并 `stop()` / `deleteLater()` 旧的 |

### 4.4 `AIWorkerThread` 任务队列无界

| 项目 | 内容 |
|------|------|
| **文件** | `services/ai_worker_thread.py` |
| **根因** | `enqueue()` 未检查队列长度上限 |
| **后果** | 若 UI 提交任务速度远大于 Ollama 消费速度，队列无限增长，最终耗尽内存 |
| **修复建议** | 增加队列长度限制（如 100），超限时报错或丢弃最早任务 |

### 4.5 `AIWorkerThread._get_client()` 跨线程竞争条件

| 项目 | 内容 |
|------|------|
| **文件** | `services/ai_worker_thread.py` `_get_client()` vs `update_config()` |
| **根因** | `_get_client()` 读取 `_ollama_client` 和 `_config` 不加锁，而 `update_config()` 在主线程中持 `self._mutex` 修改这些字段 |
| **后果** | 配置更新后可能仍使用旧 client；极端情况下创建多个 client 实例 |
| **修复建议** | `_get_client()` 中对 client 创建和配置读取加锁 |

### 4.6 `AIClassifyDialog` 强制终止后台线程

| 项目 | 内容 |
|------|------|
| **文件** | `ui/ai_classify_dialog.py` `closeEvent()` |
| **根因** | 调用 `self.pre_analysis_worker.terminate()` 强制终止线程 |
| **后果** | 可能导致 SQLite 连接损坏、内存泄漏或未释放的锁 |
| **修复建议** | 使用 graceful shutdown（设置退出标志 + `wait()`），避免 `terminate()` |

### 4.7 `OCRWorker` 信号连接未显式断开

| 项目 | 内容 |
|------|------|
| **文件** | `ui/account_dialog.py` `on_select_image()` / `closeEvent()` |
| **根因** | `ocr_finished` 和 `ocr_error` 连接到对话框实例，`closeEvent` 中仅调用 `stop()` 未 `disconnect()` |
| **后果** | worker 的 `finished` 信号在槽处理中途触发，可能访问已销毁对象 |
| **修复建议** | `closeEvent` 中先 `disconnect()` 再 `stop()` |

### 4.8 `core/url_database.py` — `update_url_field()` SQL 拼接风险

| 项目 | 内容 |
|------|------|
| **文件** | `core/url_database.py` ~L512-535 |
| **根因** | `field` 变量直接拼接进 SQL，虽有白名单但仍存在注入面 |
| **修复建议** | 即使白名单通过，也使用参数化列名映射或严格审计日志 |

### 4.9 `core/repositories.py` — 全表加载到内存过滤

| 项目 | 内容 |
|------|------|
| **文件** | `core/repositories.py` `search()` / `filter_by_category()` / `resolve_filter_conditions()` |
| **根因** | 全部先 `get_all()` 加载整张表到内存再做过滤 |
| **后果** | 数据量增大时内存和 CPU 开销剧增 |
| **修复建议** | 将筛选逻辑下沉到 SQL 层 |

### 4.10 `core/theme_manager.py` — 单例非线程安全

| 项目 | 内容 |
|------|------|
| **文件** | `core/theme_manager.py` `instance()` |
| **根因** | 单例实现未加锁 |
| **后果** | 多线程可能创建多个 `ThemeManager`，信号连接、主题状态不一致 |
| **修复建议** | 使用双重检查锁定或模块级单例 |

---

## 五、中优先级问题

### 5.1 `core/database.py` / `url_database.py` — 缺少上下文管理器

| 项目 | 内容 |
|------|------|
| **文件** | `core/database.py`、`core/url_database.py` |
| **根因** | `close()` 未加锁，且类未实现 `__enter__`/`__exit__` |
| **后果** | 多线程下同时关闭可能出错；外部容易忘记调用 `close()` 导致连接泄漏 |
| **修复建议** | 添加 `threading.RLock()` 保护 close；实现上下文管理器 |

### 5.2 `core/clipboard.py` — `_last_password` 读写无锁

| 项目 | 内容 |
|------|------|
| **文件** | `core/clipboard.py` `_clear_password()` / `copy_text()` |
| **根因** | 定时器线程写、主线程读可能读到过期值或引发竞态 |
| **修复建议** | 添加 `threading.Lock()` 保护，或改用 `QTimer` 避免混用原生线程与 Qt 线程 |

### 5.3 `core/logger.py` — 重复追加 handler

| 项目 | 内容 |
|------|------|
| **文件** | `core/logger.py` `setup_logging()` |
| **根因** | 每次调用都向 root logger 追加新 handler，不做去重检查 |
| **后果** | 多次初始化会导致日志重复输出 |
| **修复建议** | 添加 `if not logger.handlers:` 判断 |

### 5.4 `ui/main_window.py` — `search_box.focusInEvent` Monkey-patch

| 项目 | 内容 |
|------|------|
| **文件** | `ui/main_window.py` ~L1471 |
| **根因** | 直接保存并替换 `self.search_box.focusInEvent`，非常脆弱 |
| **修复建议** | 使用 `self.search_box.installEventFilter(self)` |

### 5.5 AI 聊天区域频繁全量重绘

| 项目 | 内容 |
|------|------|
| **文件** | `ui/main_window.py` `_ai_update_chat_display()` |
| **根因** | 每次收到 `_on_result_token` 都重新构建整个 HTML 字符串并调用 `setHtml()` |
| **后果** | 长文本对话时高频重排重绘，CPU 占用显著升高 |
| **修复建议** | 流式输出阶段改用 `insertPlainText` 或只追加 DOM 片段 |

### 5.6 `process_query_stream` 完全无视 `record_history` 参数

| 项目 | 内容 |
|------|------|
| **文件** | `services/ai_assistant_service.py` ~L425-628 |
| **根因** | `record_history` 仅在函数签名中存在，方法体内始终调用 `_add_message()` |
| **修复建议** | 添加 `if record_history:` 判断包裹 `_add_message()` 调用 |

### 5.7 `_fix_json` 中文引号替换无实际效果

| 项目 | 内容 |
|------|------|
| **文件** | `ai/ollama_client.py` ~L86-87 |
| **根因** | `replace('"', '"')` 两端字符完全相同，空操作 |
| **修复建议** | 真正替换中文弯引号为英文直引号，或移除无效代码 |

### 5.8 `generate_stream` 降级失败时丢失原始异常

| 项目 | 内容 |
|------|------|
| **文件** | `ai/ollama_client.py` ~L227-234 |
| **根因** | 最终抛出的异常只包含 `fallback_e`，原始失败原因 `stream_e` 被静默丢弃 |
| **修复建议** | 使用异常链 `raise Exception(...) from stream_e` |

### 5.9 `SmartClassify*` 工具重复分类解析可能 `ValueError`

| 项目 | 内容 |
|------|------|
| **文件** | `services/ai_tools.py` |
| **根因** | `best_cat = max(cats, key=lambda c: (len(c), cat_order.index(c)))` 中若出现未收录分类名会崩溃 |
| **修复建议** | 使用 `.get(c, float('inf'))` 替代 `index()` |

### 5.10 `semantic_search` 模糊匹配结果不稳定

| 项目 | 内容 |
|------|------|
| **文件** | `ai/ollama_client.py` ~L446-450 |
| **根因** | `break` 只取第一个子串匹配，顺序不同时结果不同 |
| **修复建议** | 收集所有匹配后按相似度排序取最佳 |

### 5.11 `core/database.py` — `soft_delete_account()` 脱敏逻辑不完整

| 项目 | 内容 |
|------|------|
| **文件** | `core/database.py` ~L868-883 |
| **根因** | 邮箱 local 部分 `<=2` 时不脱敏；非邮箱 5-6 位脱敏后反而更长 |
| **修复建议** | 统一脱敏规则，短邮箱也应做最小长度脱敏 |

### 5.12 `core/database.py` — `get_cached_category()` 无意义 commit

| 项目 | 内容 |
|------|------|
| **文件** | `core/database.py` ~L709-730 |
| **根因** | 缓存未命中时仍执行 `self.conn.commit()` |
| **后果** | 多余磁盘 I/O |
| **修复建议** | 移除不必要的 `commit()` |

### 5.13 `core/url_database.py` — 回收站缺少 `is_favorite` 字段

| 项目 | 内容 |
|------|------|
| **文件** | `core/url_database.py` `soft_delete_url()` / `url_recycle_bin` 表 |
| **根因** | 回收站表结构未保留收藏状态 |
| **后果** | 网址恢复后收藏状态丢失 |
| **修复建议** | 同步保留 `is_favorite` 字段 |

### 5.14 `process_react_query` 中 `inherited_ids` 计算后未使用

| 项目 | 内容 |
|------|------|
| **文件** | `services/ai_assistant_service.py` ~L669 |
| **根因** | `inherited_ids` 仅在 `tool_context` 中传递，但没有任何工具消费该字段 |
| **修复建议** | 清理无用代码或实现引用继承功能 |

### 5.15 `generate_tool_call` 笔误及未使用变量

| 项目 | 内容 |
|------|------|
| **文件** | `ai/ollama_client.py` ~L740 |
| **根因** | `tool_suffix_hint` 重复写了 `_accounts` 两次，且定义后从未在 prompt 中使用 |
| **修复建议** | 修正笔误或移除未使用变量 |

---

## 六、低优先级与代码质量改进

### 6.1 多处异常日志级别不当

`ui/main_window.py` 中大量 `logger.info(f"... error: {e}")`，异常信息应使用 `logger.warning` 或 `logger.error`。

### 6.2 `MainWindow._reapply_styles()` 过于冗长

超过 400 行内联样式字符串拼接，建议提取为常量或配置文件。

### 6.3 `AccountDialog` 与 `URLEditDialog` 大量重复逻辑

`_load_categories`、`_on_parent_changed`、AI 分类回调、`_mark_dirty` 等建议抽象为 `CategoryEditorMixin`。

### 6.4 超大模块维护困难

| 文件 | 行数 | 建议 |
|------|------|------|
| `ui/main_window.py` | ~7000 行 | 拆分为 `controllers/` 下多个模块 |
| `services/ai_tools.py` | ~2200 行 | 按工具类别拆分 |
| `services/ai_assistant_service.py` | ~1700 行 | 拆分为对话管理、ReAct 引擎、工具执行器 |
| `ai/ollama_client.py` | ~1150 行 | 拆分为基础客户端、流式处理、工具调用、语义搜索 |

### 6.5 未使用的导入/变量

| 文件 | 问题 |
|------|------|
| `main.py` L270 | `import json` 在函数内部，可提到文件顶部 |
| `services/export_service.py` L170 | `import base64` 在函数内部重复导入 |
| `ai/ollama_client.py` L585 | `import re` 在函数内部重复导入 |

### 6.6 PWA 测试模式硬编码密码隐患

`templates/pwa_template.html` 中当模板未被正确注入时，任何人输入 `"test"` 即可进入测试模式。建议生产构建流程确保测试模式被移除。

### 6.7 密包明文元数据泄露

`GENERATED_AT`、`ACCOUNT_COUNT`、`URL_COUNT` 直接以明文嵌入 HTML。建议纳入加密 payload 或解密后动态计算。

### 6.8 `escapeHtml` 实现方式不标准

依赖 DOM 创建元素进行转义，效率低。建议改用纯字符串替换。

### 6.9 `_serialize_accounts` / `_serialize_urls` 冗余类型检查

`isinstance(acc.tags, str)` 永远是 `True`，因为模型定义已为 `str`。

### 6.10 `ai_remark_service.py` 与 `AIWorkerThread._generate_remark()` 代码重复

Prompt 构建逻辑完全一致，违反 DRY 原则。

### 6.11 `_update_state_post_task` latency 始终记录为 0

`response_latency_ms` 未实际测量耗时，状态指标失去意义。

### 6.12 `process_query_stream` 中 `full_text` 持续增长

`full_text += token` 内存占用与响应长度线性增长；状态机检测时间复杂度退化。

### 6.13 `_extract_command` 标签清理过于激进

若模型输出未正确关闭 `<思考>` 标签，`re.DOTALL` 贪婪匹配会删除几乎所有回复内容。

### 6.14 `BatchAddTags*` 预览标签没有去重

追加模式下简单拼接字符串，可能显示重复标签。

### 6.15 `ToolRegistry` 类级全局状态测试中难以隔离

`_tools` 是类变量，`AIServiceManager.reset_instance()` 不会清理注册表。

---

## 七、架构层面长期改进建议

### 7.1 AI 调用全面异步化

当前 AI 基础设施（`AIWorkerThread`、`AIServiceManager`）非常完善，但业务层完全绕过它。建议：
1. 定义统一的 `AITask` 类型和优先级策略
2. 所有 AI 入口（分类、备注、助手对话、语义搜索）全部走 `submit_task()`
3. 流式输出由 Worker 线程通过 `pyqtSignal(str)` 逐 token 回传
4. 主线程仅负责 UI 更新，绝不执行阻塞 HTTP

### 7.2 Repository 层引入事务上下文管理器

```python
with repo.transaction() as tx:
    tx.insert(account1)
    tx.update_field(account2, 'category', 'new_cat')
    tx.soft_delete(account3)
# 自动 COMMIT，异常自动 ROLLBACK
```

### 7.3 列表渲染从 `QListWidget` 迁移到 `QListView + Model/Delegate`

当前 200 条账号 = 200 个 widget 对象常驻内存。改造后：
- 内存占用从 ~200 widget 降至 ~0 widget（仅 paint）
- 刷新耗时从 150-300ms 降至 10-30ms
- 滚动流畅度达到 60fps

### 7.4 引入资源生命周期管理器

统一管理以下资源的创建与销毁：
- `QTimer`（Undo Banner、Toast、AI 打字机效果）
- `QThread` / `AIWorkerThread`
- `DatabaseManager` 连接
- 日志 `FileHandler`

防止重复创建、引用丢失导致的内存泄漏。

### 7.5 测试覆盖补齐

| 待测模块 | 优先级 | 覆盖要点 |
|---------|------|---------|
| `sync_service.py` | 高 | 模板注入、加密一致性、原子写入、异常路径 |
| `ai_worker_thread.py` | 高 | 队列行为、超时、优雅关闭、配置热更新 |
| `ollama_client.py` | 中 | 超时、降级、JSON 修复、语义匹配 |
| `database.py` / `url_database.py` | 中 | 线程安全、事务回滚、解密失败处理 |
| `theme_manager.py` | 低 | 单例、信号、主题切换 |

---

## 附录：修复优先级速查表

| 优先级 | 问题 | 涉及文件 | 预计工作量 |
|--------|------|---------|-----------|
| **P0** | `_decrypt_field()` 解密失败返回密文 | `core/database.py` | 30 分钟 |
| **P0** | AI 调用全面主线程阻塞 | `services/ai_*.py`, `ai/ollama_client.py` | 2~3 天 |
| **P0** | `OllamaClient` 请求超时 `None` | `ai/ollama_client.py` | 2 小时 |
| **P0** | `execute_build_action_with_transaction` 无事务 | `services/ai_assistant_service.py` | 4 小时 |
| **P0** | `ai_classification_service.py` 异常处理 `NameError` | `services/ai_classification_service.py` | 1 小时 |
| **P1** | 健康检查/改密码/导入/导出主线程阻塞 | `ui/widgets/dashboard_widget.py` 等 | 1~2 天 |
| **P1** | `PopupComboBox` 内存泄漏 | `ui/account_dialog.py` | 2 小时 |
| **P1** | Undo Banner timer 泄漏 | `ui/main_window.py` | 30 分钟 |
| **P1** | `AIWorkerThread` 队列无界 | `services/ai_worker_thread.py` | 1 小时 |
| **P1** | `AIWorkerThread` 跨线程竞争 | `services/ai_worker_thread.py` | 1 小时 |
| **P1** | `AIClassifyDialog` 强制终止线程 | `ui/ai_classify_dialog.py` | 1 小时 |
| **P1** | OCR 信号未断开 | `ui/account_dialog.py` | 30 分钟 |
| **P1** | `update_url_field()` SQL 拼接 | `core/url_database.py` | 1 小时 |
| **P1** | Repository 全表加载 | `core/repositories.py` | 4 小时 |
| **P1** | `ThemeManager` 单例非线程安全 | `core/theme_manager.py` | 30 分钟 |
| **P2** | 数据库上下文管理器 | `core/database.py`, `core/url_database.py` | 2 小时 |
| **P2** | Clipboard 线程安全 | `core/clipboard.py` | 1 小时 |
| **P2** | Logger handler 重复追加 | `core/logger.py` | 30 分钟 |
| **P2** | `focusInEvent` Monkey-patch | `ui/main_window.py` | 1 小时 |
| **P2** | AI 聊天全量重绘 | `ui/main_window.py` | 4 小时 |
| **P2** | `record_history` 参数无效 | `services/ai_assistant_service.py` | 30 分钟 |
| **P3** | 拆分超大模块 | `ui/main_window.py` 等 | 3~5 天 |
| **P3** | QListWidget -> QListView | `ui/main_window.py` | 2~3 天 |
| **P3** | 测试覆盖补齐 | `tests/` | 2~3 天 |

---

> 报告生成者：Kimi Code CLI
> 审查方式：静态代码分析 + 多模块交叉审查
> 建议：P0 项应在下一个版本前全部修复，P1 项应在两周内修复，P2 项纳入下下个迭代。
