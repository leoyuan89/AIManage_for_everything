"""
网址添加/编辑弹窗
集成：手动输入 + AI 智能分类 + 标签/备注管理
"""
import logging
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTextEdit,
    QMessageBox, QFrame, QComboBox
)
from PyQt6.QtCore import Qt

from models.url_item import URLItem
from services.url_service import URLService
from core.repositories import RepositoryFactory, URLRepository
from services.ai_service_manager import AIServiceManager
from services.ai_worker_thread import AIStatus

logger = logging.getLogger(__name__)
from core.theme_manager import ThemeManager, ThemeColors
from core.icon_manager import IconManager
from core.password_generator import generate_password


class URLEditDialog(QDialog):
    """网址添加/编辑弹窗"""
    
    def __init__(self, url_service: URLService, url_item: URLItem = None, parent=None):
        super().__init__(parent)
        self.setWindowIcon(IconManager.app_icon())
        self.url_service = url_service
        self.url_item = url_item or URLItem()
        self.is_edit_mode = url_item is not None and url_item.id is not None
        
        self._ai_manager = AIServiceManager.instance()
        self._pending_tags_task = None
        self._pending_remark_task = None
        self._pending_categorize_parent_task = None
        self._pending_categorize_child_task = None
        self._is_dirty = False
        
        self.setup_ui()
        
        if self.is_edit_mode:
            self.load_url_data()
        
        # 绑定 AI 任务结果信号
        self._ai_manager.task_finished.connect(self._on_ai_task_finished)
        self._ai_manager.task_failed.connect(self._on_ai_task_failed)
    
    def _ensure_repository_registered(self):
        """确保 URLRepository 已在工厂中注册"""
        try:
            RepositoryFactory.get_repository('urls')
        except KeyError:
            from core.url_database import URLDatabaseManager
            repo = URLRepository(
                db=self.url_service.db,
                url_service=self.url_service
            )
            RepositoryFactory.register('urls', repo)
    
    def _get_categories(self) -> list:
        """通过 RepositoryFactory 获取分类列表（确保与数据库同步）"""
        self._ensure_repository_registered()
        try:
            cats = RepositoryFactory.get_repository('urls').get_categories()
            return cats
        except Exception as e:
            logger.error("RepositoryFactory 获取分类失败: %s", e)
            return self.url_service.get_categories()
    
    def setup_ui(self):
        """设置界面"""
        colors = ThemeManager.instance().colors
        if self.is_edit_mode:
            self.setWindowTitle(f"编辑网址 - {self.url_item.title or self.url_item.url}")
        else:
            self.setWindowTitle("添加网址")
        
        self.setMinimumSize(600, 500)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # ===== 标题 =====
        title_layout = QHBoxLayout()
        lbl_title = QLabel("标题：")
        lbl_title.setFixedWidth(80)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_layout.addWidget(lbl_title)
        
        self.txt_title = QLineEdit()
        self.txt_title.setPlaceholderText("例如：GitHub、知乎")
        self.txt_title.setFixedHeight(36)
        self.txt_title.textChanged.connect(self._mark_dirty)
        title_layout.addWidget(self.txt_title)
        layout.addLayout(title_layout)
        
        # ===== 网址 =====
        url_layout = QHBoxLayout()
        lbl_url = QLabel("网址：*")
        lbl_url.setFixedWidth(80)
        lbl_url.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        url_layout.addWidget(lbl_url)
        
        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("例如：https://github.com")
        self.txt_url.setFixedHeight(36)
        self.txt_url.textChanged.connect(self._mark_dirty)
        url_layout.addWidget(self.txt_url)
        layout.addLayout(url_layout)
        
        # ===== 密码 =====
        password_layout = QHBoxLayout()
        lbl_password = QLabel("密码：")
        lbl_password.setFixedWidth(80)
        lbl_password.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        password_layout.addWidget(lbl_password)
        
        self.txt_password = QLineEdit()
        self.txt_password.setPlaceholderText("请输入密码（可选）")
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setFixedHeight(36)
        self.txt_password.textChanged.connect(self._mark_dirty)
        password_layout.addWidget(self.txt_password)
        
        self.btn_show_url_password = QPushButton("显示")
        self.btn_show_url_password.setFixedSize(80, 36)
        self.btn_show_url_password.setCheckable(True)
        self.btn_show_url_password.toggled.connect(self._toggle_url_password_visibility)
        password_layout.addWidget(self.btn_show_url_password)
        
        self.btn_generate_url_password = QPushButton("生成")
        self.btn_generate_url_password.setFixedSize(60, 36)
        self.btn_generate_url_password.setToolTip("随机生成密码")
        self.btn_generate_url_password.clicked.connect(self._on_generate_url_password)
        password_layout.addWidget(self.btn_generate_url_password)
        
        self.btn_generator_url_settings = QPushButton("⚙")
        self.btn_generator_url_settings.setFixedSize(30, 36)
        self.btn_generator_url_settings.setToolTip("密码生成器设置")
        self.btn_generator_url_settings.clicked.connect(self._on_generate_url_password_settings)
        password_layout.addWidget(self.btn_generator_url_settings)
        
        layout.addLayout(password_layout)
        
        # ===== 分类 + AI 按钮 =====
        category_layout = QHBoxLayout()
        lbl_category = QLabel("分类：")
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
        
        # ===== 标签（带 AI 生成按钮）=====
        tags_layout = QHBoxLayout()
        lbl_tags = QLabel("标签：")
        lbl_tags.setFixedWidth(80)
        lbl_tags.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tags_layout.addWidget(lbl_tags)
        
        self.txt_tags = QLineEdit()
        self.txt_tags.setPlaceholderText("逗号分隔，如: 工作, 常用, 开源")
        self.txt_tags.setFixedHeight(36)
        self.txt_tags.textChanged.connect(self._mark_dirty)
        tags_layout.addWidget(self.txt_tags)
        
        self.btn_ai_tags = QPushButton("AI生成标签")
        self.btn_ai_tags.setFixedHeight(36)
        self.btn_ai_tags.setToolTip("根据标题和网址自动生成标签")
        self.btn_ai_tags.clicked.connect(self.on_ai_generate_tags)
        tags_layout.addWidget(self.btn_ai_tags)
        
        layout.addLayout(tags_layout)
        
        # ===== 用户备注 =====
        remark_layout = QHBoxLayout()
        lbl_remark = QLabel("备注：")
        lbl_remark.setFixedWidth(80)
        lbl_remark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        remark_layout.addWidget(lbl_remark)
        
        self.txt_remark = QTextEdit()
        self.txt_remark.setPlaceholderText("输入用户备注...")
        self.txt_remark.setMinimumHeight(60)
        self.txt_remark.setMaximumHeight(100)
        self.txt_remark.textChanged.connect(self._mark_dirty)
        remark_layout.addWidget(self.txt_remark)
        layout.addLayout(remark_layout)
        
        # ===== AI 备注（只读 + 重新生成按钮）=====
        ai_remark_layout = QHBoxLayout()
        lbl_ai_remark = QLabel("AI 备注：")
        lbl_ai_remark.setFixedWidth(80)
        lbl_ai_remark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        ai_remark_layout.addWidget(lbl_ai_remark)
        
        self.txt_ai_remark = QTextEdit()
        self.txt_ai_remark.setPlaceholderText("点击右侧按钮生成 AI 备注...")
        self.txt_ai_remark.setReadOnly(True)
        self.txt_ai_remark.setMinimumHeight(60)
        self.txt_ai_remark.setMaximumHeight(100)
        ai_remark_layout.addWidget(self.txt_ai_remark)
        
        self.btn_ai_remark = QPushButton("生成 AI 备注")
        self.btn_ai_remark.setFixedHeight(36)
        self.btn_ai_remark.setToolTip("根据标题和网址生成一句话备注")
        self.btn_ai_remark.clicked.connect(self.on_ai_generate_remark)
        ai_remark_layout.addWidget(self.btn_ai_remark)
        
        layout.addLayout(ai_remark_layout)
        
        # 更新 AI 按钮状态
        self._update_ai_buttons(self._ai_manager.get_state())
        self._ai_manager.state_changed.connect(self._update_ai_buttons)
        
        layout.addStretch()
        
        # ===== 底部按钮区 =====
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
            btn_delete = QPushButton("删除网址")
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
    
    def _load_categories(self):
        """加载主类下拉框"""
        tree = self.url_service.get_category_tree()
        self.cmb_parent.clear()
        self.cmb_parent.addItem("请选择")
        self.cmb_parent.addItems(sorted(tree.keys()))
    
    def _on_parent_changed(self, parent_name):
        """主类改变时更新子类下拉框"""
        self.cmb_child.clear()
        self.cmb_child.addItem("")  # 空表示无子类（一级分类）
        
        tree = self.url_service.get_category_tree()
        if parent_name in tree:
            for child in sorted(tree[parent_name]['children']):
                self.cmb_child.addItem(child)
    
    def _update_ai_buttons(self, state):
        """根据 AI 状态更新按钮可用性"""
        enabled = state.status == AIStatus.ONLINE
        if hasattr(self, 'btn_ai_parent'):
            self.btn_ai_parent.setEnabled(enabled)
        if hasattr(self, 'btn_ai_child'):
            self.btn_ai_child.setEnabled(enabled)
        if hasattr(self, 'btn_ai_tags'):
            self.btn_ai_tags.setEnabled(enabled)
        if hasattr(self, 'btn_ai_remark'):
            self.btn_ai_remark.setEnabled(enabled)
    
    def load_url_data(self):
        """加载网址数据（编辑模式）"""
        self.txt_title.setText(self.url_item.title)
        self.txt_url.setText(self.url_item.url)
        category = self.url_item.category or '其他'
        from core.category_utils import parse_category_path
        parent, child = parse_category_path(category)
        if parent:
            idx = self.cmb_parent.findText(parent)
            if idx < 0:
                self.cmb_parent.addItem(parent)
                idx = self.cmb_parent.count() - 1
            self.cmb_parent.setCurrentIndex(idx)
            if child:
                self.cmb_child.setCurrentText(child)
        self.txt_remark.setText(self.url_item.remark)
        self.txt_ai_remark.setText(self.url_item.ai_remark)
        self.txt_password.setText(self.url_item.password)
        
        tags = self.url_item.get_tags_list()
        self.txt_tags.setText(", ".join(tags))
        self._is_dirty = False  # 加载数据不视为修改
    
    def on_ai_categorize_parent(self):
        """AI 分析一级分类"""
        url = self.txt_url.text().strip()
        title = self.txt_title.text().strip()
        
        if not url and not title:
            QMessageBox.warning(self, "提示", "请先输入网址或标题")
            return
        
        self.btn_ai_parent.setEnabled(False)
        self.btn_ai_parent.setText("...")
        
        try:
            existing_cats = self.url_service.get_categories()
        except Exception:
            existing_cats = []
        
        remark = self.txt_remark.toPlainText().strip()
        ai_remark = self.txt_ai_remark.toPlainText().strip()
        task_id = self._ai_manager.categorize_async(title or url, url, existing_categories=existing_cats, remark=remark, ai_remark=ai_remark)
        self._pending_categorize_parent_task = task_id
    
    def on_ai_categorize_child(self):
        """AI 分析二级分类（在当前一级分类下）"""
        url = self.txt_url.text().strip()
        title = self.txt_title.text().strip()
        
        if not url and not title:
            QMessageBox.warning(self, "提示", "请先输入网址或标题")
            return
        
        current_parent = self.cmb_parent.currentText().strip()
        if not current_parent or current_parent == "请选择":
            QMessageBox.warning(self, "提示", "请先选择一级分类，或点击左侧「AI」按钮自动分析一级分类")
            return
        
        self.btn_ai_child.setEnabled(False)
        self.btn_ai_child.setText("...")
        
        try:
            existing_cats = self.url_service.get_categories()
        except Exception:
            existing_cats = []
        
        remark = self.txt_remark.toPlainText().strip()
        ai_remark = self.txt_ai_remark.toPlainText().strip()
        task_id = self._ai_manager.categorize_async(title or url, url, existing_categories=existing_cats, parent_hint=current_parent, remark=remark, ai_remark=ai_remark)
        self._pending_categorize_child_task = task_id
    
    def on_ai_generate_tags(self):
        """AI 生成标签：复用 generate_remark_async，结果按逗号拆分作为标签"""
        title = self.txt_title.text().strip()
        url = self.txt_url.text().strip()
        
        if not title and not url:
            QMessageBox.warning(self, "提示", "请先输入标题或网址")
            return
        
        self.btn_ai_tags.setEnabled(False)
        self.btn_ai_tags.setText("生成中...")
        
        # 复用 generate_remark_async，在回调中按逗号解析为标签
        task_id = self._ai_manager.generate_remark_async(title, url)
        self._pending_tags_task = task_id
    
    def on_ai_generate_remark(self):
        """AI 生成备注"""
        title = self.txt_title.text().strip()
        url = self.txt_url.text().strip()
        
        if not title and not url:
            QMessageBox.warning(self, "提示", "请先输入标题或网址")
            return
        
        parent = self.cmb_parent.currentText().strip()
        child = self.cmb_child.currentText().strip()
        from core.category_utils import format_category_path
        category = format_category_path(parent if parent != "请选择" else "", child if child else None)
        remark = self.txt_remark.toPlainText().strip()
        
        self.btn_ai_remark.setEnabled(False)
        self.btn_ai_remark.setText("生成中...")
        
        task_id = self._ai_manager.generate_remark_async(title, url, category, remark)
        self._pending_remark_task = task_id
    
    def _on_ai_task_finished(self, task_id, result):
        """AI 任务完成统一分发"""
        if task_id == self._pending_tags_task:
            self._pending_tags_task = None
            self._on_tags_result(result)
        elif task_id == self._pending_remark_task:
            self._pending_remark_task = None
            self._on_remark_result(result)
        elif task_id == self._pending_categorize_parent_task:
            self._pending_categorize_parent_task = None
            self._on_categorize_parent_result(result)
        elif task_id == self._pending_categorize_child_task:
            self._pending_categorize_child_task = None
            self._on_categorize_child_result(result)
    
    def _on_ai_task_failed(self, task_id, error_message):
        """AI 任务失败统一分发"""
        if task_id == self._pending_tags_task:
            self._pending_tags_task = None
            self._on_tags_failed(error_message)
        elif task_id == self._pending_remark_task:
            self._pending_remark_task = None
            self._on_remark_failed(error_message)
        elif task_id == self._pending_categorize_parent_task:
            self._pending_categorize_parent_task = None
            self._on_categorize_parent_failed(error_message)
        elif task_id == self._pending_categorize_child_task:
            self._pending_categorize_child_task = None
            self._on_categorize_child_failed(error_message)
    
    def _on_tags_result(self, result):
        """标签生成完成"""
        self.btn_ai_tags.setEnabled(True)
        self.btn_ai_tags.setText("AI生成标签")
        self.txt_tags.setText(result)
    
    def _on_tags_failed(self, error):
        """标签生成失败"""
        self.btn_ai_tags.setEnabled(True)
        self.btn_ai_tags.setText("AI生成标签")
        QMessageBox.warning(self, "生成失败", f"AI 标签生成失败：{error}")
    
    def _on_remark_result(self, result):
        """备注生成完成"""
        self.btn_ai_remark.setEnabled(True)
        self.btn_ai_remark.setText("生成 AI 备注")
        self.txt_ai_remark.setText(result)
    
    def _on_remark_failed(self, error):
        """备注生成失败"""
        self.btn_ai_remark.setEnabled(True)
        self.btn_ai_remark.setText("生成 AI 备注")
        QMessageBox.warning(self, "生成失败", f"AI 备注生成失败：{error}")
    
    def _on_categorize_parent_result(self, result):
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
            self.cmb_child.clear()  # 一级改变时清空二级
            self.cmb_child.addItem("")
            QMessageBox.information(self, "分类成功", f"AI 识别一级分类：{parent}")
        else:
            QMessageBox.warning(self, "分类失败", f"AI 返回的分类无法解析：{result}")
    
    def _on_categorize_parent_failed(self, error):
        """AI 一级分类失败"""
        self.btn_ai_parent.setEnabled(True)
        self.btn_ai_parent.setText("AI")
        QMessageBox.warning(self, "分类失败", f"AI 一级分类失败：{error}")
    
    def _on_categorize_child_result(self, result):
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
    
    def _on_categorize_child_failed(self, error):
        """AI 二级分类失败"""
        self.btn_ai_child.setEnabled(True)
        self.btn_ai_child.setText("AI")
        QMessageBox.warning(self, "分类失败", f"AI 二级分类失败：{error}")
    
    def _toggle_url_password_visibility(self, checked):
        """切换 URL 密码可见性"""
        if checked:
            self.txt_password.setEchoMode(QLineEdit.EchoMode.Normal)
            self.btn_show_url_password.setText("隐藏")
        else:
            self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
            self.btn_show_url_password.setText("显示")
    
    def _on_generate_url_password(self):
        """快速生成 URL 密码（默认设置）"""
        pwd = generate_password()
        self.txt_password.setText(pwd)
    
    def _on_generate_url_password_settings(self):
        """打开密码生成器设置弹窗（URL）"""
        from ui.dialogs.password_generator_dialog import PasswordGeneratorDialog
        dlg = PasswordGeneratorDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pwd = dlg.generated_password
            if pwd:
                self.txt_password.setText(pwd)
    
    def on_save(self):
        """保存网址"""
        url = self.txt_url.text().strip()
        title = self.txt_title.text().strip()
        
        if not url:
            QMessageBox.warning(self, "验证失败", "请输入网址")
            self.txt_url.setFocus()
            return
        
        # 如果没有标题，使用域名作为标题
        if not title:
            from urllib.parse import urlparse
            try:
                title = urlparse(url).netloc or url
            except Exception:
                title = url
        
        # 解析标签
        tags_text = self.txt_tags.text().strip()
        tags = [t.strip() for t in tags_text.split(",") if t.strip()]
        
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
        
        self.url_item.title = title
        self.url_item.url = url
        self.url_item.category = category
        self.url_item.remark = self.txt_remark.toPlainText().strip()
        self.url_item.ai_remark = self.txt_ai_remark.toPlainText().strip()
        self.url_item.password = self.txt_password.text().strip()
        self.url_item.set_tags_list(tags)
        
        try:
            if self.is_edit_mode:
                self.url_service.update_url(self.url_item)
            else:
                new_id = self.url_service.add_url(self.url_item)
                self.url_item.id = new_id
            
            self._is_dirty = False
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{str(e)}")
    
    def on_delete(self):
        """删除网址"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除网址「{self.url_item.title or self.url_item.url}」吗？\n删除后将移至回收站。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # 软删除：备份到网址库独立回收站，并删除原记录
                self.url_service.db.soft_delete_url(self.url_item.id, self.url_item.to_dict())
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败：{str(e)}")
    
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
        try:
            self._ai_manager.state_changed.disconnect(self._update_ai_buttons)
            self._ai_manager.task_finished.disconnect(self._on_ai_task_finished)
            self._ai_manager.task_failed.disconnect(self._on_ai_task_failed)
        except Exception:
            pass
        event.accept()
