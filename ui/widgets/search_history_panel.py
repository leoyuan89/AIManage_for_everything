"""SearchHistoryPanel - 搜索历史下拉面板（极简稳定版）"""
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout
)


class HistoryPill(QPushButton):
    """单条历史记录 pill"""
    delete_clicked = pyqtSignal(str)

    def __init__(self, text: str, edit_mode: bool = False, parent=None):
        super().__init__(text, parent)
        self._text = text
        self._edit_mode = edit_mode
        self._delete_pressed = False
        self.setFixedHeight(28)
        if edit_mode:
            self.setText(f"{text}  ×")

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = enabled
        self.setText(f"{self._text}  ×" if enabled else self._text)

    def mousePressEvent(self, event):
        if self._edit_mode:
            # 计算"文本  "的宽度，点击在其右侧则视为删除
            text_without_x = f"{self._text}  "
            fm = QFontMetrics(self.font())
            text_width = fm.horizontalAdvance(text_without_x)
            if event.pos().x() > text_width:
                self._delete_pressed = True
                self.delete_clicked.emit(self._text)
                event.accept()
                return
        self._delete_pressed = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._delete_pressed:
            self._delete_pressed = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SearchHistoryPanel(QWidget):
    """搜索历史下拉面板"""

    search_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    clear_all_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._edit_mode = False
        self._pills: List[HistoryPill] = []
        self._setup_ui()
        self.setVisible(False)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 标题行
        header = QHBoxLayout()
        self.lbl_title = QLabel("最近搜索")
        header.addWidget(self.lbl_title)
        header.addStretch()

        self.btn_trash = QPushButton("管理")
        self.btn_trash.setFixedSize(70, 24)
        self.btn_trash.clicked.connect(self._enter_edit_mode)
        header.addWidget(self.btn_trash)

        self.btn_delete_all = QPushButton("清空全部")
        self.btn_delete_all.setFixedSize(90, 24)
        self.btn_delete_all.setVisible(False)
        self.btn_delete_all.clicked.connect(self.clear_all_requested.emit)
        header.addWidget(self.btn_delete_all)

        self.btn_done = QPushButton("完成")
        self.btn_done.setFixedSize(70, 24)
        self.btn_done.setVisible(False)
        self.btn_done.clicked.connect(self._exit_edit_mode)
        header.addWidget(self.btn_done)

        layout.addLayout(header)

        # Pill 容器
        self.pills_container = QWidget()
        self.pills_layout = QGridLayout(self.pills_container)
        self.pills_layout.setContentsMargins(0, 0, 0, 0)
        self.pills_layout.setHorizontalSpacing(6)
        self.pills_layout.setVerticalSpacing(6)
        layout.addWidget(self.pills_container)

    def set_history(self, history: List[str]):
        for pill in self._pills:
            self.pills_layout.removeWidget(pill)
            pill.deleteLater()
        self._pills.clear()

        for idx, text in enumerate(history):
            pill = HistoryPill(text, self._edit_mode, self.pills_container)
            pill.clicked.connect(lambda checked, t=text: self.search_requested.emit(t))
            pill.delete_clicked.connect(self.delete_requested.emit)
            self.pills_layout.addWidget(pill, idx // 2, idx % 2)
            self._pills.append(pill)

        self.setVisible(len(self._pills) > 0)

    def _enter_edit_mode(self):
        self._edit_mode = True
        # 延迟切换按钮可见性，避免在 clicked 事件处理中直接隐藏被点击的按钮
        QTimer.singleShot(0, lambda: self.btn_trash.setVisible(False))
        QTimer.singleShot(0, lambda: self.btn_delete_all.setVisible(True))
        QTimer.singleShot(0, lambda: self.btn_done.setVisible(True))
        for pill in self._pills:
            pill.set_edit_mode(True)

    def _exit_edit_mode(self):
        self._edit_mode = False
        QTimer.singleShot(0, lambda: self.btn_trash.setVisible(True))
        QTimer.singleShot(0, lambda: self.btn_delete_all.setVisible(False))
        QTimer.singleShot(0, lambda: self.btn_done.setVisible(False))
        for pill in self._pills:
            pill.set_edit_mode(False)
