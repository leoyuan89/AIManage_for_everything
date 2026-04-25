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
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.database import DatabaseManager
from core.crypto import CryptoManager
from services.account_service import AccountService
from services.export_service import ExportService
from models.account import Account


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
        self.setWindowTitle(f"导出{'账号' if self.vault_type == 'accounts' else '网址'}")
        self.setMinimumSize(500, 580)
        
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
        
        self.cmb_category = QComboBox()
        if is_account:
            self.cmb_category.addItems(['金融', '社交', '邮箱', '游戏', '工作', '其他'])
        else:
            self.cmb_category.addItems(['常用', '工具', '娱乐', '学习', '工作', '其他'])
        self.cmb_category.setEnabled(False)
        range_layout.addWidget(self.cmb_category)
        
        # 范围选择联动
        self.rad_category.toggled.connect(self.cmb_category.setEnabled)
        
        layout.addWidget(range_group)
        
        # 导出格式
        format_group = QGroupBox("导出格式")
        format_layout = QVBoxLayout(format_group)
        
        self.cmb_format = QComboBox()
        self.cmb_format.addItems([
            "Excel 表格 (.xlsx)",
            "加密备份 (.vault)"
        ])
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
            lbl_warning.setStyleSheet("color: #f44336; font-size: 11px;")
            lbl_warning.setWordWrap(True)
            excel_layout.addWidget(lbl_warning)
        else:
            self.chk_include_password = None
            lbl_warning = QLabel("提示：网址导出不包含敏感信息，可直接使用。")
            lbl_warning.setStyleSheet("color: #2196F3; font-size: 11px;")
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
        btn_export.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        btn_export.clicked.connect(self.on_export_clicked)
        button_layout.addWidget(btn_export)
        
        layout.addLayout(button_layout)
    
    def on_format_changed(self, index):
        """格式切换"""
        if index == 0:  # Excel
            self.group_excel.show()
            self.group_vault.hide()
        else:  # 加密备份
            self.group_excel.hide()
            self.group_vault.show()
    
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
            category = self.cmb_category.currentText()
            if is_account:
                items = self.account_service.get_accounts_by_category(category)
            else:
                items = self.url_service.get_urls_by_category(category) if self.url_service else []
            scope_name = category
        else:
            # TODO: 获取当前分类
            if is_account:
                items = self.account_service.get_all_accounts()
            else:
                items = self.url_service.get_all_urls() if self.url_service else []
            scope_name = "当前分类"
        
        if not items:
            QMessageBox.warning(self, "提示", f"{scope_name}分类下没有可导出的{entity_name}")
            return
        
        # 获取导出格式
        format_index = self.cmb_format.currentIndex()
        
        if format_index == 0:  # Excel
            file_path, _ = QFileDialog.getSaveFileName(
                self, "保存 Excel 文件", 
                f"password_export_{scope_name}", 
                "Excel 文件 (*.xlsx)"
            )
            if file_path:
                if not file_path.endswith('.xlsx'):
                    file_path += '.xlsx'
                
                if is_account:
                    include_password = self.chk_include_password.isChecked()
                    success = self.export_service.export_to_excel(items, file_path, include_password)
                else:
                    success = self.export_service.export_urls_to_excel(items, file_path)
                
                if success:
                    QMessageBox.information(
                        self, "导出成功",
                        f"成功导出 {len(items)} 个{entity_name}到：\n{file_path}"
                    )
                    self.accept()
                else:
                    QMessageBox.critical(self, "导出失败", "导出过程中发生错误")
        
        else:  # 加密备份
            if not is_account:
                QMessageBox.warning(self, "暂不支持", "网址暂不支持加密备份导出")
                return
            
            file_path, _ = QFileDialog.getSaveFileName(
                self, "保存加密备份", "", "Vault 文件 (*.vault)"
            )
            if file_path:
                if not file_path.endswith('.vault'):
                    file_path += '.vault'
                
                # 确定加密密码
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
                    password_hint = "独立密码"
                else:
                    # 使用主密码
                    backup_password = None
                    password_hint = "主密码"
                
                if self.export_service.export_encrypted_backup(items, file_path, backup_password):
                    QMessageBox.information(
                        self, "导出成功",
                        f"成功导出 {len(items)} 个{entity_name}的加密备份到：\n{file_path}\n\n"
                        f"提示：加密备份使用 {password_hint} 加密，恢复时需要输入正确的密码。"
                    )
                    self.accept()
                else:
                    QMessageBox.critical(self, "导出失败", "加密备份导出过程中发生错误")
