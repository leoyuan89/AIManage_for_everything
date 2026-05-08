"""
账号添加/编辑弹窗
集成：手动输入 + 截图导入 + AI 智能分类
"""
import logging
import time
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QComboBox,
    QTextEdit, QTabWidget, QMessageBox, QFileDialog,
    QProgressDialog, QApplication, QFrame, QListWidget, QScrollArea
)
from PyQt6.QtCore import QPoint
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QColor, QPalette

from core.database import DatabaseManager
from core.clipboard import ClipboardManager
from core.password_strength import evaluate_password_strength, suggest_improvements
from core.password_generator import generate_password
from core.repositories import RepositoryFactory, AccountRepository
from core.theme_manager import ThemeManager, ThemeColors
from services.account_service import AccountService
from services.category_service import CategoryService
from services.ai_service_manager import AIServiceManager
from services.ai_worker_thread import AIStatus
from models.account import Account

logger = logging.getLogger(__name__)


def _perf_log(phase: str, t0: float, t1: float = None):
    """Phase 0 计时日志"""
    if t1 is None:
        t1 = time.perf_counter()
    msg = f"[Perf] {phase}: {(t1 - t0) * 1000:.1f} ms"
    logger.debug(msg)


class OCRWorker(QThread):
    """OCR 识别后台线程（安全模式）
    
    生命周期由 Qt 自动管理：
    1. parent=AccountDialog，对话框关闭时自动销毁
    2. self.finished.connect(self.deleteLater)，线程结束后自动销毁
    3. 外部不主动 deleteLater，避免 race condition
    """
    # 注意：不能命名为 finished，因为 QThread 本身有 finished 信号，
    # 同名会导致 C++ 层 signal/slot 冲突，引发 0xC0000409 崩溃
    ocr_finished = pyqtSignal(dict)  # 返回提取的字段
    ocr_error = pyqtSignal(str)
    
    def __init__(self, ocr_service, image_path: str, parent=None):
        super().__init__(parent)
        self.ocr_service = ocr_service
        self.image_path = image_path
        self._is_running = True
        # 线程自然结束后自动销毁，外部无需手动 deleteLater
        self.finished.connect(self.deleteLater)
    
    def run(self):
        try:
            if not self._is_running:
                return
            fields = self.ocr_service.extract_account_fields(self.image_path)
            if self._is_running:
                self.ocr_finished.emit(fields)
        except Exception as e:
            if self._is_running:
                self.ocr_error.emit(str(e))
    
    def stop(self):
        self._is_running = False
        self.wait(1000)


class PasswordHistoryDialog(QDialog):
    def __init__(self, db_manager: DatabaseManager, account_id: int, app_name: str, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.account_id = account_id
        self._decrypted_cache = {}

        self.setWindowTitle(f"密码历史记录 - {app_name}")
        self.setMinimumSize(900, 380)

        colors = ThemeManager.instance().colors
        self.setStyleSheet(f"QDialog {{ background-color: {colors.bg_primary}; }}")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(4)

        history = self.db.get_password_history(account_id)

        if not history:
            empty_label = QLabel("暂无密码历史记录")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"color: {colors.text_tertiary}; padding: 40px; font-size: 14px;")
            content_layout.addWidget(empty_label)
        else:
            for entry in history:
                entry_id, enc_pwd, changed_at = entry
                row = QWidget()
                row.setStyleSheet(f"""
                    QWidget {{
                        background-color: {colors.bg_card};
                        border: 1px solid {colors.border_light};
                        border-radius: 6px;
                    }}
                """)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(12, 6, 12, 6)
                row_layout.setSpacing(10)

                dt = changed_at if changed_at else "未知"
                dt_label = QLabel(dt)
                dt_label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 12px; border: none; background: transparent;")
                dt_label.setFixedWidth(160)
                row_layout.addWidget(dt_label)

                pwd_field = QLineEdit("••••••••")
                pwd_field.setReadOnly(True)
                pwd_field.setEchoMode(QLineEdit.EchoMode.Password)
                pwd_field.setStyleSheet(f"""
                    QLineEdit {{
                        border: 1px solid {colors.border_medium};
                        border-radius: 4px;
                        padding: 4px 8px;
                        background-color: {colors.bg_secondary};
                        color: {colors.text_primary};
                        font-size: 12px;
                    }}
                """)
                row_layout.addWidget(pwd_field, 1)

                show_btn = QPushButton("显示")
                show_btn.setCheckable(True)
                show_btn.setFixedWidth(56)
                show_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {colors.accent_blue_bg};
                        color: {colors.accent_blue};
                        border: 1px solid {colors.accent_blue_light};
                        border-radius: 4px;
                        font-size: 11px;
                        padding: 4px 8px;
                    }}
                    QPushButton:hover {{
                        background-color: {colors.accent_blue_light};
                    }}
                    QPushButton:checked {{
                        background-color: {colors.accent_blue};
                        color: {colors.text_on_accent};
                    }}
                """)
                show_btn.toggled.connect(lambda checked, eid=entry_id, f=pwd_field, b=show_btn, ep=enc_pwd:
                    self._toggle_password(checked, eid, f, b, ep))
                row_layout.addWidget(show_btn)

                copy_btn = QPushButton("复制")
                copy_btn.setFixedWidth(56)
                copy_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {colors.bg_secondary};
                        color: {colors.text_secondary};
                        border: 1px solid {colors.border_medium};
                        border-radius: 4px;
                        font-size: 11px;
                        padding: 4px 8px;
                    }}
                    QPushButton:hover {{
                        background-color: {colors.bg_tertiary};
                        color: {colors.text_primary};
                    }}
                """)
                copy_btn.clicked.connect(lambda checked, eid=entry_id, ep=enc_pwd:
                    self._copy_password(eid, ep))
                row_layout.addWidget(copy_btn)

                content_layout.addWidget(row)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(36)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_secondary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_medium};
                border-radius: 4px;
                font-size: 13px;
                padding: 4px 20px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_tertiary};
            }}
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _toggle_password(self, checked, entry_id, pwd_field, show_btn, enc_pwd):
        if checked:
            if entry_id not in self._decrypted_cache:
                try:
                    self._decrypted_cache[entry_id] = self.db._decrypt_field(enc_pwd)
                except Exception:
                    self._decrypted_cache[entry_id] = "[解密失败]"
            pwd_field.setEchoMode(QLineEdit.EchoMode.Normal)
            pwd_field.setText(self._decrypted_cache[entry_id])
            show_btn.setText("隐藏")
        else:
            pwd_field.setEchoMode(QLineEdit.EchoMode.Password)
            pwd_field.setText("••••••••")
            show_btn.setText("显示")

    def _copy_password(self, entry_id, enc_pwd):
        if entry_id not in self._decrypted_cache:
            try:
                self._decrypted_cache[entry_id] = self.db._decrypt_field(enc_pwd)
            except Exception:
                QMessageBox.warning(self, "错误", "解密失败")
                return
        ClipboardManager().copy_to_clipboard(self._decrypted_cache[entry_id])
        QMessageBox.information(self, "复制成功", "密码已复制到剪贴板")


