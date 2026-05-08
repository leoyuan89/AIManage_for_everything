"""
Ollama API 客户端
用于调用本地 Gemma 4 E4B 模型
"""
import logging
import json
import re
import requests
from typing import List, Optional, Tuple, Generator, Dict

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama HTTP API 客户端"""
    
    def __init__(self, model: str = "gemma4:4b", host: str = "http://localhost:11434"):
        """
        初始化 Ollama 客户端
        
        Args:
            model: 模型名称
            host: Ollama 服务地址
        """
        self.model = model
        self.host = host.rstrip('/')
        self.api_url = f"{self.host}/api/generate"
    
    def is_available(self) -> bool:
        """检查 Ollama 服务是否可用"""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            logger.debug("Ollama 可用性检查失败", exc_info=True)
            return False
    
    @staticmethod
    def _extract_json_object_robust(text: str) -> Optional[str]:
        """使用括号深度计数，从文本中提取第一个完整的 JSON 对象"""
        # 先尝试找 ```json ... ``` 代码块，提取块内全部内容（避免非贪婪截断嵌套 JSON）
        code_block = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if code_block:
            block_content = code_block.group(1).strip()
            start = block_content.find('{')
            if start != -1:
                text_to_scan = block_content
            else:
                text_to_scan = text
                start = text_to_scan.find('{')
        else:
            text_to_scan = text
            start = text_to_scan.find('{')
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text_to_scan[start:], start):
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return text_to_scan[start:i+1]
        return None

    @staticmethod
    def _fix_json(text: str) -> str:
        """修复常见的模型输出 JSON 语法错误"""
        # 1. 去除首尾空白和常见非 JSON 前缀/后缀
        text = text.strip()
        # 去除可能的前缀，如 "输出："、"JSON:" 等
        text = re.sub(r'^(?:输出[:：]|JSON[:：]|Response[:：])\s*', '', text, flags=re.IGNORECASE)
        # 2. 中文引号 → 英文引号（注意保留 JSON 字符串内的中文内容）
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace("'", "'").replace("'", "'")
        # 3. 字符串内未转义的换行符/回车 → \\n
        # 使用状态机修复字符串内的原始换行
        result = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                result.append(ch)
                escape = False
                continue
            if ch == '\\':
                result.append(ch)
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch in '\n\r\t':
                if ch == '\n':
                    result.append('\\n')
                elif ch == '\r':
                    result.append('\\r')
                else:
                    result.append('\\t')
                continue
            result.append(ch)
        text = ''.join(result)
        # 4. 对象/数组末尾多余逗号（如 "a": 1,} → "a": 1}）
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        # 5. 缺少逗号：}{ 之间、}{ 前面有引号等情况（保守修复，只处理明显的）
        text = re.sub(r'"\s*\}\s*\{', r'"},{', text)
        # 6. 紧凑JSON常见：数组/对象结束后直接开始下一个键，缺少逗号
        text = re.sub(r'\](\s*)"', r'],\1"', text)
        text = re.sub(r'\}(\s*)"(?!\s*[\]\}])', r'},\1"', text)
        # 7. 去除 JSON 后可能粘着的解释文字（取最后一个 } 之前的内容）
        last_brace = text.rfind('}')
        if last_brace != -1 and last_brace < len(text) - 1:
            # 检查最后一个 } 后面是否是非空白字符
            tail = text[last_brace+1:].strip()
            if tail and not tail.startswith('}'):
                text = text[:last_brace+1]
        return text

    def generate(self, prompt: str, temperature: float = 0.1, num_predict: int = 16384) -> str:
        """
        调用 Ollama 生成文本
        
        Args:
            prompt: 提示词
            temperature: 温度参数（越低越确定）
            num_predict: 最大生成 token 数（默认 -1 表示不限，由模型自行决定何时停止）
            
        Returns:
            生成的文本
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
                "num_ctx": 32768  # 上下文窗口 32K
            }
        }
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=None  # 不设超时限制，由用户手动控制
            )
            response.raise_for_status()
            
            result = response.json()
            raw_response = result.get('response', '').strip()
            done_reason = result.get('done_reason', 'N/A')
            prompt_eval_count = result.get('prompt_eval_count', 'N/A')
            eval_count = result.get('eval_count', 'N/A')
            logger.debug("status=%s, prompt_len=%s, prompt_tokens=%s, gen_tokens=%s, response_len=%s, done_reason=%s, preview=%r",
                         response.status_code, len(prompt), prompt_eval_count, eval_count, len(raw_response), done_reason, raw_response[:200])
            if not raw_response:
                logger.debug("FULL result keys=%s", list(result.keys()))
            return raw_response
            
        except requests.exceptions.ConnectionError:
            raise Exception("无法连接到 Ollama 服务，请确保 Ollama 已启动")
        except requests.exceptions.Timeout:
            raise Exception("Ollama 响应超时，请检查模型是否已加载")
        except Exception as e:
            raise Exception(f"Ollama 调用失败: {str(e)}")
    
    def generate_stream(self, prompt: str, temperature: float = 0.1, num_predict: int = 16384) -> Generator[str, None, None]:
        """
        流式生成文本，逐 token 返回。
        如果流式调用失败，降级为非流式 generate() 并一次性 yield 全部结果。
        
        Args:
            prompt: 提示词
            temperature: 温度参数
            num_predict: 最大生成 token 数
            
        Yields:
            每个 token 字符串
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
                "num_ctx": 32768
            }
        }
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                stream=True,
                timeout=None
            )
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line.decode('utf-8'))
                    token = data.get('response', '')
                    if token:
                        yield token
                    if data.get('done', False):
                        break
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                    
        except Exception as stream_e:
            logger.warning("流式生成失败，降级为非流式: %s", stream_e)
            # 降级为非流式生成
            try:
                result = self.generate(prompt, temperature=temperature, num_predict=num_predict)
                yield result
            except Exception as fallback_e:
                raise Exception(f"流式生成失败且降级失败: {fallback_e}")
    
    def generate_with_think_result(self, prompt: str, temperature: float = 0.1, num_predict: int = 16384) -> dict:
        """
        生成文本，并要求模型按 <think> 和 <result> 标签输出结构化结果。
        
        Args:
            prompt: 提示词
            temperature: 温度参数
            num_predict: 最大生成 token 数
            
        Returns:
            {"think": "思考过程", "result": "最终结果"}
        """
        wrapped_prompt = f"""{prompt}

