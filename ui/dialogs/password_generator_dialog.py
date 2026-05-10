"""
密码生成器设置弹窗
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QCheckBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.password_generator import generate_password
from core.theme_manager import ThemeManager
from core.icon_manager import IconManager
from core.icon_manager import IconManager


class PasswordGeneratorDialog(QDialog):
    """密码生成器设置弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowIcon(IconManager.app_icon())
        colors = ThemeManager.instance().colors

        self.setWindowTitle("密码生成器设置")
        self.setMinimumSize(420, 340)
        self.setMaximumSize(480, 380)

        self.generated_password = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(25, 20, 25, 20)

        # 标题
        lbl_title = QLabel("密码生成器设置")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        # 长度滑块
        length_layout = QHBoxLayout()
        length_layout.setSpacing(10)
        lbl_len = QLabel("密码长度：")
        lbl_len.setFixedWidth(80)
        length_layout.addWidget(lbl_len)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(8)
        self.slider.setMaximum(64)
        self.slider.setValue(16)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(4)
        self.slider.valueChanged.connect(self._on_config_changed)
        length_layout.addWidget(self.slider)

        self.lbl_length_value = QLabel("16")
        self.lbl_length_value.setFixedWidth(30)
        self.lbl_length_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        length_layout.addWidget(self.lbl_length_value)
        layout.addLayout(length_layout)

        # 字符类型选项
        types_layout = QVBoxLayout()
        types_layout.setSpacing(6)

        self.chk_upper = QCheckBox("大写字母 (A-Z)")
        self.chk_upper.setChecked(True)
        self.chk_upper.stateChanged.connect(self._on_config_changed)
        types_layout.addWidget(self.chk_upper)

        self.chk_lower = QCheckBox("小写字母 (a-z)")
        self.chk_lower.setChecked(True)
        self.chk_lower.stateChanged.connect(self._on_config_changed)
        types_layout.addWidget(self.chk_lower)

        self.chk_digits = QCheckBox("数字 (0-9)")
        self.chk_digits.setChecked(True)
        self.chk_digits.stateChanged.connect(self._on_config_changed)
        types_layout.addWidget(self.chk_digits)

        self.chk_symbols = QCheckBox("特殊符号 (!@#$%^&*-_=+)")
        self.chk_symbols.setChecked(True)
        self.chk_symbols.stateChanged.connect(self._on_config_changed)
        types_layout.addWidget(self.chk_symbols)

        layout.addLayout(types_layout)

        # 实时预览
        preview_layout = QHBoxLayout()
        lbl_preview = QLabel("预览：")
        lbl_preview.setFixedWidth(80)
        preview_layout.addWidget(lbl_preview)

        self.lbl_preview = QLabel("")
        self.lbl_preview.setFixedHeight(32)
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet(f"""
            QLabel {{
                border: 1px solid {colors.border_medium};
                border-radius: 4px;
                background-color: {colors.bg_secondary};
                color: {colors.accent_blue};
                font-family: "Consolas", "Courier New", monospace;
                font-size: 13px;
                padding: 2px 8px;
            }}
        """)
        preview_layout.addWidget(self.lbl_preview)
        layout.addLayout(preview_layout)

        layout.addStretch()

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_layout.addSpacing(10)

        btn_generate = QPushButton("生成并复制")
        btn_generate.setFixedHeight(36)
        btn_generate.setFixedWidth(120)
        btn_generate.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_dark};
            }}
        """)
        btn_generate.clicked.connect(self._on_generate)
        btn_layout.addWidget(btn_generate)

        layout.addLayout(btn_layout)

        self._refresh_preview()

    def _on_config_changed(self):
        self.lbl_length_value.setText(str(self.slider.value()))
        self._refresh_preview()

    def _refresh_preview(self):
        try:
            pwd = generate_password(
                length=self.slider.value(),
                upper=self.chk_upper.isChecked(),
                lower=self.chk_lower.isChecked(),
                digits=self.chk_digits.isChecked(),
                symbols=self.chk_symbols.isChecked(),
            )
            self.lbl_preview.setText(pwd)
        except ValueError:
            self.lbl_preview.setText("(请至少选择一种字符类型)")

    def _on_generate(self):
        try:
            pwd = generate_password(
                length=self.slider.value(),
                upper=self.chk_upper.isChecked(),
                lower=self.chk_lower.isChecked(),
                digits=self.chk_digits.isChecked(),
                symbols=self.chk_symbols.isChecked(),
            )
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(pwd)
            self.generated_password = pwd
            self.accept()
        except ValueError:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请至少选择一种字符类型")
