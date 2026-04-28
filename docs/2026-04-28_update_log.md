# 2026-04-28 更新日志

## 一、今日工作总览

今日核心工作是 **迭代自纠正循环实现与修复**、**同步到手机功能增强**（类别排序 + 备注显示）、以及 **手机端返回按钮导航栈 bug 修复**。经过多轮验证和紧急修复，解决了模型返回字符串数组导致数据丢失、手机端分类排序错乱、返回按钮点击异常等关键问题。

---

## 二、功能增加与修复明细

### 1. 迭代自纠正循环实现（AI 分类核心）

- **位置**：`services/ai_tools.py` → `SmartClassifyAccountsTool` + `SmartClassifyUrlsTool`
- **目标**：解决 `gemma4:4b` 模型一次性分类大批量条目（>150条）时因输出 token 天花板导致部分 ID 被静默丢弃的问题
- **实现逻辑**：
  1. 第一轮 JSON 解析、force_subclass 修正完成后，自动检测遗漏 ID
  2. 构造精简补充 Prompt（仅含遗漏条目 + 已建立分类体系 + 紧凑格式要求）
  3. 调用 `ollama.generate(temperature=0.3)` 进行第二轮（及第三轮）纠正
  4. 最多 2 次 retry，剩余遗漏由现有 fallback 机制兜底
- **Prompt 关键约束**：
  - 附带已建立的分类体系 `established_cats`，引导模型在现有分类内选择
  - 要求【紧凑格式】单行 JSON
  - 要求【覆盖检查】必须包含全部遗漏 ID

### 2. 自纠正循环紧急修复（数据丢失 bug）

- **位置**：`services/ai_tools.py`
- **现象**：对 212 个网址进行细分时，所有条目被分到 `编程学习与工具>其他`
- **根因**：模型返回的 JSON 中 ID 列表的值是**字符串**而非数组：
  ```json
  {"编程学习与工具>算法与理论":"[97,98,99,...]"}
  ```
  `_normalize_data` 中 `isinstance(id_list, list)` 为 False，所有分类结果被过滤，`data` 变为空字典，212 个 ID 全部变成 missing
- **修复**：`_normalize_data` 增加对字符串数组的处理：
  ```javascript
  if isinstance(id_list, str):
      s = id_list.strip()
      if s.startswith('[') and s.endswith(']'):
          try:
              id_list = json.loads(s)
          except Exception:
              continue
  ```

### 3. force_subclass 模式下 retry 结果未修正（核心 Bug）

- **位置**：`services/ai_tools.py`
- **现象**：force_subclass=True 时，retry 补充的分类可能返回一级分类（如 `考试`）或错误主类（如 `一般与其他>考试`）
- **根因**：retry 结果只经过 `sanitize_ai_category` 就合并到 `data`，没有像第一轮那样的 force_subclass 强制修正
- **修复**：retry 循环内增加与第一轮完全一致的 force_subclass 修正逻辑

### 4. ID 类型不匹配与边界问题修复

- **位置**：`services/ai_tools.py`
- **修复清单**：
  - **ID 类型统一**：新增 `_normalize_data()`，将所有 ID 转为 `int` 并去重，解决 `{1} - {'1'} == {1}` 导致的误判遗漏
  - **0 污染风险**：`input_ids` 和 `missing_xxx` 改用 `getattr(..., None)` 并 `discard(None)`，避免 `getattr(..., 0)` 默认值污染
  - **空值安全**：`SmartClassifyAccountsTool` 中直接属性访问（`a.id`, `acc.app_name` 等）全部替换为 `getattr`
  - **app_name 截断**：初始 prompt 和 retry prompt 中 `app_name` 添加 `[:30]` 截断
  - **日志准确性**：改为 `Retry X: N missing -> M still missing`，合并 retry 结果后重新计算实际遗漏数

---

### 5. 同步到手机：按软件类别顺序排序

- **位置**：`services/sync_service.py` + `ui/main_window.py` + `templates/pwa_template.html`
- **现象**：手机端分类按拼音排序（工具效率类、金融支付类、学习教育类...），与 PC 端用户自定义顺序不一致
- **根因 1（后端）**：`sync_service.py` 后端虽按 `category_orders` 对数据排序，但模板渲染分类网格时又按拼音重新排序
- **根因 2（前端）**：`renderMainScreen` 和 `openSubCategories` 中使用了 `a.localeCompare(b, 'zh-CN')`
- **修复**：
  - `sync_service.py`：payload 中新增 `account_category_orders` 和 `url_category_orders`
  - 模板：新增 `getCurrentCategoryOrders()` 和 `sortCategoriesByOrder()` 函数
  - `renderMainScreen` / `openSubCategories`：按 `sort_index` 排序一级/二级分类，不再按拼音排序

### 6. 同步到手机：添加备注和 AI 备注显示

- **位置**：`services/sync_service.py` + `templates/pwa_template.html`
- **修复清单**：
  - `_serialize_accounts()` 新增 `ai_remark` 字段（之前只有网址库有，账号库漏掉了）
  - 列表页 `createItemCell`：subtitle 中拼接显示备注/AI备注，如 `用户名 · 备注内容`
  - 详情页 `openDetail`：分别显示 **AI 备注** 和 **备注** 两个区域

### 7. 手机端返回按钮修复（导航栈逻辑 bug）

- **位置**：`templates/pwa_template.html` → `popScreen()`
- **现象**：第一次点击返回没反应，第二次点击返回两页；在 PC Edge 中同样复现
- **根因**：`pushScreen` 把目标页面 push 进 `navStack`，但 `popScreen` 把栈顶页面 pop 出来并显示它：
  ```javascript
  // navStack = ['itemsScreen']
  const prev = navStack.pop();  // prev = 'itemsScreen'
  show(prev.screen);            // 显示 'itemsScreen' —— 还是当前页！
  ```
- **修复**：`popScreen` 改为先丢弃当前页，再显示栈顶的上一个页面：
  ```javascript
  navStack.pop(); // 丢弃当前 screen
  const prev = navStack.length > 0 ? navStack[navStack.length - 1] : null;
  // 显示 prev.screen（上一个页面）
  ```
- **附加优化**：
  - 去掉有问题的 300ms 防抖机制
  - 增大返回按钮触摸区域：`padding:0 12px`，CSS 改为 `top:0; bottom:0` 垂直居中，去掉 `transform:translateY(-50%)`

---

## 三、涉及文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `services/ai_tools.py` | 修改 | 迭代自纠正循环实现 + 字符串数组处理 + ID 类型统一 + force_subclass retry 修正 |
| `services/sync_service.py` | 修改 | 类别排序传入模板 + 账号 ai_remark 字段 |
| `ui/main_window.py` | 修改 | 同步时传入 category_orders |
| `templates/pwa_template.html` | 修改 | 分类按 order 排序 + 备注/AI备注显示 + 返回按钮导航栈修复 |
| `docs/2026-04-28_update_log.md` | 新增 | 本文档 |

---

## 四、遗留待验证项

- [ ] 200+ 条网址大规模分类覆盖率验证（自纠正循环实际效果）
- [ ] Build 模式下预览确认后左侧高亮受影响账号