请按以下格式输出：

<think>
[你的思考过程]
</think>

<result>
[最终结果]
</result>
"""
        raw = self.generate(wrapped_prompt, temperature=temperature, num_predict=num_predict)
        think_match = re.search(r'<think\s*>\s*(.*?)\s*</think\s*>', raw, re.DOTALL)
        result_match = re.search(r'<result\s*>\s*(.*?)\s*</result\s*>', raw, re.DOTALL)
        
        think = think_match.group(1).strip() if think_match else ""
        result_text = result_match.group(1).strip() if result_match else raw.strip()
        
        return {"think": think, "result": result_text}
    
    def categorize(self, app_name: str, url: str = "", existing_categories: list = None, parent_hint: str = None, remark: str = "", ai_remark: str = "") -> str:
        """
        AI 智能分类
        
        Args:
            app_name: 应用名称/标题
            url: 网址（可选）
            existing_categories: 当前已有的分类列表（可选），AI 优先从中匹配
            parent_hint: 当前已选中的一级分类（可选）。传入时只要求返回二级子类
            remark: 用户手动备注（可选）
            ai_remark: AI 生成备注（可选）
            
        Returns:
            分类名称（parent_hint 为空时返回完整分类，否则只返回子类名）
        """
        cat_hint = ""
        if existing_categories:
            cat_list = "\n".join(f"- {c}" for c in existing_categories if c and c != '全部')
            cat_hint = f"""当前已有的分类：
{cat_list}

"""
        
        extra_info = ""
        if remark:
            extra_info += f"用户备注：{remark}\n"
        if ai_remark:
            extra_info += f"AI备注：{ai_remark}\n"
        
        if parent_hint:
            # 二级分类模式：只返回子类名
            prompt = f"""你是一款密码管理软件的智能分类助手。当前已选中的一级分类是「{parent_hint}」，请为该条目推荐一个最合适的二级子类。

