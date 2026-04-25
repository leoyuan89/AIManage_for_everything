"""
Ollama API 客户端
用于调用本地 Gemma 4 E4B 模型
"""
import json
import re
import requests
from typing import List, Optional, Tuple, Generator


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
        except:
            return False
    
    def generate(self, prompt: str, temperature: float = 0.1, num_predict: int = -1) -> str:
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
            return result.get('response', '').strip()
            
        except requests.exceptions.ConnectionError:
            raise Exception("无法连接到 Ollama 服务，请确保 Ollama 已启动")
        except requests.exceptions.Timeout:
            raise Exception("Ollama 响应超时，请检查模型是否已加载")
        except Exception as e:
            raise Exception(f"Ollama 调用失败: {str(e)}")
    
    def generate_stream(self, prompt: str, temperature: float = 0.1, num_predict: int = -1) -> Generator[str, None, None]:
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
                    
        except Exception:
            # 降级为非流式生成
            try:
                result = self.generate(prompt, temperature=temperature, num_predict=num_predict)
                yield result
            except Exception as fallback_e:
                raise Exception(f"流式生成失败且降级失败: {fallback_e}")
    
    def generate_with_think_result(self, prompt: str, temperature: float = 0.1, num_predict: int = -1) -> dict:
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
    
    def categorize(self, app_name: str, url: str = "") -> str:
        """
        AI 智能分类
        
        Args:
            app_name: 应用名称
            url: 网址（可选）
            
        Returns:
            分类名称（社交/金融/邮箱/游戏/工作/其他）
        """
        prompt = f"""你是一款密码管理软件的分类助手。请根据应用名称和网址，判断该账号属于以下哪个分类：社交、金融、邮箱、游戏、工作、其他。

规则：
- 只返回分类名称中的一个词，不要解释
- 如果无法判断，返回"其他"

应用名称：{app_name}
网址：{url}

分类："""
        
        try:
            result = self.generate(prompt, temperature=0.1, num_predict=50)
            
            # 清洗结果
            result = result.strip()
            
            # 提取分类词（可能返回 "金融" 或 "分类：金融"）
            valid_categories = ['社交', '金融', '邮箱', '游戏', '工作', '其他']
            
            for cat in valid_categories:
                if cat in result:
                    return cat
            
            return '其他'
            
        except Exception as e:
            print(f"AI 分类失败: {e}")
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
        print(f"[SemanticSearch] Prompt length: {len(prompt)} chars, accounts: {len(app_list)}")
        
        try:
            result = self.generate(prompt, temperature=0.2, num_predict=1500)
            print(f"[SemanticSearch] Raw response ({len(result)} chars):\n{result[:500]}")
            
            # 如果结果只有"无"相关行（没有其他匹配项），返回空列表
            lines = [l.strip() for l in result.strip().split('\n') if l.strip()]
            non_empty_lines = [l for l in lines if l.lower() not in ('无', 'none', '')]
            if not non_empty_lines:
                print("[SemanticSearch] No non-empty lines found")
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
                    print(f"[SemanticSearch] Matched exact: {app_name} ({confidence})")
                else:
                    # 尝试子串匹配
                    for orig in app_list:
                        if app_name in orig or orig in app_name:
                            matched_apps.append((orig, confidence))
                            print(f"[SemanticSearch] Matched fuzzy: {orig} via '{app_name}' ({confidence})")
                            break
            
            print(f"[SemanticSearch] Total matched: {len(matched_apps)}")
            return matched_apps
            
        except Exception as e:
            print(f"语义搜索失败: {e}")
            return []
    
    def semantic_match(self, query: str, items_summary: str) -> dict:
        """
        语义匹配：理解用户查询，从条目摘要中返回匹配的 ID 列表与置信度。
        
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
        prompt = f"""用户正在密码管理软件中搜索账号，他说："{query}"

软件中存储的账号列表如下（每行格式：ID | 应用名 | 分类 | 标签 | 备注）：
{items_summary}

请从列表中严格筛选出与用户需求**直接相关**的应用。
返回 JSON 格式：
{{
  "matched_ids": [匹配的ID列表],
  "reasoning": "你的推理过程（中文）",
  "confidence_scores": {{"ID": 置信度(0-1)}}
}}

规则：
1. 只返回确实相关的 ID，不要为了提高召回率而滥发
2. 如果没有匹配的，返回空数组 []
3. confidence > 0.6 才纳入结果
4. 只输出 JSON，不要其他解释
5. 示例：用户说"支付类"，应返回支付宝、银行、PayPal 等相关账号，不应返回游戏、社交类账号
"""
        try:
            raw = self.generate(prompt, temperature=0.1, num_predict=800)
            text = raw.strip()
            print(f"[SemanticMatch] Raw response ({len(text)} chars): {text[:300]}")
            
            # 去除可能的 markdown 代码块标记
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            
            data = json.loads(text)
            matched_ids = data.get("matched_ids", [])
            reasoning = data.get("reasoning", "")
            confidence_scores = data.get("confidence_scores", {})
            print(f"[SemanticMatch] Parsed matched_ids: {matched_ids[:20]}{'...' if len(matched_ids) > 20 else ''} (total: {len(matched_ids)})")
            
            # 过滤置信度并清洗 ID 类型（统一转为 int）
            cleaned_ids = []
            filtered_scores = {}
            for mid in matched_ids:
                try:
                    mid_int = int(mid)
                except (ValueError, TypeError):
                    continue
                sid = str(mid_int)
                score = confidence_scores.get(sid, confidence_scores.get(mid, 0.8))
                try:
                    score = float(score)
                except (ValueError, TypeError):
                    score = 0.8
                if score > 0.6:
                    cleaned_ids.append(mid_int)
                    filtered_scores[sid] = score
            
            return {
                "matched_ids": cleaned_ids,
                "reasoning": reasoning,
                "confidence_scores": filtered_scores
            }
        except Exception as e:
            return {
                "matched_ids": [],
                "reasoning": f"语义匹配解析失败: {e}",
                "confidence_scores": {}
            }
    
    def chat(self, messages: List[dict], temperature: float = 0.3, num_predict: int = 1200) -> str:
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
            return default
