"""
Ollama 工具调用与命令解析模块
包含 Tool Call 生成和指令解析功能
"""
import logging
import json
import re
from typing import Optional, List, Dict

from ai.client_base import OllamaClient

logger = logging.getLogger(__name__)


class ToolClient(OllamaClient):
    """工具调用与命令解析客户端，继承基础 OllamaClient"""

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
- 用户："给这些账号添加备注：账号1是学生账号，账号2是工作账号" → {{"thought": "用户要求添加指定内容的备注", "tool": "batch_add_remark_accounts", "params": {{"changes": [{{"target_id": 1, "content": "学生账号"}}, {{"target_id": 2, "content": "工作账号"}}], "remark_type": "remark"}}}}
- 用户："给这些账号添加ai备注" → {{"thought": "用户要求AI自动生成备注", "tool": "batch_add_remark_accounts", "params": {{"changes": [{{"target_id": 1, "content": ""}}, {{"target_id": 2, "content": ""}}], "remark_type": "ai_remark"}}}}
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
- search: 用户要求"找出...相关的"、"查找..."、"搜索..."时使用。params={{{"keywords": ["关键词1", "关键词2"]}}}。关键词应提取用户query中的核心概念词（如"学习"、"支付"），不要包含"所有"、"相关"等泛词。
- filter: 按分类/标签筛选，params={{{"category": "金融"}}} 或 {{{"tag": "支付"}}}
- list: 仅当用户明确要求"列出全部"、"显示所有账号"时使用。params={{{"scope": "all|uncategorized"}}}
- reorganize: 建议重新整理分类，params={{{"changes": [{{"target_id": 1, "field": "category", "new_value": "金融", "reason": "..."}}]}}}
- add_remark: 建议添加AI备注，params={{{"changes": [{{"target_id": 1, "field": "ai_remark", "new_value": "备注内容"}}]}}}
- delete: 删除条目，params={{{"target_ids": [1, 2, 3], "query_description": "删掉所有分类为未整理的网址", "item_type": "account|url"}}}
- add: 新增条目，params={{{"item_type": "account|url", "fields": {{{"app_name": "B站", "username": "abc@qq.com", "password": "123456", "url": "https://www.bilibili.com", "category": "视频", "remark": "", "tags": []}}}}}}
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
                        # 移除 <动作> 块（仅在存在配对关闭标签时）
                        if '<动作>' in after_thinking and '</动作>' in after_thinking:
                            after_thinking = re.sub(r'<动作\s*>.*?</动作\s*>', '', after_thinking, flags=re.DOTALL)
                        response = after_thinking.strip()
                    else:
                        response = raw_text

            # 提取 query_summary（在清理前提取）
            query_summary_match = re.search(r'<query_summary\s*>\s*(.*?)\s*</query_summary\s*>', raw_text, re.DOTALL)
            query_summary = query_summary_match.group(1).strip() if query_summary_match else ""

            # 清理 response 中可能残留的标签（仅在存在配对关闭标签时）
            if '<思考>' in response and '</思考>' in response:
                response = re.sub(r'<思考\s*>.*?</思考\s*>', '', response, flags=re.DOTALL)
            if '<动作>' in response and '</动作>' in response:
                response = re.sub(r'<动作\s*>.*?</动作\s*>', '', response, flags=re.DOTALL)
            if '<query_summary>' in response and '</query_summary>' in response:
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