{cat_hint}规则：
1. 该条目属于「{parent_hint}」分类体系，请只给出二级子类名称（不要带一级分类前缀）
2. 如果现有子类中有高度匹配的，优先使用已有子类名
3. 如果现有子类都不合适，可以自创一个更精准的子类名称
4. 子类名应简洁明确（2-5个字），如"前端框架"、"后端开发"、"机器学习"等
5. 只返回子类名称，不要解释、不要加引号、不要返回多余内容
6. 禁止包含 "/"、">"、"·" 等符号

应用名称/标题：{app_name}
网址：{url}
{extra_info}二级子类："""
        else:
            # 一级分类模式：返回完整分类名
            prompt = f"""你是一款密码管理软件的智能分类助手。请根据以下信息，分析该条目最合理的一级分类。

{cat_hint}规则：
1. 优先从「当前已有的分类」中找出最接近的一个直接使用
2. 如果现有分类都不合适，再自创一个更精准的新分类名称
3. 分类名称应简洁明确（2-6个字），如"开发工具"、"学术资源"、"生活服务"等
4. 只返回一级分类名称，不要解释、不要加引号、不要返回多余内容
5. 禁止包含 "/"、">"、"·" 等符号

应用名称/标题：{app_name}
网址：{url}
{extra_info}一级分类："""
        
        try:
            result = self.generate(prompt, temperature=0.2, num_predict=50)
            
            # 清洗结果
            result = result.strip().strip('"').strip("'")
            
            # 如果AI返回了分析内容+分类，尝试提取最后一行或第一个有意义的词
            lines = [l.strip() for l in result.split('\n') if l.strip()]
            if lines:
                result = lines[-1]
            
            # 过滤掉常见的前缀噪音
            for prefix in ['分类：', '分类:', '分类是', '属于', '结果为', '答案是', '一级分类：', '二级子类：', '子类：']:
                if result.startswith(prefix):
                    result = result[len(prefix):].strip()
            
            # 清理非法字符
            result = result.replace('/', '-').replace('·', '-')
            
            return result if result else '其他'
            
        except Exception as e:
            logger.error("AI 分类失败: %s", e)
            return '其他'
    
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
                    # 尝试子串匹配
                    for orig in app_list:
                        if app_name in orig or orig in app_name:
                            matched_apps.append((orig, confidence))
                            logger.debug("Matched fuzzy: %s via '%s' (%s)", orig, app_name, confidence)
                            break
            
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
    
    def chat(self, messages: List[dict], temperature: float = 0.3, num_predict: int = 16384) -> str:
        """
        对话模式：支持多轮上下文（通过 messages 拼接为 prompt）
        
        Args:
            messages: 消息列表，每项为 {"role": "user"|"assistant", "content": "..."}
            temperature: 温度参数
            num_predict: 最大生成 token 数
            
        Returns:
            模型回复文本
        """
        # 将 messages 拼接为单个 prompt（gemma4:4b 不支持原生 chat API，用 prompt 模拟）
        prompt_parts = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if role == 'user':
                prompt_parts.append(f"用户：{content}")
            else:
                prompt_parts.append(f"助手：{content}")
        
        prompt = '\n\n'.join(prompt_parts) + "\n\n助手："
        
        return self.generate(prompt, temperature=temperature, num_predict=num_predict)
    
    def generate_tool_call(self, query: str, category_tree: str,
                           observations: str, tools: List[Dict],
                           vault_type: str = 'accounts') -> Dict:
        """
        生成Tool Call决策。

        Returns:
            {"thought": str, "tool": str, "params": dict, "response": str}
        """
        tools_text = json.dumps(tools, ensure_ascii=False, indent=2)
        vault_label = '密码库（账号）' if vault_type == 'accounts' else '网址库'
        tool_suffix_hint = '以 "_accounts" 或 "_accounts" 结尾' if vault_type == 'accounts' else '以 "_urls" 结尾'

        prompt = f"""你是密码管理软件的AI助手。请根据用户请求、当前分类体系和可用工具，决定下一步操作。

当前分类体系（仅用于判断用户提到的分类是否存在）：
{category_tree}

{observations}

用户请求：{query}

可用工具列表：
{tools_text}

