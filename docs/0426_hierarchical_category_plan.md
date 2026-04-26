# 0426 二级分类（路径分隔符）实施方案

## 一、背景与目标

将现有的一级分类体系升级为**二级（可扩展至多级）分类体系**，使用 `>` 作为层级分隔符。

- **旧格式**：`金融`、`工具`、`工作`（一级）
- **新格式**：`工作>开发工具`、`娱乐>游戏`（二级），同时兼容旧一级格式如 `工作`

## 二、核心设计原则

1. **零数据库表结构变更**：`category` 字段语义不变，仅值格式扩展
2. **向后兼容**：无 `>` 的旧分类视为一级节点，无需修改即可正常展示
3. **数据清洗**：现有数据中的 `/`（如 `金融/支付`）统一替换为 `·`，消除与分隔符的歧义
4. **AI 防错**：Prompt 中明确 `>` 是唯一层级分隔符，分类名禁止包含 `/`、`>`、`·`

## 三、数据清洗方案（一次性脚本）

**脚本位置**：`scripts/migrate_category_separator.py`（新建）

**操作内容**：
- 扫描 `accounts` 表和 `urls` 表的 `category` 字段
- 将所有 `/` 替换为 `·`（如 `金融/支付` → `金融·支付`）
- 同时清理 `category_cache` 表中的旧缓存

**执行时机**：在代码升级前执行，升级后的代码不再产生含 `/` 的分类名。

## 四、各模块改动清单

### 4.1 AI 分类与 Prompt（高优先级）

| 文件 | 改动内容 |
|---|---|
| `services/ai_tools.py` | 1. 分类 Prompt 中增加规则：`>` 是唯一层级分隔符；分类名禁止包含 `/`、`>`、`·`<br>2. 输出校验：若 AI 返回的分类名含非法字符，自动替换为 `-` 或拒绝重试 |
| `services/batch_add_processor.py` | 批量添加的 Prompt 示例和约束同步更新 |
| `services/ai_classification_service.py` | AI 智能归类时的分类建议支持 `>` 格式 |
| `services/ai_assistant_service.py` | AI 助手对话中涉及分类的 Prompt 和解析逻辑更新 |

### 4.2 分类服务与数据层（高优先级）

| 文件 | 改动内容 |
|---|---|
| `services/account_service.py` | `get_categories()` 返回结构从扁平列表改为**树形结构**（或增加 `get_category_tree()` 方法） |
| `services/url_service.py` | 同上 |
| `services/category_service.py` | 1. 规则匹配和 AI 分类输出支持 `>` 路径<br>2. 缓存键需兼容含 `>` 的分类名 |
| `core/database.py` | `get_categories()`、`get_accounts_by_category()` 等查询需支持**前缀匹配**（点选父节点时显示所有子类条目） |
| `core/url_database.py` | 同上 |

### 4.3 主界面分类侧边栏（高优先级）

| 文件 | 改动内容 |
|---|---|
| `ui/main_window.py` | 1. 分类列表从 `QListWidget` 改为 `QTreeWidget`<br>2. 解析 `>` 分隔的路径自动构建树节点<br>3. 点击父节点（如 `工作`）→ 显示 `工作` 和 `工作>开发工具` 等所有条目<br>4. 点击子节点（如 `工作>开发工具`）→ 精确匹配<br>5. 右键重命名/删除需支持树节点操作 |

### 4.4 编辑/添加弹窗（中优先级）

| 文件 | 改动内容 |
|---|---|
| `ui/account_dialog.py` | 分类选择器支持输入含 `>` 的路径，或提供级联选择（一级下拉 + 二级下拉/输入） |
| `ui/url_dialog.py` | 同上 |
| `ui/ai_classify_dialog.py` | AI 分类预览展示层级路径 |

### 4.5 导入导出（中优先级）

