"""
对话上下文管理器
用于多轮上下文对话与意图继承
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Set, List, Dict
import time
import re


@dataclass
class TurnSnapshot:
    """单轮对话快照"""
    user_input: str
    parsed_action: str
    params_summary: str
    ai_reply_summary: str
    plan_entity_ids: Optional[Set[int]] = None
    build_entity_refs: Optional[List[Dict]] = None
    vault_type: str = 'accounts'
    timestamp: float = field(default_factory=time.time)


class ConversationContext:
    """对话上下文管理器，维护多轮对话状态"""

    def __init__(self, max_turns=6, idle_timeout=300):
        self.history: deque[TurnSnapshot] = deque(maxlen=max_turns)
        self.last_active_timestamp = time.time()
        self.idle_timeout = idle_timeout
        self.current_vault_type: Optional[str] = None

    def reset(self):
        """重置对话上下文"""
        self.history.clear()
        self.last_active_timestamp = time.time()
        self.current_vault_type = None

    def is_expired(self) -> bool:
        """检查上下文是否因空闲超时而过期"""
        return time.time() - self.last_active_timestamp > self.idle_timeout

    def append_turn(self, snapshot: TurnSnapshot):
        """追加一轮对话快照"""
        self.history.append(snapshot)
        self.last_active_timestamp = time.time()
        self.current_vault_type = snapshot.vault_type

    def get_recent_entities(self, turn_offset: int = 1) -> Set[int]:
        """获取最近某一轮涉及的实体 ID 集合"""
        if len(self.history) < turn_offset:
            return set()
        turn = list(self.history)[-turn_offset]
        ids = set()
        if turn.plan_entity_ids:
            ids.update(turn.plan_entity_ids)
        if turn.build_entity_refs:
            ids.update(ref.get('id') for ref in turn.build_entity_refs if ref.get('id'))
        return ids

    def serialize_for_prompt(self, max_chars=2000) -> str:
        """将对话历史序列化为 Prompt 可用的字符串"""
        lines = []
        total = len(self.history)
        for idx, turn in enumerate(self.history, 1):
            if total - idx < 2:
                detail = f"用户: {turn.user_input[:80]} | AI: {turn.ai_reply_summary[:80]}"
            else:
                detail = f"动作: {turn.parsed_action}"
            entity_info = f"实体: {list(turn.plan_entity_ids or [])[:5]}" if turn.plan_entity_ids else ""
            lines.append(f"第{idx}轮({turn.vault_type}): {detail} {entity_info}")

        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[-max_chars:]
            first_idx = result.find("第")
            if first_idx > 0:
                result = result[first_idx:]
        return result

    def get_compressed_history(self, total_chars_threshold: int = 2000) -> str:
        """
        获取自适应压缩后的对话历史。
        
        自适应压缩规则：
        - 历史总字符 > 2000：仅保留最近 3 轮
        - 历史总字符 > 3000：仅保留最近 2 轮极简格式
        """
        if not self.history:
            return ""

        full_serialized = self.serialize_for_prompt(max_chars=99999)
        total_chars = len(full_serialized)

        if total_chars > 3000:
            # 极简格式：仅保留最近 2 轮
            lines = []
            for turn in list(self.history)[-2:]:
                entity_ids = list(turn.plan_entity_ids or [])[:5]
                lines.append(f"({turn.parsed_action}, {entity_ids})")
            return "历史: " + " -> ".join(lines)

        elif total_chars > 2000:
            # 保留最近 3 轮，详细格式
            lines = []
            total = len(self.history)
            for idx, turn in enumerate(list(self.history)[-3:], max(1, total - 2)):
                detail = f"用户: {turn.user_input[:80]} | AI: {turn.ai_reply_summary[:80]}"
                entity_info = f"实体: {list(turn.plan_entity_ids or [])[:5]}" if turn.plan_entity_ids else ""
                lines.append(f"第{idx}轮({turn.vault_type}): {detail} {entity_info}")
            return "\n".join(lines)

        return full_serialized


class ReferenceResolver:
    """指代消解预处理器，检测用户输入中的指代/省略表达并解析"""

    PRONOUNS = {'这些', '那些', '它们', '他们', '她们', '这个', '那个',
                '刚才', '之前', '上面', '下边', '前面'}
    OMISSION_PATTERNS = [
        r'^删除[吧呢]?$',
        r'^删掉[吧呢]?$',
        r'^修改分类[吧呢]?$',
        r'^确认[吧呢]?$',
        r'^好的[吧呢]?$',
        r'^执行[吧呢]?$',
        r'^同意[吧呢]?$',
    ]

    @staticmethod
    def _sanitize_query(query: str) -> str:
        """去除可能导致 Prompt 注入的特殊标签"""
        import re
        # 去除 XML 标签样式的内容
        query = re.sub(r'<[^>]+>', '', query)
        # 去除控制字符
        query = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', query)
        return query.strip()

    @classmethod
    def resolve(cls, query: str, context: ConversationContext) -> tuple[str, Optional[Set[int]]]:
        """
        解析用户查询中的指代和省略表达。
        
        Returns:
            (enhanced_query, inherited_ids)
            - enhanced_query: 增强后的查询（包含系统提示）
            - inherited_ids: 继承的实体 ID 集合（若无则为 None）
        """
        query = query.strip()
        query = cls._sanitize_query(query)
        has_pronoun = any(p in query for p in cls.PRONOUNS)
        is_omission = any(re.match(pat, query) for pat in cls.OMISSION_PATTERNS)

        if not (has_pronoun or is_omission):
            return query, None

        inherited_ids = context.get_recent_entities(turn_offset=1)
        if not inherited_ids:
            return query, None

        scope_hint = f"[系统提示：用户使用了指代/省略表达，当前作用域包含 ID: {sorted(inherited_ids)}]"
        enhanced_query = f"{scope_hint}\n用户输入：{query}"
        return enhanced_query, inherited_ids
