"""
批量导入对话框
支持：Markdown (.md)、文本 (.txt)、Excel (.xlsx)
"""
import sys
from typing import List, Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QCheckBox, QAbstractItemView,
    QGroupBox, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QColor

from models.account import Account
from services.import_service import parse_import_file, ImportItem
from services.account_service import AccountService


class ImportDialog(QDialog):
    """批量导入对话框"""
    
    def __init__(self, account_service: AccountService, parent=None):
        super().__init__(parent)
        self.account_service = account_service
        self.import_items: List[ImportItem] = []
        self.file_type: str = ""
        self.file_path: str = ""
        
        self.setup_ui()
    
    def setup_ui(self):
        """设置界面"""
        self.setWindowTitle("批量导入账号")
        self.setMinimumSize(900, 700)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # ===== 标题 =====
        lbl_title = QLabel("批量导入账号")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        # ===== 文件选择区 =====
        file_group = QGroupBox("选择文件")
        file_layout = QHBoxLayout(file_group)
        
        self.txt_file_path = QLineEdit()
        self.txt_file_path.setPlaceholderText("选择 Markdown (.md)、文本 (.txt)、Excel (.xlsx) 或加密备份 (.vault) 文件")
        self.txt_file_path.setReadOnly(True)
        file_layout.addWidget(self.txt_file_path)
        
        btn_browse = QPushButton("浏览...")
        btn_browse.setFixedWidth(100)
        btn_browse.clicked.connect(self.on_browse)
        file_layout.addWidget(btn_browse)
        
        layout.addWidget(file_group)
        
        # ===== 统计信息 =====
        self.lbl_stats = QLabel("请选择要导入的文件")
        self.lbl_stats.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(self.lbl_stats)
        
        # ===== 预览表格 =====
        table_group = QGroupBox("导入预览（可编辑、勾选导入）")
        table_layout = QVBoxLayout(table_group)
        
        # 工具栏
        toolbar = QHBoxLayout()
        
        self.chk_select_all = QCheckBox("全选")
        self.chk_select_all.setChecked(True)
        self.chk_select_all.stateChanged.connect(self.on_select_all)
        toolbar.addWidget(self.chk_select_all)
        
        toolbar.addSpacing(20)
        
        btn_remove_invalid = QPushButton("移除无效项")
        btn_remove_invalid.clicked.connect(self.on_remove_invalid)
        toolbar.addWidget(btn_remove_invalid)
        
        btn_remove_selected = QPushButton("删除选中行")
        btn_remove_selected.clicked.connect(self.on_remove_selected)
        toolbar.addWidget(btn_remove_selected)
        
        toolbar.addStretch()
        
        table_layout.addLayout(toolbar)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "导入", "应用名*", "账号*", "密码*", "网址", "分类", "备注"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 50)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self.on_item_changed)
        
        table_layout.addWidget(self.table)
        
        layout.addWidget(table_group)
        
        # ===== 底部按钮 =====
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setFixedWidth(120)
        btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_cancel)
        
        bottom_layout.addSpacing(10)
        
        self.btn_import = QPushButton("确认导入")
        self.btn_import.setFixedHeight(40)
        self.btn_import.setFixedWidth(120)
        self.btn_import.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
        """)
        self.btn_import.clicked.connect(self.on_import)
        self.btn_import.setEnabled(False)
        bottom_layout.addWidget(self.btn_import)
        
        layout.addLayout(bottom_layout)
    
    def on_browse(self):
        """浏览文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择导入文件",
            "",
            "支持的文件 (*.md *.txt *.xlsx *.xls *.vault);;Markdown (*.md);;文本文件 (*.txt);;Excel (*.xlsx *.xls);;加密备份 (*.vault)"
        )
        
        if not file_path:
            return
        
        self.file_path = file_path
        self.txt_file_path.setText(file_path)
        
        try:
            if file_path.endswith('.vault'):
                # 解密并解析加密备份文件
                self.import_items = self._parse_vault_file(file_path)
                self.file_type = "vault"
            else:
                self.file_type, self.import_items = parse_import_file(file_path)
            
            self.refresh_table()
            self.update_stats()
            self.btn_import.setEnabled(len(self.import_items) > 0)
        except Exception as e:
            QMessageBox.critical(self, "解析失败", f"无法解析文件：\n{str(e)}")
    
    def _parse_vault_file(self, file_path: str) -> List[ImportItem]:
        """解析加密备份文件 (.vault)"""
        from services.export_service import ExportService
        
        # 弹出密码输入对话框
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        
        password, ok = QInputDialog.getText(
            self, "输入主密码",
            "请输入导出此备份时使用的的主密码：",
            QLineEdit.EchoMode.Password
        )
        
        if not ok or not password:
            raise ValueError("未输入密码，已取消导入")
        
        # 尝试解密
        export_service = ExportService(None)
        accounts = export_service.import_from_vault(file_path, password)
        
        if accounts is None:
            raise ValueError("密码错误或文件损坏，无法解密")
        
        # 转换为 ImportItem
        items = []
        for account in accounts:
            item = ImportItem(
                app_name=account.app_name,
                username=account.username,
                password=account.password,
                url=account.url,
                category=account.category,
                remark=account.remark
            )
            # 验证有效性
            if item.app_name and item.username and item.password:
                item.valid = True
            else:
                item.valid = False
                missing = []
                if not item.app_name:
                    missing.append('应用名')
                if not item.username:
                    missing.append('账号')
                if not item.password:
                    missing.append('密码')
                item.error_msg = f"缺少字段：{', '.join(missing)}"
            
            items.append(item)
        
        return items
    
    def refresh_table(self):
        """刷新表格"""
        self.table.setRowCount(len(self.import_items))
        
        for row, item in enumerate(self.import_items):
            # 复选框
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if item.valid else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, chk)
            
            # 应用名
            cell = QTableWidgetItem(item.app_name)
            if not item.app_name:
                cell.setBackground(QColor(255, 200, 200))
            self.table.setItem(row, 1, cell)
            
            # 账号
            cell = QTableWidgetItem(item.username)
            if not item.username:
                cell.setBackground(QColor(255, 200, 200))
            self.table.setItem(row, 2, cell)
            
            # 密码
            cell = QTableWidgetItem(item.password)
            if not item.password:
                cell.setBackground(QColor(255, 200, 200))
            self.table.setItem(row, 3, cell)
            
            # 网址
            self.table.setItem(row, 4, QTableWidgetItem(item.url))
            
            # 分类
            self.table.setItem(row, 5, QTableWidgetItem(item.category))
            
            # 备注
            self.table.setItem(row, 6, QTableWidgetItem(item.remark))
            
            # 如果无效，标记整行
            if not item.valid:
                for col in range(7):
                    item_cell = self.table.item(row, col)
                    if item_cell:
                        item_cell.setToolTip(item.error_msg)
    
    def update_stats(self):
        """更新统计信息"""
        total = len(self.import_items)
        valid = sum(1 for item in self.import_items if item.valid)
        invalid = total - valid
        
        if total == 0:
            self.lbl_stats.setText("未检测到有效数据")
        else:
            stats_text = f"共 {total} 条记录，有效 {valid} 条"
            if invalid > 0:
                stats_text += f"，无效 {invalid} 条（标红显示）"
            self.lbl_stats.setText(stats_text)
    
    def on_select_all(self, state):
        """全选/取消全选"""
        check_state = Qt.CheckState.Checked if state == Qt.CheckState.Checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(check_state)
    
    def on_remove_invalid(self):
        """移除无效项"""
        self.import_items = [item for item in self.import_items if item.valid]
        self.refresh_table()
        self.update_stats()
    
    def on_remove_selected(self):
        """删除选中行"""
        rows_to_remove = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                rows_to_remove.append(row)
        
        # 从后往前删除，避免索引变化
        for row in reversed(rows_to_remove):
            if row < len(self.import_items):
                self.import_items.pop(row)
        
        self.refresh_table()
        self.update_stats()
    
    def on_item_changed(self, item):
        """表格项编辑后更新数据"""
        row = item.row()
        col = item.column()
        
        if row >= len(self.import_items):
            return
        
        import_item = self.import_items[row]
        value = item.text()
        
        # 更新对应字段
        if col == 1:
            import_item.app_name = value
        elif col == 2:
            import_item.username = value
        elif col == 3:
            import_item.password = value
        elif col == 4:
            import_item.url = value
        elif col == 5:
            import_item.category = value
        elif col == 6:
            import_item.remark = value
        
        # 重新验证
        if import_item.app_name and import_item.username and import_item.password:
            import_item.valid = True
            import_item.error_msg = ""
            item.setBackground(QColor(255, 255, 255))
        else:
            import_item.valid = False
            missing = []
            if not import_item.app_name:
                missing.append('应用名')
            if not import_item.username:
                missing.append('账号')
            if not import_item.password:
                missing.append('密码')
            import_item.error_msg = f"缺少字段：{', '.join(missing)}"
            if col in [1, 2, 3] and not value:
                item.setBackground(QColor(255, 200, 200))
    
    def on_import(self):
        """执行导入"""
        # 收集选中的有效项
        items_to_import = []
        for row, item in enumerate(self.import_items):
            chk_item = self.table.item(row, 0)
            if chk_item and chk_item.checkState() == Qt.CheckState.Checked and item.valid:
                items_to_import.append(item)
        
        if not items_to_import:
            QMessageBox.warning(self, "导入失败", "没有选中的有效记录可供导入")
            return
        
        # 检查重复
        existing = self.account_service.get_all_accounts()
        existing_keys = {(acc.app_name, acc.username) for acc in existing}
        
        duplicates = []
        new_items = []
        
        for item in items_to_import:
            key = (item.app_name, item.username)
            if key in existing_keys:
                duplicates.append(item)
            else:
                new_items.append(item)
        
        # 提示重复
        if duplicates:
            reply = QMessageBox.question(
                self,
                "发现重复",
                f"检测到 {len(duplicates)} 条重复记录（应用名+账号相同），是否跳过这些记录导入其余 {len(new_items)} 条？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        # 执行导入
        success_count = 0
        for item in new_items:
            try:
                account = item.to_account()
                self.account_service.add_account(account)
                success_count += 1
            except Exception as e:
                print(f"导入失败：{item.app_name} - {e}")
        
        # 显示结果
        QMessageBox.information(
            self,
            "导入完成",
            f"成功导入 {success_count} 条记录\n"
            f"跳过重复 {len(duplicates)} 条\n"
            f"失败 {len(new_items) - success_count} 条"
        )
        
        self.accept()
