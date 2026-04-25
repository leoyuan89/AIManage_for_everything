"""
回收站管理对话框
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt
from typing import Optional


class RecycleBinDialog(QDialog):
    """回收站对话框"""
    
    def __init__(self, db_manager, url_db_manager=None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.url_db = url_db_manager
        self.setWindowTitle("回收站")
        self.setMinimumSize(700, 500)
        self.setup_ui()
        self.load_items()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 筛选栏
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("类型："))
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["全部", "账号", "网址"])
        self.cmb_type.currentTextChanged.connect(self.load_items)
        filter_layout.addWidget(self.cmb_type)
        filter_layout.addStretch()
        
        # 清空按钮
        btn_empty = QPushButton("清空回收站")
        btn_empty.setStyleSheet("color: #f44336;")
        btn_empty.clicked.connect(self.on_empty)
        filter_layout.addWidget(btn_empty)
        layout.addLayout(filter_layout)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "类型", "名称/标题", "分类", "删除时间", "剩余天数"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_restore = QPushButton("恢复选中")
        btn_restore.clicked.connect(self.on_restore)
        btn_layout.addWidget(btn_restore)
        
        btn_delete = QPushButton("永久删除")
        btn_delete.setStyleSheet("color: #f44336;")
        btn_delete.clicked.connect(self.on_permanent_delete)
        btn_layout.addWidget(btn_delete)
        
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
    
    def load_items(self):
        type_filter = self.cmb_type.currentText()
        if type_filter == "账号":
            items = self.db.get_recycle_bin_items(item_type='account')
        elif type_filter == "网址":
            items = self.db.get_recycle_bin_items(item_type='url')
        else:
            items = self.db.get_recycle_bin_items()
        
        self.table.setRowCount(len(items))
        for i, item in enumerate(items):
            self.table.setItem(i, 0, QTableWidgetItem(str(item['id'])))
            self.table.setItem(i, 1, QTableWidgetItem(item.get('item_type', '')))
            self.table.setItem(i, 2, QTableWidgetItem(item.get('app_name', item.get('username', item.get('url', '')))))
            self.table.setItem(i, 3, QTableWidgetItem(item.get('category', '')))
            self.table.setItem(i, 4, QTableWidgetItem(str(item.get('deleted_at', ''))))
            
            # 计算剩余天数
            from datetime import datetime
            expires = item.get('expires_at', '')
            if expires:
                try:
                    exp = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                    days = (exp - datetime.now()).days
                    self.table.setItem(i, 5, QTableWidgetItem(f"{days}天"))
                except:
                    self.table.setItem(i, 5, QTableWidgetItem("-"))
            else:
                self.table.setItem(i, 5, QTableWidgetItem("30天"))
    
    def on_restore(self):
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.information(self, "提示", "请选择要恢复的条目")
            return
        
        row = selected[0].row()
        recycle_id = int(self.table.item(row, 0).text())
        item_type = self.table.item(row, 1).text()
        
        try:
            if item_type == 'account':
                restored = self.db.restore_account(recycle_id)
                if restored:
                    QMessageBox.information(self, "成功", f"账号已恢复，新ID：{restored.get('id')}")
            else:
                restored = self.db.restore_url(recycle_id)
                if restored and self.url_db:
                    from models.url_item import URLItem
                    url_item = URLItem.from_dict(restored)
                    new_id = self.url_db.insert_url(url_item.to_dict())
                    QMessageBox.information(self, "成功", f"网址已恢复，新ID：{new_id}")
            self.load_items()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"恢复失败：{str(e)}")
    
    def on_permanent_delete(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        
        row = selected[0].row()
        recycle_id = int(self.table.item(row, 0).text())
        
        reply = QMessageBox.question(
            self, "确认", "确定永久删除该条目？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.permanently_delete_recycle_item(recycle_id)
            self.load_items()
    
    def on_empty(self):
        reply = QMessageBox.question(
            self, "确认", "确定清空回收站？所有条目将被永久删除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            items = self.db.get_recycle_bin_items(include_expired=True)
            for item in items:
                self.db.permanently_delete_recycle_item(item['id'])
            self.load_items()
