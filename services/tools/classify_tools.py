"""
智能分类类工具 — 智能分类账号和网址
"""
import json
import logging

from .base import AITool, ToolRegistry, ToolResult, PermissionLevel

logger = logging.getLogger(__name__)


def sanitize_ai_category(ai_output: str) -> str:
    """
    校验并修正 AI 输出的分类路径。

    规则：
    1. 去除首尾空白
    2. 替换非法字符 `/`、`·` 为 `-`
    3. 截断三级及以上为二级
    4. 规范 `> ` 和 ` >` 等空格问题（通过 parse + format 自然实现）
    """
    from core.category_utils import format_category_path, parse_category_path

    # 1. 去除首尾空白
    cleaned = ai_output.strip()

    # 2. 替换非法字符
    if any(c in cleaned for c in ['/', '·']):
        cleaned = cleaned.replace('/', '-').replace('·', '-')

    # 3. 使用 parse_category_path 解析，三级及以上截断为二级
    try:
        parent, child = parse_category_path(cleaned)
    except ValueError:
        first_sep = cleaned.find('>')
        if first_sep != -1:
            second_sep = cleaned.find('>', first_sep + 1)
            if second_sep != -1:
                cleaned = cleaned[:second_sep]
        parent, child = parse_category_path(cleaned)

    # 4. 通过 format_category_path 规范化空格
    return format_category_path(parent, child)


