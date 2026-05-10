"""
Ollama 语义搜索模块
包含语义搜索和本地降级匹配功能
"""
import logging
import re
from typing import List, Tuple, Dict

from ai.client_base import OllamaClient

logger = logging.getLogger(__name__)


class SemanticClient(OllamaClient):
    """语义搜索客户端，继承基础 OllamaClient"""

    def semantic_search(self, query: str, app_list: List[str], accounts_info: List[dict] = None) -> List[Tuple[str, float]]:
        """
        语义搜索：理解用户自然语言查询，从应用列表中找出最相关的应用

        Args:
            query: 用户搜索词（如"我的游戏账号"、"支付类账号"）
            app_list: 应用名称列表
            accounts_info: 每个账号的额外信息，包含 category/tags/remark/ai_remark

        Returns:
            [(应用名, 置信度), ...]
        """
        if not app_list:
            return []

        # 构建提示中的账号信息（精简：备注截断到20字，减少prompt长度）
        if accounts_info and len(accounts_info) == len(app_list):
            info_lines = []
            for info in accounts_info:
                parts = [f"应用名: {info.get('app_name', '')}", f"类别: {info.get('category', '')}"]
                tags = info.get('tags', '')
                if tags:
                    parts.append(f"标签: {tags}")
                remark = info.get('remark', '')
                if remark:
                    parts.append(f"备注: {remark[:20]}")
                ai_remark = info.get('ai_remark', '')
                if ai_remark:
                    parts.append(f"AI备注: {ai_remark[:20]}")
                info_lines.append(" | ".join(parts))
            app_list_str = '\n'.join([f"- {line}" for line in info_lines])
        else:
            app_list_str = '\n'.join([f"- {name}" for name in app_list])

        prompt = f"""你是密码管理软件的搜索助手。用户正在搜索账号，他说："{query}"

软件中存储的账号列表如下（每行为一个账号的完整信息）：
{app_list_str}

请从列表中找出用户可能想找的应用。要求：
1. 不仅看字面匹配，还要理解语义（如"支付类"对应支付宝、银行、云闪付等）
2. 综合考虑应用名、类别、标签、备注来判断相关性
3. 选出所有相关的匹配项，不要遗漏
4. 每行严格格式：应用名 | 置信度（0-1之间的小数）
5. 必须直接使用列表中原始应用名，不要修改或缩写
6. 如果没有匹配的，只返回一行：无 | 0.0

匹配结果："""

        # 调试日志
        logger.info("SemanticSearch Prompt length: %d chars, accounts: %d", len(prompt), len(app_list))

        try:
            result = self.generate(prompt, temperature=0.2)
            logger.info("SemanticSearch Raw response (%d chars):\n%s", len(result), result[:500])

            # 如果结果只有"无"相关行（没有其他匹配项），返回空列表
            lines = [l.strip() for l in result.strip().split('\n') if l.strip()]
            non_empty_lines = [l for l in lines if l.lower() not in ('无', 'none', '')]
            if not non_empty_lines:
                logger.debug("No non-empty lines found")
                return []

            # 解析返回的应用名列表
            matched_apps = []
            for line in result.strip().split('\n'):
                line = line.strip()
                if not line or line.lower() in ('无', 'none', ''):
                    continue

                # 去除可能的序号前缀（如 "1. "、"- "、"* "）
                line = re.sub(r'^[\d]+[\.\)\-\*\s]+', '', line).strip()
                if not line:
                    continue

                # 尝试解析 "应用名 | 置信度" 格式
                parts = line.split('|')
                app_name = parts[0].strip()
                confidence = 0.8  # 默认置信度

                if len(parts) >= 2:
                    try:
                        confidence = float(parts[1].strip())
                        confidence = max(0.0, min(1.0, confidence))
                    except ValueError:
                        pass

                # 确保应用名在原始列表中（精确或模糊匹配）
                if app_name in app_list:
                    matched_apps.append((app_name, confidence))
                    logger.debug("Matched exact: %s (%s)", app_name, confidence)
                else:
                    # 尝试子串匹配：收集所有匹配后按置信度排序取最佳
                    fuzzy_matches = []
                    for orig in app_list:
                        if app_name in orig or orig in app_name:
                            fuzzy_matches.append((orig, confidence))
                    if fuzzy_matches:
                        fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
                        best = fuzzy_matches[0]
                        matched_apps.append(best)
                        logger.debug("Matched fuzzy: %s via '%s' (%s)", best[0], app_name, best[1])

            logger.info("Total matched: %d", len(matched_apps))
            return matched_apps

        except Exception as e:
            logger.error("语义搜索失败: %s", e)
            return []

    def semantic_match(self, query: str, items_summary: str) -> dict:
        """
        语义匹配：调用本地 AI 模型进行真正的语义理解匹配。

        将查询词和条目摘要一起发送给模型，由模型基于语义理解判断相关性。
        如果模型调用失败，自动降级到本地关键词匹配。

        Args:
            query: 用户搜索词
            items_summary: 格式化的条目摘要（每行：ID | 应用名 | 分类 | 标签 | 备注）

        Returns:
            {
                "matched_ids": [匹配的ID列表],
                "reasoning": "推理过程（中文）",
                "confidence_scores": {"ID": 置信度(0-1)}
            }
        """
        import json as _json

        if not query or not items_summary:
            return {"matched_ids": [], "reasoning": "空查询或空数据", "confidence_scores": {}}

        prompt = f"""你是语义匹配专家。请根据用户的查询意图，从下面的条目列表中找出所有语义相关的条目。

用户查询："{query}"

条目列表（每行格式：ID | 应用名/标题 | 分类 | 标签 | 备注）：
{items_summary}

重要规则：
1. 必须理解语义，不要只做字面匹配。例如：
   - 查询"青岛大学"应该匹配"青大学工"、"青岛大学财务处"等
   - 查询"支付类"应该匹配"支付宝"、"微信"、"银行"等
   - 查询"学习"应该匹配"学习通"、"慕课"、"知网"等
2. 综合考虑应用名、分类、标签、备注来判断相关性
3. 选出所有相关的匹配项，不要遗漏
4. 如果没有匹配的，返回空数组

请严格输出JSON格式（不要添加任何其他文字、解释、markdown代码块）：
{{"matched_ids": [相关的ID列表，如 [1, 5, 10]], "reasoning": "匹配理由", "confidence_scores": {{"1": 0.95, "5": 0.88}}}}

输出："""

        try:
            raw = self.generate(prompt, temperature=0.2)
            text = raw.strip()
            logger.info("SemanticMatch Raw response (%d chars):\n%s", len(text), text[:300])

            # 去除 markdown 代码块
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()

            # 尝试直接解析
            result = None
            try:
                result = _json.loads(text)
            except _json.JSONDecodeError:
                pass

            # 尝试 _fix_json 修复后解析
            if result is None:
                try:
                    fixed = self._fix_json(text)
                    result = _json.loads(fixed)
                    logger.debug("Used _fix_json, len=%d", len(fixed))
                except _json.JSONDecodeError:
                    pass

            # 尝试 _extract_json_object_robust 提取后解析
            if result is None:
                extracted = self._extract_json_object_robust(text)
                if extracted:
                    try:
                        result = _json.loads(extracted)
                        logger.debug("Used robust extraction, len=%d", len(extracted))
                    except _json.JSONDecodeError:
                        pass

                    # 提取后 _fix_json 再解析
                    if result is None:
                        try:
                            fixed_extracted = self._fix_json(extracted)
                            result = _json.loads(fixed_extracted)
                            logger.debug("Used robust+fix_json, len=%d", len(fixed_extracted))
                        except _json.JSONDecodeError:
                            pass

            if result is None:
                raise _json.JSONDecodeError("All JSON parsing attempts failed", text, 0)

            matched_ids = result.get("matched_ids", [])
            confidence_scores = result.get("confidence_scores", {})
            reasoning = result.get("reasoning", "")

            # 确保 matched_ids 都是整数
            clean_ids = []
            for mid in matched_ids:
                try:
                    clean_ids.append(int(mid))
                except (ValueError, TypeError):
                    pass

            # 清理 confidence_scores 的 key
            clean_scores = {}
            for k, v in confidence_scores.items():
                try:
                    clean_scores[str(int(k))] = float(v)
                except (ValueError, TypeError):
                    pass

            line_count = len([l for l in items_summary.strip().split(chr(10)) if l.strip()])
            logger.info("Model match: query='%s', items=%d, matched=%d", query, line_count, len(clean_ids))

            return {
                "matched_ids": clean_ids,
                "reasoning": reasoning or f"模型语义匹配：查询'{query}'命中{len(clean_ids)}条",
                "confidence_scores": clean_scores
            }

        except Exception as e:
            logger.error("Model match failed: %s, fallback to local", e)
            return self._local_semantic_match(query, items_summary)

    def _local_semantic_match(self, query: str, items_summary: str) -> dict:
        """本地语义匹配（降级备用）：关键词匹配、拼音首字母匹配、同义词扩展等。"""
        import re
        from difflib import SequenceMatcher
        try:
            from core.pinyin import PinyinConverter
        except Exception:
            logger.debug("PinyinConverter 导入失败", exc_info=True)
            PinyinConverter = None

        if not query or not items_summary:
            return {"matched_ids": [], "reasoning": "空查询或空数据", "confidence_scores": {}}

        query = query.strip().lower()

        synonym_map = {
            "竞赛": ["比赛", "大赛", "赛事", "美赛", "大创", "创新创业", "挑战杯", "acm", "cpcc", "蓝桥杯"],
            "论文": ["知网", "arxiv", "ieee", "学术", "文献", "期刊", "会议", "投稿"],
            "支付": ["支付宝", "微信", "银行", "paypal", "stripe", "收银", "付款", "转账", "充值"],
            "社交": ["微信", "qq", "微博", "twitter", "x", "facebook", "instagram", "telegram", "钉钉", "飞书"],
            "游戏": ["steam", "epic", "xbox", "playstation", "nintendo", "原神", "王者", "lol", "联盟", "吃鸡"],
            "学习": ["学校", "大学", "mooc", "网课", "学堂", "课程", "教育", "考试", "cet", "四六级"],
            "工作": ["公司", "企业", "办公", "oa", "erp", "crm", "邮箱", "邮件", "招聘", "简历"],
            "购物": ["淘宝", "京东", "拼多多", "amazon", "购物", "电商", "外卖", "美团", "饿了么"],
            "视频": ["b站", "bilibili", "youtube", "抖音", "快手", "爱奇艺", "腾讯", "优酷", "netflix"],
            "开发": ["github", "gitlab", "gitee", "coding", "stackoverflow", "leetcode", "力扣", "vscode"],
        }

        search_terms = [query]
        for key, synonyms in synonym_map.items():
            if key in query or any(s in query for s in synonyms):
                search_terms.extend([key] + synonyms)
        search_terms = list(set(search_terms))

        items = []
        for line in items_summary.strip().split("\n"):
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|", 4)]
            if len(parts) < 2:
                continue
            try:
                item_id = int(parts[0])
            except (ValueError, TypeError):
                continue
            app_name = parts[1] if len(parts) > 1 else ""
            category = parts[2] if len(parts) > 2 else ""
            tags = parts[3] if len(parts) > 3 else ""
            remark = parts[4] if len(parts) > 4 else ""
            items.append({
                "id": item_id,
                "app_name": app_name,
                "category": category,
                "tags": tags,
                "remark": remark,
                "text": f"{app_name} {category} {tags} {remark}".lower()
            })

        matched_ids = []
        confidence_scores = {}
        matched_details = []

        for item in items:
            max_score = 0.0
            for term in search_terms:
                term = term.lower().strip()
                if not term:
                    continue
                score = 0.0
                text = item["text"]
                app = item["app_name"].lower()
                if term == app:
                    score = max(score, 1.0)
                elif term in app:
                    score = max(score, 0.95)
                elif term in text:
                    score = max(score, 0.85)
                if PinyinConverter and score < 0.85:
                    try:
                        app_pinyin = PinyinConverter.get_pinyin_initials(item["app_name"])
                        if term == app_pinyin.lower():
                            score = max(score, 0.9)
                        elif term in app_pinyin.lower():
                            score = max(score, 0.8)
                    except Exception:
                        logger.debug("拼音转换失败: %s", item["app_name"], exc_info=True)
                if score < 0.7 and len(term) >= 2 and len(app) >= 2:
                    try:
                        ratio = SequenceMatcher(None, term, app).ratio()
                        if ratio > 0.75:
                            score = max(score, ratio * 0.85)
                    except Exception:
                        logger.debug("序列相似度计算失败", exc_info=True)
                if score > max_score:
                    max_score = score

            if max_score >= 0.6:
                matched_ids.append(item["id"])
                confidence_scores[str(item["id"])] = round(max_score, 2)
                matched_details.append(f"{item['app_name']}({max_score:.0%})")

        matched_ids.sort(key=lambda x: confidence_scores.get(str(x), 0), reverse=True)

        reasoning = f"本地语义匹配：查询词 '{query}'，在 {len(items)} 条记录中命中 {len(matched_ids)} 条"
        if matched_details:
            reasoning += "；主要匹配：" + ", ".join(matched_details[:8])
            if len(matched_details) > 8:
                reasoning += f" 等共{len(matched_details)}项"

        logger.info("Local fallback: query='%s', items=%d, matched=%d", query, len(items), len(matched_ids))

        return {
            "matched_ids": matched_ids,
            "reasoning": reasoning,
            "confidence_scores": confidence_scores
        }
