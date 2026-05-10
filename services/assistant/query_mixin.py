import json
import logging
import os
from typing import List, Optional, Dict, Any

from models.account import Account
from core.repositories import RepositoryFactory
from services.ai_tools import ToolRegistry, PermissionLevel

_prompt_path = os.path.join(os.path.dirname(__file__), '..', '..', 'prompts', 'classify_prompt.txt')
with open(_prompt_path, 'r', encoding='utf-8') as f:
    CLASSIFY_PROMPT = f.read()

logger = logging.getLogger(__name__)


class QueryMixin:
    def semantic_query(self, query: str, accounts: List[Account] = None, urls: List = None, vault_type: str = 'accounts') -> dict:
        """
        Plan 模式语义查询：基于自然语言理解返回可能匹配的账号/网址 ID。
        
        Args:
            query: 用户输入
            accounts: 账号列表上下文
            urls: 网址列表上下文
            vault_type: 'accounts' 或 'urls'
            
        Returns:
            {"matched_ids": [...], "reasoning": "...", "confidence_scores": {...}}
        """
        if vault_type == 'accounts':
            if accounts is None:
                accounts_data = self.db.get_all_accounts()
                accounts = [Account.from_dict(data) for data in accounts_data]
            
            if not accounts:
                return {"matched_ids": [], "reasoning": "数据库为空", "confidence_scores": {}}
            
            lines = []
            for acc in accounts:
                tags_str = ""
                if acc.tags:
                    try:
                        tags = json.loads(acc.tags) if isinstance(acc.tags, str) else acc.tags
                        if isinstance(tags, list):
                            tags_str = ','.join(tags)
                    except Exception:
                        logger.debug("账号标签解析失败: %s", acc.tags, exc_info=True)
                        tags_str = str(acc.tags)
                remark = acc.remark or ''
                lines.append(f"{acc.id} | {acc.app_name} | {acc.category or '未分类'} | {tags_str} | {remark}")
        else:
            if urls is None and self.url_db:
                urls = self.url_db.get_all_urls()
            
            if not urls:
                return {"matched_ids": [], "reasoning": "网址库为空", "confidence_scores": {}}
            
            lines = []
            for u in urls:
                tags_str = ""
                u_tags = getattr(u, 'tags', None)
                if u_tags:
                    try:
                        tags = json.loads(u_tags) if isinstance(u_tags, str) else u_tags
                        if isinstance(tags, list):
                            tags_str = ','.join(tags)
                    except Exception:
                        logger.debug("网址标签解析失败: %s", u_tags, exc_info=True)
                        tags_str = str(u_tags)
                remark = (getattr(u, 'remark', '') or '')[:20]
                ai_remark = (getattr(u, 'ai_remark', '') or '')[:20]
                parts = [f"{getattr(u, 'id', '')}", getattr(u, 'title', ''), getattr(u, 'category', '未分类'), tags_str]
                if remark:
                    parts.append(f"备注:{remark}")
                if ai_remark:
                    parts.append(f"AI备注:{ai_remark}")
                lines.append(' | '.join(parts))
        
        items_summary = '\n'.join(lines)
        
        try:
            from services.ai_service_manager import AIServiceManager
            ai_manager = AIServiceManager.instance()
            if not ai_manager.is_available():
                return {"matched_ids": [], "reasoning": "Ollama 未初始化", "confidence_scores": {}}
            from ai.ollama_client import OllamaClient
            state = ai_manager.get_state()
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=300)
            return ollama.semantic_match(query, items_summary)
        except Exception as e:
            return {"matched_ids": [], "reasoning": f"语义查询异常: {e}", "confidence_scores": {}}
    
    def process_query(self, query: str, accounts: List[Account] = None,
                      mode: str = 'plan', record_history: bool = True,
                      vault_type: str = 'accounts') -> Dict:
        """
        处理用户自然语言查询
        
        Args:
            query: 用户输入（如"查找支付类账号"、"帮我整理分类"）
            accounts: 当前账号列表上下文
            mode: 'plan' 或 'build'，Plan 模式仅允许只读操作
            record_history: 是否记录到对话历史（分段输出模式由 UI 层控制历史）
            
        Returns:
            {
                "success": bool,
                "thinking": str,
                "action": str,
                "params": dict,
                "response": str,  # 给用户的自然语言回复
                "semantic_result": dict or None,
                "error": str      # 错误信息（如有）
            }
        """
        if not self.is_available():
            return {
                "success": False,
                "thinking": "",
                "action": "explain",
                "params": {},
                "response": "AI 服务未连接。请确保 Ollama 已启动并加载了 gemma4:4b 模型。",
                "semantic_result": None,
                "error": "Ollama not available"
            }
        
        # 指代消解
        from services.conversation_context import ReferenceResolver
        enhanced_query = ReferenceResolver.resolve(query, self.conversation_context)

        # 根据查询筛选目标分类下的账号（局部操作时不传全部数据）
        filtered_accounts, scope_hint = self._filter_items_by_query(accounts or [], enhanced_query)

        # 构建数据库摘要（32K 上下文窗口，500 个账号约占用 15K-18K tokens）
        db_summary = self.build_db_summary(filtered_accounts, vault_type=vault_type, max_items=500)

        # 构建对话历史（不含当前查询，供模型理解上下文）
        if self.conversation_context.history:
            history = []
            conversation_history = self.conversation_context.get_compressed_history()
        else:
            source_history = self._history if mode == 'plan' else self._history_build
            history = []
            for msg in source_history:
                history.append({
                    'role': msg.role,
                    'content': msg.content
                })
            conversation_history = ""
        
        # 调用模型解析指令
        try:
            from services.ai_service_manager import AIServiceManager
            ai_manager = AIServiceManager.instance()
            from ai.ollama_client import OllamaClient
            state = ai_manager.get_state()
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=300)
            result = ollama.parse_command(
                enhanced_query, db_summary, history,
                conversation_history=conversation_history
            )
            
            # 验证 action
            action = result.get('action', 'explain')
            if action not in self.VALID_ACTIONS:
                action = 'explain'
            
            # Plan 模式：拦截写操作
            if mode == 'plan' and action not in self.READONLY_ACTIONS:
                action = 'explain'
                original_response = result.get('response', '')
                result['response'] = (
                    f"【Plan 模式保护】当前模式仅支持查询操作。"
                    f"如需执行「{result.get('action')}」，请切换到 Build 模式。\n\n{original_response}"
                )
            
            # add 操作的缺项追问
            if action == 'add':
                params = result.get('params', {})
                fields = params.get('fields', {})
                item_type = params.get('item_type', 'account')
                missing = []
                
                if item_type == 'account':
                    if not fields.get('app_name'): missing.append('应用名称')
                    if not fields.get('username'): missing.append('账号')
                    if not fields.get('password'): missing.append('密码')
                elif item_type == 'url':
                    if not fields.get('title'): missing.append('标题')
                    if not fields.get('url'): missing.append('网址')
                
                if missing:
                    result['response'] = f"请补充以下信息：{', '.join(missing)}"
                    result['action'] = 'explain'  # 降级为 explain，等待用户补全
                    result['params'] = {'pending_add': params}  # 保存已抽取的字段
                    action = 'explain'
            
            # 使用 parse_command 返回的 matched_ids 构建 semantic_result（替代独立的 semantic_query）
            matched_ids = result.get('matched_ids', [])
            semantic_result = None
            if matched_ids:
                semantic_result = {
                    "matched_ids": matched_ids,
                    "reasoning": result.get('thinking', ''),
                    "confidence_scores": {str(m): 0.8 for m in matched_ids}
                }
            
            # 记录对话历史
            if record_history:
                self._add_message('user', query, mode=mode)
                self._add_message(
                    'assistant',
                    result.get('response', ''),
                    mode=mode,
                    thinking=result.get('thinking', ''),
                    action=action
                )
            
            # 追加到 ConversationContext
            if mode == 'plan':
                from services.conversation_context import TurnSnapshot
                snapshot = TurnSnapshot(
                    user_input=query,
                    parsed_action=action,
                    params_summary=str(result.get('params', {})),
                    ai_reply_summary=result.get('response', ''),
                    plan_entity_ids=set(matched_ids) if matched_ids else None,
                    vault_type=vault_type
                )
                self.conversation_context.append_turn(snapshot)
            
            return {
                "success": True,
                "thinking": result.get('thinking', ''),
                "action": action,
                "params": result.get('params', {}),
                "response": result.get('response', ''),
                "semantic_result": semantic_result,
                "error": ""
            }
            
        except Exception as e:
            error_msg = str(e)
            semantic_result = None
            logger.exception("process_query exception")
            if record_history:
                self._add_message('assistant', f"处理失败: {error_msg}", mode=mode)
            return {
                "success": False,
                "thinking": "",
                "action": "explain",
                "params": {},
                "response": f"AI 处理出错：{error_msg}",
                "semantic_result": semantic_result,
                "error": error_msg
            }
    
    def process_query_stream(self, query: str, accounts: List[Account] = None,
                             mode: str = 'plan', on_token=None,
                             record_history: bool = True,
                             vault_type: str = 'accounts') -> Dict:
        """
        流式处理用户自然语言查询。
        
        Args:
            query: 用户输入
            accounts: 当前账号列表上下文
            mode: 'plan' 或 'build'
            on_token: 回调函数(token: str, section: str)，section 为 'thinking' 或 'result'
            
        Returns:
            与 process_query 相同格式的字典
        """
        if not self.is_available():
            return {
                "success": False,
                "thinking": "",
                "action": "explain",
                "params": {},
                "response": "AI 服务未连接。请确保 Ollama 已启动并加载了 gemma4:4b 模型。",
                "semantic_result": None,
                "error": "Ollama not available"
            }
        
        # 指代消解
        from services.conversation_context import ReferenceResolver
        enhanced_query = ReferenceResolver.resolve(query, self.conversation_context)

        # 根据查询筛选目标分类下的账号（局部操作时不传全部数据）
        filtered_accounts, scope_hint = self._filter_items_by_query(accounts or [], enhanced_query)

        # 构建数据库摘要
        db_summary = self.build_db_summary(filtered_accounts, vault_type=vault_type, max_items=500)

        # 构建历史上下文字符串
        if self.conversation_context.history:
            history_str = "\n\n之前的对话：\n" + self.conversation_context.get_compressed_history() + "\n"
        else:
            source_history = self._history if mode == 'plan' else self._history_build
            history = []
            for msg in source_history:
                history.append({'role': msg.role, 'content': msg.content})
            history_str = ""
            if history:
                history_lines = []
                for msg in history[-6:]:
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')
                    if role == 'user':
                        history_lines.append(f"用户：{content}")
                    else:
                        history_lines.append(f"助手：{content}")
                if history_lines:
                    history_str = "\n\n之前的对话：\n" + "\n".join(history_lines) + "\n"
        
        prompt = CLASSIFY_PROMPT.format(scope_hint=scope_hint, db_summary=db_summary, history_str=history_str, enhanced_query=enhanced_query)
        
        # 使用列表累积 token，避免频繁的字符串拼接；buffer 用于状态机检测
        full_text_parts = []
        buffer = ""
        seen_thinking_open = False
        seen_thinking_close = False
        seen_response_open = False
        seen_response_close = False
        
        try:
            logger.info("Starting generate_stream, prompt_len=%d", len(prompt))
            from services.ai_service_manager import AIServiceManager
            ai_manager = AIServiceManager.instance()
            from ai.ollama_client import OllamaClient
            state = ai_manager.get_state()
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=300)
            token_count = 0
            for token in ollama.generate_stream(prompt, temperature=0.2):
                token_count += 1
                full_text_parts.append(token)
                buffer += token
                # 限制 buffer 长度，避免状态机检测时内存线性增长
                if len(buffer) > 200:
                    buffer = buffer[-100:]
                
                # 简单状态机标记 section
                if '<思考' in buffer:
                    seen_thinking_open = True
                if '</思考' in buffer:
                    seen_thinking_close = True
                if '<回复' in buffer:
                    seen_response_open = True
                if '</回复' in buffer:
                    seen_response_close = True
                
                # 决定当前 token 的 section
                if seen_thinking_open and not seen_thinking_close:
                    section = 'thinking'
                elif seen_response_open and not seen_response_close:
                    section = 'result'
                else:
                    section = 'unknown'
                
                # 排除标签文本本身
                clean_token = token
                if section == 'thinking' and ('<思考' in token or '</思考' in token):
                    clean_token = token.replace('<思考>', '').replace('</思考>', '').replace('<思考 >', '').replace('</思考 >', '')
                elif section == 'result' and ('<回复' in token or '</回复' in token):
                    clean_token = token.replace('<回复>', '').replace('</回复>', '').replace('<回复 >', '').replace('</回复 >', '')
                
                if on_token and clean_token and section in ('thinking', 'result'):
                    try:
                        on_token(clean_token, section)
                    except Exception as cb_err:
                        logger.error("on_token callback error: %s", cb_err)
            
            full_text = "".join(full_text_parts)
            logger.info("generate_stream finished, total_tokens=%d, response_len=%d", token_count, len(full_text))
            # 解析完整结果
            result = ollama._extract_command(full_text)
            
            # 验证 action
            action = result.get('action', 'explain')
            if action not in self.VALID_ACTIONS:
                action = 'explain'
            
            # Plan 模式拦截写操作
            if mode == 'plan' and action not in self.READONLY_ACTIONS:
                action = 'explain'
                original_response = result.get('response', '')
                result['response'] = (
                    f"【Plan 模式保护】当前模式仅支持查询操作。"
                    f"如需执行「{result.get('action')}」，请切换到 Build 模式。\n\n{original_response}"
                )
            
            # add 操作的缺项追问
            if action == 'add':
                params = result.get('params', {})
                fields = params.get('fields', {})
                item_type = params.get('item_type', 'account')
                missing = []
                
                if item_type == 'account':
                    if not fields.get('app_name'): missing.append('应用名称')
                    if not fields.get('username'): missing.append('账号')
                    if not fields.get('password'): missing.append('密码')
                elif item_type == 'url':
                    if not fields.get('title'): missing.append('标题')
                    if not fields.get('url'): missing.append('网址')
                
                if missing:
                    result['response'] = f"请补充以下信息：{', '.join(missing)}"
                    result['action'] = 'explain'  # 降级为 explain，等待用户补全
                    result['params'] = {'pending_add': params}  # 保存已抽取的字段
                    action = 'explain'
            
            # 使用 parse_command 返回的 matched_ids 构建 semantic_result
            matched_ids = result.get('matched_ids', [])
            semantic_result = None
            if matched_ids:
                semantic_result = {
                    "matched_ids": matched_ids,
                    "reasoning": result.get('thinking', ''),
                    "confidence_scores": {str(m): 0.8 for m in matched_ids}
                }
            
            # 记录对话历史
            if record_history:
                self._add_message('user', query, mode=mode)
                self._add_message(
                    'assistant',
                    result.get('response', ''),
                    mode=mode,
                    thinking=result.get('thinking', ''),
                    action=action
                )
            
            # 追加到 ConversationContext
            if mode == 'plan':
                from services.conversation_context import TurnSnapshot
                snapshot = TurnSnapshot(
                    user_input=query,
                    parsed_action=action,
                    params_summary=str(result.get('params', {})),
                    ai_reply_summary=result.get('response', ''),
                    plan_entity_ids=set(matched_ids) if matched_ids else None,
                    vault_type=vault_type
                )
                self.conversation_context.append_turn(snapshot)
            
            return {
                "success": True,
                "thinking": result.get('thinking', ''),
                "action": action,
                "params": result.get('params', {}),
                "response": result.get('response', ''),
                "semantic_result": semantic_result,
                "error": ""
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.exception("process_query_stream exception")
            if record_history:
                self._add_message('assistant', f"处理失败: {error_msg}", mode=mode)
            return {
                "success": False,
                "thinking": "",
                "action": "explain",
                "params": {},
                "response": f"AI 处理出错：{error_msg}",
                "semantic_result": None,
                "error": error_msg
            }
    
    def process_react_query(self, query: str, context_items: List = None,
                            mode: str = 'plan', vault_type: str = 'accounts',
                            max_turns: int = 5) -> Dict:
        """
        ReAct Tool Calling Agent 主循环。

        最多执行 max_turns 轮单步 ReAct 循环，每轮：
        1. 组装 ReAct Prompt（Observation 历史 + Tool Schema）
        2. 调用 Ollama generate_tool_call 获取决策
        3. 执行工具或返回结果

        Returns:
            {
                "success": bool,
                "done": bool,
                "turns_used": int,
                "response": str,
                "preview": Dict or None,
                "awaiting_confirm": bool,
                "pending_tool": Dict or None,
                "observations": List,
                "error": str
            }
        """
        if not self.is_available():
            return {
                "success": False,
                "done": True,
                "turns_used": 0,
                "response": "AI 服务未连接。请确保 Ollama 已启动并加载了 gemma4:4b 模型。",
                "preview": None,
                "awaiting_confirm": False,
                "pending_tool": None,
                "observations": [],
                "error": "Ollama not available"
            }

        # 1. 指代消解（先处理，以便后续根据查询内容筛选）
        from services.conversation_context import ReferenceResolver
        enhanced_query = ReferenceResolver.resolve(query, self.conversation_context)

        # 2. 构建分类树（先用总数，后续根据大模型解析的目标分类更新）
        repo = RepositoryFactory.get_repository(vault_type)
        try:
            existing_categories = repo.get_categories() if hasattr(repo, 'get_categories') else []
        except Exception:
            logger.warning("获取分类列表失败", exc_info=True)
            existing_categories = []
        from core.category_utils import build_category_tree
        tree = build_category_tree([c for c in existing_categories if c and c != '全部'])
        tree_lines = []
        for parent, info in sorted(tree.items()):
            children = sorted(info.get('children', set()))
            if children:
                tree_lines.append(f"- {parent}")
                for child in children:
                    tree_lines.append(f"  - {parent}>{child}")
            else:
                tree_lines.append(f"- {parent}")
        tree_body = "\n".join(tree_lines) if tree_lines else "（暂无分类）"
        vault_type_name = '网址库' if vault_type == 'urls' else '密码库'
        item_type_name = '网址' if vault_type == 'urls' else '账号'
        total_count = len(context_items or [])
        category_tree_text = f"当前库类型：{vault_type_name}\n共{total_count}个{item_type_name}\n分类体系：\n{tree_body}"
        logger.info("category_tree length=%d, text=%r", len(category_tree_text), category_tree_text[:200])

        # 3. 预决策：让大模型解析用户提到的目标分类（语义理解替代硬编码字符串匹配）
        from ai.ollama_client import OllamaClient
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
        ollama = OllamaClient(model=ai_manager.get_state().model_name or "gemma4:4b", timeout=300)
        
        tools = []
        for tool in ToolRegistry.list():
            name = tool.name
            if '_accounts' in name and vault_type != 'accounts':
                continue
            if '_urls' in name and vault_type != 'urls':
                continue
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "params_schema": tool.params_schema
            })
        
        pre_decision = ollama.generate_tool_call(enhanced_query, category_tree_text, "", tools, vault_type=vault_type)
        target_categories = pre_decision.get("target_categories", [])
        logger.info("target_categories=%s", target_categories)

        # 4. 用 target_categories 筛选条目（支持多分类和二级分类）
        if target_categories:
            from core.category_utils import get_prefix_matcher
            filtered_items = []
            seen_ids = set()
            for cat in target_categories:
                matcher = get_prefix_matcher(cat)
                for item in (context_items or []):
                    item_id = getattr(item, 'id', 0)
                    if item_id in seen_ids:
                        continue
                    if matcher(getattr(item, 'category', '') or ''):
                        seen_ids.add(item_id)
                        filtered_items.append(item)
            if filtered_items:
                scope_hint = f"（仅包含{', '.join(target_categories)}分类下的 {len(filtered_items)} 个{item_type_name}）"
            else:
                filtered_items, scope_hint = self._filter_items_by_query(context_items or [], enhanced_query)
        else:
            filtered_items, scope_hint = self._filter_items_by_query(context_items or [], enhanced_query)
        logger.info("filtered=%d, scope_hint='%s'", len(filtered_items), scope_hint)

        # 5. 更新分类树中的数量（用筛选后的结果）
        category_tree_text = f"当前库类型：{vault_type_name}\n共{len(filtered_items)}个{item_type_name}\n分类体系：\n{tree_body}"

        # 完整的db_summary保留构建供工具内部或日志参考
        if scope_hint:
            if vault_type == 'accounts':
                db_summary = self.build_db_summary(filtered_items, vault_type=vault_type, max_items=500)
            else:
                db_summary = self.build_db_summary(urls=filtered_items, vault_type=vault_type, max_items=500)
        else:
            db_summary = self.conversation_context.get_db_summary(vault_type, item_count=len(filtered_items))
            if db_summary is None:
                if vault_type == 'accounts':
                    db_summary = self.build_db_summary(filtered_items, vault_type=vault_type, max_items=500)
                else:
                    db_summary = self.build_db_summary(urls=filtered_items, vault_type=vault_type, max_items=500)
                self.conversation_context.set_db_summary(db_summary, vault_type, item_count=len(filtered_items))

        # 6. 准备 tool_context（使用筛选后的数据，确保工具内部也只看到这些条目）
        tool_context = {
            "accounts": filtered_items if vault_type == 'accounts' else None,
            "urls": filtered_items if vault_type == 'urls' else None,
            "vault_type": vault_type,
            "db": self.db,
            "url_db": self.url_db,
            "repo": RepositoryFactory.get_repository(vault_type),
            "query": enhanced_query
        }

        observations = []

        # 7. ReAct 循环
        for turn in range(max_turns):
            observations_text = self.conversation_context.get_observations_text(max_count=5)

            try:
                if turn == 0:
                    # 第一轮直接使用预决策结果，避免重复调用模型
                    decision = pre_decision
                else:
                    decision = ollama.generate_tool_call(enhanced_query, category_tree_text, observations_text, tools, vault_type=vault_type)
            except Exception as e:
                return {
                    "success": False,
                    "done": True,
                    "turns_used": turn + 1,
                    "response": f"AI 决策调用失败: {e}",
                    "preview": None,
                    "awaiting_confirm": False,
                    "pending_tool": None,
                    "observations": observations,
                    "error": str(e)
                }

            tool_name = decision.get("tool", "direct_answer")
            thought = decision.get("thought", "")
            params = decision.get("params", {})
            direct_response = decision.get("response", "")

            # direct_answer -> 完成
            if tool_name == "direct_answer":
                return {
                    "success": True,
                    "done": True,
                    "turns_used": turn + 1,
                    "response": direct_response or thought,
                    "preview": None,
                    "awaiting_confirm": False,
                    "pending_tool": None,
                    "observations": observations,
                    "error": ""
                }

            # 获取 Tool 实例
            tool = ToolRegistry.get(tool_name)
            if tool is None:
                obs_msg = f"工具 {tool_name} 不存在"
                observations.append({"turn": turn + 1, "tool": tool_name, "observation": obs_msg})
                self.conversation_context.add_observation(tool_name, params, obs_msg, turn + 1)
                continue

            # Plan 模式拦截非只读工具
            if mode == 'plan' and tool.permission.value != PermissionLevel.READONLY.value:
                return {
                    "success": True,
                    "done": True,
                    "turns_used": turn + 1,
                    "response": f"【Plan 模式保护】当前模式仅支持查询操作。如需执行「{tool_name}」，请切换到 Build 模式并经你确认后可执行。",
                    "preview": None,
                    "awaiting_confirm": False,
                    "pending_tool": None,
                    "observations": observations,
                    "error": ""
                }

            # 验证参数
            valid, err = tool.validate_params(params)
            if not valid:
                obs_msg = f"参数验证失败: {err}"
                observations.append({"turn": turn + 1, "tool": tool_name, "observation": obs_msg})
                self.conversation_context.add_observation(tool_name, params, obs_msg, turn + 1)
                continue

            # 执行工具
            try:
                tool_result = tool.execute(params, tool_context)
            except Exception as e:
                obs_msg = f"工具执行异常: {e}"
                observations.append({"turn": turn + 1, "tool": tool_name, "observation": obs_msg})
                self.conversation_context.add_observation(tool_name, params, obs_msg, turn + 1)
                continue

            # PREVIEW/CONFIRM 权限 + build 模式 -> 暂停等待确认
            if tool.permission.value in (PermissionLevel.PREVIEW.value, PermissionLevel.CONFIRM.value) and mode == 'build':
                preview = self.build_action_preview_from_tool_result(tool_result, tool) if tool_result.preview_data else None
                return {
                    "success": True,
                    "done": False,
                    "turns_used": turn + 1,
                    "response": tool_result.message or f"需要确认执行 {tool_name}",
                    "preview": preview,
                    "awaiting_confirm": True,
                    "pending_tool": {
                        "tool": tool_name,
                        "params": params,
                        "thought": thought
                    },
                    "observations": observations,
                    "error": ""
                }

            # READONLY 工具
            if tool.permission.value == PermissionLevel.READONLY.value:
                # 构造格式化回复
                response = tool_result.message or "查询完成"
                matched_ids = []
                if tool_result.data:
                    data = tool_result.data
                    matched_count = data.get("matched_count", 0)
                    matched_ids = data.get("matched_ids", [])
                    
                    # 处理 get_recent_changes 等特殊工具返回的 changes 列表
                    if not matched_ids and "changes" in data:
                        changes = data["changes"]
                        matched_ids = [c["id"] for c in changes if c.get("id") is not None]
                        matched_count = len(matched_ids)
                    
                    if matched_count > 0 and matched_ids:
                        # 反查匹配项名称，生成更友好的回复
                        items = tool_context.get("accounts") or tool_context.get("urls") or []
                        id_to_name = {}
                        for item in items:
                            item_id = getattr(item, 'id', None)
                            if item_id is not None:
                                name = getattr(item, 'app_name', None) or getattr(item, 'title', None) or str(item_id)
                                id_to_name[str(item_id)] = name
                        
                        names = []
                        for mid in matched_ids:
                            names.append(id_to_name.get(str(mid), f"ID:{mid}"))
                        name_list = "、".join(names)
                        response = f"找到 {matched_count} 个相关结果：{name_list}（共 {matched_count} 个）"
                
                # Plan 模式：直接返回查询结果，不再进行第二轮模型调用
                if mode == 'plan':
                    return {
                        "success": True,
                        "done": True,
                        "turns_used": turn + 1,
                        "response": response,
                        "preview": None,
                        "awaiting_confirm": False,
                        "pending_tool": None,
                        "observations": observations,
                        "error": "",
                        "matched_ids": matched_ids
                    }
                
                # Build 模式：记录 observation 并继续循环，让模型有机会基于查询结果调用写操作工具
                # 在 observation 中附加 matched_ids，让模型下一轮能精确构造写操作参数
                obs_matched_ids = []
                if tool_result.data:
                    obs_matched_ids = tool_result.data.get("matched_ids", [])
                obs_result = {
                    "message": tool_result.message,
                    "matched_ids": obs_matched_ids,
                    "matched_count": len(obs_matched_ids)
                }
                observations.append({
                    "turn": turn + 1,
                    "tool": tool_name,
                    "params": params,
                    "result": obs_result
                })
                self.conversation_context.add_observation(tool_name, params, obs_result, turn + 1)
                continue

            # 记录 observation 并继续（非 READONLY 工具）
            obs_record = {
                "turn": turn + 1,
                "tool": tool_name,
                "params": params,
                "result": {
                    "success": tool_result.success,
                    "message": tool_result.message,
                    "data_summary": str(tool_result.data) if tool_result.data else ""
                }
            }
            observations.append(obs_record)
            self.conversation_context.add_observation(tool_name, params, tool_result.message, turn + 1)

        # 达到 max_turns，防循环保护
        return {
            "success": False,
            "done": True,
            "turns_used": max_turns,
            "response": "AI 思考轮数已达到上限，未能完成操作。请简化您的指令或分步执行。",
            "preview": None,
            "awaiting_confirm": False,
            "pending_tool": None,
            "observations": observations,
            "error": "Max turns reached"
        }
