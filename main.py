"""
本地密码保险箱 - 主入口
"""
import logging
import sys
import os

# 启用 faulthandler：崩溃时打印 Python 堆栈（帮助定位 0xC0000409 等底层崩溃）
import faulthandler
faulthandler.enable()

# 设置 UTF-8 编码（Windows 兼容）
if sys.platform == 'win32':
    import locale
    if locale.getpreferredencoding() != 'utf-8':
        import _winapi
        _winapi.GetConsoleOutputCP = lambda: 65001

from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtCore import Qt

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logger import setup_logging
from core.crypto import CryptoManager
from core.database import DatabaseManager
from core.theme_manager import ThemeManager, style_button_primary
from ui.main_window import MainWindow


class SetupDialog(QDialog):
    """首次启动设置主密码对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        self.setWindowTitle("欢迎使用本地密码保险箱")
        self.setMinimumSize(450, 300)
        
        from PyQt6.QtWidgets import (
            QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QPushButton, QMessageBox
        )
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        lbl_title = QLabel("🔐 设置主密码")
        font = lbl_title.font()
        font.setPointSize(16)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        layout.addSpacing(20)
        
        # 说明
        lbl_desc = QLabel("这是您第一次使用本软件。\n\n"
                         "请设置一个主密码，用于加密所有账号数据。\n"
                         "请牢记此密码，遗忘后将无法恢复数据。")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)
        
        layout.addSpacing(20)
        
        # 密码输入
        lbl_password = QLabel("主密码 *")
        layout.addWidget(lbl_password)
        
        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText("请输入主密码（至少 6 位）")
        self.txt_password.setFixedHeight(40)
        layout.addWidget(self.txt_password)
        
        # 确认密码
        lbl_confirm = QLabel("确认密码 *")
        layout.addWidget(lbl_confirm)
        
        self.txt_confirm = QLineEdit()
        self.txt_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_confirm.setPlaceholderText("请再次输入主密码")
        self.txt_confirm.setFixedHeight(40)
        layout.addWidget(self.txt_confirm)
        
        layout.addStretch()
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_ok = QPushButton("确定")
        btn_ok.setFixedHeight(40)
        btn_ok.setFixedWidth(120)
        btn_ok.setStyleSheet(style_button_primary(ThemeManager.instance().colors))
        btn_ok.clicked.connect(self.on_ok)
        btn_layout.addWidget(btn_ok)
        
        layout.addLayout(btn_layout)
        
        self.password = None
    
    def on_ok(self):
        password = self.txt_password.text().strip()
        confirm = self.txt_confirm.text().strip()
        
        if len(password) < 6:
            QMessageBox.warning(self, "验证失败", "主密码至少需要 6 位")
            return
        
        if password != confirm:
            QMessageBox.warning(self, "验证失败", "两次输入的密码不一致")
            return
        
        self.password = password
        self.accept()


class LoginDialog(QDialog):
    """登录对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        self.setWindowTitle("登录")
        self.setMinimumSize(400, 250)
        
        from PyQt6.QtWidgets import (
            QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
            QPushButton, QMessageBox
        )
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        lbl_title = QLabel("🔐 输入主密码")
        font = lbl_title.font()
        font.setPointSize(16)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        layout.addSpacing(30)
        
        # 说明
        lbl_desc = QLabel("请输入您的主密码以解锁密码保险箱")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)
        
        layout.addSpacing(20)
        
        # 密码输入
        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText("请输入主密码")
        self.txt_password.setFixedHeight(40)
        layout.addWidget(self.txt_password)
        
        layout.addStretch()
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_login = QPushButton("解锁")
        btn_login.setFixedHeight(40)
        btn_login.setFixedWidth(120)
        btn_login.setStyleSheet(style_button_primary(ThemeManager.instance().colors))
        btn_login.clicked.connect(self.on_login)
        btn_layout.addWidget(btn_login)
        
        layout.addLayout(btn_layout)
        
        self.password = None
    
    def on_login(self):
        password = self.txt_password.text().strip()
        
        if not password:
            QMessageBox.warning(self, "验证失败", "请输入主密码")
            return
        
        self.password = password
        self.accept()


def main():
    """主函数"""
    setup_logging()

    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("本地密码保险箱")
    app.setApplicationVersion("1.0")
    
    # 数据目录
    data_dir = Path.home() / '.local_password_vault'
    data_dir.mkdir(exist_ok=True)
    
    db_path = data_dir / 'vault.db'
    config_path = data_dir / 'config.json'
    
    # 加载并应用主题配置
    import json
    theme = 'light'
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            theme = config.get('theme', 'light')
        except Exception:
            theme = 'light'

    # 初始化主题管理器
    ThemeManager.instance().init_app(app, theme)
    
    # 检查是否是首次启动
    is_first_run = not db_path.exists()
    
    crypto = None
    db = None
    
    if is_first_run:
        # 首次启动：设置主密码
        setup_dialog = SetupDialog()
        if setup_dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        
        master_password = setup_dialog.password
        
        # 创建加密管理器
        crypto = CryptoManager(master_password)
        
        # 保存盐值到配置
        config = {
            'salt': crypto.salt.hex(),
            'version': '1.0',

            'theme': 'light'
        }
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f)
        
        # 创建数据库
        db = DatabaseManager(str(db_path), crypto)
        
        QMessageBox.information(
            None, "设置完成",
            "主密码已设置！\n\n"
            "请牢记您的主密码，遗忘后将无法恢复数据。\n"
            "建议定期导出备份。"
        )
    else:
        # 非首次启动：验证主密码（循环直到密码正确或用户取消）
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        salt = bytes.fromhex(config['salt'])
        
        db = None
        while db is None:
            login_dialog = LoginDialog()
            if login_dialog.exec() != QDialog.DialogCode.Accepted:
                sys.exit(0)
            
            master_password = login_dialog.password
            crypto = CryptoManager(master_password, salt)
            
            # 尝试创建数据库连接并验证解密能力
            try:
                db = DatabaseManager(str(db_path), crypto)
                # 关键：若数据库有数据，必须能成功解密才算密码正确
                db.cursor.execute("SELECT app_name FROM accounts LIMIT 1")
                row = db.cursor.fetchone()
                if row and row['app_name'] and db.crypto:
                    # 尝试解密：若失败或返回原密文，说明密码错误
                    decrypted = db._decrypt_field(row['app_name'])
                    if decrypted == row['app_name']:
                        # 解密失败（返回原始密文）
                        raise ValueError("Decryption failed: password incorrect")
            except Exception as e:
                logging.getLogger(__name__).warning("Password verification failed: %s", e)
                QMessageBox.critical(
                    None, "密码错误",
                    "主密码验证失败，无法解密数据。\n\n"
                    "请确认输入的密码是否正确，注意大小写和空格。"
                )
                db = None  # 重置，循环继续
        
    
    # 初始化 AI Service Manager（单例，后台线程自动探测 Ollama 状态）
    from services.ai_service_manager import AIServiceManager
    ai_manager = AIServiceManager.instance()
    
    # 创建主窗口
    window = MainWindow(db, str(config_path))
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
