"""AIChatRenderer - 渲染 AI 聊天消息"""
import re
from core.theme_manager import ThemeManager


class AIChatRenderer:
    """负责 AI 聊天内容的 Markdown/HTML 渲染"""

    def escape_html(self, text: str) -> str:
        """转义 HTML 特殊字符"""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    def welcome_md(self, vault: str) -> str:
        """欢迎语 Markdown（根据当前库切换内容）"""
        if vault == 'accounts':
            return (
                "🦁🔥 **密码库模式**\n\n"
                "炽阳 已觉醒\n\n"
                "你好，狮子座的主人。\n\n"
                "⚡ **首次同步**：请发送任意消息完成神经连接预热，预热完成后即可执行操作。"
            )
        else:
            return (
                "🦁🔥 **网址库模式**\n\n"
                "炽阳 已觉醒\n\n"
                "你好，狮子座的主人。\n\n"
                "⚡ **首次同步**：请发送任意消息完成神经连接预热，预热完成后即可执行操作。"
            )

    def render_user_md(self, text: str) -> str:
        """渲染用户消息（Markdown）"""
        # 用户消息用引用块显示在右侧
        lines = text.strip().split('\n')
        quoted = '\n'.join(f'> {line}' for line in lines)
        return f"**用户**：\n\n{quoted}"

    def render_assistant_md(self, msg, msg_index: int, is_last: bool = False,
                            thinking_expanded: dict = None, last_elapsed: float = 0) -> str:
        """渲染 AI 消息（Markdown）—— 思考过程在回答上方，可展开/折叠"""
        parts = []
        thinking_expanded = thinking_expanded or {}

        # 思考过程（放在回答上方，参考图3 Thinking 风格；如果和回复重复则不显示）
        if msg.thinking and msg.thinking.strip() and not self.thinking_is_redundant(msg.thinking, msg.content):
            expanded = thinking_expanded.get(msg_index, False)
            if expanded:
                thinking_lines = msg.thinking.strip().split('\n')
                quoted = '\n'.join(f'> {line}' for line in thinking_lines)
                parts.append(f"> 💡 [思考过程 ▲](thinking://{msg_index})\n>\n{quoted}")
            else:
                parts.append(f"> 💡 [思考过程 ▼](thinking://{msg_index})")

        parts.append(f"**🦁 炽阳**：\n")
        parts.append(msg.content)

        # 最后一条消息显示回答用时
        if is_last and last_elapsed > 0:
            parts.append(f"\n_⏱️ 用时 {last_elapsed:.1f}s_")

        return '\n\n'.join(parts)

    def thinking_is_redundant(self, thinking: str, response: str) -> bool:
        """Check if thinking content is redundant with the response (same information)"""
        if not thinking or not response:
            return False
        # Normalize: strip whitespace, lowercase
        t = thinking.strip().lower()
        r = response.strip().lower()
        # If thinking is entirely contained in response, it's redundant
        if t in r:
            return True
        # If response is entirely contained in thinking, it's redundant
        if r in t:
            return True
        # If more than 70% of lines overlap
        t_lines = set(line.strip() for line in thinking.strip().split('\n') if line.strip())
        r_lines = set(line.strip() for line in response.strip().split('\n') if line.strip())
        if t_lines and r_lines:
            overlap = len(t_lines & r_lines)
            if overlap / min(len(t_lines), len(r_lines)) > 0.7:
                return True
        return False

    def markdown_to_html(self, text: str) -> str:
        """将 Markdown 转为 HTML（安全可控，避免 Qt setMarkdown 崩溃）"""
        colors = ThemeManager.instance().colors
        import re

        # 安全清理：移除 NULL 字节和控制字符（这些可能导致 Qt 解析器崩溃）
        text = text.replace('\x00', '')
        text = ''.join(ch if ord(ch) >= 32 or ch in '\n\r\t' else ' ' for ch in text)

        # 先转义 HTML 特殊字符
        text = (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

        # 代码块 ```code```
        def code_block_repl(m):
            colors = ThemeManager.instance().colors
            code = m.group(1)
            return f'<pre style="background:{colors.bg_secondary};padding:8px;border-radius:4px;overflow-x:auto;font-size:12px;"><code>{code}</code></pre>'
        text = re.sub(r'```(.*?)```', code_block_repl, text, flags=re.DOTALL)

        # 行内代码 `code`
        text = re.sub(r'`([^`]+)`', rf'<code style="background:{colors.bg_secondary};padding:2px 4px;border-radius:3px;font-size:12px;">\1</code>', text)

        # 加粗 **text**
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)

        # 斜体 *text*（避免匹配已处理的 **）
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)

        # 标题
        text = re.sub(r'^###\s+(.+)$', rf'<h4 style="margin:6px 0;color:{colors.text_primary};">\1</h4>', text, flags=re.MULTILINE)
        text = re.sub(r'^##\s+(.+)$', rf'<h3 style="margin:8px 0;color:{colors.text_primary};">\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^#\s+(.+)$', rf'<h2 style="margin:10px 0;color:{colors.text_primary};">\1</h2>', text, flags=re.MULTILINE)

        # 分隔线 ---
        text = re.sub(r'^---+\s*$', rf'<hr style="border:none;border-top:1px solid {colors.border_default};margin:8px 0;">', text, flags=re.MULTILINE)

        # 链接 [text](url)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', rf'<a href="\2" style="color:{colors.accent_orange};text-decoration:none;">\1</a>', text)

        # 列表项 - item
        def list_repl(m):
            items = m.group(0).strip().split('\n')
            lis = ''.join(f'<li style="margin:3px 0;">{item.lstrip("- ").strip()}</li>' for item in items)
            return f'<ul style="margin:6px 0;padding-left:18px;">{lis}</ul>'
        text = re.sub(r'(?:^-\s+.+\n?)+', list_repl, text, flags=re.MULTILINE)

        # 引用块 > text
        def quote_repl(m):
            colors = ThemeManager.instance().colors
            lines = m.group(0).strip().split('\n')
            content = '<br>'.join(line.lstrip('> ').strip() for line in lines)
            return f'<blockquote style="margin:6px 0;padding:6px 10px;border-left:3px solid {colors.accent_orange};color:{colors.text_secondary};background:{colors.ai_thinking_bg};border-radius:0 4px 4px 0;">{content}</blockquote>'
        text = re.sub(r'(?:^>\s*.+\n?)+', quote_repl, text, flags=re.MULTILINE)

        # 段落处理：保留换行
        paragraphs = text.split('\n\n')
        result = []
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            # 如果已经是块级元素，不加 p 包裹
            if p.startswith('<') and any(tag in p for tag in ['<pre', '<ul', '<blockquote', '<h', '<hr']):
                result.append(p)
            else:
                p = p.replace('\n', '<br>')
                result.append(f'<p style="margin:4px 0;">{p}</p>')

        return '\n'.join(result)
