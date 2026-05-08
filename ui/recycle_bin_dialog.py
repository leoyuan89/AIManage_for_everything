"""
回收站管理对话框
支持密码库回收站和网址库回收站（根据当前 tab 自动区分）
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)
from PyQt6.QtCore import Qt
from typing import Optional
import logging

from core.theme_manager import ThemeManager, ThemeColors

logger = logging.getLogger(__name__)


class RecycleBinDialog(QDialog):
    """回收站对话框"""

    def __init__(self, db_manager, vault_type: str = 'accounts', parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.vault_type = vault_type  # 'accounts' 或 'urls'
        self.setWindowTitle("密码库回收站" if vault_type == 'accounts' else "网址库回收站")
        self.setMinimumSize(700, 500)
        self.setup_ui()
        self.load_items()

    def setup_ui(self):
        colors = ThemeManager.instance().colors
        layout = QVBoxLayout(self)

        # 标题栏
        header_layout = QHBoxLayout()
        self.lbl_title = QLabel(
            "回收站中的密码库账号（30天后自动清理）" if self.vault_type == 'accounts'
            else "回收站中的网址（30天后自动清理）"
        )
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()

        # 清空按钮
        btn_empty = QPushButton("清空回收站")
        btn_empty.setStyleSheet(f"color: {colors.accent_red};")
        btn_empty.clicked.connect(self.on_empty)
        header_layout.addWidget(btn_empty)
        layout.addLayout(header_layout)

        # 表格
        self.table = QTableWidget()
        if self.vault_type == 'accounts':
            self.table.setColumnCount(6)
            self.table.setHorizontalHeaderLabels(["ID", "应用名", "用户名", "分类", "删除时间", "剩余天数"])
        else:
            self.table.setColumnCount(6)
            self.table.setHorizontalHeaderLabels(["ID", "标题", "网址", "分类", "删除时间", "剩余天数"])
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
        btn_delete.setStyleSheet(f"color: {colors.accent_red};")
        btn_delete.clicked.connect(self.on_permanent_delete)
        btn_layout.addWidget(btn_delete)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def load_items(self):
        if self.vault_type == 'accounts':
            items = self.db.get_recycle_bin_items(item_type='account')
        else:
            items = self.db.get_recycle_bin_items()

        self.table.setRowCount(len(items))
        for i, item in enumerate(items):
            self.table.setItem(i, 0, QTableWidgetItem(str(item['id'])))

            if self.vault_type == 'accounts':
                self.table.setItem(i, 1, QTableWidgetItem(item.get('app_name', '')))
                self.table.setItem(i, 2, QTableWidgetItem(item.get('username', '')))
            else:
                self.table.setItem(i, 1, QTableWidgetItem(item.get('title', '')))
                self.table.setItem(i, 2, QTableWidgetItem(item.get('url', '')[:40]))

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
                except Exception:
                    logger.debug("回收站条目剩余天数计算失败", exc_info=True)
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

        try:
            if self.vault_type == 'accounts':
                restored = self.db.restore_account(recycle_id)
                if restored:
                    QMessageBox.information(self, "成功", f"账号已恢复，新ID：{restored.get('id')}")
            else:
                restored = self.db.restore_url(recycle_id)
                if restored:
                    QMessageBox.information(self, "成功", f"网址已恢复，新ID：{restored.get('id')}")
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
