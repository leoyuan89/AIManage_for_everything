"""
设置对话框
主界面为功能按钮列表，点击后弹出对应操作弹窗
"""
import logging
import json
import time
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox,
    QGroupBox, QFormLayout, QCheckBox, QFrame,
    QRadioButton, QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from core.database import DatabaseManager
from core.crypto import CryptoManager
from core.theme_manager import ThemeManager, ThemeColors

logger = logging.getLogger(__name__)



def _perf_log(phase: str, t0: float, t1: float = None):
    """Phase 0 计时日志（输出到 debug_output.txt）"""
    if t1 is None:
        t1 = time.perf_counter()
    msg = f"[Perf] {phase}: {(t1 - t0) * 1000:.1f} ms"
    logger.debug(msg)
    try:
        with open("debug_output.txt", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


class ChangePasswordDialog(QDialog):
    """修改主密码弹窗"""
    
    def __init__(self, db_manager: DatabaseManager, config_path: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.config_path = config_path
        self.setup_ui()
    
    def setup_ui(self):
        colors = ThemeManager.instance().colors
        self.setWindowTitle("修改主密码")
        self.setMinimumSize(450, 350)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        lbl_title = QLabel("修改主密码")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        layout.addSpacing(10)
        
        # 说明
        lbl_desc = QLabel("修改主密码需要重新加密所有数据，请谨慎操作。")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {colors.text_secondary};")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)
        
        layout.addSpacing(10)
        
        # 表单
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        
        self.txt_current_password = QLineEdit()
        self.txt_current_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_current_password.setPlaceholderText("请输入当前主密码")
        self.txt_current_password.setFixedHeight(36)
        form_layout.addRow("当前密码：", self.txt_current_password)
        
        self.txt_new_password = QLineEdit()
        self.txt_new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_new_password.setPlaceholderText("请输入新主密码（至少6位）")
        self.txt_new_password.setFixedHeight(36)
        form_layout.addRow("新密码：", self.txt_new_password)
        
        self.txt_confirm_password = QLineEdit()
        self.txt_confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_confirm_password.setPlaceholderText("请再次输入新主密码")
        self.txt_confirm_password.setFixedHeight(36)
        form_layout.addRow("确认密码：", self.txt_confirm_password)
        
        layout.addLayout(form_layout)
        
        layout.addStretch()
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_layout.addSpacing(10)
        
        btn_ok = QPushButton("确认修改")
        btn_ok.setFixedHeight(40)
        btn_ok.setFixedWidth(120)
        btn_ok.setStyleSheet(f"""
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
        btn_ok.clicked.connect(self.on_change_password)
        btn_layout.addWidget(btn_ok)
        
        layout.addLayout(btn_layout)
    
    def on_change_password(self):
        """修改主密码"""
        current_password = self.txt_current_password.text().strip()
        new_password = self.txt_new_password.text().strip()
        confirm_password = self.txt_confirm_password.text().strip()
        
        if not current_password:
            QMessageBox.warning(self, "验证失败", "请输入当前主密码")
            return
        
        if len(new_password) < 6:
            QMessageBox.warning(self, "验证失败", "新密码至少需要 6 位")
            return
        
        if new_password != confirm_password:
            QMessageBox.warning(self, "验证失败", "两次输入的新密码不一致")
            return
        
        if current_password == new_password:
            QMessageBox.warning(self, "验证失败", "新密码不能与当前密码相同")
            return
        
        reply = QMessageBox.question(
            self,
            "确认修改",
            "修改主密码需要重新加密所有数据，可能需要一些时间。\n\n"
            "请确保：\n"
            "1. 您已记住新密码\n"
            "2. 已导出加密备份（以防万一）\n\n"
            "是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            if self._do_change_password(current_password, new_password):
                self.db.increment_session_version()
                QMessageBox.information(
                    self,
                    "修改成功",
                    "主密码已修改成功！\n\n"
                    "请牢记新密码，遗忘后将无法恢复数据。"
                )
                QMessageBox.information(
                    self,
                    "会话提示",
                    "密码已修改，部分敏感操作需要重新验证。"
                )
                self.accept()
            else:
                QMessageBox.critical(self, "修改失败", "密码修改失败，可能是当前密码错误。")
        except Exception as e:
            QMessageBox.critical(self, "修改失败", f"密码修改过程中发生错误：\n{str(e)}")
    
    def _do_change_password(self, old_password: str, new_password: str) -> bool:
        """执行密码修改"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        old_salt = bytes.fromhex(config['salt'])
        old_crypto = CryptoManager(old_password, old_salt)
        
        try:
            self.db.cursor.execute("SELECT app_name FROM accounts LIMIT 1")
            row = self.db.cursor.fetchone()
            if row and row['app_name']:
                old_crypto.decrypt_from_string(row['app_name'])
        except Exception:
            return False
        
        new_crypto = CryptoManager(new_password)
        
        self.db.cursor.execute("""
            SELECT id, app_name, url, username, password, category, tags, remark, 
                   ai_remark, security_level, created_at, updated_at
            FROM accounts
        """)
        rows = self.db.cursor.fetchall()
        
        for row in rows:
            encrypted_data = {
                'app_name': new_crypto.encrypt_to_string(
                    old_crypto.decrypt_from_string(row['app_name']) if row['app_name'] else ''
                ),
                'url': new_crypto.encrypt_to_string(
                    old_crypto.decrypt_from_string(row['url']) if row['url'] else ''
                ),
                'username': new_crypto.encrypt_to_string(
                    old_crypto.decrypt_from_string(row['username']) if row['username'] else ''
                ),
                'password': new_crypto.encrypt_to_string(
                    old_crypto.decrypt_from_string(row['password']) if row['password'] else ''
                ),
                'remark': new_crypto.encrypt_to_string(
                    old_crypto.decrypt_from_string(row['remark']) if row['remark'] else ''
                ),
                'ai_remark': new_crypto.encrypt_to_string(
                    old_crypto.decrypt_from_string(row['ai_remark']) if row['ai_remark'] else ''
                ),
                'security_level': new_crypto.encrypt_to_string(
                    old_crypto.decrypt_from_string(row['security_level']) if row['security_level'] else ''
                ),
            }
            
            self.db.cursor.execute("""
                UPDATE accounts SET
                    app_name = ?, url = ?, username = ?, password = ?,
                    remark = ?, ai_remark = ?, security_level = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                encrypted_data['app_name'], encrypted_data['url'],
                encrypted_data['username'], encrypted_data['password'],
                encrypted_data['remark'], encrypted_data['ai_remark'],
                encrypted_data['security_level'], row['id']
            ))
        
        self.db.conn.commit()
        self.db.crypto = new_crypto
        
        config['salt'] = new_crypto.salt.hex()
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        
        return True


class ThemeSettingsDialog(QDialog):
    """主题设置弹窗"""
    
    theme_applied = pyqtSignal(str)
    
    def __init__(self, config_path: str, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.current_theme = 'light'
        self._load_theme()
        self.setup_ui()
    
    def _load_theme(self):
        """从配置读取当前主题"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.current_theme = config.get('theme', 'light')
        except Exception:
            self.current_theme = 'light'
    
    def setup_ui(self):
        colors = ThemeManager.instance().colors
        self.setWindowTitle("主题设置")
        self.setMinimumSize(400, 280)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        lbl_title = QLabel("主题设置")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        layout.addSpacing(10)
        
        # 说明
        lbl_desc = QLabel("选择您喜欢的界面主题风格。")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {colors.text_secondary};")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)
        
        layout.addSpacing(10)
        
        # 主题选项
        self.rb_light = QRadioButton("浅色主题")
        self.rb_light.setChecked(self.current_theme == 'light')
        self.rb_light.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.rb_light)
        
        lbl_light_desc = QLabel("    清爽明亮的界面风格，适合日间使用")
        lbl_light_desc.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
        layout.addWidget(lbl_light_desc)
        
        layout.addSpacing(10)
        
        self.rb_dark = QRadioButton("深色主题")
        self.rb_dark.setChecked(self.current_theme == 'dark')
        self.rb_dark.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.rb_dark)
        
        lbl_dark_desc = QLabel("    护眼暗色界面风格，适合夜间使用")
        lbl_dark_desc.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
        layout.addWidget(lbl_dark_desc)
        
        layout.addStretch()
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_layout.addSpacing(10)
        
        btn_apply = QPushButton("应用")
        btn_apply.setFixedHeight(40)
        btn_apply.setFixedWidth(120)
        btn_apply.setStyleSheet(f"""
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
        btn_apply.clicked.connect(self.on_apply)
        btn_layout.addWidget(btn_apply)
        
        layout.addLayout(btn_layout)
    
    def on_apply(self):
        """应用主题"""
        theme = 'dark' if self.rb_dark.isChecked() else 'light'
        
        # 保存到配置
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            config['theme'] = theme
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"主题配置保存失败：{str(e)}")
            return
        
        # 发出信号通知主窗口应用主题
        self.theme_applied.emit(theme)
        
        QMessageBox.information(self, "应用成功", f"已切换至{'深色' if theme == 'dark' else '浅色'}主题")
        self.accept()


class AIAssistantSettingsDialog(QDialog):
    """AI 助手设置弹窗"""
    
    settings_applied = pyqtSignal(dict)
    
    def __init__(self, config_path: str, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self._load_config()
        self.setup_ui()
    
    def _load_config(self):
        """从配置读取当前 AI 助手设置"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.idle_timeout = config.get('ai_idle_timeout', 300)
        except Exception:
            self.idle_timeout = 300
    
    def setup_ui(self):
        colors = ThemeManager.instance().colors
        self.setWindowTitle("AI 助手设置")
        self.setMinimumSize(400, 250)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        lbl_title = QLabel("AI 助手设置")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        layout.addSpacing(10)
        
        # 说明
        lbl_desc = QLabel("配置 AI 助手对话上下文的行为参数。")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {colors.text_secondary};")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)
        
        layout.addSpacing(10)
        
        # AI 助手设置分组
        ai_group = QGroupBox("AI 助手设置")
        ai_form = QFormLayout(ai_group)
        ai_form.setSpacing(12)
        
        self.spin_idle_timeout = QSpinBox()
        self.spin_idle_timeout.setRange(60, 3600)
        self.spin_idle_timeout.setValue(self.idle_timeout)
        self.spin_idle_timeout.setSuffix(" 秒")
        self.spin_idle_timeout.setSingleStep(30)
        ai_form.addRow("对话上下文超时:", self.spin_idle_timeout)
        
        lbl_hint = QLabel("超过此时长未与 AI 对话，上下文将自动清空。")
        lbl_hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
        ai_form.addRow("", lbl_hint)
        
        layout.addWidget(ai_group)
        
        layout.addStretch()
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_layout.addSpacing(10)
        
        btn_apply = QPushButton("保存")
        btn_apply.setFixedHeight(40)
        btn_apply.setFixedWidth(120)
        btn_apply.setStyleSheet(f"""
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
        btn_apply.clicked.connect(self.on_save)
        btn_layout.addWidget(btn_apply)
        
        layout.addLayout(btn_layout)
    
    def on_save(self):
        """保存 AI 助手设置"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception:
            config = {}
        
        config['ai_idle_timeout'] = self.spin_idle_timeout.value()
        
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"AI 助手设置保存失败：{str(e)}")
            return
        
        self.settings_applied.emit({'ai_idle_timeout': self.spin_idle_timeout.value()})
        QMessageBox.information(self, "保存成功", "AI 助手设置已保存。")
        self.accept()


class SettingsDialog(QDialog):
    """设置对话框主界面 - 按钮列表"""
    
    theme_changed = pyqtSignal(str)
    ai_settings_changed = pyqtSignal(dict)
    
    def __init__(self, db_manager: DatabaseManager, config_path: str,
                 parent=None):
        t0 = time.perf_counter()
        super().__init__(parent)
        t1 = time.perf_counter(); _perf_log("SettingsDialog super().__init__", t0, t1)
        
        self.db = db_manager
        self.config_path = config_path
        
        t2 = time.perf_counter()
        
        self.setup_ui()
        t3 = time.perf_counter(); _perf_log("SettingsDialog setup_ui", t2, t3)
        _perf_log("SettingsDialog __init__ TOTAL", t0, t3)
    
    def setup_ui(self):
        colors = ThemeManager.instance().colors
        t0 = time.perf_counter()
        self.setWindowTitle("设置")
        self.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        lbl_title = QLabel("设置")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        layout.addSpacing(20)
        
        # 按钮列表
        t_btns0 = time.perf_counter()
        # 修改主密码
        self.btn_change_password = QPushButton("修改主密码")
        self.btn_change_password.setFixedHeight(50)
        self.btn_change_password.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 8px;
                font-size: 14px;
                text-align: left;
                padding-left: 20px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg};
                border-color: {colors.accent_blue};
            }}
        """)
        self.btn_change_password.clicked.connect(self.on_change_password_click)
        layout.addWidget(self.btn_change_password)
        
        # 主题设置
        self.btn_theme = QPushButton("主题设置")
        self.btn_theme.setFixedHeight(50)
        self.btn_theme.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 8px;
                font-size: 14px;
                text-align: left;
                padding-left: 20px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg};
                border-color: {colors.accent_blue};
            }}
        """)
        self.btn_theme.clicked.connect(self.on_theme_click)
        layout.addWidget(self.btn_theme)
        
        # AI 助手设置
        self.btn_ai_settings = QPushButton("AI 助手设置")
        self.btn_ai_settings.setFixedHeight(50)
        self.btn_ai_settings.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 8px;
                font-size: 14px;
                text-align: left;
                padding-left: 20px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg};
                border-color: {colors.accent_blue};
            }}
        """)
        self.btn_ai_settings.clicked.connect(self.on_ai_settings_click)
        layout.addWidget(self.btn_ai_settings)
        
        t_btns1 = time.perf_counter(); _perf_log("SettingsDialog button list", t_btns0, t_btns1)
        
        layout.addStretch()
        
        # 关闭按钮
        btn_close = QPushButton("关闭")
        btn_close.setFixedHeight(40)
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignCenter)
        
        _perf_log("SettingsDialog setup_ui total", t0)
        
        # 监听主题变化，实时更新自身样式
        ThemeManager.instance().theme_changed.connect(self._on_settings_theme_changed)
    
    def _on_settings_theme_changed(self, theme_name: str):
        """主题变化时更新设置弹窗自身样式"""
        colors = ThemeManager.instance().colors
        btn_style = f"""
            QPushButton {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 8px;
                font-size: 14px;
                text-align: left;
                padding-left: 20px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg};
                border-color: {colors.accent_blue};
            }}
        """
        if hasattr(self, 'btn_change_password'):
            self.btn_change_password.setStyleSheet(btn_style)
        if hasattr(self, 'btn_theme'):
            self.btn_theme.setStyleSheet(btn_style)
        if hasattr(self, 'btn_ai_settings'):
            self.btn_ai_settings.setStyleSheet(btn_style)
    
    def on_change_password_click(self):
        """点击修改主密码"""
        dialog = ChangePasswordDialog(self.db, self.config_path, parent=self)
        dialog.exec()
    
    def on_theme_click(self):
        """点击主题设置"""
        dialog = ThemeSettingsDialog(self.config_path, parent=self)
        dialog.theme_applied.connect(self.theme_changed.emit)
        dialog.exec()
    
    def on_ai_settings_click(self):
        """点击 AI 助手设置"""
        dialog = AIAssistantSettingsDialog(self.config_path, parent=self)
        dialog.settings_applied.connect(self.ai_settings_changed.emit)
        dialog.exec()
    

