"""
导出对话框
支持：Excel 导出、加密备份
"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QCheckBox, QComboBox,
    QFileDialog, QMessageBox, QGroupBox, QRadioButton,
    QButtonGroup, QProgressBar, QLineEdit
)

from core.category_utils import format_category_path
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from core.database import DatabaseManager
from core.crypto import CryptoManager
from core.theme_manager import ThemeManager, ThemeColors
from services.account_service import AccountService
from services.export_service import ExportService
from models.account import Account


class _ExportWorkerThread(QThread):
    """后台线程：执行导出操作（Excel / 加密备份 / CSV / HTML）"""
    finished_export = pyqtSignal(bool, str)  # (success, error_msg)

    def __init__(self, export_service, export_type, items, file_path, extra=None, parent=None):
        super().__init__(parent)
        self.export_service = export_service
        self.export_type = export_type
        self.items = items
        self.file_path = file_path
        self.extra = extra or {}

    def run(self):
        try:
            if self.export_type == 'excel':
                success = self.export_service.export_to_excel(
                    self.items, self.file_path, self.extra.get('include_password', False)
                )
            elif self.export_type == 'excel_urls':
                success = self.export_service.export_urls_to_excel(self.items, self.file_path)
            elif self.export_type == 'vault':
                success = self.export_service.export_encrypted_backup(
                    self.items, self.file_path, self.extra.get('backup_password')
                )
            elif self.export_type == 'bitwarden':
                success = self.export_service.export_bitwarden_csv(self.items, self.file_path)
            elif self.export_type == 'html':
                success = self.export_service.export_urls_to_html(self.items, self.file_path)
            else:
                success = False

            if success:
                self.finished_export.emit(True, "")
            else:
                self.finished_export.emit(False, "导出过程中发生错误")
        except Exception as e:
            self.finished_export.emit(False, str(e))


class ExportDialog(QDialog):
    """导出对话框"""
    
    def __init__(self, db_manager: DatabaseManager, account_service: AccountService,
                 export_service: ExportService, vault_type='accounts', url_service=None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.account_service = account_service
        self.export_service = export_service
        self.vault_type = vault_type
        self.url_service = url_service
        
        self.setup_ui()
    
    def setup_ui(self):
        """设置界面"""
        colors = ThemeManager.instance().colors
        self.setWindowTitle(f"导出{'账号' if self.vault_type == 'accounts' else '网址'}")
        self.setMinimumSize(600, 800)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        is_account = self.vault_type == 'accounts'
        entity_name = "账号" if is_account else "网址"
        lbl_title = QLabel(f"导出{entity_name}数据")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        # 导出范围
        range_group = QGroupBox("导出范围")
        range_layout = QVBoxLayout(range_group)
        
        self.rad_all = QRadioButton(f"全部{entity_name}")
        self.rad_all.setChecked(True)
        range_layout.addWidget(self.rad_all)
        
        self.rad_current = QRadioButton(f"当前分类{entity_name}")
        range_layout.addWidget(self.rad_current)
        
        self.rad_category = QRadioButton("指定分类")
        range_layout.addWidget(self.rad_category)
        
        # 级联分类选择（主类 + 子类）
        category_select_layout = QHBoxLayout()
        
        self.cmb_parent = QComboBox()
        self.cmb_parent.setEditable(True)
        self.cmb_parent.setPlaceholderText("主分类")
        self.cmb_parent.setFixedHeight(32)
        self.cmb_parent.currentTextChanged.connect(self._on_parent_changed)
        category_select_layout.addWidget(self.cmb_parent)
        
        lbl_sep = QLabel(">")
        lbl_sep.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 14px; font-weight: bold;")
        lbl_sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sep.setFixedWidth(20)
        category_select_layout.addWidget(lbl_sep)
        
        self.cmb_child = QComboBox()
        self.cmb_child.setEditable(True)
        self.cmb_child.setPlaceholderText("子分类（可选）")
        self.cmb_child.setFixedHeight(32)
        category_select_layout.addWidget(self.cmb_child)
        
        range_layout.addLayout(category_select_layout)
        self._load_categories()
        
        # 范围选择联动
        self.cmb_parent.setEnabled(False)
        self.cmb_child.setEnabled(False)
        self.rad_category.toggled.connect(self._on_category_toggled)
        
        layout.addWidget(range_group)
        
        # 导出格式
        format_group = QGroupBox("导出格式")
        format_layout = QVBoxLayout(format_group)
        
        self.cmb_format = QComboBox()
        formats = [
            "Excel 表格 (.xlsx)",
            "加密备份 (.vault)"
        ]
        if is_account:
            formats.append("Bitwarden CSV (.csv)")
        if not is_account:
            formats.append("HTML 书签 (.html)")
        self.cmb_format.addItems(formats)
        self.cmb_format.currentIndexChanged.connect(self.on_format_changed)
        format_layout.addWidget(self.cmb_format)
        
        layout.addWidget(format_group)
        
        # Excel 选项
        self.group_excel = QGroupBox("Excel 选项")
        excel_layout = QVBoxLayout(self.group_excel)
        
        if is_account:
            self.chk_include_password = QCheckBox("包含密码（明文）")
            self.chk_include_password.setChecked(True)
            excel_layout.addWidget(self.chk_include_password)
            
            lbl_warning = QLabel("警告：导出包含密码的 Excel 文件存在安全风险，请妥善保管！")
            lbl_warning.setStyleSheet(f"color: {colors.accent_red}; font-size: 11px;")
            lbl_warning.setWordWrap(True)
            excel_layout.addWidget(lbl_warning)
        else:
            self.chk_include_password = None
            lbl_warning = QLabel("提示：网址导出不包含敏感信息，可直接使用。")
            lbl_warning.setStyleSheet(f"color: {colors.accent_blue}; font-size: 11px;")
            lbl_warning.setWordWrap(True)
            excel_layout.addWidget(lbl_warning)
        
        layout.addWidget(self.group_excel)
        
        # 加密备份选项
        self.group_vault = QGroupBox("加密备份选项")
        vault_layout = QVBoxLayout(self.group_vault)
        
        lbl_vault_info = QLabel("加密备份可跨设备恢复数据。")
        lbl_vault_info.setWordWrap(True)
        vault_layout.addWidget(lbl_vault_info)
        
        # 密码选择
        self.chk_custom_password = QCheckBox("使用独立密码加密（不勾选则使用主密码）")
        self.chk_custom_password.stateChanged.connect(self.on_custom_password_changed)
        vault_layout.addWidget(self.chk_custom_password)
        
        # 独立密码输入（默认隐藏）
        self.vault_password_widget = QWidget()
        password_layout = QVBoxLayout(self.vault_password_widget)
        password_layout.setContentsMargins(20, 5, 0, 5)
        
        # 密码
        lbl_vault_pwd = QLabel("备份密码：")
        password_layout.addWidget(lbl_vault_pwd)
        
        self.txt_vault_password = QLineEdit()
        self.txt_vault_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_vault_password.setPlaceholderText("请输入备份密码（至少6位）")
        self.txt_vault_password.setFixedHeight(32)
        password_layout.addWidget(self.txt_vault_password)
        
        # 确认密码
        lbl_vault_pwd2 = QLabel("确认密码：")
        password_layout.addWidget(lbl_vault_pwd2)
        
        self.txt_vault_password2 = QLineEdit()
        self.txt_vault_password2.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_vault_password2.setPlaceholderText("请再次输入备份密码")
        self.txt_vault_password2.setFixedHeight(32)
        password_layout.addWidget(self.txt_vault_password2)
        
        self.vault_password_widget.hide()
        vault_layout.addWidget(self.vault_password_widget)
        
        self.group_vault.hide()  # 默认隐藏
        layout.addWidget(self.group_vault)
        
        layout.addStretch()
        
        # 按钮区
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancel)
        
        button_layout.addSpacing(10)
        
        btn_export = QPushButton("导出")
        btn_export.setFixedHeight(40)
        btn_export.setFixedWidth(100)
        btn_export.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_green};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_green_dark};
            }}
        """)
        btn_export.clicked.connect(self.on_export_clicked)
        button_layout.addWidget(btn_export)
        
        layout.addLayout(button_layout)
    
    def _load_categories(self):
        """加载主类下拉框"""
        is_account = self.vault_type == 'accounts'
        try:
            if is_account:
                tree = self.account_service.get_category_tree()
            else:
                tree = self.url_service.get_category_tree() if self.url_service else {}
        except Exception:
            tree = {}
        
        self.cmb_parent.clear()
        self.cmb_parent.addItem("请选择")
        self.cmb_parent.addItems(sorted(tree.keys()))
    
    def _on_parent_changed(self, parent_name):
        """主类改变时更新子类下拉框"""
        self.cmb_child.clear()
        self.cmb_child.addItem("")  # 空表示无子类（导出整个主类）
        
        is_account = self.vault_type == 'accounts'
        try:
            if is_account:
                tree = self.account_service.get_category_tree()
            else:
                tree = self.url_service.get_category_tree() if self.url_service else {}
        except Exception:
            tree = {}
        
        if parent_name in tree:
            for child in sorted(tree[parent_name]['children']):
                self.cmb_child.addItem(child)
    
    def _get_selected_category(self) -> str:
        """获取选中的分类路径"""
        parent = self.cmb_parent.currentText().strip()
        child = self.cmb_child.currentText().strip()
        if not parent or parent == "请选择":
            return ""
        return format_category_path(parent, child if child else None)
    
    def _on_category_toggled(self, checked):
        """指定分类选项切换"""
        self.cmb_parent.setEnabled(checked)
        self.cmb_child.setEnabled(checked)
    
    def on_format_changed(self, index):
        """格式切换"""
        is_account = self.vault_type == 'accounts'
        if index == 0:  # Excel
            self.group_excel.show()
            self.group_vault.hide()
        elif index == 1:  # 加密备份
            self.group_excel.hide()
            self.group_vault.show()
        elif is_account and index == 2:  # Bitwarden CSV
            self.group_excel.show()
            self.group_vault.hide()
        else:  # HTML 书签
            self.group_excel.hide()
            self.group_vault.hide()
    
    def on_custom_password_changed(self, state):
        """独立密码选项切换"""
        if state == 2:  # Qt.CheckState.Checked = 2
            self.vault_password_widget.show()
        else:
            self.vault_password_widget.hide()
    
    def on_export_clicked(self):
        """导出按钮点击"""
        is_account = self.vault_type == 'accounts'
        entity_name = "账号" if is_account else "网址"

        # 获取导出范围
        if self.rad_all.isChecked():
            if is_account:
                items = self.account_service.get_all_accounts()
            else:
                items = self.url_service.get_all_urls() if self.url_service else []
            scope_name = "全部"
        elif self.rad_category.isChecked():
            category = self._get_selected_category()
            if not category:
                QMessageBox.warning(self, "提示", "请选择要导出的分类")
                return
            if is_account:
                items = self.account_service.get_accounts_by_category(category)
            else:
                items = self.url_service.get_urls_by_category(category) if self.url_service else []
            scope_name = category
        else:
            if is_account:
                items = self.account_service.get_all_accounts()
            else:
                items = self.url_service.get_all_urls() if self.url_service else []
            scope_name = "当前分类"

        if not items:
            QMessageBox.warning(self, "提示", f"{scope_name}分类下没有可导出的{entity_name}")
            return

        format_index = self.cmb_format.currentIndex()

        # 根据格式获取文件路径，然后启动后台线程导出
        if format_index == 0:  # Excel
            file_path, _ = QFileDialog.getSaveFileName(
                self, "保存 Excel 文件",
                f"password_export_{scope_name}",
                "Excel 文件 (*.xlsx)"
            )
            if file_path:
                if not file_path.endswith('.xlsx'):
                    file_path += '.xlsx'
                export_type = 'excel' if is_account else 'excel_urls'
                extra = {'include_password': self.chk_include_password.isChecked()} if is_account else {}
                self._start_export_thread(export_type, items, file_path, extra, entity_name)

        elif format_index == 1:  # 加密备份
            if not is_account:
                QMessageBox.warning(self, "暂不支持", "网址暂不支持加密备份导出")
                return
            file_path, _ = QFileDialog.getSaveFileName(
                self, "保存加密备份", "", "Vault 文件 (*.vault)"
            )
            if file_path:
                if not file_path.endswith('.vault'):
                    file_path += '.vault'
                use_custom_password = self.chk_custom_password.isChecked()
                backup_password = None
                if use_custom_password:
                    pwd1 = self.txt_vault_password.text().strip()
                    pwd2 = self.txt_vault_password2.text().strip()
                    if len(pwd1) < 6:
                        QMessageBox.warning(self, "验证失败", "备份密码至少需要 6 位")
                        return
                    if pwd1 != pwd2:
                        QMessageBox.warning(self, "验证失败", "两次输入的备份密码不一致")
                        return
                    backup_password = pwd1
                extra = {'backup_password': backup_password}
                self._start_export_thread('vault', items, file_path, extra, entity_name, backup_hint="独立密码" if backup_password else "主密码")

        elif is_account and format_index == 2:  # Bitwarden CSV
            file_path, _ = QFileDialog.getSaveFileName(
                self, "保存 Bitwarden CSV 文件",
                f"bitwarden_export_{scope_name}",
                "CSV 文件 (*.csv)"
            )
            if file_path:
                if not file_path.endswith('.csv'):
                    file_path += '.csv'
                self._start_export_thread('bitwarden', items, file_path, {}, entity_name, format_hint="Bitwarden CSV")

        else:  # HTML 书签
            if is_account:
                QMessageBox.warning(self, "暂不支持", "账号暂不支持 HTML 书签导出")
                return
            file_path, _ = QFileDialog.getSaveFileName(
                self, "保存 HTML 书签",
                f"bookmarks_{scope_name}",
                "HTML 文件 (*.html)"
            )
            if file_path:
                if not file_path.endswith('.html'):
                    file_path += '.html'
                self._start_export_thread('html', items, file_path, {}, entity_name, format_hint="HTML 书签")

    def _start_export_thread(self, export_type, items, file_path, extra, entity_name, format_hint="", backup_hint=""):
        """启动后台导出线程"""
        self._export_thread = _ExportWorkerThread(
            self.export_service, export_type, items, file_path, extra, parent=self
        )
        self._export_thread.finished_export.connect(
            lambda success, err: self._on_export_finished(success, err, len(items), entity_name, file_path, format_hint, backup_hint)
        )
        self._export_thread.start()

    def _on_export_finished(self, success, error_msg, count, entity_name, file_path, format_hint="", backup_hint=""):
        """导出完成回调（UI 线程）"""
        if success:
            msg = f"成功导出 {count} 个{entity_name}到：\n{file_path}"
            if format_hint:
                msg += f"\n\n提示：可在 {format_hint} 中导入此文件。"
            if backup_hint:
                msg += f"\n\n提示：加密备份使用 {backup_hint} 加密，恢复时需要输入正确的密码。"
            QMessageBox.information(self, "导出成功", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "导出失败", f"导出过程中发生错误：\n{error_msg}")
