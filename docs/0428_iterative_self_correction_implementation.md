# 0428 迭代自纠正循环实现 — 完成待检查文档

## 一、实现目标

解决 `gemma4:4b` 模型在一次性分类大批量条目（>150条）时因输出 token 天花板导致部分 ID 被静默丢弃的问题。

通过在第一轮全量分类后，**自动检测遗漏 ID 并构造精简补充 Prompt 进行第二轮（及第三轮）纠正**，提升分类覆盖率。

---

## 二、修改文件清单

| 文件 | 修改位置 | 说明 |
|------|----------|------|
| `services/ai_tools.py` | `SmartClassifyAccountsTool.execute()` 内 line ~1166 | 账号分类自纠正循环 |
| `services/ai_tools.py` | `SmartClassifyUrlsTool.execute()` 内 line ~1470 | 网址分类自纠正循环 |

---

## 三、实现逻辑

### 3.1 触发时机
第一轮 JSON 解析、force_subclass 修正完成后，进入分类预览生成**之前**。

### 3.2 循环流程
```
for retry in range(2):          # 最多补充 2 轮
    1. 统计 data 中所有已分类的 ID
    2. 与 input_ids 对比，得到 missing_ids
    3. 若 missing_ids 为空 → break，流程正常继续
    4. 提取遗漏条目的精简信息（ID + 标题/应用名 + 原分类 + 备注）
    5. 构造补充 Prompt：
       - 告知模型"这是第一轮遗漏的条目"
       - 附带已建立的分类体系（established_cats）
       - 要求【紧凑格式】单行 JSON
       - 要求【覆盖检查】必须包含全部遗漏 ID
    6. 调用 ollama.generate(temperature=0.3)
    7. 用现有的 _extract_json_object_robust + _fix_json 解析
    8. 合并结果到 data（sanitize_ai_category + setdefault）
    9. 若解析失败 → break，避免无限循环
```

### 3.3 Prompt 关键约束
- **已建立分类体系**：`{', '.join(established_cats)}`，引导模型在现有分类内选择，避免引入新的不一致分类
- **覆盖检查**：明确要求输出包含全部 N 个遗漏 ID
- **紧凑格式**：单行 JSON，减少 token 消耗

### 3.4 遗漏条目信息构成
| 字段 | 长度限制 | 说明 |
|------|----------|------|
| ID | 完整 | 必须保留，否则无法回填 |
| 标题/应用名 | 30字符 | 提供语义线索 |
| 原分类 | 完整 | 帮助模型判断归属 |
| 备注 | 20字符 | 补充语义线索 |
| AI备注 | 20字符 | 补充语义线索 |

---

## 四、与现有机制的协作关系

| 现有机制 | 自纠正循环如何与之配合 |
|----------|------------------------|
| Missing-ID Fallback（未分类兜底） | 自纠正循环在兜底**之前**执行，尽量让模型主动分类，减少 fallback 数量 |
| 重复去重（最长路径保留） | 自纠正循环合并结果后，正常进入重复去重逻辑，不会破坏现有策略 |
| force_subclass 自动修正 | 自纠正循环在 force_subclass 修正**之后**执行，确保补充分类也受到主类约束 |
| Compact JSON + _fix_json | 复用现有 JSON 提取和修复链，无需额外逻辑 |

---

## 五、待检查事项清单

### ☐ 5.1 覆盖率提升验证
- [ ] 对 200+ 条网址执行"智能分类"
- [ ] 观察控制台输出，检查是否有 `[SmartClassifyUrls] Retry 1: X missing classified`
- [ ] 对比修改前后，统计最终 missing fallback 的数量（目标：从 60+ 降至接近 0）

### ☐ 5.2 循环终止验证
- [ ] 测试小规模数据（<50条，无遗漏场景），确认循环不触发
- [ ] 测试中等规模数据（100-150条），确认最多触发 1 次 retry
- [ ] 故意构造 JSON 解析失败场景（如模型返回非 JSON），确认循环在 `except` 中正确 break

### ☐ 5.3 分类质量验证
- [ ] 检查 retry 补充的分类是否与第一轮分类风格一致
- [ ] 确认 retry 没有引入新的、奇怪的分类名称（应优先使用 established_cats）
- [ ] 确认 force_subclass 模式下，retry 补充的分类也符合主类约束

### ☐ 5.4 账号库验证
- [ ] 对账号库执行批量智能分类（如"按平台细分"）
- [ ] 检查 `[SmartClassify] Retry X` 日志输出
- [ ] 验证覆盖率与网址库一致

### ☐ 5.5 性能与稳定性
- [ ] 观察 retry 是否显著增加总耗时（每次 retry 约 1-3s，可接受）
- [ ] 确认 retry Prompt 不会导致上下文过长（遗漏条目通常 <100 条，Prompt 长度可控）

---

## 六、已知限制

1. **最多 2 次 retry**：若模型连续两轮都遗漏部分 ID，第三轮将停止，剩余遗漏由现有 fallback 机制兜底到 `主类>未分类`
2. **不处理重复**：retry 只解决"遗漏"，不解决"重复分配"。重复问题仍由现有的"最长路径保留"策略处理
3. **依赖模型配合**：即使 Prompt 明确要求"零遗漏"，模型仍可能不守规矩，fallback 机制是最后保障

---

## 七、调试命令

观察 retry 行为的控制台关键词：
```
[SmartClassifyUrls] Retry 1: 45 missing classified
[SmartClassifyUrls] Retry 2: 3 missing classified
[SmartClassify] Retry 1: 12 missing classified
```

若未看到 retry 日志但仍有遗漏，检查：
- 模型是否在第一轮就完整输出了（可能是小规模数据）
- `generate()` 调用是否因网络/模型问题抛出异常

---

**文档创建时间**：2026-04-28  
**对应提交**：自纠正循环实现（`services/ai_tools.py` 双工具更新）
