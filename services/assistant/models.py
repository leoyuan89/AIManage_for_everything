from dataclasses import dataclass


@dataclass
class ConversationMessage:
    """对话消息"""
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    timestamp: str
    thinking: str = ""  # AI 的思考过程（仅 assistant 有）
    action: str = ""    # 解析后的动作（仅 assistant 有）