【极其重要 - 库类型强制匹配规则】
当前用户正在 **{vault_label}** 页面操作。用户的用词（如"账号"、"网址"、"密码"、"URL"等）可能不准确，**请以当前库类型为准选择工具，不要拒绝执行**：
- 当前是 **密码库** → 调用 _accounts 结尾的工具（如 smart_classify_accounts）
- 当前是 **网址库** → 调用 _urls 结尾的工具（如 smart_classify_urls）
即使用户说"细分账号"但当前在网址库，也直接调用 smart_classify_urls，不要提示用户切换页面！

【极其重要 - 决策规则】
1. 如果用户请求是**纯查询类**（查找、搜索、筛选、统计、询问信息），且不需要修改数据 → 使用 tool="direct_answer"
2. 如果用户请求涉及**任何数据修改**（新增、删除、修改分类、修改备注、添加标签、整理、重组、批量更新） → **必须调用对应工具**，绝对不能用 direct_answer
3. **特别重要**：如果用户要求"分类"、"细分"、"细分二级子类"、"整理分类"、"重组分类" → **必须调用与当前库类型匹配的 smart_classify 工具**（密码库用 smart_classify_accounts，网址库用 smart_classify_urls），绝对不能用 direct_answer。这是**分类操作**，不是纯查询！
4. 如果 observation 中已经包含搜索结果（如 matched_ids），你要**直接使用这些 ID** 构造写操作工具的参数，不要返回 direct_answer 说"我找不到 ID"
5. 你只能决定调用哪个工具，不能直接替用户执行修改

【多轮工具调用示例】
场景：用户说"查找青岛大学有关的网址，并将类别改为青岛大学"
- 第1轮：{{"thought": "先查找相关网址", "tool": "semantic_search_urls", "params": {{"query": "青岛大学"}}}}
- 第2轮（基于 observation 中的 matched_ids）：{{"thought": "已找到相关网址 IDs，现在批量修改分类", "tool": "batch_update_urls", "params": {{"target_ids": [101, 102, 103], "updates": {{"category": "青岛大学"}}}}}}

【单轮示例】
- 用户："查找和青岛大学有关的账号" → {{"thought": "用户要查询", "tool": "semantic_search_accounts", "params": {{"query": "青岛大学"}}}}
- 用户："将支付类账号改为金融" → {{"thought": "用户要求修改分类", "tool": "batch_update_accounts", "params": {{"items": [{{"target_id": 1, "field": "category", "new_value": "金融"}}]}}}}
- 用户："删除这些账号" → {{"thought": "用户要求删除", "tool": "batch_delete_accounts", "params": {{"target_ids": [1, 2, 3]}}}}
- 用户："给这些账号添加备注" → {{"thought": "每个账号需要不同的针对性备注", "tool": "batch_add_remark_accounts", "params": {{"changes": [{{"target_id": 1, "content": "学工系统报到账号"}}, {{"target_id": 2, "content": "财务处缴费系统"}}]}}}}
- 用户："给教育与学习细分二级子类" → {{"thought": "用户要求对教育与学习分类进行细分，生成二级子类", "tool": "smart_classify_accounts", "params": {{}}}}
- 用户："有哪些金融类账号？" → {{"thought": "用户只是询问", "tool": "direct_answer", "response": "..."}}

【添加账号示例 - 重点】
用户输入可能包含应用名、网址、用户名、密码、备注等信息，格式不固定（可能无标签、多行、连在一起）。你需要自行分析提取各字段：
- 应用名(app_name)：通常是第一个词或最显眼的名称，如"B站"、"专利"
- 网址(url)：以http://或https://开头的链接，如果没有协议头但有域名，补全为https://
- 用户名(username)：看起来像手机号、邮箱、学号、QQ号等的字符串
- 密码(password)：紧跟在"密码"、"pwd"、"pass"等词后面的内容，或单独一行看起来像密码的字符串
- 分类(category)：根据应用名/网址推测最合适的分类，如学术网站→"学术与研究", 银行→"金融与支付"
- 备注(remark)：用户额外说明的信息
- 标签(tags)：可留空数组[]