| 文件 | 改动内容 |
|---|---|
| `services/export_service.py` | 1. Excel 导出：分类列展示完整路径（如 `工作>开发工具`）<br>2. HTML 书签导出：按 `>` 解析为嵌套文件夹结构（`<H3>` 层级嵌套） |
| `services/import_service.py` | 浏览器 HTML 书签导入：嵌套文件夹解析为 `>` 路径 |
| `ui/export_dialog.py` | 分类下拉框展示树形层级 |
| `ui/import_dialog.py` | 分类映射界面支持层级展示 |

### 4.6 输入校验与工具函数（中优先级）

| 文件/位置 | 改动内容 |
|---|---|
| 新增 `core/category_utils.py` | 提供工具函数：`parse_category_path()`、`get_parent_category()`、`validate_category_name()`（禁止 `/`、`>`、`·`） |
| `ui/account_dialog.py`、`ui/url_dialog.py` | 用户手动输入分类名时调用校验，含非法字符时提示并阻止保存 |

### 4.7 其他（低优先级）

| 文件 | 改动内容 |
|---|---|
| `services/search_service.py` | 分类筛选搜索支持按层级前缀匹配 |
| `services/semantic_search_service.py` | 如有分类相关逻辑，同步适配 |
| `ui/recycle_bin_dialog.py` | 回收站展示分类路径 |

## 五、实施步骤（优先级排序）

### Phase 1：基础设施（约 2h）
1. 编写并执行数据清洗脚本（`/ `→ `·`）
2. 新建 `core/category_utils.py`，封装路径解析和校验工具
3. 更新 `services/ai_tools.py` 和所有 AI Prompt，约束 `>` 为唯一分隔符

### Phase 2：数据层与服务层（约 3h）
4. 更新 `services/account_service.py`、`services/url_service.py` 的 `get_categories()`，支持返回树形结构
5. 更新 `core/database.py`、`core/url_database.py` 的分类查询，支持前缀匹配
6. 更新 `services/category_service.py` 的 AI 分类输出逻辑

### Phase 3：UI 核心（约 4h）
7. `ui/main_window.py` 侧边栏改为 `QTreeWidget`，实现路径解析和树形展示
8. `ui/account_dialog.py`、`ui/url_dialog.py` 分类选择器支持 `>` 路径输入/级联选择
9. `ui/ai_classify_dialog.py` 预览层级展示

### Phase 4：导入导出（约 2h）
10. `services/export_service.py` HTML 书签导出支持嵌套文件夹
11. `services/import_service.py` HTML 书签导入解析嵌套为路径
12. `ui/export_dialog.py`、`ui/import_dialog.py` 分类选择器适配

### Phase 5：收尾（约 1h）
13. 全项目搜索含 `/` 的分类相关硬编码，统一清理
14. 回归测试：AI 分类、批量添加、导入导出、筛选搜索

## 六、风险与回退方案

| 风险 | 应对措施 |
|---|---|
| AI 仍输出含 `/` 的分类名 | Prompt 增加强约束 + 输出校验拦截 + 自动替换为 `-` |
| 树形控件性能差（分类数量大时） | 采用懒加载，只展开时解析子节点；或限制层级深度为 2 级 |
| 旧数据清洗遗漏 | 清洗脚本增加校验日志，运行后输出所有被修改的条目供人工复核 |
| 用户不习惯输入 `>` | 提供级联下拉选择（一级 + 二级），无需手动输入 |

## 七、示例数据流转

```
【用户添加账号】
应用名：GitHub
用户选择分类：工作 > 开发工具
实际存储：category = "工作>开发工具"

【主界面侧边栏展示】
▼ 工作 (12)
  ├── 开发工具 (5)
  ├── 设计 (3)
  └── 其他 (4)

【点击"工作"】→ 显示所有 category 以 "工作" 开头的条目
【点击"工作>开发工具"】→ 精确匹配 category = "工作>开发工具"

【导出 HTML 书签】
<DT><H3>工作</H3>
<DL><p>
    <DT><H3>开发工具</H3>
    <DL><p>
        <DT><A HREF="https://github.com">GitHub</A>
    </DL><p>
</DL><p>
```

---

**预计总工时**：约 12 小时（可分 2~3 次完成）
**是否立即实施**：由用户确认后启动
