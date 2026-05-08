"""
AI 助手服务
提供自然语言指令解析、数据库摘要构建、对话历史管理
"""
import logging
import json
import uuid
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

import os
_prompt_path = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'classify_prompt.txt')
with open(_prompt_path, 'r', encoding='utf-8') as f:
    CLASSIFY_PROMPT = f.read()

from core.database import DatabaseManager
from models.account import Account
from models.url_item import URLItem
from core.repositories import RepositoryFactory
from services.ai_tools import ToolRegistry, AITool, ToolResult, PermissionLevel


@dataclass
class ConversationMessage:
    """对话消息"""
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    timestamp: str
    thinking: str = ""  # AI 的思考过程（仅 assistant 有）
    action: str = ""    # 解析后的动作（仅 assistant 有）


class AIAssistantService:
    """AI 助手服务"""
    
    # 支持的动作类型
    VALID_ACTIONS = ['search', 'filter', 'list', 'reorganize', 'add_remark',
                     'delete', 'add', 'explain', 'get_category_tree',
                     'batch_add_account', 'batch_add_url']
    READONLY_ACTIONS = {'search', 'filter', 'list', 'explain', 'get_category_tree'}
    WRITE_ACTIONS = {'reorganize', 'add_remark', 'delete', 'add',
                     'batch_add_account', 'batch_add_url'}
    
    def __init__(self, db_manager: DatabaseManager, url_db_manager=None):
        self.db = db_manager
        self.url_db = url_db_manager  # 新增
        self._history: List[ConversationMessage] = []  # Plan 模式历史（兼容旧代码直接访问）
        self._history_build: List[ConversationMessage] = []  # Build 模式历史
        self._max_history = 20
        from services.conversation_context import ConversationContext
        self.conversation_context = ConversationContext()
    
    def is_available(self) -> bool:
        """检查 AI 服务是否可用"""
        from services.ai_service_manager import AIServiceManager
        return AIServiceManager.instance().is_available()
    
    def _filter_items_by_query(self, items: list, query: str) -> tuple:
        """
        根据用户查询筛选目标分类下的条目。
        如果查询中提到了具体分类且包含局部操作关键词，只返回该分类下的条目。
        返回: (filtered_items, scope_hint)
        """
        if not items:
            return items, ""
        
        # 提取所有现有分类
        categories = set()
        for item in items:
            cat = getattr(item, 'category', '') or ''
            if cat:
                categories.add(cat)
        
        # 目标指示词：出现在这些词后面的分类名通常是操作目标，不是源筛选条件
        target_indicators = ['改为', '改成', '修改为', '变更为', '调整为', '重命名为', 
                             '设置为', '定义为', '移到', '移动到', '转移至', '归类到', 
                             '归类为', '分配到', '映射到']
        
        def _is_target_category(cat_name: str, q: str) -> bool:
            """判断分类名是否出现在目标指示词之后"""
            for indicator in target_indicators:
                # 查找指示词位置
                idx = q.find(indicator)
                if idx == -1:
                    continue
                # 指示词后面的内容
                after = q[idx + len(indicator):]
                # 如果分类名出现在指示词后面（允许中间有少量字符如"的"、"为"等）
                if cat_name in after[:len(cat_name) + 5]:
                    return True
            return False
        
        # 查找查询中提到的分类名（完整路径或父节点）
        matched_cats = []
        for cat in categories:
            if not cat:
                continue
            if cat in query and not _is_target_category(cat, query):
                matched_cats.append(cat)
            # 二级路径的父节点也可能在查询中被提及
            elif '>' in cat:
                parent = cat.split('>')[0].strip()
                if parent in query and not _is_target_category(parent, query):
                    matched_cats.append(parent)
        if not matched_cats:
            return items, ""
        
        target_category = max(matched_cats, key=len)
        
        # 局部操作关键词：这些操作通常只涉及某个分类下的条目
        local_op_keywords = [
            '细分', '二级', '子类', '子分类',
            '添加备注', '添加标签',
            '整理分类', '整理', '重组', '重命名',
            '分类', '重新分类', '调整分类', '修改分类', '改变分类', '变更分类',
            '移到', '移动到', '转移至', '归类',
        ]
        is_local_op = any(kw in query for kw in local_op_keywords)
        
        if not is_local_op:
            return items, ""
        
        from core.category_utils import get_prefix_matcher
        matcher = get_prefix_matcher(target_category)
        filtered = [item for item in items if matcher(getattr(item, 'category', '') or '')]
        
        if filtered:
            item_type = '网址' if hasattr(items[0], 'url') and not hasattr(items[0], 'app_name') else '账号'
            return filtered, f"（仅包含「{target_category}」分类下的 {len(filtered)} 个{item_type}）"
        return items, ""
    
    def build_db_summary(self, accounts: List[Account] = None, urls: List = None, vault_type: str = 'accounts', max_items: int = 200) -> str:
        """
        构建数据库摘要（不含密码）
        """
        if vault_type == 'accounts':
            if accounts is None:
                accounts_data = self.db.get_all_accounts()
                accounts = [Account.from_dict(data) for data in accounts_data]
            if not accounts:
                return "无账号。"
            categories = {}
            for acc in accounts:
                cat = acc.category or '未分类'
                categories[cat] = categories.get(cat, 0) + 1
            cats = ' '.join(f"{k}({v})" for k, v in sorted(categories.items(), key=lambda x: -x[1]))
            lines = [f"共{len(accounts)}个账号。分类：{cats}", "ID|应用名|分类|备注"]
            for acc in accounts[:max_items]:
                remark = (acc.remark or '')[:30]
                lines.append(f"{acc.id}|{acc.app_name}|{acc.category or '未分类'}|{remark}")
            if len(accounts) > max_items:
                lines.append(f"...还有{len(accounts)-max_items}个未列出")
            return '\n'.join(lines)
        else:
            if urls is None and self.url_db:
                urls = self.url_db.get_all_urls()
            if not urls:
                return "无网址。"
            categories = {}
            for u in urls:
                cat = getattr(u, 'category', None) or '未分类'
                categories[cat] = categories.get(cat, 0) + 1
            cats = ' '.join(f"{k}({v})" for k, v in sorted(categories.items(), key=lambda x: -x[1]))
            lines = [f"共{len(urls)}个网址。分类：{cats}", "ID|标题|分类|备注|AI备注"]
            for u in urls[:max_items]:
                title = getattr(u, 'title', '')[:30]
                remark = (getattr(u, 'remark', '') or '')[:20]
                ai_remark = (getattr(u, 'ai_remark', '') or '')[:20]
                parts = [f"{getattr(u, 'id', 0)}", title, getattr(u, 'category', '') or '未分类']
                if remark:
                    parts.append(remark)
                else:
                    parts.append('')
                if ai_remark:
                    parts.append(ai_remark)
                lines.append('|'.join(parts))
            if len(urls) > max_items:
                lines.append(f"...还有{len(urls)-max_items}个未列出")
            return '\n'.join(lines)
    
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
            ollama = OllamaClient(model=state.model_name or "gemma4:4b")
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
        enhanced_query, inherited_ids = ReferenceResolver.resolve(query, self.conversation_context)
        
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
            ollama = OllamaClient(model=state.model_name or "gemma4:4b")
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
        enhanced_query, inherited_ids = ReferenceResolver.resolve(query, self.conversation_context)
        
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
        
        full_text = ""
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
            ollama = OllamaClient(model=state.model_name or "gemma4:4b")
            token_count = 0
            for token in ollama.generate_stream(prompt, temperature=0.2):
                token_count += 1
                full_text += token
                
                # 简单状态机标记 section
                if '<思考' in full_text:
                    seen_thinking_open = True
                if '</思考' in full_text:
                    seen_thinking_close = True
                if '<回复' in full_text:
                    seen_response_open = True
                if '</回复' in full_text:
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
        enhanced_query, inherited_ids = ReferenceResolver.resolve(query, self.conversation_context)

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
        ollama = OllamaClient(model=ai_manager.get_state().model_name or "gemma4:4b")
        
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
            "inherited_ids": inherited_ids,
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

    def _heuristic_reorganize(self, context_items: List[Any], repo) -> List[Dict]:
        """本地启发式分类（模型未返回结构化 changes 时的兜底）"""
        category_keywords = {
            '金融': ['银行', '支付', '理财', '保险', '证券', '信用卡', '支付宝', '财富', '股票', '东方财富', '银联', 'paypal', 'pay'],
            '社交': ['微信', 'QQ', '微博', '抖音', '小红书', '知乎', '推特', 'facebook', 'telegram', 'whatsapp', 'line'],
            '邮箱': ['邮箱', 'mail', 'gmail', 'outlook', '163', 'qq邮箱', 'email', '126'],
            '游戏': ['游戏', 'steam', 'epic', '暴雪', '腾讯游戏', '网易游戏', 'bilibili游戏', '原神', '王者'],
            '工作': ['办公', '企业', '钉钉', '飞书', 'slack', 'github', 'gitlab', 'notion', '语雀', '金山', 'wps', 'office', 'confluence'],
            '购物': ['淘宝', '京东', '拼多多', '亚马逊', '天猫', '购物', '商城', '电商', '便利店', '美团', '饿了么', '外卖'],
            '教育': ['学习', '课程', 'edu', '学堂', 'mooc', 'coursera', 'academy', 'acwing', 'leetcode', '知网', '学习通', 'cet', '四六级', '慕课', '校园', '大学', '图书馆'],
            '娱乐': ['视频', '影视', '音乐', 'bilibili', 'youtube', 'netflix', 'spotify', '直播', '斗鱼', '虎牙', '综艺', '电影', '追剧'],
            '开发': ['开发', '代码', 'git', 'api', 'docker', 'vscode', 'jetbrains', '编程', 'leetcode', 'acwing', 'github', 'gitlab', 'stackoverflow', 'hackerrank'],
            '云服务': ['云', '服务器', 'aws', '阿里云', '腾讯云', 'heroku', 'vercel', 'vps', '主机', 'cdn', '域名'],
            '健康': ['健康', '医院', '医保', '健身', 'medical', 'health', '体检', '疫苗'],
            '政府': ['政府', '社保', '公积金', '税务', 'gov', '政务', '国家', '图书馆', '医保', '公安部', '交管'],
            '翻译': ['翻译', 'deepl', 'translate', '词典', '字典', 'dictionary'],
            '竞赛': ['竞赛', '比赛', '大赛', '蓝桥', '大创', 'cvpr', 'acm', '挑战杯', 'kaggle'],
            '网盘': ['网盘', '云盘', '百度网盘', '阿里云盘', '坚果云', 'dropbox', 'onedrive', 'icloud'],
        }
        preview_items = []
        for item in context_items:
            name = (repo.get_display_name(item) or '').lower()
            if not name:
                continue
            old_cat = repo.get_field_value(item, 'category') or '其他'
            new_cat = None
            for cat, keywords in category_keywords.items():
                if any(kw in name for kw in keywords):
                    new_cat = cat
                    break
            if new_cat and new_cat != old_cat:
                tid = item.id if hasattr(item, 'id') else item.get('id')
                preview_items.append({
                    "target_id": tid,
                    "app_name": repo.get_display_name(item),
                    "field": "category",
                    "old_value": old_cat,
                    "new_value": new_cat,
                    "reason": "本地关键词匹配"
                })
        return preview_items
    
    def build_action_preview(self, action: str, params: dict,
                             context_items: List[Any] = None,
                             vault_type: str = 'accounts') -> Dict:
        """
        Build 模式：生成结构化操作预览。
        
        Args:
            action: 动作类型
            params: 动作参数
            context_items: 当前上下文条目列表
            vault_type: 'accounts' 或 'urls'
            
        Returns:
            {
                "success": bool,
                "action": str,
                "preview_items": [...],
                "affected_count": int,
                "action_type": str,
                "message": str,
                "vault_type": str
            }
        """
        repo = RepositoryFactory.get_repository(vault_type)
        
        if context_items is None:
            context_items = repo.get_all()
        
        item_map = {item.id: item for item in context_items}
        preview_items = []
        affected_count = 0
        item_type_name = repo.get_item_type_name()
        
        if action == 'reorganize':
            changes = params.get('changes', [])
            if changes:
                for change in changes:
                    tid = change.get('target_id')
                    field = change.get('field', 'category')
                    new_val = change.get('new_value', '')
                    reason = change.get('reason', '')
                    item = item_map.get(tid)
                    if item is None:
                        continue
                    old_val = repo.get_field_value(item, field) or ''
                    preview_items.append({
                        "target_id": tid,
                        "app_name": repo.get_display_name(item),
                        "field": field,
                        "old_value": old_val,
                        "new_value": new_val,
                        "reason": reason
                    })
                affected_count = len(preview_items)
            else:
                # 模型未返回结构化 changes（数据量过大时常见），本地启发式兜底
                preview_items = self._heuristic_reorganize(context_items, repo)
                affected_count = len(preview_items)
        
        elif action == 'add_remark':
            changes = params.get('changes', [])
            if changes:
                for change in changes:
                    tid = change.get('target_id')
                    field = change.get('field', 'ai_remark')
                    new_val = change.get('new_value', '')
                    item = item_map.get(tid)
                    if item is None:
                        continue
                    old_val = repo.get_field_value(item, field) or ''
                    preview_items.append({
                        "target_id": tid,
                        "app_name": repo.get_display_name(item),
                        "field": field,
                        "old_value": old_val,
                        "new_value": new_val
                    })
                affected_count = len(preview_items)
            else:
                target_ids = params.get('target_ids', [])
                remark = params.get('remark', '')
                for tid in target_ids:
                    item = item_map.get(tid)
                    if item is None:
                        continue
                    old_val = repo.get_field_value(item, 'ai_remark') or ''
                    preview_items.append({
                        "target_id": tid,
                        "app_name": repo.get_display_name(item),
                        "field": "ai_remark",
                        "old_value": old_val,
                        "new_value": remark
                    })
                affected_count = len(preview_items)
        
        elif action == 'delete':
            target_ids = params.get('target_ids', [])
            item_type = params.get('item_type', 'account')
            
            # 如果模型返回的是条件而非具体 ID
            if not target_ids and 'filter_conditions' in params:
                conditions = params['filter_conditions']
                target_ids = repo.resolve_filter_conditions(conditions)
                params['target_ids'] = target_ids  # 回写
            
            for tid in target_ids:
                item = item_map.get(tid)
                if item:
                    preview_items.append({
                        "target_id": tid,
                        "item_type": item_type,
                        "app_name": repo.get_display_name(item),
                        "username": repo.get_secondary_info(item),
                        "category": repo.get_field_value(item, 'category'),
                        "impact": f"将从{item_type}库中删除，移入回收站保留30天"
                    })
            affected_count = len(preview_items)
        
        elif action == 'add':
            fields = params.get('fields', {})
            item_type = params.get('item_type', 'account')
            preview_items.append({
                "type": "add",
                "item_type": item_type,
                "fields": fields,
                "impact": f"新增到{item_type}库"
            })
            affected_count = 1
        
        elif action in ('batch_add_account', 'batch_add_url'):
            raw_items = params.get('items', [])
            from services.batch_add_processor import BatchAddProcessor
            batch_items = BatchAddProcessor.prepare_batch_items(raw_items, repo)
            for bi in batch_items:
                preview_items.append({
                    "type": "batch_add",
                    "batch_item": bi,
                    "display_name": bi.app if action == 'batch_add_account' else bi.title,
                    "impact": f"新增到{'账号' if action == 'batch_add_account' else '网址'}库"
                })
            affected_count = len(batch_items)
        
        return {
            "success": True,
            "action": action,
            "preview_items": preview_items,
            "affected_count": affected_count,
            "action_type": action,
            "vault_type": vault_type,
            "message": f"操作预览：将影响 {affected_count} 个{item_type_name}，请确认后执行。"
        }
    
    def build_action_preview_from_tool_result(self, tool_result: ToolResult, tool: AITool) -> Dict:
        """
        将 Tool 返回的 preview_data 封装为 UI 可用的预览结构。

        做格式校验和默认值填充。
        """
        preview_data = tool_result.preview_data or {}

        # 校验必填字段
        if "operation_type" not in preview_data:
            preview_data["operation_type"] = "unknown"
        if "target_vault" not in preview_data:
            preview_data["target_vault"] = "unknown"
        if "total_items" not in preview_data:
            preview_data["total_items"] = 0
        if "items" not in preview_data or not isinstance(preview_data["items"], list):
            preview_data["items"] = []

        validated_items = []
        for item in preview_data["items"]:
            if not isinstance(item, dict):
                continue
            validated_item = {
                "row_id": str(item.get("row_id", "")),
                "display_name": item.get("display_name", "未命名"),
                "secondary_name": item.get("secondary_name", ""),
                "fields": item.get("fields", []) if isinstance(item.get("fields"), list) else [],
                "raw_data": item.get("raw_data", {}) if isinstance(item.get("raw_data"), dict) else {}
            }
            validated_items.append(validated_item)

        preview_data["items"] = validated_items
        preview_data["total_items"] = len(validated_items)

        return {
            "preview_data": preview_data,
            "tool_name": tool.name,
            "tool_description": tool.description,
            "permission": tool.permission.value if hasattr(tool.permission, 'value') else str(tool.permission),
            "message": tool_result.message or f"{tool.name} 操作预览",
            "success": tool_result.success
        }
    
    def execute_action(self, action: str, params: dict,
                        context_items: List[Any] = None,
                        vault_type: str = 'accounts',
                        mode: str = 'plan') -> Dict:
        """
        在本地执行 AI 建议的动作（不涉及敏感操作，敏感操作需弹窗确认）
        
        Args:
            action: 动作类型
            params: 动作参数
            context_items: 当前上下文条目列表
            vault_type: 'accounts' 或 'urls'
            mode: 'plan' 或 'build'
            
        Returns:
            执行结果
        """
        repo = RepositoryFactory.get_repository(vault_type)
        
        if context_items is None:
            context_items = repo.get_all()
        
        # Plan 模式：batch_add 特殊处理（解析后降级为 explain）
        if mode == 'plan' and action in ('batch_add_account', 'batch_add_url'):
            text = params.get('text', '')
            vault_type_for_batch = 'accounts' if action == 'batch_add_account' else 'urls'
            parsed_items = []
            failed_chunks = []
            if text:
                try:
                    from services.batch_add_processor import BatchAddProcessor
                    from ai.ollama_client import OllamaClient
                    from services.ai_service_manager import AIServiceManager
                    ai_manager = AIServiceManager.instance()
                    if ai_manager.is_available():
                        ollama = OllamaClient(model=ai_manager.get_state().model_name or "gemma4:4b")
                        parsed_items, failed_chunks = BatchAddProcessor.parse_batch_text(text, vault_type_for_batch, ollama)
                except Exception:
                    logger.warning("批量添加文本解析失败", exc_info=True)
            if not parsed_items:
                parsed_items = params.get('items', [])
            
            item_names = [item.get('app') or item.get('title', '未知') for item in parsed_items]
            msg = f"解析到 {len(parsed_items)} 条待导入数据"
            if item_names:
                msg += "：" + "、".join(item_names)
            msg += "\n\n💡 切换到 Build 模式可执行导入。"
            
            return {
                "success": True,
                "action": "explain",
                "matched_accounts": [],
                "message": msg,
                "is_preview": False,
                "parsed_items": parsed_items,
                "failed_chunks": failed_chunks
            }
        
        # Plan 模式：拒绝写操作
        if mode == 'plan' and action not in self.READONLY_ACTIONS:
            return {
                "success": False,
                "action": action,
                "matched_accounts": [],
                "message": f"Plan 模式下不能执行写操作「{action}」，请切换到 Build 模式。",
                "is_preview": False
            }
        
        # Build 模式：写操作返回结构化预览
        if mode == 'build' and action in self.WRITE_ACTIONS:
            preview = self.build_action_preview(action, params, context_items, vault_type)
            preview['is_preview'] = True
            return preview
        
        result = {
            "success": True,
            "action": action,
            "matched_accounts": [],
            "message": "",
            "is_preview": False
        }
        
        if action == 'search':
            keywords = params.get('keywords', [])
            if isinstance(keywords, str):
                keywords = [keywords]
            keywords = [kw for kw in keywords if kw and str(kw).strip()]
            
            search_result = repo.search(keywords)
            result["matched_accounts"] = search_result.items
            result["matched_ids"] = search_result.matched_ids
            result["message"] = f"找到 {len(search_result.items)} 个匹配的{repo.get_item_type_name()}"
        
        elif action == 'filter':
            if 'category' in params:
                search_result = repo.filter_by_category(params['category'])
            elif 'tag' in params:
                search_result = repo.filter_by_tags(params['tag'])
            else:
                from core.repositories import SearchResult
                search_result = SearchResult(context_items, [i.id for i in context_items], "全部")
            
            result["matched_accounts"] = search_result.items
            result["matched_ids"] = search_result.matched_ids
            result["message"] = f"筛选出 {len(search_result.items)} 个{repo.get_item_type_name()}"
        
        elif action == 'get_category_tree':
            item_type = params.get('item_type', 'account')
            tree = self.tool_get_category_tree(item_type)
            if tree:
                tree_lines = []
                for k, v in tree.items():
                    if v:
                        tree_lines.append(f"• {k} → {', '.join(v)}")
                    else:
                        tree_lines.append(f"• {k}")
                result["message"] = f"当前{item_type}库分类树：\n" + "\n".join(tree_lines)
            else:
                result["message"] = "暂无分类"
        
        elif action == 'list':
            if params.get('scope') == 'uncategorized':
                search_result = repo.get_uncategorized()
            else:
                from core.repositories import SearchResult
                search_result = SearchResult(context_items, [i.id for i in context_items], "全部")
            
            result["matched_accounts"] = search_result.items
            result["matched_ids"] = search_result.matched_ids
            result["message"] = search_result.query_description
        
        elif action == 'reorganize':
            changes = params.get('changes', [])
            if changes:
                result["message"] = f"整理建议：共 {len(changes)} 条分类调整"
            else:
                suggestions = params.get('suggestions', [])
                result["message"] = "整理建议：" + '\n'.join(f"• {s}" for s in suggestions) if suggestions else "暂无具体建议"
        
        elif action == 'add_remark':
            target_ids = params.get('target_ids', [])
            remark = params.get('remark', '')
            result["message"] = f"建议给 {len(target_ids)} 个{repo.get_item_type_name()}添加备注：{remark}"
        
        else:  # explain
            result["message"] = params.get('response', '') or '已收到您的指令。'
        
        return result
    
    def execute_build_action_with_transaction(self, confirmed_items=None, tool_name=None, user_query="", _force=False):
        """
        Build 模式：在 SQLite 事务中批量执行写操作，并写入审计日志。

        兼容两种调用方式：
        1. 新签名：execute_build_action_with_transaction(confirmed_items, tool_name, user_query, _force)
        2. 旧签名：execute_build_action_with_transaction(action_preview: dict, user_query: str = "")
        """
        # 兼容旧签名
        if isinstance(confirmed_items, dict) and tool_name is None:
            return self._execute_build_action_with_transaction_legacy(confirmed_items, user_query)

        # 新签名逻辑
        if not confirmed_items:
            return {
                "success": False,
                "affected_count": 0,
                "affected_ids": [],
                "transaction_id": "",
                "error": "没有可执行的操作项"
            }

        transaction_id = str(uuid.uuid4())[:8]
        affected_ids = []
        error_msg = None
        fail_ids = []
        success = True
        result_msg = ""

        logger.info("execute_build_action_with_transaction starting, items=%d, tool=%s", len(confirmed_items), tool_name)

        if tool_name in ('batch_add_accounts', 'batch_add_urls'):
            vault_type = 'accounts' if tool_name == 'batch_add_accounts' else 'urls'
            repo = RepositoryFactory.get_repository(vault_type)
            for item in confirmed_items:
                try:
                    if vault_type == 'accounts':
                        account = Account(**item)
                        new_id = repo.insert(account.to_dict())
                    else:
                        url_item = URLItem(**item)
                        new_id = repo.insert(url_item.to_dict())
                    affected_ids.append(new_id)
                except Exception as e:
                    logger.exception("Batch add item failed")
                    fail_ids.append((item, str(e)))
            success = len(fail_ids) == 0
            result_msg = f"批量导入完成：成功 {len(affected_ids)} 条" + (f"，失败 {len(fail_ids)} 条" if fail_ids else "")
            logger.info("Batch add completed, success=%d", len(affected_ids))

        elif tool_name in ('batch_update_accounts', 'batch_update_urls',
                           'batch_reorganize_accounts', 'batch_reorganize_urls',
                           'batch_add_remark_accounts', 'batch_add_remark_urls',
                           'batch_add_tags_accounts', 'batch_add_tags_urls',
                           'smart_classify_accounts', 'smart_classify_urls'):
            vault_type = 'accounts' if tool_name.endswith('_accounts') else 'urls'
            repo = RepositoryFactory.get_repository(vault_type)
            for item in confirmed_items:
                try:
                    if 'updates' in item:
                        target_id = item.get('target_id')
                        for field, value in item['updates'].items():
                            repo.update_field(target_id, field, value)
                        affected_ids.append(target_id)
                    elif 'field' in item and 'new_value' in item:
                        target_id = item.get('target_id')
                        repo.update_field(target_id, item['field'], item['new_value'])
                        affected_ids.append(target_id)
                    elif 'remark_type' in item and 'content' in item:
                        target_id = item.get('target_id')
                        repo.update_field(target_id, item['remark_type'], item['content'])
                        affected_ids.append(target_id)
                    elif 'tags' in item and 'mode' in item:
                        target_id = item.get('target_id')
                        existing = repo.get_by_id(target_id)
                        if existing:
                            old_tags = repo.get_field_value(existing, 'tags') or []
                            if not isinstance(old_tags, list):
                                try:
                                    old_tags = json.loads(old_tags) if old_tags else []
                                except:
                                    old_tags = []
                            if item['mode'] == 'append':
                                new_tags = list(set(old_tags + item['tags']))
                            else:
                                new_tags = item['tags']
                            repo.update_field(target_id, 'tags', new_tags)
                        affected_ids.append(target_id)
                    else:
                        # 通用 raw_data 处理
                        target_id = item.get('target_id')
                        if target_id:
                            for field in ['category', 'remark', 'ai_remark', 'tags']:
                                if field in item:
                                    repo.update_field(target_id, field, item[field])
                            affected_ids.append(target_id)
                except Exception as e:
                    logger.exception("Batch update item failed")
                    fail_ids.append((item, str(e)))
            success = len(fail_ids) == 0
            result_msg = f"批量更新完成：成功 {len(affected_ids)} 条" + (f"，失败 {len(fail_ids)} 条" if fail_ids else "")
            logger.info("Batch update completed, success=%d", len(affected_ids))

        elif tool_name in ('batch_delete_accounts', 'batch_delete_urls'):
            if len(confirmed_items) > 50 and not _force:
                return {
                    "success": False,
                    "needs_confirmation": True,
                    "affected_count": len(confirmed_items),
                    "message": f"即将删除 {len(confirmed_items)} 条记录，数量较多，请确认",
                    "preview": {"items": confirmed_items}
                }

            for item in confirmed_items:
                try:
                    target_id = item.get('target_id')
                    if tool_name == 'batch_delete_accounts':
                        original = self.db.get_account_by_id(target_id)
                        if original:
                            self.db.soft_delete_account(target_id, original)
                    else:
                        original = self.db.get_url_by_id(target_id)
                        if original:
                            # 网址库独立回收站
                            if self.url_db:
                                self.url_db.soft_delete_url(target_id, original)
                            else:
                                self.db.soft_delete_url(target_id, original)
                    affected_ids.append(target_id)
                except Exception as e:
                    logger.exception("Batch delete item failed")
                    fail_ids.append((item, str(e)))
            success = len(fail_ids) == 0
            result_msg = f"删除完成：成功 {len(affected_ids)} 条" + (f"，失败 {len(fail_ids)} 条" if fail_ids else "")
            logger.info("Delete completed, success=%d", len(affected_ids))

        else:
            return {
                "success": False,
                "affected_count": 0,
                "affected_ids": [],
                "transaction_id": "",
                "error": f"不支持的 tool_name: {tool_name}"
            }

        # 写入审计日志
        try:
            self.db.insert_audit_log(
                mode='build',
                user_query=user_query,
                parsed_action=tool_name,
                parsed_params={"tool_name": tool_name, "count": len(confirmed_items)},
                affected_count=len(affected_ids),
                affected_ids=affected_ids,
                result=result_msg,
                error_message=error_msg,
                transaction_id=transaction_id
            )
        except Exception as e:
            logger.error("写入审计日志失败: %s", e)

        return {
            "success": success,
            "affected_count": len(affected_ids),
            "affected_ids": affected_ids,
            "transaction_id": transaction_id,
            "result_msg": result_msg,
            "error": error_msg or "",
            "fail_ids": fail_ids
        }

    def _execute_build_action_with_transaction_legacy(self, action_preview: dict, user_query: str = "") -> Dict:
        """
        旧版 execute_build_action_with_transaction 实现（兼容保留）。
        """
        preview_items = action_preview.get('preview_items', [])
        action_type = action_preview.get('action_type', '')
        vault_type = action_preview.get('vault_type', 'accounts')

        if action_type in ('reorganize', 'add_remark'):
            executable_items = [item for item in preview_items if 'target_id' in item and 'field' in item]
        elif action_type == 'delete':
            executable_items = [item for item in preview_items if 'target_id' in item and 'item_type' in item]
        elif action_type == 'add':
            executable_items = [item for item in preview_items if item.get('type') == 'add']
        elif action_type in ('batch_add_account', 'batch_add_url'):
            executable_items = [item for item in preview_items if item.get('type') == 'batch_add']
        else:
            executable_items = []

        if not executable_items:
            return {
                "success": False,
                "affected_count": 0,
                "affected_ids": [],
                "transaction_id": "",
                "error": "没有可执行的操作项"
            }

        transaction_id = str(uuid.uuid4())[:8]
        affected_ids = []
        error_msg = None
        fail_ids = []

        logger.info("execute_build_action_with_transaction starting, items=%d, vault=%s", len(executable_items), vault_type)

        if action_type == 'delete':
            if not action_preview.get('_force'):
                target_ids = [item['target_id'] for item in executable_items]

                if len(target_ids) > 50:
                    return {
                        "success": False,
                        "needs_confirmation": True,
                        "affected_count": len(target_ids),
                        "message": f"即将删除 {len(target_ids)} 条记录，数量较多，请确认",
                        "preview": action_preview
                    }

            for item in executable_items:
                target_id = item['target_id']
                item_vault_type = 'urls' if item.get('item_type') == 'url' else 'accounts'
                try:
                    repo = RepositoryFactory.get_repository(item_vault_type)
                    repo.soft_delete(target_id)
                    affected_ids.append(target_id)
                except Exception as e:
                    fail_ids.append((target_id, str(e)))

            success = len(fail_ids) == 0
            result_msg = f"删除完成：成功 {len(affected_ids)} 条" + (f"，失败 {len(fail_ids)} 条" if fail_ids else "")
            logger.info("Delete completed, success=%d, fail=%d", len(affected_ids), len(fail_ids))
        elif action_type in ('batch_add_account', 'batch_add_url'):
            repo = RepositoryFactory.get_repository(vault_type)
            from services.batch_add_processor import BatchAddProcessor
            batch_items = [item['batch_item'] for item in executable_items]
            batch_result = BatchAddProcessor.execute_batch_add(batch_items, repo)
            affected_ids = batch_result.get('inserted_ids', [])
            success = batch_result.get('success', 0) > 0 or len(affected_ids) > 0
            result_msg = f"批量导入完成：成功 {batch_result.get('success', 0)} 条，跳过 {batch_result.get('skip', 0)} 条，失败 {batch_result.get('fail', 0)} 条"
            logger.info("Batch add completed, success=%s", batch_result.get('success', 0))
        else:
            repo = RepositoryFactory.get_repository(vault_type)
            item_type_name = repo.get_item_type_name()

            for item in executable_items:
                try:
                    if action_type in ('reorganize', 'add_remark'):
                        target_id = item['target_id']
                        field = item['field']
                        new_value = item['new_value']
                        logger.debug("UPDATE id=%s, field=%s, new_value=%s", target_id, field, new_value)
                        repo.update_field(target_id, field, new_value)
                        affected_ids.append(target_id)

                    elif action_type == 'add':
                        fields = item['fields']
                        new_id = repo.insert(fields)
                        affected_ids.append(new_id)

                except Exception as e:
                    tid = item.get('target_id', item.get('fields', {}).get('app_name', 'unknown'))
                    logger.exception("Item execution failed: %s, error=%s", tid, e)
                    fail_ids.append((tid, str(e)))

            success = len(fail_ids) == 0
            result_msg = f"成功执行 {action_type}，共影响 {len(affected_ids)} 个{item_type_name}"
            if fail_ids:
                result_msg += f"，失败 {len(fail_ids)} 条"
            logger.info("Execution completed, success=%d, fail=%d", len(affected_ids), len(fail_ids))

        # 写入审计日志
        try:
            self.db.insert_audit_log(
                mode='build',
                user_query=user_query,
                parsed_action=action_type,
                parsed_params=action_preview,
                affected_count=len(affected_ids),
                affected_ids=affected_ids,
                result=result_msg,
                error_message=error_msg,
                transaction_id=transaction_id
            )
        except Exception as e:
            logger.error("写入审计日志失败: %s", e)

        return {
            "success": success,
            "affected_count": len(affected_ids),
            "affected_ids": affected_ids,
            "transaction_id": transaction_id,
            "result_msg": result_msg,
            "error": error_msg or "",
            "fail_ids": fail_ids
        }
    
    def tool_get_category_tree(self, item_type: str) -> dict:
        """获取当前分类树结构（供 AI 工具调用）"""
        from core.category_utils import build_category_tree
        if item_type == 'account':
            cats = self.db.get_categories() if self.db else []
        else:
            cats = self.url_db.get_categories() if self.url_db else []
        tree = build_category_tree([c for c in cats if c != '全部'])
        return {k: sorted(v.get('children', set())) for k, v in tree.items()}
    
    def _add_message(self, role: str, content: str, mode: str = 'plan', thinking: str = "", action: str = ""):
        """添加消息到历史"""
        msg = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            thinking=thinking,
            action=action
        )
        if mode == 'plan':
            self._history.append(msg)
            if len(self._history) > self._max_history * 2:
                self._history = self._history[-self._max_history * 2:]
        else:
            self._history_build.append(msg)
            if len(self._history_build) > self._max_history * 2:
                self._history_build = self._history_build[-self._max_history * 2:]
    
    def get_history(self, mode: str = 'plan') -> List[ConversationMessage]:
        """获取对话历史"""
        if mode == 'plan':
            return self._history.copy()
        return self._history_build.copy()
    
    def clear_history(self, mode: str = 'plan'):
        """清空对话历史"""
        if mode == 'plan':
            self._history.clear()
        elif mode == 'build':
            self._history_build.clear()
    
    def get_stats(self) -> Dict:
        """获取数据库统计信息（用于快速展示）"""
        accounts_data = self.db.get_all_accounts()
        accounts = [Account.from_dict(data) for data in accounts_data]
        
        total = len(accounts)
        categories = {}
        uncategorized = 0
        
        for acc in accounts:
            cat = acc.category or '未分类'
            if cat in ('其他', '未分类', ''):
                uncategorized += 1
            categories[cat] = categories.get(cat, 0) + 1
        
        return {
            "total": total,
            "categories": categories,
            "uncategorized": uncategorized,
            "top_category": max(categories, key=categories.get) if categories else None
        }