示例1：用户："专利 https://pss-system.cponline.cnipa.gov.cn/conventionalSearch，13959106910，密码qazPLM89！，添加一下" → {{"thought": "用户要求添加专利查询网站账号", "tool": "batch_add_accounts", "params": {{"items": [{{"app_name": "专利", "url": "https://pss-system.cponline.cnipa.gov.cn/conventionalSearch", "username": "13959106910", "password": "qazPLM89!", "category": "学术与研究", "remark": "", "tags": []}}]}}}}
示例2：用户："添加B站账号 abc@qq.com 密码123456" → {{"thought": "用户要求添加B站账号", "tool": "batch_add_accounts", "params": {{"items": [{{"app_name": "B站", "url": "https://www.bilibili.com", "username": "abc@qq.com", "password": "123456", "category": "娱乐>视频", "remark": "", "tags": []}}]}}}}
示例3：用户："帮我存一个学工系统 xgxt.qdu.edu.cn 学号2023001" → {{"thought": "用户要求添加学工系统账号", "tool": "batch_add_accounts", "params": {{"items": [{{"app_name": "学工系统", "url": "https://xgxt.qdu.edu.cn", "username": "2023001", "password": "", "category": "青岛大学", "remark": "", "tags": []}}]}}}}

【添加网址示例】
- 用户："添加网址 https://github.com 分类开发工具" → {{"thought": "用户要求添加网址", "tool": "batch_add_urls", "params": {{"items": [{{"title": "GitHub", "url": "https://github.com", "category": "专业与开发", "remark": "", "tags": []}}]}}}}

【修改密码示例】
- 用户："把支付宝密码改成abc123" → {{"thought": "用户要求修改支付宝密码", "tool": "batch_update_accounts", "params": {{"items": [{{"target_id": 1, "field": "password", "new_value": "abc123"}}]}}}}

【最近修改查询示例】
- 用户："最近修改了哪些账号？" → {{"thought": "用户查询最近变更记录", "tool": "get_recent_changes", "params": {{"vault_type": "account"}}}}

【分类解析规则】
你必须从用户请求中解析出所有涉及的目标分类，利用语义理解而不仅仅是字符串匹配：
- 用户说"细分编程学习与工具" → target_categories: ["编程学习与工具"]
- 用户说"整理算法类的" → target_categories: ["编程学习与工具"]（语义理解：算法类属于编程学习）
- 用户说"看看青岛大学和学术的" → target_categories: ["青岛大学", "学术考试与学习资料"]
- 用户说"整理编程学习与工具>算法理论" → target_categories: ["编程学习与工具>算法理论"]（支持二级分类）
- 用户没有提到具体分类 → target_categories: []

【输出格式 - 严格JSON】
你必须只输出一个JSON对象，不要添加任何其他文字、解释、markdown代码块：
{{"thought": "你的思考过程", "tool": "工具名称或直接_answer", "params": {{参数}}, "target_categories": ["用户提到的目标分类1", "目标分类2"], "response": "给用户的回复（仅direct_answer时需要）"}}

