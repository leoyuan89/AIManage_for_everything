"""
AI 助手服务
提供自然语言指令解析、数据库摘要构建、对话历史管理
"""
import logging
from typing import List

logger = logging.getLogger(__name__)

from core.database import DatabaseManager
from models.account import Account

from services.assistant.models import ConversationMessage
from services.assistant.history_mixin import HistoryMixin
from services.assistant.action_mixin import ActionMixin
from services.assistant.query_mixin import QueryMixin


class AIAssistantService(HistoryMixin, ActionMixin, QueryMixin):
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
            if not urls and self.url_db:
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
    
    def tool_get_category_tree(self, item_type: str) -> dict:
        """获取当前分类树结构（供 AI 工具调用）"""
        from core.category_utils import build_category_tree
        if item_type == 'account':
            cats = self.db.get_categories() if self.db else []
        else:
            cats = self.url_db.get_categories() if self.url_db else []
        tree = build_category_tree([c for c in cats if c != '全部'])
        return {k: sorted(v.get('children', set())) for k, v in tree.items()}
