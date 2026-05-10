import logging
from typing import List, Dict
from datetime import datetime

from services.assistant.models import ConversationMessage
from models.account import Account

logger = logging.getLogger(__name__)


class HistoryMixin:
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