输出："""
        
        raw = ""
        try:
            raw = self.generate(prompt, temperature=0.2)
            text = raw.strip()
            
            # 去除 markdown 代码块
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            
            # 尝试1：直接解析
            try:
                result = json.loads(text)
                logger.debug("L1 success")
                return {
                    "thought": result.get("thought", ""),
                    "tool": result.get("tool", "direct_answer"),
                    "params": result.get("params", {}),
                    "target_categories": result.get("target_categories", []),
                    "response": result.get("response", "")
                }
            except json.JSONDecodeError as e1:
                logger.debug("L1 fail: %s | text_preview=%r", e1, text[:100])
            
            # 尝试2：_fix_json 修复常见错误后解析
            fixed = self._fix_json(text)
            try:
                result = json.loads(fixed)
                logger.debug("L2 success")
                return {
                    "thought": result.get("thought", ""),
                    "tool": result.get("tool", "direct_answer"),
                    "params": result.get("params", {}),
                    "target_categories": result.get("target_categories", []),
                    "response": result.get("response", "")
                }
            except json.JSONDecodeError as e2:
                logger.debug("L2 fail: %s | fixed_preview=%r", e2, fixed[:100])
            
            # 尝试3：_extract_json_object_robust 提取后再解析
            extracted = self._extract_json_object_robust(raw)
            if extracted:
                try:
                    result = json.loads(extracted)
                    logger.debug("L3 success")
                    return {
                        "thought": result.get("thought", ""),
                        "tool": result.get("tool", "direct_answer"),
                        "params": result.get("params", {}),
                        "target_categories": result.get("target_categories", []),
                        "response": result.get("response", "")
                    }
                except json.JSONDecodeError as e3:
                    logger.debug("L3 fail: %s | extracted_preview=%r", e3, extracted[:100])
                # 尝试4：提取后 _fix_json 再解析
                fixed_extracted = self._fix_json(extracted)
                try:
                    result = json.loads(fixed_extracted)
                    logger.debug("L4 success")
                    return {
                        "thought": result.get("thought", ""),
                        "tool": result.get("tool", "direct_answer"),
                        "params": result.get("params", {}),
                        "target_categories": result.get("target_categories", []),
                        "response": result.get("response", "")
                    }
                except json.JSONDecodeError as e4:
                    logger.debug("L4 fail: %s | fixed_extracted_preview=%r", e4, fixed_extracted[:100])
            else:
                logger.debug("L3 skipped: _extract_json_object_robust returned None")
            
            logger.warning("ALL FAILED, raw_preview=%r", raw[:200])
            
            # 最后一道防线：文本中显式 tool 提取
            # 即使 JSON 结构坏了，只要文本里有 "tool": "xxx" 且不是 direct_answer，就提取出来
            tool_match = re.search(r'"tool"\s*[:：]\s*"([^"]+)"', raw)
            if tool_match:
                extracted_tool = tool_match.group(1).strip()
                if extracted_tool and extracted_tool != "direct_answer":
                    # 尝试提取 params
                    params_match = re.search(r'"params"\s*[:：]\s*(\{[\s\S]*?\})', raw)
                    extracted_params = {}
                    if params_match:
                        try:
                            extracted_params = json.loads(params_match.group(1))
                        except Exception:
                            logger.debug("params JSON 解析失败", exc_info=True)
                            # params 也坏了，但至少 tool 名是对的，params 可以空着让 validate_params 报错
                    thought_match = re.search(r'"thought"\s*[:：]\s*"([^"]*)"', raw)
                    extracted_thought = thought_match.group(1) if thought_match else ""
                    response_match = re.search(r'"response"\s*[:：]\s*"([^"]*)"', raw)
                    extracted_response = response_match.group(1) if response_match else ""
                    logger.debug("L5 text-extract success: tool=%s", extracted_tool)
                    return {
                        "thought": extracted_thought,
                        "tool": extracted_tool,
                        "params": extracted_params,
                        "target_categories": [],
                        "response": extracted_response
                    }
            
            # 兜底：使用 _extract_command 的容错逻辑
            fallback = self._extract_command(raw)
            return {
                "thought": fallback.get("thinking", f"JSON解析失败，使用兜底逻辑"),
                "tool": "direct_answer",
                "params": {},
                "response": fallback.get("response", "AI处理中遇到问题，请重试")
            }
            
        except Exception as e:
            logger.exception("JSONParse EXCEPTION")
            # 兜底：使用 _extract_command 的容错逻辑
            fallback = self._extract_command(raw)
            return {
                "thought": fallback.get("thinking", f"JSON解析失败，使用兜底逻辑: {e}"),
                "tool": "direct_answer",
                "params": {},
                "response": fallback.get("response", "AI处理中遇到问题，请重试")
            }
    
    def parse_command(self, query: str, db_summary: str, history: list = None,
                       conversation_history: str = "", scope_hint: str = "") -> dict:
        """
        解析用户指令，返回结构化动作（支持多轮对话上下文）
        
        Args:
            query: 用户输入
            db_summary: 数据库摘要
            history: 对话历史列表（旧格式，保留兼容），每项为 {"role": "user|assistant", "content": "..."}
            conversation_history: 对话历史摘要字符串（Phase 2 新格式，优先使用）
            scope_hint: 指代消解后的增强查询前缀
            
        Returns:
            结构化命令字典
        """
        # 构建历史上下文（优先使用新格式的 conversation_history）
        history_str = ""
        if conversation_history:
            # 自适应压缩已在 ConversationContext 中处理
            history_str = f"\n\n[对话历史]\n{conversation_history}\n"
        elif history:
            history_lines = []
            for msg in history[-6:]:  # 只取最近 6 轮，避免 prompt 过长
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                if role == 'user':
                    history_lines.append(f"用户：{content}")
                else:
                    history_lines.append(f"助手：{content}")
            if history_lines:
                history_str = "\n\n之前的对话：\n" + "\n".join(history_lines) + "\n"
        
        # 指代消解增强查询
        user_input_section = query
        if scope_hint:
            user_input_section = f"{scope_hint}\n\n用户当前说：\"{query}\""
        
        prompt = f"""你是密码管理软件的AI助手。请根据用户的指令和当前数据库信息，分析用户需求并返回结构化结果。