@ToolRegistry.register(
    name="smart_classify_accounts",
    description="智能分类账号（自动获取全部账号，无需传入ID列表）",
    permission=PermissionLevel.PREVIEW,
    params_schema={}
)
class SmartClassifyAccountsTool(AITool):
    def execute(self, params, context):
        accounts = context.get("accounts", [])
        if not accounts:
            return ToolResult(success=False, message="没有可分类的账号")

        # 获取用户原始查询作为分类指令
        user_query = context.get('query', '请对以下账号进行分类')

        # 获取现有分类列表
        existing_categories = []
        repo = context.get("repo")
        if repo and hasattr(repo, 'get_categories'):
            try:
                existing_categories = repo.get_categories()
            except Exception:
                pass

        # 检测用户是否在查询中指定了某个具体分类
        # 从现有分类中查找在 user_query 中出现过的分类名（支持完整路径或父节点匹配）
        target_category = None
        matched_cats = []
        for cat in existing_categories:
            if not cat or cat == '全部':
                continue
            if cat in user_query:
                matched_cats.append(cat)
            elif '>' in cat:
                parent = cat.split('>')[0].strip()
                if parent in user_query:
                    matched_cats.append(parent)
        if matched_cats:
            # 优先匹配最长的（更精确）
            target_category = max(matched_cats, key=len)

        # 如果用户指定了具体分类，只筛选该分类下的账号
        if target_category:
            from core.category_utils import get_prefix_matcher
            matcher = get_prefix_matcher(target_category)
            filtered_accounts = [acc for acc in accounts if matcher(acc.category or '')]
            if filtered_accounts:
                accounts = filtered_accounts
                scope_hint = f"（仅处理「{target_category}」分类下的 {len(accounts)} 个账号）"
            else:
                scope_hint = ""
        else:
            scope_hint = ""

        # 构建账号信息（key=value 形式，不暴露内部格式）
        lines = []
        for acc in accounts:
            remark = (acc.remark or '')[:20]
            ai_remark = (getattr(acc, 'ai_remark', '') or '')[:20]
            parts = [f"ID={acc.id}", f"应用名={(acc.app_name or '')[:30]}", f"分类={(acc.category or '未分类')[:30]}"]
            if remark:
                parts.append(f"备注={remark}")
            if ai_remark:
                parts.append(f"AI备注={ai_remark}")
            lines.append(", ".join(parts))
        items_str = '\n'.join(lines)

        # 格式化现有分类列表，同时提取一级分类名
        top_level_cats = set()
        if existing_categories:
            tree_lines = []
            for cat in sorted(existing_categories):
                if cat and cat != '全部':
                    tree_lines.append(f"  - {cat}")
                    if '>' in cat:
                        top_level_cats.add(cat.split('>')[0].strip())
                    else:
                        top_level_cats.add(cat.strip())
            category_tree_text = "\n".join(tree_lines) if tree_lines else "  （暂无分类）"
            top_level_text = "\n".join(f"  - {c}" for c in sorted(top_level_cats)) if top_level_cats else "  （暂无）"
        else:
            category_tree_text = "  （暂无分类）"
            top_level_text = "  （暂无）"

        # 检测用户是否明确要求细分二级子类
        force_subclass_keywords = ['细分', '二级', '子类', '子分类']
        force_subclass = any(kw in user_query for kw in force_subclass_keywords)

        if force_subclass:
            # 推断主分类名（从 target_category 或 top_level_cats）
            main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
            rules_text = f"""【输出规则】（必须严格遵守）：
1. 输出格式必须是严格JSON：{{"类别名": [ID列表], ...}}
2. 每个类别名必须是二级分类路径，格式为 `主类>子类`，如 `{main_category}>考试`、`{main_category}>课程平台`
3. 这些账号都属于 `{main_category}` 分类体系（有些可能已有二级子类如 `{main_category}>xxx`，有些可能仍是一级 `{main_category}`）。你的任务是重新细分/调整二级子类，但主类必须是 `{main_category}`，绝对不允许更改
4. 子类名绝对不能和以下一级分类名重复：
{top_level_text}
5. 你必须根据每个账号的应用名、备注等信息，尽可能细分到合理的二级子类。不允许因为"看起来比较杂"就把所有条目归到同一个分类下偷懒
6. 优先匹配【当前分类体系】中已有的路径
7. 如需新建子类，子类名应简洁明确（2-4个字），如 `考试`、`课程平台`、`学术工具`、`语言学习`
8. 分类名中禁止包含 `/`、`·` 两个符号
9. 层级分隔符 `>` 最多出现一次，禁止输出三级及以上路径（如 `A>B>C` 是非法的）
10. 不要在任何值中包含英文双引号"，如需引用请用中文引号「」
11. 【绝对禁止】更改一级分类。所有输出分类的主类必须是 `{main_category}`，不允许改成其他主类如 `一般与其他>xxx`
12. 【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。ID之间只用逗号分隔，如 `[101,102,103,104]`
13. 【覆盖检查】输出JSON中所有类别的ID总数必须等于输入条目总数，不允许遗漏任何一个ID。如果某个ID确实难以归类，也必须分配到一个最接近的类别中，绝不能跳过。

【输出示例】
{{"{main_category}>考试":[101,102],"{main_category}>课程平台":[103,104,105],"{main_category}>学术工具":[106]}}"""
        else:
            rules_text = """【输出规则】（必须严格遵守）：
1. 输出格式必须是严格JSON：{"类别名": [ID列表], ...}
2. 类别名使用分类路径格式：`主类>子类`（最多二级），如 `工作>开发工具`、`娱乐>游戏`
3. 默认情况下只输出一级分类。如果某个条目确实无法归入更细的子类，只输出主类，如 `教育与学习`。
4. 只有在用户明确要求细分或条目明显需要细分时，才输出二级分类路径，如 `教育与学习>考试`。
5. 优先匹配【当前分类体系】中已有的路径
6. 如需新建子类，确保主类已存在于体系中；如需新建主类，直接输出主类名
7. 分类名中禁止包含 `/`、`·` 两个符号
8. 并列概念用"与"连接，如 `金融与支付`、`工具与系统`
9. 层级分隔符 `>` 最多出现一次，禁止输出三级及以上路径（如 `A>B>C` 是非法的）
10. 不要在任何值中包含英文双引号"，如需引用请用中文引号「」
11. 【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。ID之间只用逗号分隔，如 `[101,102,103,104]`
12. 【覆盖检查】输出JSON中所有类别的ID总数必须等于输入条目总数，不允许遗漏任何一个ID。如果某个ID确实难以归类，也必须分配到一个最接近的类别中，绝不能跳过。

【输出示例】
{"工作>开发工具":[101,102],"娱乐>游戏":[103,104,105]}"""

        prompt = f"""你正在执行用户的分类指令。请仔细阅读所有账号信息，严格按照用户指令进行分类。

【重要】输入共 {len(accounts)} 个账号，你必须为每一个账号分配分类。输出JSON必须包含全部 {len(accounts)} 个ID，不允许遗漏任何一个。遗漏会导致数据丢失！

用户指令：{user_query} {scope_hint}

【当前分类体系】
{category_tree_text}

账号信息（共 {len(accounts)} 条）：
{items_str}

{rules_text}

输出："""

        # 调用大模型一次完成全部分类
        from ai.ollama_client import OllamaClient
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        state = ai_manager.get_state()
        ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=300)
        raw = ollama.generate(prompt, temperature=0.3)

        # 解析JSON
        extracted = OllamaClient._extract_json_object_robust(raw) or raw
        fixed = OllamaClient._fix_json(extracted)
        try:
            data = json.loads(fixed)
        except Exception as e:
            logger.warning("JSON parse failed: %s, raw preview: %r", e, raw[:300])
            return ToolResult(success=False, message=f"分类结果解析失败: {e}")

        # 统一ID类型为int，并去重
        def _normalize_data(raw_data):
            """将分类结果中的ID统一转为int并去重，同时处理模型返回的字符串数组"""
            result = {}
            for cat_name, id_list in raw_data.items():
                # 处理模型返回字符串形式如 "[1,2,3]" 的情况
                if isinstance(id_list, str):
                    s = id_list.strip()
                    if s.startswith('[') and s.endswith(']'):
                        try:
                            id_list = json.loads(s)
                        except Exception:
                            continue
                    else:
                        continue
                if not isinstance(id_list, list):
                    continue
                cleaned_name = sanitize_ai_category(cat_name)
                int_ids = []
                seen = set()
                for tid in id_list:
                    try:
                        int_tid = int(tid)
                        if int_tid not in seen:
                            seen.add(int_tid)
                            int_ids.append(int_tid)
                    except (ValueError, TypeError):
                        continue
                if int_ids:
                    result.setdefault(cleaned_name, []).extend(int_ids)
            return result

        data = _normalize_data(data)

        # 兜底：force_subclass 模式下，强制修正一级分类和错误的主类
        if force_subclass:
            main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
            corrected_data = {}
            for cat_name, id_list in data.items():
                cleaned = sanitize_ai_category(cat_name)
                if '>' not in cleaned:
                    logger.debug("AUTO-CORRECT: '%s' -> '%s>其他' (force_subclass)", cleaned, main_category)
                    cleaned = f"{main_category}>其他"
                else:
                    actual_main = cleaned.split('>')[0].strip()
                    if actual_main != main_category:
                        sub = cleaned.split('>', 1)[1].strip()
                        logger.debug("AUTO-CORRECT: main '%s' -> '%s', sub '%s' (force_subclass)", actual_main, main_category, sub)
                        cleaned = f"{main_category}>{sub}"
                corrected_data.setdefault(cleaned, []).extend(id_list)
            data = corrected_data

        # 自纠正循环：处理遗漏的ID
        input_ids = {getattr(a, 'id', None) for a in accounts}
        input_ids.discard(None)
        for retry in range(2):
            classified_ids = set()
            for id_list in data.values():
                if isinstance(id_list, list):
                    classified_ids.update(id_list)
            missing_ids = input_ids - classified_ids
            if not missing_ids:
                break

            missing_accounts = [a for a in accounts if getattr(a, 'id', None) in missing_ids]
            missing_lines = []
            for acc in missing_accounts:
                remark = (getattr(acc, 'remark', '') or '')[:20]
                ai_remark = (getattr(acc, 'ai_remark', '') or '')[:20]
                parts = [f"ID={getattr(acc, 'id', 0)}", f"应用名={(getattr(acc, 'app_name', '') or '')[:30]}", f"分类={(getattr(acc, 'category', '') or '未分类')[:30]}"]
                if remark:
                    parts.append(f"备注={remark}")
                if ai_remark:
                    parts.append(f"AI备注={ai_remark}")
                missing_lines.append(", ".join(parts))
            missing_items_str = '\n'.join(missing_lines)

            established_cats = list(dict.fromkeys(sanitize_ai_category(c) for c in data.keys()))
            retry_prompt = f"""你正在执行分类补充任务。以下是第一轮分类时遗漏的账号，请为它们分配最合适的分类。

【重要】这些是第一轮遗漏的 {len(missing_accounts)} 个账号，必须全部分类，不允许再遗漏！

已建立的分类体系（请优先从中选择）：
{', '.join(established_cats)}

账号信息（共 {len(missing_accounts)} 条）：
{missing_items_str}

输出格式必须是严格JSON：{{"类别名": [ID列表], ...}}
【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。
【覆盖检查】输出必须包含全部 {len(missing_accounts)} 个ID。

输出："""

            raw_retry = ollama.generate(retry_prompt, temperature=0.3)
            extracted_retry = OllamaClient._extract_json_object_robust(raw_retry) or raw_retry
            fixed_retry = OllamaClient._fix_json(extracted_retry)
            try:
                retry_data = json.loads(fixed_retry)
                retry_data = _normalize_data(retry_data)
                # force_subclass 模式下对retry结果同样强制修正主类
                if force_subclass:
                    main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
                    corrected_retry = {}
                    for cat_name, id_list in retry_data.items():
                        cleaned = sanitize_ai_category(cat_name)
                        if '>' not in cleaned:
                            logger.debug("AUTO-CORRECT retry: '%s' -> '%s>其他' (force_subclass)", cleaned, main_category)
                            cleaned = f"{main_category}>其他"
                        else:
                            actual_main = cleaned.split('>')[0].strip()
                            if actual_main != main_category:
                                sub = cleaned.split('>', 1)[1].strip()
                                logger.debug("AUTO-CORRECT retry: main '%s' -> '%s', sub '%s' (force_subclass)", actual_main, main_category, sub)
                                cleaned = f"{main_category}>{sub}"
                        corrected_retry.setdefault(cleaned, []).extend(id_list)
                    retry_data = corrected_retry
                for cat_name, id_list in retry_data.items():
                    data.setdefault(sanitize_ai_category(cat_name), []).extend(id_list)
                # 重新计算仍然遗漏的数量
                classified_ids = set()
                for id_list in data.values():
                    if isinstance(id_list, list):
                        classified_ids.update(id_list)
                still_missing = input_ids - classified_ids
                logger.info("Retry %d: %d missing -> %d still missing", retry+1, len(missing_ids), len(still_missing))
            except Exception as e:
                logger.warning("Retry %d failed: %s", retry+1, e)
                break

        # 生成分类变更预览
        item_map = {a.id: a for a in accounts if hasattr(a, 'id')}
        preview_items = []
        
        # 第一轮：收集每个ID被分配到的所有分类
        id_to_cats = {}
        cat_order = []
        for cat_name, id_list in data.items():
            if not isinstance(id_list, list):
                continue
            cat_name = sanitize_ai_category(cat_name)
            if cat_name not in cat_order:
                cat_order.append(cat_name)
            for tid in id_list:
                id_to_cats.setdefault(tid, []).append(cat_name)
        
        # 第二轮：处理重复，保留路径最长的分类（长度相同保留首次出现的）
        resolved = {}
        cat_rank = {c: i for i, c in enumerate(cat_order)}
        for tid, cats in id_to_cats.items():
            if len(cats) > 1:
                best_cat = max(cats, key=lambda c: (len(c), cat_rank.get(c, float('inf'))))
                logger.debug("RESOLVE duplicate id=%s: keep '%s', drop %s", tid, best_cat, cats)
            else:
                best_cat = cats[0]
            resolved[tid] = best_cat
        
        # 收集实际使用的分类（保持顺序）
        categories = list(dict.fromkeys(resolved.values()))
        
        # 第三轮：生成预览
        seen_ids = set()
        for tid, best_cat in resolved.items():
            item = item_map.get(tid)
            if item:
                seen_ids.add(tid)
                preview_items.append(self._make_preview_item(
                    row_id=str(tid),
                    display_name=item.app_name,
                    secondary_name="",
                    fields=[{"field_name": "category", "old_value": item.category or '未分类', "new_value": best_cat}],
                    raw_data={"target_id": tid, "field": "category", "new_value": best_cat}
                ))

        # 遗漏检测：找出模型未返回的ID
        input_ids = {a.id for a in accounts if hasattr(a, 'id')}
        missing_ids = input_ids - seen_ids
        if missing_ids:
            fallback_cat = f"{main_category}>未分类" if force_subclass else '其他'
            logger.warning("MISSING %d IDs: %s%s", len(missing_ids), sorted(missing_ids)[:20], '...' if len(missing_ids) > 20 else '')
            for tid in missing_ids:
                item = item_map.get(tid)
                if item:
                    old_cat = item.category or '未分类'
                    preview_items.append(self._make_preview_item(
                        row_id=str(tid),
                        display_name=item.app_name,
                        secondary_name="",
                        fields=[{"field_name": "category", "old_value": old_cat, "new_value": fallback_cat}],
                        raw_data={"target_id": tid, "field": "category", "new_value": fallback_cat}
                    ))
                    seen_ids.add(tid)

        preview = self._make_preview("classify", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items), "categories": categories},
            message=f"待智能分类 {len(preview_items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="smart_classify_urls",
    description="智能分类网址（自动获取全部网址，无需传入ID列表）",
    permission=PermissionLevel.PREVIEW,
    params_schema={}
)
class SmartClassifyUrlsTool(AITool):
    def execute(self, params, context):
        urls = context.get("urls", [])
        if not urls:
            return ToolResult(success=False, message="没有可分类的网址")

        # 获取用户原始查询作为分类指令
        user_query = context.get('query', '请对以下网址进行分类')

        # 获取现有分类列表
        existing_categories = []
        repo = context.get("repo")
        if repo and hasattr(repo, 'get_categories'):
            try:
                existing_categories = repo.get_categories()
            except Exception:
                pass

        # 检测用户是否在查询中指定了某个具体分类
        # 从现有分类中查找在 user_query 中出现过的分类名（支持完整路径或父节点匹配）
        target_category = None
        matched_cats = []
        for cat in existing_categories:
            if not cat or cat == '全部':
                continue
            if cat in user_query:
                matched_cats.append(cat)
            elif '>' in cat:
                parent = cat.split('>')[0].strip()
                if parent in user_query:
                    matched_cats.append(parent)
        if matched_cats:
            target_category = max(matched_cats, key=len)

        # 如果用户指定了具体分类，只筛选该分类下的网址
        if target_category:
            from core.category_utils import get_prefix_matcher
            matcher = get_prefix_matcher(target_category)
            filtered_urls = [u for u in urls if matcher(getattr(u, 'category', '') or '')]
            if filtered_urls:
                urls = filtered_urls
                scope_hint = f"（仅处理「{target_category}」分类下的 {len(urls)} 个网址）"
            else:
                scope_hint = ""
        else:
            scope_hint = ""

        # 构建网址信息（key=value 形式，精简：去掉网址URL，保留标题/分类/备注/AI备注）
        lines = []
        for u in urls:
            title = getattr(u, 'title', '')[:30]
            cat = getattr(u, 'category', '') or '未分类'
            remark = (getattr(u, 'remark', '') or '')[:20]
            ai_remark = (getattr(u, 'ai_remark', '') or '')[:20]
            parts = [f"ID={getattr(u, 'id', 0)}", f"标题={title}", f"分类={cat}"]
            if remark:
                parts.append(f"备注={remark}")
            if ai_remark:
                parts.append(f"AI备注={ai_remark}")
            lines.append(", ".join(parts))
        items_str = '\n'.join(lines)

        # 格式化现有分类列表，同时提取一级分类名
        top_level_cats = set()
        if existing_categories:
            tree_lines = []
            for cat in sorted(existing_categories):
                if cat and cat != '全部':
                    tree_lines.append(f"  - {cat}")
                    if '>' in cat:
                        top_level_cats.add(cat.split('>')[0].strip())
                    else:
                        top_level_cats.add(cat.strip())
            category_tree_text = "\n".join(tree_lines) if tree_lines else "  （暂无分类）"
            top_level_text = "\n".join(f"  - {c}" for c in sorted(top_level_cats)) if top_level_cats else "  （暂无）"
        else:
            category_tree_text = "  （暂无分类）"
            top_level_text = "  （暂无）"

        # 检测用户是否明确要求细分二级子类
        force_subclass_keywords = ['细分', '二级', '子类', '子分类']
        force_subclass = any(kw in user_query for kw in force_subclass_keywords)

        if force_subclass:
            main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
            rules_text = f"""【输出规则】（必须严格遵守）：
1. 输出格式必须是严格JSON：{{"类别名": [ID列表], ...}}
2. 每个类别名必须是二级分类路径，格式为 `主类>子类`，如 `{main_category}>考试`、`{main_category}>课程平台`
3. 这些网址都属于 `{main_category}` 分类体系（有些可能已有二级子类如 `{main_category}>xxx`，有些可能仍是一级 `{main_category}`）。你的任务是重新细分/调整二级子类，但主类必须是 `{main_category}`，绝对不允许更改
4. 子类名绝对不能和以下一级分类名重复：
{top_level_text}
5. 你必须根据每个网址的标题、备注等信息，尽可能细分到合理的二级子类。不允许因为"看起来比较杂"就把所有条目归到同一个分类下偷懒
6. 优先匹配【当前分类体系】中已有的路径
7. 如需新建子类，子类名应简洁明确（2-4个字），如 `考试`、`课程平台`、`学术工具`、`语言学习`
8. 分类名中禁止包含 `/`、`·` 两个符号
9. 层级分隔符 `>` 最多出现一次，禁止输出三级及以上路径（如 `A>B>C` 是非法的）
10. 不要在任何值中包含英文双引号"，如需引用请用中文引号「」
11. 【绝对禁止】更改一级分类。所有输出分类的主类必须是 `{main_category}`，不允许改成其他主类如 `一般与其他>xxx`
12. 【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。ID之间只用逗号分隔，如 `[101,102,103,104]`
13. 【覆盖检查】输出JSON中所有类别的ID总数必须等于输入条目总数，不允许遗漏任何一个ID。如果某个ID确实难以归类，也必须分配到一个最接近的类别中，绝不能跳过。

【输出示例】
{{"{main_category}>考试":[101,102],"{main_category}>课程平台":[103,104,105],"{main_category}>学术工具":[106]}}"""
        else:
            rules_text = """【输出规则】（必须严格遵守）：
1. 输出格式必须是严格JSON：{"类别名": [ID列表], ...}
2. 类别名使用分类路径格式：`主类>子类`（最多二级），如 `工作>开发工具`、`娱乐>游戏`
3. 默认情况下只输出一级分类。如果某个条目确实无法归入更细的子类，只输出主类，如 `教育与学习`。
4. 只有在用户明确要求细分或条目明显需要细分时，才输出二级分类路径，如 `教育与学习>考试`。
5. 优先匹配【当前分类体系】中已有的路径
6. 如需新建子类，确保主类已存在于体系中；如需新建主类，直接输出主类名
7. 分类名中禁止包含 `/`、`·` 两个符号
8. 并列概念用"与"连接，如 `金融与支付`、`工具与系统`
9. 层级分隔符 `>` 最多出现一次，禁止输出三级及以上路径（如 `A>B>C` 是非法的）
10. 不要在任何值中包含英文双引号"，如需引用请用中文引号「」
11. 【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。ID之间只用逗号分隔，如 `[101,102,103,104]`
12. 【覆盖检查】输出JSON中所有类别的ID总数必须等于输入条目总数，不允许遗漏任何一个ID。如果某个ID确实难以归类，也必须分配到一个最接近的类别中，绝不能跳过。

【输出示例】
{"工作>开发工具":[101,102],"娱乐>游戏":[103,104,105]}"""

        prompt = f"""你正在执行用户的分类指令。请仔细阅读所有网址信息，严格按照用户指令进行分类。

【重要】输入共 {len(urls)} 个网址，你必须为每一个网址分配分类。输出JSON必须包含全部 {len(urls)} 个ID，不允许遗漏任何一个。遗漏会导致数据丢失！

用户指令：{user_query} {scope_hint}

【当前分类体系】
{category_tree_text}

网址信息（共 {len(urls)} 条）：
{items_str}

{rules_text}

输出："""

        from ai.ollama_client import OllamaClient
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        state = ai_manager.get_state()
        ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=300)
        raw = ollama.generate(prompt, temperature=0.3)

        extracted = OllamaClient._extract_json_object_robust(raw) or raw
        fixed = OllamaClient._fix_json(extracted)
        try:
            data = json.loads(fixed)
        except Exception as e:
            logger.warning("JSON parse failed: %s, raw preview: %r", e, raw[:300])
            return ToolResult(success=False, message=f"分类结果解析失败: {e}")

        # 统一ID类型为int，并去重
        def _normalize_data(raw_data):
            """将分类结果中的ID统一转为int并去重，同时处理模型返回的字符串数组"""
            result = {}
            for cat_name, id_list in raw_data.items():
                # 处理模型返回字符串形式如 "[1,2,3]" 的情况
                if isinstance(id_list, str):
                    s = id_list.strip()
                    if s.startswith('[') and s.endswith(']'):
                        try:
                            id_list = json.loads(s)
                        except Exception:
                            continue
                    else:
                        continue
                if not isinstance(id_list, list):
                    continue
                cleaned_name = sanitize_ai_category(cat_name)
                int_ids = []
                seen = set()
                for tid in id_list:
                    try:
                        int_tid = int(tid)
                        if int_tid not in seen:
                            seen.add(int_tid)
                            int_ids.append(int_tid)
                    except (ValueError, TypeError):
                        continue
                if int_ids:
                    result.setdefault(cleaned_name, []).extend(int_ids)
            return result

        data = _normalize_data(data)

        # 兜底：force_subclass 模式下，强制修正一级分类和错误的主类
        if force_subclass:
            main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
            corrected_data = {}
            for cat_name, id_list in data.items():
                cleaned = sanitize_ai_category(cat_name)
                if '>' not in cleaned:
                    logger.debug("AUTO-CORRECT: '%s' -> '%s>其他' (force_subclass)", cleaned, main_category)
                    cleaned = f"{main_category}>其他"
                else:
                    actual_main = cleaned.split('>')[0].strip()
                    if actual_main != main_category:
                        sub = cleaned.split('>', 1)[1].strip()
                        logger.debug("AUTO-CORRECT: main '%s' -> '%s', sub '%s' (force_subclass)", actual_main, main_category, sub)
                        cleaned = f"{main_category}>{sub}"
                corrected_data.setdefault(cleaned, []).extend(id_list)
            data = corrected_data

        # 自纠正循环：处理遗漏的ID
        input_ids = {getattr(u, 'id', None) for u in urls}
        input_ids.discard(None)
        for retry in range(2):
            classified_ids = set()
            for id_list in data.values():
                if isinstance(id_list, list):
                    classified_ids.update(id_list)
            missing_ids = input_ids - classified_ids
            if not missing_ids:
                break

            missing_urls = [u for u in urls if getattr(u, 'id', None) in missing_ids]
            missing_lines = []
            for u in missing_urls:
                title = getattr(u, 'title', '')[:30]
                cat = getattr(u, 'category', '') or '未分类'
                remark = (getattr(u, 'remark', '') or '')[:20]
                ai_remark = (getattr(u, 'ai_remark', '') or '')[:20]
                parts = [f"ID={getattr(u, 'id', 0)}", f"标题={title}", f"分类={cat}"]
                if remark:
                    parts.append(f"备注={remark}")
                if ai_remark:
                    parts.append(f"AI备注={ai_remark}")
                missing_lines.append(", ".join(parts))
            missing_items_str = '\n'.join(missing_lines)

            established_cats = list(dict.fromkeys(sanitize_ai_category(c) for c in data.keys()))
            retry_prompt = f"""你正在执行分类补充任务。以下是第一轮分类时遗漏的网址，请为它们分配最合适的分类。

【重要】这些是第一轮遗漏的 {len(missing_urls)} 个网址，必须全部分类，不允许再遗漏！

已建立的分类体系（请优先从中选择）：
{', '.join(established_cats)}

网址信息（共 {len(missing_urls)} 条）：
{missing_items_str}

输出格式必须是严格JSON：{{"类别名": [ID列表], ...}}
【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。
【覆盖检查】输出必须包含全部 {len(missing_urls)} 个ID。

输出："""

            raw_retry = ollama.generate(retry_prompt, temperature=0.3)
            extracted_retry = OllamaClient._extract_json_object_robust(raw_retry) or raw_retry
            fixed_retry = OllamaClient._fix_json(extracted_retry)
            try:
                retry_data = json.loads(fixed_retry)
                retry_data = _normalize_data(retry_data)
                # force_subclass 模式下对retry结果同样强制修正主类
                if force_subclass:
                    main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
                    corrected_retry = {}
                    for cat_name, id_list in retry_data.items():
                        cleaned = sanitize_ai_category(cat_name)
                        if '>' not in cleaned:
                            logger.debug("AUTO-CORRECT retry: '%s' -> '%s>其他' (force_subclass)", cleaned, main_category)
                            cleaned = f"{main_category}>其他"
                        else:
                            actual_main = cleaned.split('>')[0].strip()
                            if actual_main != main_category:
                                sub = cleaned.split('>', 1)[1].strip()
                                logger.debug("AUTO-CORRECT retry: main '%s' -> '%s', sub '%s' (force_subclass)", actual_main, main_category, sub)
                                cleaned = f"{main_category}>{sub}"
                        corrected_retry.setdefault(cleaned, []).extend(id_list)
                    retry_data = corrected_retry
                for cat_name, id_list in retry_data.items():
                    data.setdefault(sanitize_ai_category(cat_name), []).extend(id_list)
                # 重新计算仍然遗漏的数量
                classified_ids = set()
                for id_list in data.values():
                    if isinstance(id_list, list):
                        classified_ids.update(id_list)
                still_missing = input_ids - classified_ids
                logger.info("SmartClassifyUrls Retry %d: %d missing -> %d still missing", retry+1, len(missing_ids), len(still_missing))
            except Exception as e:
                logger.warning("SmartClassifyUrls Retry %d failed: %s", retry+1, e)
                break

        item_map = {getattr(u, 'id', 0): u for u in urls if hasattr(u, 'id')}
        preview_items = []
        
        # 第一轮：收集每个ID被分配到的所有分类
        id_to_cats = {}
        cat_order = []
        for cat_name, id_list in data.items():
            if not isinstance(id_list, list):
                continue
            cat_name = sanitize_ai_category(cat_name)
            if cat_name not in cat_order:
                cat_order.append(cat_name)
            for tid in id_list:
                id_to_cats.setdefault(tid, []).append(cat_name)
        
        # 第二轮：处理重复，保留路径最长的分类（长度相同保留首次出现的）
        resolved = {}
        cat_rank = {c: i for i, c in enumerate(cat_order)}
        for tid, cats in id_to_cats.items():
            if len(cats) > 1:
                best_cat = max(cats, key=lambda c: (len(c), cat_rank.get(c, float('inf'))))
                logger.debug("RESOLVE duplicate id=%s: keep '%s', drop %s", tid, best_cat, cats)
            else:
                best_cat = cats[0]
            resolved[tid] = best_cat
        
        # 收集实际使用的分类（保持顺序）
        categories = list(dict.fromkeys(resolved.values()))
        
        # 第三轮：生成预览
        seen_ids = set()
        for tid, best_cat in resolved.items():
            item = item_map.get(tid)
            if item:
                seen_ids.add(tid)
                preview_items.append(self._make_preview_item(
                    row_id=str(tid),
                    display_name=getattr(item, 'title', ''),
                    secondary_name="",
                    fields=[{"field_name": "category", "old_value": getattr(item, 'category', '') or '未分类', "new_value": best_cat}],
                    raw_data={"target_id": tid, "field": "category", "new_value": best_cat}
                ))

        # 遗漏检测：找出模型未返回的ID
        input_ids = {getattr(u, 'id', 0) for u in urls if hasattr(u, 'id')}
        missing_ids = input_ids - seen_ids
        if missing_ids:
            fallback_cat = f"{main_category}>未分类" if force_subclass else '其他'
            logger.warning("SmartClassifyUrls MISSING %d IDs: %s%s", len(missing_ids), sorted(missing_ids)[:20], '...' if len(missing_ids) > 20 else '')
            for tid in missing_ids:
                item = item_map.get(tid)
                if item:
                    old_cat = getattr(item, 'category', '') or '未分类'
                    preview_items.append(self._make_preview_item(
                        row_id=str(tid),
                        display_name=getattr(item, 'title', ''),
                        secondary_name="",
                        fields=[{"field_name": "category", "old_value": old_cat, "new_value": fallback_cat}],
                        raw_data={"target_id": tid, "field": "category", "new_value": fallback_cat}
                    ))
                    seen_ids.add(tid)

        preview = self._make_preview("classify", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items), "categories": categories},
            message=f"待智能分类 {len(preview_items)} 个网址，请确认"
        )
