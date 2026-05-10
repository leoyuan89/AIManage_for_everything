"""AIInputEdit - AI 输入框：Enter 发送，Shift+Enter 换行"""
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtCore import Qt, pyqtSignal
from core.theme_manager import ThemeManager

class AIInputEdit(QTextEdit):
    """AI 输入框：Enter 发送，Shift+Enter 换行，最多显示5行"""
    def __init__(self, parent=None, send_callback=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self.send_callback = send_callback
        self.setPlaceholderText("输入指令，如：查找支付类账号")
        # 最小高度约1行，最大高度约5行
        self.setMinimumHeight(40)
        self.setMaximumHeight(110)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                line-height: 1.4;
            }}
        """)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    
    def keyPressEvent(self, event):
        colors = ThemeManager.instance().colors
        if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Enter（不带Shift）→ 发送
            if self.send_callback:
                self.send_callback()
            return
        super().keyPressEvent(event)