当前数据库中的账号信息如下：
{db_summary}
{history_str}
{user_input_section}

重要规则：
1. 记住之前的对话上下文。如果用户说"确认"、"好的"、"执行吧"等，通常是对你之前建议的确认，请返回对应的 action 和 params。
2. 你只是一个建议助手，**没有执行任何操作的权限**，也**不存在"系统后台"或"已提交"**的说法。
3. 当用户要求添加备注或整理分类时，你必须在<回复>中**逐条列出具体的建议内容**。
4. 你的回复必须包含可操作的具体信息，不要含糊其辞。
5. **严格区分 search 和 list**：用户说"找出...相关的"、"查找..."、"搜索..."、"有哪些..."时，action 必须是 search；只有用户明确说"列出全部"、"显示所有"时，才用 list。
6. **matched_ids**: 如果你识别出了与用户查询相关的账号，请在 matched_ids 中列出它们的 ID。这用于在软件左侧高亮显示相关账号。

请按以下格式返回分析结果（严格遵循格式，不要添加额外说明）：

<思考>
[你的分析过程，用中文，说明用户想要什么，数据库中有哪些相关信息]
</思考>

<动作>
action: [search|filter|list|reorganize|add_remark|delete|add|explain]
params: [JSON格式参数]
matched_ids: [相关的账号ID列表，如 [174, 175, 211]]
</动作>

<回复>
[给用户的自然语言回复，友好简洁。如果涉及建议，必须逐条列出具体内容。]
</回复>

说明：
- search: 用户要求"找出...相关的"、"查找..."、"搜索..."时使用。params={{"keywords": ["关键词1", "关键词2"]}}。关键词应提取用户query中的核心概念词（如"学习"、"支付"），不要包含"所有"、"相关"等泛词。
- filter: 按分类/标签筛选，params={{"category": "金融"}} 或 {{"tag": "支付"}}
- list: 仅当用户明确要求"列出全部"、"显示所有账号"时使用。params={{"scope": "all|uncategorized"}}
- reorganize: 建议重新整理分类，params={{"changes": [{{"target_id": 1, "field": "category", "new_value": "金融", "reason": "..."}}]}}
- add_remark: 建议添加AI备注，params={{"changes": [{{"target_id": 1, "field": "ai_remark", "new_value": "备注内容"}}]}}
- delete: 删除条目，params={{"target_ids": [1, 2, 3], "query_description": "删掉所有分类为未整理的网址", "item_type": "account|url"}}
- add: 新增条目，params={{"item_type": "account|url", "fields": {{"app_name": "B站", "username": "abc@qq.com", "password": "123456", "url": "https://www.bilibili.com", "category": "视频", "remark": "", "tags": []}}}}
- explain: 仅解释回答，不操作数据，params={{}}
- matched_ids: 数组，包含你识别出的相关账号的整数ID。如果用户搜索"支付类"，这里应该填 [174, 175, 211, ...] 等支付相关账号的ID。没有匹配的填 []。

