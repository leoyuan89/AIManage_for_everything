"""
锁定屏幕模块
提供自动空闲锁定和手动锁定功能
"""
import json
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor

from core.crypto import CryptoManager
from core.theme_manager import ThemeManager, ThemeColors


class LockScreen(QWidget):
    """锁定屏幕：全屏半透明遮罩，覆盖在主窗口之上"""
    
    unlocked = pyqtSignal()
    
    def __init__(self, db_manager, config_path: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.config_path = config_path
        
        # 错误尝试控制
        self._failed_attempts = 0
        self._max_attempts = 5
        self._lockout_duration = 60  # 秒
        self._lockout_until = 0
        
        self.setup_ui()
        self.apply_styles()
    
    def setup_ui(self):
        """设置UI布局"""
        colors = ThemeManager.instance().colors
        # 填充父窗口
        if self.parent():
            self.setGeometry(self.parent().rect())
        
        # 主布局：垂直居中
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 内容容器（固定宽度，居中显示）
        content = QWidget()
        content.setFixedWidth(400)
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(20)
        content_layout.setContentsMargins(40, 50, 40, 50)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 锁图标
        lbl_icon = QLabel("🔒")
        icon_font = QFont()
        icon_font.setPointSize(48)
        lbl_icon.setFont(icon_font)
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(lbl_icon)
        
        # 标题
        lbl_title = QLabel("程序已锁定")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        lbl_title.setFont(title_font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet(f"color: {colors.text_on_dark};")
        content_layout.addWidget(lbl_title)
        
        # 说明文字
        lbl_desc = QLabel("请输入主密码解锁")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_desc.setStyleSheet(f"color: {colors.text_secondary}; font-size: 13px;")
        content_layout.addWidget(lbl_desc)
        
        # 密码输入框
        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText("主密码")
        self.txt_password.setFixedHeight(44)
        bg_color = QColor(colors.bg_card)
        bg_color.setAlpha(26)
        border_color = QColor(colors.border_default)
        border_color.setAlpha(77)
        self.txt_password.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba({bg_color.red()}, {bg_color.green()}, {bg_color.blue()}, {bg_color.alpha() / 255.0:.2f});
                border: 1px solid rgba({border_color.red()}, {border_color.green()}, {border_color.blue()}, {border_color.alpha() / 255.0:.2f});
                border-radius: 6px;
                color: {colors.text_primary};
                padding: 0 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border: 1px solid {colors.accent_blue_light};
            }}
        """)
        self.txt_password.returnPressed.connect(self.on_unlock)
        content_layout.addWidget(self.txt_password)
        
        # 错误提示标签
        self.lbl_error = QLabel("")
        self.lbl_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_error.setStyleSheet(f"color: {colors.accent_red}; font-size: 12px;")
        self.lbl_error.hide()
        content_layout.addWidget(self.lbl_error)
        
        # 解锁按钮
        self.btn_unlock = QPushButton("解锁")
        self.btn_unlock.setFixedHeight(44)
        self.btn_unlock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unlock.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_light};
                color: {colors.text_on_dark};
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue};
            }}
            QPushButton:pressed {{
                background-color: {colors.accent_blue_dark};
            }}
            QPushButton:disabled {{
                background-color: {colors.text_disabled};
                color: {colors.text_tertiary};
            }}
        """)
        self.btn_unlock.clicked.connect(self.on_unlock)
        content_layout.addWidget(self.btn_unlock)
        
        main_layout.addWidget(content, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def apply_styles(self):
        """应用半透明遮罩样式"""
        self.setStyleSheet("""
            LockScreen {
                background-color: rgba(0, 0, 0, 0.85);
            }
        """)
    
    def showEvent(self, event):
        """显示时重置输入并聚焦"""
        super().showEvent(event)
        self.txt_password.clear()
        self.lbl_error.hide()
        self.txt_password.setFocus()
        self.raise_()
    
    def resizeEvent(self, event):
        """父窗口大小变化时同步调整"""
        super().resizeEvent(event)
        if self.parent():
            self.setGeometry(self.parent().rect())
    
    def on_unlock(self):
        """解锁按钮点击：验证密码"""
        password = self.txt_password.text().strip()
        
        if not password:
            self._show_error("请输入主密码")
            return
        
        # 检查是否处于锁定冷却期
        now = time.time()
        if now < self._lockout_until:
            remaining = int(self._lockout_until - now)
            self._show_error(f"连续错误次数过多，请 {remaining} 秒后再试")
            return
        
        # 读取配置获取 salt
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            salt = bytes.fromhex(config['salt'])
            iterations = config.get('iterations', 600000)
        except Exception as e:
            self._show_error(f"读取配置失败: {e}")
            return
        
        # 用输入的密码 + salt 创建 CryptoManager
        try:
            test_crypto = CryptoManager(password, salt, iterations=iterations)
        except Exception as e:
            self._show_error("密码验证失败")
            self._record_failure()
            return
        
        # 尝试解密一条数据库记录验证密码
        try:
            if not self._verify_password_with_db(test_crypto):
                self._show_error("密码错误")
                self._record_failure()
                return
        except Exception as e:
            self._show_error(f"验证出错: {e}")
            self._record_failure()
            return
        
        # 验证通过
        self._failed_attempts = 0
        self._lockout_until = 0
        self.txt_password.clear()
        self.lbl_error.hide()
        self.hide()
        self.unlocked.emit()
    
    def _verify_password_with_db(self, test_crypto: CryptoManager) -> bool:
        """验证密码：直接比较派生密钥，无需解密（速度更快）"""
        if self.db.crypto and hasattr(self.db.crypto, '_key'):
            return test_crypto._key == self.db.crypto._key
        
        # 回退：数据库 crypto 不存在时，尝试解密验证
        self.db.cursor.execute(
            "SELECT username, password FROM accounts LIMIT 1"
        )
        row = self.db.cursor.fetchone()
        
        if row:
            encrypted_fields = [row['username'], row['password']]
            for field in encrypted_fields:
                if field and isinstance(field, str) and len(field) > 20:
                    try:
                        test_crypto.decrypt_from_string(field)
                        return True
                    except Exception:
                        continue
            return False
        
        return False
    
    def _record_failure(self):
        """记录一次失败尝试"""
        self._failed_attempts += 1
        if self._failed_attempts >= self._max_attempts:
            self._lockout_until = time.time() + self._lockout_duration
            self._show_error(f"连续错误 {self._max_attempts} 次，锁定 {self._lockout_duration} 秒")
            self._failed_attempts = 0  # 重置计数，下次从0开始
    
    def _show_error(self, message: str):
        """显示错误信息"""
        self.lbl_error.setText(message)
        self.lbl_error.show()
    
    def reset_lockout(self):
        """重置错误计数（用于手动锁定时）"""
        self._failed_attempts = 0
        self._lockout_until = 0
        self.txt_password.clear()
        self.lbl_error.hide()


class IdleTimer(QObject):
    """
    空闲检测定时器
    监听鼠标/键盘事件，5分钟无操作触发锁定
    """
    
    lock_requested = pyqtSignal()
    
    def __init__(self, timeout_ms: int = 300000, parent=None):
        super().__init__(parent)
        self.timeout_ms = timeout_ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timeout)
        self._timer.setSingleShot(True)
        self._active = True
    
    def start(self):
        """启动定时器"""
        if self._active:
            self._timer.start(self.timeout_ms)
    
    def stop(self):
        """停止定时器"""
        self._timer.stop()
    
    def reset(self):
        """重置定时器（用户有操作时调用）"""
        if self._active and self._timer.isActive():
            self._timer.stop()
            self._timer.start(self.timeout_ms)
    
    def _on_timeout(self):
        """定时器超时：请求锁定"""
        self.lock_requested.emit()
    
    def set_active(self, active: bool):
        """设置是否启用空闲检测"""
        self._active = active
        if active:
            self.start()
        else:
            self.stop()
