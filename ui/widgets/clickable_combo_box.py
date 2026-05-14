from PyQt6.QtWidgets import QComboBox, QLabel
from PyQt6.QtCore import Qt, QEvent
from core.theme_manager import ThemeManager


class ClickableComboBox(QComboBox):
    """可编辑 QComboBox，点击文本区域也弹出下拉列表
    
    解决 qt-material 主题下可编辑 QComboBox 下拉箭头 SVG 图标无法加载、
    点击文本区域无法弹出列表的问题。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().installEventFilter(self)
        colors = ThemeManager.instance().colors
        
        # 隐藏默认的 SVG 箭头，保留 drop-down 可点击区域
        self.setStyleSheet("""
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                image: none;
                width: 0px;
                height: 0px;
            }
        """)
        
        # 用 QLabel 绘制自定义箭头覆盖在右侧
        self._arrow = QLabel("▼", self)
        self._arrow.setStyleSheet(f"color: {colors.text_secondary}; font-size: 10px; background: transparent;")
        self._arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arrow.setFixedSize(20, 20)
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 箭头固定在右侧居中
        self._arrow.move(self.width() - 24, (self.height() - 20) // 2)
    
    def eventFilter(self, obj, event):
        if obj == self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            if not self.view().isVisible():
                self.showPopup()
        return super().eventFilter(obj, event)