输出："""
        
        try:
            result = self.generate(prompt, temperature=0.2)
            return self._extract_command(result)
        except Exception as e:
            return {
                "thinking": f"调用模型失败: {str(e)}",
                "action": "explain",
                "params": {},
                "response": f"AI助手暂时无法响应，请检查 Ollama 是否运行。错误：{str(e)}"
            }
    
    def _extract_json_after_marker(self, text: str, marker: str) -> Optional[str]:
        """使用括号深度计数，从 marker 后提取完整的 JSON 对象或数组"""
        idx = text.find(marker)
        if idx == -1:
            return None
        idx += len(marker)
        # 跳过空白
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            return None
        
        start_char = text[idx]
        if start_char not in ('{', '['):
            return None
        
        # 目标闭合字符
        end_char = '}' if start_char == '{' else ']'
        depth = 1
        in_string = False
        escape = False
        i = idx + 1
        
        while i < len(text):
            ch = text[i]
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = not in_string
            elif not in_string:
                if ch == start_char:
                    depth += 1
                elif ch == end_char:
                    depth -= 1
                    if depth == 0:
                        return text[idx:i+1]
            i += 1
        return None
    
    def _extract_command(self, raw_text: str) -> dict:
        """从模型输出中提取结构化命令（增强版，更健壮）"""
        default = {
            "thinking": "",
            "action": "explain",
            "params": {},
            "response": raw_text,
            "query_summary": ""
        }
        
        try:
            # 提取 <思考> 块（支持变体如 <思考 > 或多余空格）
            thinking_match = re.search(r'<思考\s*>\s*(.*?)\s*</思考\s*>', raw_text, re.DOTALL)
            thinking = thinking_match.group(1).strip() if thinking_match else ""
            
            # 提取 <动作> 块
            action_match = re.search(r'<动作\s*>\s*(.*?)\s*</动作\s*>', raw_text, re.DOTALL)
            action_text = action_match.group(1).strip() if action_match else ""
            
            # 提取 <回复> 块（如果模型没有正确关闭标签，尝试提取到末尾）
            response_match = re.search(r'<回复\s*>\s*(.*?)\s*</回复\s*>', raw_text, re.DOTALL)
            if response_match:
                response = response_match.group(1).strip()
            else:
                # 备用：尝试提取 <回复> 之后到文本末尾的内容
                response_fallback = re.search(r'<回复\s*>\s*(.*)', raw_text, re.DOTALL)
                if response_fallback:
                    response = response_fallback.group(1).strip()
                else:
                    # 再备用：如果回复标签完全缺失，尝试用 <思考> 之后的内容作为回复
                    if thinking_match:
                        after_thinking = raw_text[thinking_match.end():]
                        # 移除 <动作> 块
                        after_thinking = re.sub(r'<动作\s*>.*?</动作\s*>', '', after_thinking, flags=re.DOTALL)
                        response = after_thinking.strip()
                    else:
                        response = raw_text
            
            # 提取 query_summary（在清理前提取）
            query_summary_match = re.search(r'<query_summary\s*>\s*(.*?)\s*</query_summary\s*>', raw_text, re.DOTALL)
            query_summary = query_summary_match.group(1).strip() if query_summary_match else ""
            
            # 清理 response 中可能残留的标签
            response = re.sub(r'<思考\s*>.*?</思考\s*>', '', response, flags=re.DOTALL)
            response = re.sub(r'<动作\s*>.*?</动作\s*>', '', response, flags=re.DOTALL)
            response = re.sub(r'<query_summary\s*>.*?</query_summary\s*>', '', response, flags=re.DOTALL)
            response = response.strip()
            
            # 解析 action 和 params
            action = "explain"
            params = {}
            matched_ids = []
            
            action_line = re.search(r'action:\s*(\w+)', action_text, re.IGNORECASE)
            if action_line:
                action = action_line.group(1).lower()
            
            # 使用括号深度计数提取完整的 params JSON 对象（替代正则，支持嵌套）
            params_json = self._extract_json_after_marker(action_text, 'params:')
            if params_json:
                try:
                    params = json.loads(params_json)
                except json.JSONDecodeError:
                    pass
            
            # 解析 matched_ids（同样使用深度计数，更稳健）
            matched_ids_json = self._extract_json_after_marker(action_text, 'matched_ids:')
            if matched_ids_json:
                try:
                    matched_ids = json.loads(matched_ids_json)
                    # 确保都是整数
                    matched_ids = [int(m) for m in matched_ids if isinstance(m, (int, float, str))]
                except (json.JSONDecodeError, ValueError):
                    matched_ids = []
            
            return {
                "thinking": thinking,
                "action": action,
                "params": params,
                "matched_ids": matched_ids,
                "response": response,
                "query_summary": query_summary
            }
        except Exception:
            logger.debug("_extract_command 解析失败", exc_info=True)
            return default