class PopupComboBox(QWidget):
    """自定义下拉框：弹出列表与触发器保持间距，不遮住当前选项"""
    currentIndexChanged = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._current_index = -1
        self._popup = None
        self._list_widget = None
        
        self._btn = QPushButton(self)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._show_popup)
        
        self._arrow = QLabel("▼", self)
        colors = ThemeManager.instance().colors
        self._arrow.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px; background: transparent;")
        self._arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arrow.setFixedSize(20, 20)
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._btn)
        
        # 箭头通过绝对定位覆盖在按钮右侧
        self._apply_btn_style()
        self._update_btn_text()
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 箭头固定在右侧居中
        self._arrow.move(self.width() - 26, (self.height() - 20) // 2)
    
    def addItems(self, items):
        self._items = list(items)
        if self._current_index < 0 and self._items:
            self._current_index = 0
        self._update_btn_text()
    
    def addItem(self, text):
        self._items.append(text)
        if self._current_index < 0:
            self._current_index = 0
        self._update_btn_text()
    
    def currentText(self):
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]
        return ""
    
    def setCurrentIndex(self, index):
        if 0 <= index < len(self._items):
            old = self._current_index
            self._current_index = index
            self._update_btn_text()
            if old != index:
                self.currentIndexChanged.emit(index)
    
    def currentIndex(self):
        return self._current_index
    
    def count(self):
        return len(self._items)
    
    def findText(self, text):
        try:
            return self._items.index(text)
        except ValueError:
            return -1
    
    def setFixedHeight(self, height):
        super().setFixedHeight(height)
        self._btn.setFixedHeight(height)
    
    def setStyleSheet(self, sheet):
        """外部传入的样式应用于按钮"""
        self._btn.setStyleSheet(sheet)
    
    def _apply_btn_style(self):
        colors = ThemeManager.instance().colors
        self._btn.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {colors.border_medium};
                border-radius: 4px;
                background-color: {colors.bg_primary};
                padding: 4px 28px 4px 10px;
                text-align: left;
                color: {colors.text_primary};
                font-size: 13px;
            }}
            QPushButton:hover {{
                border-color: {colors.accent_blue};
            }}
        """)
    
    def _update_btn_text(self):
        text = self.currentText()
        self._btn.setText(text if text else " ")
    
    def _show_popup(self):
        colors = ThemeManager.instance().colors
        if not self._items:
            return
        
        # 关闭已打开的弹出框
        if self._popup:
            self._popup.close()
            self._popup = None
        
        # 计算列表尺寸
        # item 实际高度 = min-height(24) + padding-top(6) + padding-bottom(6) = 36
        item_h = 36
        max_items = min(len(self._items), 6)
        list_height = item_h * max_items + 4  # +4 给边框留余量
        popup_width = self.width()
        
        # 创建弹出窗口（Popup + 无边框，白色背景）
        self._popup = QWidget(self.window(), Qt.WindowType.Popup)
        self._popup.setWindowFlags(
            self._popup.windowFlags() | Qt.WindowType.FramelessWindowHint
        )
        self._popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._popup.setStyleSheet("background-color: transparent;")
        self._popup.setFixedSize(popup_width, list_height)
        
        self._list_widget = QListWidget(self._popup)
        self._list_widget.setFrameShape(QFrame.Shape.NoFrame)
        self._list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget.setFixedSize(popup_width, list_height)
        self._list_widget.setStyleSheet(f"""
            QListWidget {{
                border: 1px solid {colors.border_medium};
                border-radius: 4px;
                background-color: {colors.bg_primary};
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 10px;
                min-height: 24px;
                color: {colors.text_primary};
            }}
            QListWidget::item:hover {{
                background-color: {colors.bg_secondary};
            }}
            QListWidget::item:selected {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
            }}
        """)
        
        for item in self._items:
            self._list_widget.addItem(item)
        
        if self._current_index >= 0:
            self._list_widget.setCurrentRow(self._current_index)
        
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        
        # 计算弹出位置
        gap = 4
        btn_global = self._btn.mapToGlobal(QPoint(0, 0))
        screen = QApplication.primaryScreen().availableGeometry()
        
        x = btn_global.x()
        # 优先尝试下方
        y_below = btn_global.y() + self._btn.height() + gap
        if y_below + list_height <= screen.bottom():
            y = y_below
        else:
            # 上方
            y = btn_global.y() - list_height - gap
        
        self._popup.move(x, y)
        self._popup.show()
    
    def _on_item_clicked(self, item):
        row = self._list_widget.row(item)
        self.setCurrentIndex(row)
        if self._popup:
            self._popup.close()
            self._popup = None
        self._list_widget = None


class JustifyLabel(QLabel):
    """两端对齐标签：主文字在可用宽度内均匀分布，支持后缀（如 *）"""
    def __init__(self, text: str, suffix: str = "", parent=None):
        super().__init__(parent)
        self._main_text = text
        self._suffix = suffix
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    
    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QFontMetrics
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        
        rect = self.rect()
        fm = QFontMetrics(self.font())
        align = self.alignment()
        
        # 垂直对齐标志
        v_align = Qt.AlignmentFlag.AlignVCenter
        if align & Qt.AlignmentFlag.AlignTop:
            v_align = Qt.AlignmentFlag.AlignTop
        elif align & Qt.AlignmentFlag.AlignBottom:
            v_align = Qt.AlignmentFlag.AlignBottom
        
        suffix_w = fm.horizontalAdvance(self._suffix)
        avail_w = rect.width() - suffix_w
        
        chars = list(self._main_text)
        total_w = sum(fm.horizontalAdvance(c) for c in chars)
        
        if len(chars) > 1 and total_w < avail_w:
            gap = (avail_w - total_w) / (len(chars) - 1)
            x = 0
            for c in chars:
                cw = fm.horizontalAdvance(c)
                painter.drawText(int(x), rect.top(), int(cw), rect.height(),
                                 Qt.AlignmentFlag.AlignCenter | v_align, c)
                x += cw + gap
        else:
            painter.drawText(0, rect.top(), int(avail_w), rect.height(),
                             Qt.AlignmentFlag.AlignRight | v_align,
                             self._main_text)
        
        if self._suffix:
            painter.drawText(int(avail_w), rect.top(), int(suffix_w), rect.height(),
                             Qt.AlignmentFlag.AlignLeft | v_align,
                             self._suffix)
        
        painter.end()


class AccountDialog(QDialog):
    """账号添加/编辑弹窗"""
    
    def __init__(self, db_manager: DatabaseManager, account: Account = None, parent=None):
        t0 = time.perf_counter()
        super().__init__(parent)
        t1 = time.perf_counter(); _perf_log("AccountDialog super().__init__", t0, t1)
        
        self.db = db_manager
        self.account_service = AccountService(db_manager)
        t2 = time.perf_counter(); _perf_log("AccountDialog attr init", t1, t2)
        
        # CategoryService 只需要 db_manager，AI 能力走 AIServiceManager
        self.category_service = CategoryService(db_manager)
        t3 = time.perf_counter(); _perf_log("CategoryService init", t2, t3)
        
        self.ocr_service = None  # 延迟初始化
        self.clipboard = ClipboardManager()
        t4 = time.perf_counter(); _perf_log("ClipboardManager init", t3, t4)
        
        # 接入 AIServiceManager 单例
        self._ai_manager = AIServiceManager.instance()
        t5 = time.perf_counter(); _perf_log("AIServiceManager.instance()", t4, t5)
        
        self.account = account
        self.is_edit_mode = account is not None
        
        self.ocr_worker = None
        
        # 用于跟踪待处理的 AI 任务
        self._pending_categorize_parent_task = None
        self._pending_categorize_child_task = None
        self._pending_remark_task = None
        self._is_dirty = False
        
        # 注册 Repository（若未注册）
        self._ensure_repository_registered()
        
        self.setup_ui()
        t6 = time.perf_counter(); _perf_log("setup_ui total", t5, t6)
        
        # 绑定 AI 任务结果信号
        self._ai_manager.task_finished.connect(self._on_ai_task_finished)
        self._ai_manager.task_failed.connect(self._on_ai_task_failed)
        t7 = time.perf_counter(); _perf_log("AI signal bindings", t6, t7)
        
        if self.is_edit_mode:
            self.load_account_data()
            t8 = time.perf_counter(); _perf_log("load_account_data", t7, t8)
        
        _perf_log("AccountDialog __init__ TOTAL", t0)
    
    def _ensure_repository_registered(self):
        """确保 AccountRepository 已在工厂中注册"""
        try:
            RepositoryFactory.get_repository('accounts')
        except KeyError:
            repo = AccountRepository(
                db=self.db,
                category_service=self.category_service,
                classification_service=None
            )
            RepositoryFactory.register('accounts', repo)
    

    def _load_categories(self):
        """加载主类下拉框"""
        tree = self.account_service.get_category_tree()
        self.cmb_parent.clear()
        self.cmb_parent.addItem("请选择")
        self.cmb_parent.addItems(sorted(tree.keys()))
    
    def _on_parent_changed(self, parent_name):
        """主类改变时更新子类下拉框"""
        self.cmb_child.clear()
        self.cmb_child.addItem("")  # 空表示无子类（一级分类）
        
        tree = self.account_service.get_category_tree()
        if parent_name in tree:
            for child in sorted(tree[parent_name]['children']):
                self.cmb_child.addItem(child)
    
    def get_ocr_service(self):
        """延迟获取 OCR 服务"""
        if self.ocr_service is None:
            try:
                from services.ocr_service import OCRService
                self.ocr_service = OCRService()
            except Exception as e:
                logger.error("OCR 服务初始化失败: %s", e)
                QMessageBox.warning(self, "提示", "OCR 服务初始化失败，截图导入功能不可用")
        return self.ocr_service
    
    def setup_ui(self):
        """设置界面"""
        colors = ThemeManager.instance().colors
        t_setup0 = time.perf_counter()
        if self.is_edit_mode:
            self.setWindowTitle(f"编辑账号 - {self.account.app_name}")
        else:
            self.setWindowTitle("添加账号")
        
        self.setMinimumSize(800, 750)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # ==================== 标签页切换 ====================
        t_tab0 = time.perf_counter()
        self.tabs = QTabWidget()
        
        # ---- 手动输入标签 ----
        self.tab_manual = QWidget()
        self.setup_manual_tab()
        self.tabs.addTab(self.tab_manual, "手动输入")
        
        # ---- 截图导入标签 ----
        if not self.is_edit_mode:  # 仅在添加模式显示截图导入
            self.tab_ocr = QWidget()
            self.setup_ocr_tab()
            self.tabs.addTab(self.tab_ocr, "截图导入")
        
        layout.addWidget(self.tabs)
        t_tab1 = time.perf_counter(); _perf_log("setup_ui TabWidget+tabs", t_tab0, t_tab1)
        
        # ==================== 底部按钮区 ====================
        t_btn0 = time.perf_counter()
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancel)
        
        button_layout.addSpacing(10)
        
        btn_save = QPushButton("保存")
        btn_save.setFixedHeight(40)
        btn_save.setFixedWidth(100)
        btn_save.setStyleSheet(f"""
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
        btn_save.clicked.connect(self.on_save)
        button_layout.addWidget(btn_save)
        
        layout.addLayout(button_layout)
        
        # 删除按钮（仅编辑模式）
        if self.is_edit_mode:
            btn_delete = QPushButton("删除账号")
            btn_delete.setFixedHeight(40)
            btn_delete.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.accent_red};
                    color: {colors.text_on_dark};
                    border: none;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    background-color: {colors.accent_red_dark};
                }}
            """)
            btn_delete.clicked.connect(self.on_delete)
            layout.addWidget(btn_delete, alignment=Qt.AlignmentFlag.AlignCenter)
        t_btn1 = time.perf_counter(); _perf_log("setup_ui bottom buttons", t_btn0, t_btn1)
        
        _perf_log("setup_ui total", t_setup0)
    
    def setup_manual_tab(self):
        """设置手动输入标签页"""
        colors = ThemeManager.instance().colors
        t_manual0 = time.perf_counter()
        layout = QVBoxLayout(self.tab_manual)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 应用名
        name_layout = QHBoxLayout()
        lbl_name = JustifyLabel("应用名：", "*")
        lbl_name.setFixedWidth(80)
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_name.setStyleSheet("font-weight: bold;")
        name_layout.addWidget(lbl_name)
        
        self.txt_app_name = QLineEdit()
        self.txt_app_name.setPlaceholderText("例如：支付宝、微信")
        self.txt_app_name.setFixedHeight(36)
        self.txt_app_name.textChanged.connect(self.on_app_name_changed)
        self.txt_app_name.textChanged.connect(self._mark_dirty)
        name_layout.addWidget(self.txt_app_name)
        layout.addLayout(name_layout)
        
        # 网址
        url_layout = QHBoxLayout()
        lbl_url = JustifyLabel("网址：")
        lbl_url.setFixedWidth(80)
        lbl_url.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        url_layout.addWidget(lbl_url)
        
        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("例如：https://www.alipay.com")
        self.txt_url.setFixedHeight(36)
        self.txt_url.textChanged.connect(self._mark_dirty)
        url_layout.addWidget(self.txt_url)
        layout.addLayout(url_layout)
        
        # 账号
        username_layout = QHBoxLayout()
        lbl_username = JustifyLabel("账号：", "*")
        lbl_username.setFixedWidth(80)
        lbl_username.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_username.setStyleSheet("font-weight: bold;")
        username_layout.addWidget(lbl_username)
        
        self.txt_username = QLineEdit()
        self.txt_username.setPlaceholderText("请输入账号")
        self.txt_username.setFixedHeight(36)
        self.txt_username.textChanged.connect(self._mark_dirty)
        username_layout.addWidget(self.txt_username)
        layout.addLayout(username_layout)
        
        # 密码
        password_layout = QHBoxLayout()
        
        lbl_password = JustifyLabel("密码：", "*")
        lbl_password.setFixedWidth(80)
        lbl_password.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_password.setStyleSheet("font-weight: bold;")
        password_layout.addWidget(lbl_password)
        
        self.txt_password = QLineEdit()
        self.txt_password.setPlaceholderText("请输入密码")
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setFixedHeight(36)
        self.txt_password.textChanged.connect(self.on_password_changed)
        self.txt_password.textChanged.connect(self._mark_dirty)
        password_layout.addWidget(self.txt_password)
        
        self.btn_show_password = QPushButton("显示")
        self.btn_show_password.setFixedSize(80, 36)
        self.btn_show_password.setCheckable(True)
        self.btn_show_password.toggled.connect(self.toggle_password_visibility)
        password_layout.addWidget(self.btn_show_password)
        
        layout.addLayout(password_layout)
        
        # 密码强度行 (与上方输入框对齐，左侧留80px标签宽度)
        strength_layout = QHBoxLayout()
        strength_layout.setSpacing(6)
        strength_spacer = QLabel("")
        strength_spacer.setFixedWidth(80)
        strength_layout.addWidget(strength_spacer)
        
        self.lbl_password_strength = QLabel("")
        self.lbl_password_strength.setFixedHeight(24)
        self.lbl_password_strength.hide()
        strength_layout.addWidget(self.lbl_password_strength)
        
        strength_layout.addStretch()
        
        self.btn_generate_password = QPushButton("生成")
        self.btn_generate_password.setFixedSize(100, 26)
        self.btn_generate_password.setToolTip("随机生成密码")
        self.btn_generate_password.clicked.connect(self.on_generate_password)
        strength_layout.addWidget(self.btn_generate_password)
        
        self.btn_generator_settings = QPushButton("⚙")
        self.btn_generator_settings.setFixedSize(70, 26)
        self.btn_generator_settings.setToolTip("密码生成器设置")
        self.btn_generator_settings.clicked.connect(self.on_generate_password_settings)
        strength_layout.addWidget(self.btn_generator_settings)
        
        self.btn_password_history = QPushButton("历史")
        self.btn_password_history.setFixedSize(100, 26)
        self.btn_password_history.setToolTip("查看密码历史记录")
        self.btn_password_history.clicked.connect(self.on_show_password_history)
        strength_layout.addWidget(self.btn_password_history)
        
        layout.addLayout(strength_layout)

        # 密码改进建议
        tips_layout = QHBoxLayout()
        tips_layout.setSpacing(10)
        tips_spacer = QLabel("")
        tips_spacer.setFixedWidth(80)
        tips_layout.addWidget(tips_spacer)

        self.lbl_strength_tips = QLabel("")
        self.lbl_strength_tips.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 11px;")
        self.lbl_strength_tips.setWordWrap(True)
        tips_layout.addWidget(self.lbl_strength_tips, 1)

        layout.addLayout(tips_layout)

        # 分类 + AI 按钮
        t_cat0 = time.perf_counter()
        category_layout = QHBoxLayout()
        
        lbl_category = JustifyLabel("分类：")
        lbl_category.setFixedWidth(80)
        lbl_category.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        category_layout.addWidget(lbl_category)
        
        self.cmb_parent = QComboBox()
        self.cmb_parent.setEditable(True)
        self.cmb_parent.setPlaceholderText("请选择")
        self.cmb_parent.setFixedHeight(36)
        self.cmb_parent.currentTextChanged.connect(self._on_parent_changed)
        self.cmb_parent.currentTextChanged.connect(self._mark_dirty)
        category_layout.addWidget(self.cmb_parent)
        
        lbl_sep = QLabel(">")
        lbl_sep.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 14px; font-weight: bold;")
        lbl_sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        category_layout.addWidget(lbl_sep)
        
        self.cmb_child = QComboBox()
        self.cmb_child.setEditable(True)
        self.cmb_child.setPlaceholderText("子类（可选）")
        self.cmb_child.setFixedHeight(36)
        self.cmb_child.currentTextChanged.connect(self._mark_dirty)
        category_layout.addWidget(self.cmb_child)
        
        self._load_categories()
        
        self.btn_ai_parent = QPushButton("AI")
        self.btn_ai_parent.setFixedHeight(36)
        self.btn_ai_parent.setFixedWidth(50)
        self.btn_ai_parent.setToolTip("AI分析一级分类")
        self.btn_ai_parent.clicked.connect(self.on_ai_categorize_parent)
        category_layout.addWidget(self.btn_ai_parent)
        
        self.btn_ai_child = QPushButton("AI")
        self.btn_ai_child.setFixedHeight(36)
        self.btn_ai_child.setFixedWidth(50)
        self.btn_ai_child.setToolTip("AI分析二级分类（在当前一级下）")
        self.btn_ai_child.clicked.connect(self.on_ai_categorize_child)
        category_layout.addWidget(self.btn_ai_child)
        
        layout.addLayout(category_layout)
        t_cat1 = time.perf_counter(); _perf_log("setup_manual_tab category+AI buttons", t_cat0, t_cat1)
        
        # 标签
        t_tags0 = time.perf_counter()
        tags_layout = QHBoxLayout()
        
        lbl_tags = JustifyLabel("标签：")
        lbl_tags.setFixedWidth(80)
        lbl_tags.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tags_layout.addWidget(lbl_tags)
        
        self.tags_container = QWidget()
        self.tags_layout = QHBoxLayout(self.tags_container)
        self.tags_layout.setSpacing(5)
        self.tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.addWidget(self.tags_container)
        
        tags_layout.addStretch()
        
        btn_edit_tags = QPushButton("编辑标签")
        btn_edit_tags.setFixedHeight(32)
        btn_edit_tags.setFixedWidth(80)
        btn_edit_tags.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border: 1px solid {colors.accent_blue_light};
                border-radius: 4px;
                font-size: 11px;
            }}
        """)
        btn_edit_tags.clicked.connect(self.on_edit_tags)
        tags_layout.addWidget(btn_edit_tags)
        
        layout.addLayout(tags_layout)
        t_tags1 = time.perf_counter(); _perf_log("setup_manual_tab tags UI", t_tags0, t_tags1)
        
        # AI 备注
        t_remark0 = time.perf_counter()
        ai_remark_layout = QHBoxLayout()
        
        lbl_ai_remark = JustifyLabel("AI 备注：")
        lbl_ai_remark.setFixedWidth(80)
        lbl_ai_remark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ai_remark_layout.addWidget(lbl_ai_remark)
        
        self.txt_ai_remark = QLineEdit()
        self.txt_ai_remark.setPlaceholderText("AI 生成的一句话备注（选填）")
        self.txt_ai_remark.setFixedHeight(36)
        self.txt_ai_remark.textChanged.connect(self._mark_dirty)
        ai_remark_layout.addWidget(self.txt_ai_remark)
        
        self.btn_ai_remark = QPushButton("✨ AI生成")
        self.btn_ai_remark.setFixedHeight(36)
        self.btn_ai_remark.setFixedWidth(110)
        self.btn_ai_remark.setToolTip("根据应用名称、网址和分类自动生成一句话备注")
        self.btn_ai_remark.clicked.connect(self.on_ai_generate_remark)
        
        ai_remark_layout.addWidget(self.btn_ai_remark)
        layout.addLayout(ai_remark_layout)
        t_remark1 = time.perf_counter(); _perf_log("setup_manual_tab AI remark init", t_remark0, t_remark1)
        
        # 备注
        remark_layout = QHBoxLayout()
        lbl_remark = JustifyLabel("用户备注：")
        lbl_remark.setFixedWidth(80)
        lbl_remark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        remark_layout.addWidget(lbl_remark)
        
        self.txt_remark = QTextEdit()
        self.txt_remark.setPlaceholderText("其他信息（选填）")
        self.txt_remark.setMinimumHeight(80)
        self.txt_remark.setMaximumHeight(120)
        self.txt_remark.textChanged.connect(self._mark_dirty)
        remark_layout.addWidget(self.txt_remark)
        layout.addLayout(remark_layout)
        
        layout.addStretch()
        
        # 所有 AI 相关控件已创建，绑定状态信号并更新初始状态
        self._ai_manager.state_changed.connect(self._update_ai_buttons)
        self._update_ai_buttons(self._ai_manager.get_state())
        
        _perf_log("setup_manual_tab total", t_manual0)
    
    def setup_ocr_tab(self):
        """设置截图导入标签页"""
        colors = ThemeManager.instance().colors
        layout = QVBoxLayout(self.tab_ocr)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 说明文字
        lbl_desc = QLabel("上传包含账号密码的截图，系统将自动识别并填充")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {colors.text_secondary}; padding: 10px;")
        layout.addWidget(lbl_desc)
        
        # 选择图片按钮
        self.btn_select_image = QPushButton("选择图片")
        self.btn_select_image.setFixedHeight(45)
        self.btn_select_image.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_green};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_green_dark};
            }}
        """)
        self.btn_select_image.clicked.connect(self.on_select_image)
        layout.addWidget(self.btn_select_image)
        
        # 图片预览区域
        self.lbl_preview = QLabel("未选择图片")
        self.lbl_preview.setFixedHeight(150)
        self.lbl_preview.setStyleSheet(f"""
            QLabel {{
                background-color: {colors.bg_secondary};
                border: 2px dashed {colors.border_medium};
                border-radius: 8px;
                color: {colors.text_tertiary};
                font-size: 16px;
            }}
        """)
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_preview)
        
        # 识别状态
        self.lbl_ocr_status = QLabel("")
        self.lbl_ocr_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_ocr_status.setStyleSheet(f"color: {colors.accent_blue}; font-weight: bold;")
        layout.addWidget(self.lbl_ocr_status)
        
        # 识别结果预览
        self.frame_ocr_result = QFrame()
        self.frame_ocr_result.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.bg_card};
                border: 1px solid {colors.border_light};
                border-radius: 8px;
            }}
        """)
        result_layout = QVBoxLayout(self.frame_ocr_result)
        
        self.lbl_ocr_app = QLabel("应用：-")
        self.lbl_ocr_username = QLabel("账号：-")
        self.lbl_ocr_password = QLabel("密码：-")
        
        for lbl in [self.lbl_ocr_app, self.lbl_ocr_username, self.lbl_ocr_password]:
            lbl.setStyleSheet("padding: 5px; font-size: 12px;")
            result_layout.addWidget(lbl)
        
        # 添加分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {colors.border_default};")
        line.setFixedHeight(1)
        result_layout.addWidget(line)
        
        # 显示所有识别的文字
        lbl_all_texts_title = QLabel("识别到的所有文字：")
        lbl_all_texts_title.setStyleSheet(f"padding: 5px; font-size: 11px; color: {colors.text_secondary};")
        result_layout.addWidget(lbl_all_texts_title)
        
        self.lbl_all_texts = QLabel("-")
        self.lbl_all_texts.setStyleSheet(f"padding: 5px; font-size: 10px; color: {colors.text_tertiary};")
        self.lbl_all_texts.setWordWrap(True)
        result_layout.addWidget(self.lbl_all_texts)
        
        self.frame_ocr_result.hide()  # 初始隐藏
        layout.addWidget(self.frame_ocr_result)
        
        # 应用识别结果按钮
        self.btn_apply_ocr = QPushButton("应用识别结果")
        self.btn_apply_ocr.setFixedHeight(40)
        self.btn_apply_ocr.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }}
        """)
        self.btn_apply_ocr.clicked.connect(self.on_apply_ocr_result)
        self.btn_apply_ocr.hide()  # 初始隐藏
        layout.addWidget(self.btn_apply_ocr)
        
        layout.addStretch()
        
        self.ocr_result = {}  # 存储 OCR 识别结果
    
    def _update_ai_buttons(self, state):
        """根据 AI 状态更新按钮可用性"""
        enabled = state.status == AIStatus.ONLINE
        if hasattr(self, 'btn_ai_parent'):
            self.btn_ai_parent.setEnabled(enabled)
            self.btn_ai_parent.setToolTip(
                "AI分析一级分类" if enabled else f"Ollama 未连接 ({state.error_message})"
            )
        if hasattr(self, 'btn_ai_child'):
            self.btn_ai_child.setEnabled(enabled)
            self.btn_ai_child.setToolTip(
                "AI分析二级分类（在当前一级下）" if enabled else f"Ollama 未连接 ({state.error_message})"
            )
        if hasattr(self, 'btn_ai_remark'):
            self.btn_ai_remark.setEnabled(enabled)
            self.btn_ai_remark.setToolTip(
                "根据应用名称、网址和分类自动生成一句话备注" if enabled else f"Ollama 未连接 ({state.error_message})"
            )
    
    def on_app_name_changed(self, text):
        """应用名改变时触发（可在此做自动分类，但避免过于频繁）"""
        pass  # 暂时不自动触发，等待用户点击 AI 按钮或失去焦点
    
    def on_ai_categorize_parent(self):
        """AI 分析一级分类"""
        app_name = self.txt_app_name.text().strip()
        url = self.txt_url.text().strip()
        
        if not app_name:
            QMessageBox.warning(self, "提示", "请先输入应用名")
            return
        
        self.btn_ai_parent.setEnabled(False)
        self.btn_ai_parent.setText("...")
        
        try:
            existing_cats = self.account_service.get_categories()
        except Exception:
            existing_cats = []
        
        remark = self.txt_remark.toPlainText().strip()
        ai_remark = self.txt_ai_remark.text().strip()
        task_id = self._ai_manager.categorize_async(app_name, url, existing_categories=existing_cats, remark=remark, ai_remark=ai_remark)
        self._pending_categorize_parent_task = task_id
    
    def on_ai_categorize_child(self):
        """AI 分析二级分类（在当前一级分类下）"""
        app_name = self.txt_app_name.text().strip()
        url = self.txt_url.text().strip()
        
        if not app_name:
            QMessageBox.warning(self, "提示", "请先输入应用名")
            return
        
        current_parent = self.cmb_parent.currentText().strip()
        if not current_parent or current_parent == "请选择":
            QMessageBox.warning(self, "提示", "请先选择一级分类，或点击左侧「AI」按钮自动分析一级分类")
            return
        
        self.btn_ai_child.setEnabled(False)
        self.btn_ai_child.setText("...")
        
        try:
            existing_cats = self.account_service.get_categories()
        except Exception:
            existing_cats = []
        
        remark = self.txt_remark.toPlainText().strip()
        ai_remark = self.txt_ai_remark.text().strip()
        task_id = self._ai_manager.categorize_async(app_name, url, existing_categories=existing_cats, parent_hint=current_parent, remark=remark, ai_remark=ai_remark)
        self._pending_categorize_child_task = task_id
    
    def _on_ai_task_finished(self, task_id, result):
        """AI 任务完成统一分发"""
        if task_id == self._pending_categorize_parent_task:
            self._pending_categorize_parent_task = None
            self._on_categorize_parent_result(task_id, result)
        elif task_id == self._pending_categorize_child_task:
            self._pending_categorize_child_task = None
            self._on_categorize_child_result(task_id, result)
        elif task_id == self._pending_remark_task:
            self._pending_remark_task = None
            self._on_remark_result(task_id, result)
    
    def _on_ai_task_failed(self, task_id, error_message):
        """AI 任务失败统一分发"""
        if task_id == self._pending_categorize_parent_task:
            self._pending_categorize_parent_task = None
            self._on_categorize_parent_failed(task_id, error_message)
        elif task_id == self._pending_categorize_child_task:
            self._pending_categorize_child_task = None
            self._on_categorize_child_failed(task_id, error_message)
        elif task_id == self._pending_remark_task:
            self._pending_remark_task = None
            self._on_remark_failed(task_id, error_message)
    
    def _on_categorize_parent_result(self, task_id, result):
        """AI 一级分类完成"""
        self.btn_ai_parent.setEnabled(True)
        self.btn_ai_parent.setText("AI")
        
        from core.category_utils import parse_category_path
        parent, _ = parse_category_path(result)
        if not parent:
            parent = result.strip()
        if parent:
            idx = self.cmb_parent.findText(parent)
            if idx < 0:
                self.cmb_parent.addItem(parent)
                idx = self.cmb_parent.count() - 1
            self.cmb_parent.setCurrentIndex(idx)
            self.cmb_child.clear()
            self.cmb_child.addItem("")
            QMessageBox.information(self, "分类成功", f"AI 识别一级分类：{parent}")
    
    def _on_categorize_parent_failed(self, task_id, error):
        """AI 一级分类失败"""
        self.btn_ai_parent.setEnabled(True)
        self.btn_ai_parent.setText("AI")
        QMessageBox.warning(self, "分类失败", f"AI 一级分类失败：{error}")
    
    def _on_categorize_child_result(self, task_id, result):
        """AI 二级分类完成"""
        self.btn_ai_child.setEnabled(True)
        self.btn_ai_child.setText("AI")
        
        child = result.strip()
        if child:
            idx = self.cmb_child.findText(child)
            if idx < 0:
                self.cmb_child.addItem(child)
                idx = self.cmb_child.count() - 1
            self.cmb_child.setCurrentIndex(idx)
            QMessageBox.information(self, "分类成功", f"AI 识别二级分类：{child}")
        else:
            QMessageBox.warning(self, "分类失败", f"AI 返回的二级分类无法解析：{result}")
    
    def _on_categorize_child_failed(self, task_id, error):
        """AI 二级分类失败"""
        self.btn_ai_child.setEnabled(True)
        self.btn_ai_child.setText("AI")
        QMessageBox.warning(self, "分类失败", f"AI 二级分类失败：{error}")
    
    def on_select_image(self):
        """选择图片按钮点击"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择截图", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        
        if not file_path:
            return
        
        # 延迟初始化 OCR 服务
        ocr_service = self.get_ocr_service()
        if ocr_service is None:
            QMessageBox.warning(self, "提示", "OCR 服务不可用")
            return
        
        # 显示预览
        pixmap = QPixmap(file_path)
        scaled_pixmap = pixmap.scaled(
            self.lbl_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.lbl_preview.setPixmap(scaled_pixmap)
        
        # 显示状态
        self.lbl_ocr_status.setText("正在识别...")
        self.frame_ocr_result.hide()
        self.btn_apply_ocr.hide()
        
        # 启动 OCR 后台线程（安全模式：parent=self + finished→deleteLater）
        self.ocr_worker = OCRWorker(ocr_service, file_path, parent=self)
        self.ocr_worker.ocr_finished.connect(self.on_ocr_finished)
        self.ocr_worker.ocr_error.connect(self.on_ocr_error)
        self.ocr_worker.start()
    
    def on_ocr_finished(self, fields: dict):
        """OCR 识别完成"""
        try:
            self.lbl_ocr_status.setText("识别完成，请核对信息")
            self.ocr_result = fields
            
            # 更新预览
            app = fields.get('app_name', '-') or '-'
            username = fields.get('username', '-') or '-'
            password = fields.get('password', '-') or '-'
            
            self.lbl_ocr_app.setText(f"应用：{app}")
            self.lbl_ocr_username.setText(f"账号：{username}")
            self.lbl_ocr_password.setText(f"密码：{password}")
            
            # 显示所有识别的文字
            all_texts = fields.get('all_texts', [])
            if all_texts:
                all_texts_str = ' | '.join(all_texts[:10])  # 最多显示10个
                if len(all_texts) > 10:
                    all_texts_str += f" ... (共{len(all_texts)}个)"
                self.lbl_all_texts.setText(all_texts_str)
            else:
                self.lbl_all_texts.setText("-")
            
            self.frame_ocr_result.show()
            self.btn_apply_ocr.show()
        except Exception as e:
            import traceback
            logger.exception("on_ocr_finished ERROR")
        # 不在这里清理 worker，等 QThread.finished 信号触发 _on_ocr_worker_finished
    
    def on_ocr_error(self, error_msg: str):
        """OCR 识别失败"""
        self.lbl_ocr_status.setText(f"识别失败：{error_msg}")
        # 不在这里清理 worker，等 QThread.finished 信号触发 _on_ocr_worker_finished
    

    
    def on_apply_ocr_result(self):
        """应用 OCR 识别结果"""
        try:
            logger.debug("Step 1: setCurrentIndex")
            self.tabs.setCurrentIndex(0)

            logger.debug("Step 2: get fields")
            app_name = self.ocr_result.get('app_name', '')
            username = self.ocr_result.get('username', '')
            password = self.ocr_result.get('password', '')
            url = self.ocr_result.get('url', '')
            all_texts = self.ocr_result.get('all_texts', [])
            
            logger.debug("Step 3: fill fields")
            if app_name:
                self.txt_app_name.setText(app_name)
            if url:
                self.txt_url.setText(url)
            if username:
                self.txt_username.setText(username)
            if password:
                self.txt_password.setText(password)
            
            logger.debug("Step 4: build remark")
            remark_lines = []
            remark_lines.append("【OCR识别结果】")
            remark_lines.append(f"应用：{app_name or '(未识别)'}")
            remark_lines.append(f"账号：{username or '(未识别)'}")
            remark_lines.append(f"密码：{password or '(未识别)'}")
            if url:
                remark_lines.append(f"网址：{url}")
            remark_lines.append("")
            remark_lines.append("【原始识别文字】")
            for i, text in enumerate(all_texts, 1):
                remark_lines.append(f"{i}. {text}")
            
            remark_text = "\n".join(remark_lines)
            
            logger.debug("Step 5: set remark")
            current_remark = self.txt_remark.toPlainText().strip()
            if current_remark:
                self.txt_remark.setText(current_remark + "\n\n" + remark_text)
            else:
                self.txt_remark.setText(remark_text)
            
            logger.debug("Step 6: AI categorize")
            self.on_ai_categorize_parent()
            logger.debug("Step 7: done")
            QMessageBox.information(self, "成功", "已应用识别结果，请核对并补充信息\n\n识别详情已添加到备注区域，如有错误请手动修改。")
        except Exception as e:
            logger.exception("on_apply_ocr_result ERROR")
            QMessageBox.warning(self, "应用失败", f"应用 OCR 结果时出错：{str(e)}")
    
    def load_account_data(self):
        """加载账号数据（编辑模式）"""
        self.txt_app_name.setText(self.account.app_name)
        self.txt_url.setText(self.account.url)
        self.txt_username.setText(self.account.username)
        self.txt_password.setText(self.account.password)
        self.txt_remark.setText(self.account.remark)
        self.txt_ai_remark.setText(self.account.ai_remark)
        
        # 设置分类
        if self.account.category:
            from core.category_utils import parse_category_path
            parent, child = parse_category_path(self.account.category)
            if parent:
                idx = self.cmb_parent.findText(parent)
                if idx < 0:
                    self.cmb_parent.addItem(parent)
                    idx = self.cmb_parent.count() - 1
                self.cmb_parent.setCurrentIndex(idx)
                if child:
                    self.cmb_child.setCurrentText(child)
        
        # 刷新标签显示
        self.refresh_tags_display()
        
        # 显示已保存的密码强度
        if self.account.security_level:
            self._show_strength_label(self.account.security_level, self._get_strength_color(self.account.security_level))
        
        self._is_dirty = False  # 加载数据不视为修改
    
    def on_password_changed(self, text):
        """密码输入变化时更新强度显示"""
        if not text:
            self.lbl_password_strength.hide()
            self.lbl_strength_tips.setText("")
            return
        
        result = evaluate_password_strength(text)
        color = self._get_strength_color(result['label'])
        self._show_strength_label(result['label'], color)

        self._update_strength_suggestions()
    
    def _get_strength_color(self, level: str) -> str:
        """根据安全等级文本获取颜色"""
        colors = ThemeManager.instance().colors
        color_map = {
            "弱": colors.accent_red,
            "中": colors.accent_orange,
            "强": colors.accent_green,
            "极强": colors.accent_blue
        }
        return color_map.get(level, colors.text_tertiary)
    
    def _show_strength_label(self, level: str, color: str):
        """显示指定等级的强度标签"""
        colors = ThemeManager.instance().colors
        self.lbl_password_strength.show()
        self.lbl_password_strength.setText(f"  密码强度：{level}  ")
        bg_color = {
            colors.accent_red: colors.accent_red_bg,
            colors.accent_orange: colors.accent_orange_bg,
            colors.accent_green: colors.accent_green_bg,
            colors.accent_blue: colors.accent_blue_bg,
            colors.text_tertiary: colors.bg_secondary
        }.get(color, colors.bg_secondary)
        self.lbl_password_strength.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background-color: {bg_color};
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                padding: 2px 8px;
            }}
        """)
    
    def toggle_password_visibility(self, checked):
        """切换密码可见性"""
        if checked:
            self.txt_password.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_show_password.setText("隐藏")
        else:
            self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_show_password.setText("显示")
    
    def on_generate_password(self):
        """快速生成密码（默认设置）"""
        pwd = generate_password()
        self.txt_password.setText(pwd)
        self._trigger_strength_evaluation()
    
    def on_generate_password_settings(self):
        """打开密码生成器设置弹窗"""
        from ui.dialogs.password_generator_dialog import PasswordGeneratorDialog
        dlg = PasswordGeneratorDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pwd = dlg.generated_password
            if pwd:
                self.txt_password.setText(pwd)
                self._trigger_strength_evaluation()

    def on_show_password_history(self):
        """打开密码历史记录对话框"""
        if not self.is_edit_mode:
            QMessageBox.information(self, "提示", "密码历史记录仅在编辑模式下可用，请先保存账号")
            return
        dlg = PasswordHistoryDialog(self.db, self.account.id, self.account.app_name, parent=self)
        dlg.exec()
    
    def _trigger_strength_evaluation(self):
        """手动触发密码强度评估"""
        self.on_password_changed(self.txt_password.text())

    def _update_strength_suggestions(self):
        colors = ThemeManager.instance().colors
        password = self.txt_password.text()
        if not password:
            self.lbl_strength_tips.setText("")
            return

        tips = suggest_improvements(password)
        if tips:
            self.lbl_strength_tips.setText("建议: " + " | ".join(tips[:3]))
            self.lbl_strength_tips.setStyleSheet(f"color: {colors.accent_red}; font-size: 11px;")
        else:
            self.lbl_strength_tips.setText("密码强度良好")
            self.lbl_strength_tips.setStyleSheet(f"color: {colors.accent_green}; font-size: 11px;")

    def on_ai_generate_remark(self):
        """AI 生成备注按钮点击（异步）"""
        app_name = self.txt_app_name.text().strip()
        url = self.txt_url.text().strip()
        parent = self.cmb_parent.currentText().strip()
        child = self.cmb_child.currentText().strip()
        from core.category_utils import format_category_path
        category = format_category_path(parent if parent != "请选择" else "", child if child else None)
        
        if not app_name:
            QMessageBox.warning(self, "提示", "请先输入应用名")
            return
        
        self.btn_ai_remark.setEnabled(False)
        self.btn_ai_remark.setText("生成中...")
        
        remark = self.txt_remark.toPlainText().strip()
        task_id = self._ai_manager.generate_remark_async(app_name, url, category, remark)
        self._pending_remark_task = task_id
    
    def _on_remark_result(self, task_id, result):
        """AI 备注生成完成"""
        self.btn_ai_remark.setEnabled(True)
        self.btn_ai_remark.setText("✨ AI生成")
        
        if not result or not str(result).strip():
            QMessageBox.warning(self, "生成失败", "AI 备注生成失败：返回内容为空，请重试")
            return
        
        self.txt_ai_remark.setText(result)
        QMessageBox.information(self, "生成成功", f"AI 备注：{result}")
    
    def _on_remark_failed(self, task_id, error):
        """AI 备注生成失败"""
        self.btn_ai_remark.setEnabled(True)
        self.btn_ai_remark.setText("✨ AI生成")
        QMessageBox.warning(self, "生成失败", f"AI 备注生成失败：{error}")
    
    def on_save(self):
        """保存账号"""
        # 验证必填字段
        app_name = self.txt_app_name.text().strip()
        username = self.txt_username.text().strip()
        password = self.txt_password.text().strip()
        
        if not app_name:
            QMessageBox.warning(self, "验证失败", "请输入应用名")
            self.tabs.setCurrentIndex(0)
            self.txt_app_name.setFocus()
            return
        
        if not username:
            QMessageBox.warning(self, "验证失败", "请输入账号")
            self.tabs.setCurrentIndex(0)
            self.txt_username.setFocus()
            return
        
        if not password:
            QMessageBox.warning(self, "验证失败", "请输入密码")
            self.tabs.setCurrentIndex(0)
            self.txt_password.setFocus()
            return
        
        # 评估密码强度
        strength_result = evaluate_password_strength(password)
        security_level = strength_result['label']
        
        from core.category_utils import validate_category_name, format_category_path
        
        parent = self.cmb_parent.currentText().strip()
        child = self.cmb_child.currentText().strip()
        
        if not parent or parent == "请选择":
            QMessageBox.warning(self, "验证失败", "请选择主分类")
            return
        
        if not validate_category_name(parent):
            QMessageBox.warning(self, "验证失败", "主分类名不能包含 /、>、· 或首尾空白")
            return
        
        if child and not validate_category_name(child):
            QMessageBox.warning(self, "验证失败", "子分类名不能包含 /、>、· 或首尾空白")
            return
        
        category = format_category_path(parent, child if child else None)
        
        # 创建账号对象
        account = Account(
            id=self.account.id if self.is_edit_mode else None,
            app_name=app_name,
            url=self.txt_url.text().strip(),
            username=username,
            password=password,
            category=category,
            tags=self.account.tags if self.is_edit_mode else '[]',
            remark=self.txt_remark.toPlainText().strip(),
            ai_remark=self.txt_ai_remark.text().strip(),
            security_level=security_level
        )
        
        try:
            if self.is_edit_mode:
                old_enc_pwd = None
                old_decrypted_pwd = ""
                old_row = self.db.cursor.execute(
                    "SELECT password FROM accounts WHERE id = ?", (self.account.id,)
                ).fetchone()
                if old_row:
                    old_enc_pwd = old_row['password']
                    old_decrypted_pwd = self.db._decrypt_field(old_enc_pwd)

                self.account_service.update_account(account)

                if old_enc_pwd and password != old_decrypted_pwd:
                    self.db.add_password_history(self.account.id, old_enc_pwd)

            else:
                # 新增
                new_id = self.account_service.add_account(account)
                account.id = new_id
            
            self.account = account
            self._is_dirty = False
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{str(e)}")
    
    def on_delete(self):
        """删除账号（移入回收站，30天后自动清理）"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除账号「{self.account.app_name}」吗？\n删除后将移至回收站，可在 30 天内恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 软删除：移入回收站
                success = self.db.soft_delete_account(self.account.id, self.account.to_dict())
                if success:
                    self.accept()
                else:
                    QMessageBox.critical(self, "错误", "移至回收站失败")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败：{str(e)}")
    
    def refresh_tags_display(self):
        """刷新标签显示"""
        colors = ThemeManager.instance().colors
        # 清除现有标签
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        tags = self.account.get_tags_list() if self.is_edit_mode else []
        
        if not tags:
            lbl_empty = QLabel("暂无标签")
            lbl_empty.setStyleSheet(f"color: {colors.text_tertiary}; font-style: italic; font-size: 11px;")
            self.tags_layout.addWidget(lbl_empty)
            return
        
        for tag in tags:
            lbl_tag = QLabel(f"  {tag}  ")
            lbl_tag.setStyleSheet(f"""
                QLabel {{
                    background-color: {colors.accent_blue_bg};
                    color: {colors.accent_blue};
                    border: 1px solid {colors.accent_blue_light};
                    border-radius: 10px;
                    font-size: 11px;
                    padding: 2px 8px;
                }}
            """)
            self.tags_layout.addWidget(lbl_tag)
        
        self.tags_layout.addStretch()
    
    def on_edit_tags(self):
        """编辑标签"""
        from .tag_editor_dialog import TagEditorDialog
        from services.tag_service import TagService
        
        parent = self.cmb_parent.currentText().strip()
        child = self.cmb_child.currentText().strip()
        from core.category_utils import format_category_path
        category = format_category_path(parent if parent != "请选择" else "", child if child else None)
        
        # 创建临时账号对象（用于编辑）
        temp_account = Account(
            id=self.account.id if self.is_edit_mode else None,
            app_name=self.txt_app_name.text(),
            url=self.txt_url.text(),
            username=self.txt_username.text(),
            password=self.txt_password.text(),
            category=category,
            tags=self.account.tags if self.is_edit_mode else '[]'
        )
        
        tag_service = TagService()  # AI 标签生成走 AIServiceManager，此处不再传入 ollama_client
        dialog = TagEditorDialog(temp_account, tag_service, parent=self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 更新账号标签
            if self.is_edit_mode:
                self.account.tags = temp_account.tags
                self.account_service.update_account(self.account)
            
            self.refresh_tags_display()
    
    def _mark_dirty(self):
        self._is_dirty = True

    def reject(self):
        # 取消按钮：直接关闭，不检查是否修改
        self._is_dirty = False
        self.close()

    def closeEvent(self, event):
        """关闭时清理"""
        if self._is_dirty:
            reply = QMessageBox.question(
                self, "未保存的修改",
                "有未保存的修改，是否保存？",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )
            if reply == QMessageBox.StandardButton.Save:
                self.on_save()
                if self._is_dirty:
                    event.ignore()
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        # 断开 AI 信号
        try:
            self._ai_manager.state_changed.disconnect(self._update_ai_buttons)
            self._ai_manager.task_finished.disconnect(self._on_ai_task_finished)
            self._ai_manager.task_failed.disconnect(self._on_ai_task_failed)
        except Exception:
            pass
        
        # 停止后台线程
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_worker.stop()
        
        event.accept()
