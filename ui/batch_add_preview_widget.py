"""
批量导入预览组件
采用 QTableView + QAbstractTableModel 架构
支持：勾选、编辑、批量修改分类、智能推断分类、状态预检展示
"""
from typing import List, Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableView, QComboBox,
    QStyledItemDelegate, QMessageBox, QMenu, QAbstractItemView,
    QHeaderView
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QModelIndex, QAbstractTableModel
from PyQt6.QtGui import QColor

from core.repositories import BatchItem, VaultRepository


class CategoryDelegate(QStyledItemDelegate):
    """分类列下拉框委托"""

    def __init__(self, categories: List[str], parent=None):
        super().__init__(parent)
        self._categories = categories

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(self._categories)
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.EditRole)
        idx = editor.findText(value or '')
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class BatchItemTableModel(QAbstractTableModel):
    """批量导入表格模型"""

    def __init__(self, items: List[BatchItem] = None, vault_type: str = 'accounts',
                 categories: List[str] = None, parent=None):
        super().__init__(parent)
        self._items = items or []
        self._vault_type = vault_type
        self._categories = categories or []
        self._password_visible = False  # 密码默认掩码

        if vault_type == 'accounts':
            self._headers = ['☑', '应用', '账号', '密码', '网址', '分类', '备注', '标签', '状态']
            self._editable_cols = {1, 2, 3, 4, 5, 6, 7}
            self._category_col = 5
            self._password_col = 3
        else:
            self._headers = ['☑', '标题', '网址', '分类', '标签', '备注', '状态']
            self._editable_cols = {1, 2, 3, 4, 5}
            self._category_col = 3
            self._password_col = -1

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return len(self._headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._items):
            return None

        item = self._items[row]

        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if item.confirmed else Qt.CheckState.Unchecked

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._get_display_data(item, col)

        if role == Qt.ItemDataRole.ForegroundRole and col == self.columnCount() - 1:
            return self._get_status_color(item.status)

        return None

    def _get_display_data(self, item: BatchItem, col: int):
        if self._vault_type == 'accounts':
            mapping = {
                1: item.app,
                2: item.account,
                3: item.password if self._password_visible else '***',
                4: item.url,
                5: item.category,
                6: item.remark,
                7: ', '.join(item.tags) if item.tags else '',
                8: item.status,
            }
        else:
            mapping = {
                1: item.title,
                2: item.url,
                3: item.category,
                4: ', '.join(item.tags) if item.tags else '',
                5: item.remark,
                6: item.status,
            }
        return mapping.get(col, '')

    def _get_status_color(self, status: str):
        if status == "就绪":
            return QColor("#4CAF50")
        elif status.startswith("重复"):
            return QColor("#FF9800")
        elif status.startswith("格式错误"):
            return QColor("#f44336")
        elif "已归入" in status or "已推断分类" in status:
            return QColor("#2196F3")
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False

        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._items):
            return False

        item = self._items[row]

        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            item.confirmed = (value == Qt.CheckState.Checked)
            self.dataChanged.emit(index, index, [role])
            return True

        if role == Qt.ItemDataRole.EditRole and col in self._editable_cols:
            self._set_item_data(item, col, value)
            self.dataChanged.emit(index, index, [role])
            return True

        return False

    def _set_item_data(self, item: BatchItem, col: int, value):
        value = str(value) if value is not None else ''
        if self._vault_type == 'accounts':
            mapping = {
                1: ('app', lambda x: str(x)),
                2: ('account', lambda x: str(x)),
                3: ('password', lambda x: str(x)),
                4: ('url', lambda x: str(x)),
                5: ('category', lambda x: str(x)),
                6: ('remark', lambda x: str(x)),
                7: ('tags', lambda x: [t.strip() for t in str(x).split(',') if t.strip()]),
            }
        else:
            mapping = {
                1: ('title', lambda x: str(x)),
                2: ('url', lambda x: str(x)),
                3: ('category', lambda x: str(x)),
                4: ('tags', lambda x: [t.strip() for t in str(x).split(',') if t.strip()]),
                5: ('remark', lambda x: str(x)),
            }

        if col in mapping:
            attr_name, converter = mapping[col]
            setattr(item, attr_name, converter(value))

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        col = index.column()
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        if col == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        elif col in self._editable_cols:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        return None

    def set_items(self, items: List[BatchItem]):
        """重置数据"""
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def set_password_visible(self, visible: bool):
        """切换密码显示/掩码"""
        if self._password_visible == visible:
            return
        self._password_visible = visible
        if self._password_col >= 0 and self._items:
            self.dataChanged.emit(
                self.index(0, self._password_col),
                self.index(self.rowCount() - 1, self._password_col),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole]
            )

    def get_items(self) -> List[BatchItem]:
        return self._items

    def set_category_for_rows(self, rows: List[int], category: str):
        """批量设置指定行的分类"""
        changed = False
        for row in rows:
            if 0 <= row < len(self._items):
                self._items[row].category = category
                changed = True
        if changed and rows:
            top_left = self.index(min(rows), 0)
            bottom_right = self.index(max(rows), self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right)

    def set_all_checked(self, checked: bool):
        """全选或全不选"""
        for item in self._items:
            item.confirmed = checked
        if self._items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, 0),
                [Qt.ItemDataRole.CheckStateRole]
            )

    def invert_selection(self):
        """反选"""
        for item in self._items:
            item.confirmed = not item.confirmed
        if self._items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, 0),
                [Qt.ItemDataRole.CheckStateRole]
            )


class BatchAddPreviewWidget(QWidget):
    """批量导入预览组件"""

    items_changed = pyqtSignal()

    def __init__(self, parent=None, repo: VaultRepository = None):
        super().__init__(parent)
        self._repo = repo
        self._vault_type = 'accounts'
        self._categories = []
        self._model = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 统计标签（顶部）
        self._lbl_stats = QLabel("共 0 条 | 已勾选 0 条")
        self._lbl_stats.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self._lbl_stats)

        # 表格
        self._table = QTableView()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet("""
            QTableView {
                border: 1px solid #ddd;
                gridline-color: #eee;
            }
            QTableView::item {
                padding: 4px;
            }
        """)
        layout.addWidget(self._table)

        # 底部操作栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._btn_select_all = QPushButton("全选")
        self._btn_select_none = QPushButton("全不选")
        self._btn_invert = QPushButton("反选")
        self._btn_batch_category = QPushButton("批量修改分类 ▼")
        self._btn_auto_classify = QPushButton("智能推断分类")
        self._btn_toggle_password = QPushButton("👁 显示密码")

        self._btn_select_all.clicked.connect(self._on_select_all)
        self._btn_select_none.clicked.connect(self._on_select_none)
        self._btn_invert.clicked.connect(self._on_invert)
        self._btn_batch_category.clicked.connect(self._on_batch_category)
        self._btn_auto_classify.clicked.connect(self._on_auto_classify)
        self._btn_toggle_password.clicked.connect(self._on_toggle_password)

        toolbar.addWidget(self._btn_select_all)
        toolbar.addWidget(self._btn_select_none)
        toolbar.addWidget(self._btn_invert)
        toolbar.addSpacing(16)
        toolbar.addWidget(self._btn_batch_category)
        toolbar.addWidget(self._btn_auto_classify)
        toolbar.addWidget(self._btn_toggle_password)
        toolbar.addStretch()

        layout.addLayout(toolbar)

    def set_items(self, items: List[BatchItem], vault_type: str, categories: List[str]):
        """设置预览数据"""
        self._vault_type = vault_type
        self._categories = categories

        self._model = BatchItemTableModel(items, vault_type, categories, parent=self)
        self._table.setModel(self._model)

        # 设置分类列委托
        delegate = CategoryDelegate(categories, self._table)
        self._table.setItemDelegateForColumn(self._model._category_col, delegate)

        # 调整列宽
        self._table.resizeColumnsToContents()
        # 让最后一列（状态）自动填充剩余空间
        last_col = self._model.columnCount() - 1
        self._table.horizontalHeader().setSectionResizeMode(
            last_col, QHeaderView.ResizeMode.Stretch
        )

        self._update_stats()

    def _update_stats(self):
        if self._model is None:
            self._lbl_stats.setText("共 0 条 | 已勾选 0 条")
            return
        items = self._model.get_items()
        total = len(items)
        confirmed = sum(1 for i in items if i.confirmed)
        ready = sum(1 for i in items if i.status == "就绪")
        dup = sum(1 for i in items if i.status.startswith("重复"))
        err = sum(1 for i in items if i.status.startswith("格式错误"))
        self._lbl_stats.setText(
            f"共 {total} 条 | 已勾选 {confirmed} 条 | "
            f"就绪 {ready} / 重复 {dup} / 错误 {err}"
        )

    def _on_select_all(self):
        self._model.set_all_checked(True)
        self._update_stats()
        self.items_changed.emit()

    def _on_select_none(self):
        self._model.set_all_checked(False)
        self._update_stats()
        self.items_changed.emit()

    def _on_invert(self):
        self._model.invert_selection()
        self._update_stats()
        self.items_changed.emit()

    def _on_batch_category(self):
        if not self._categories:
            QMessageBox.warning(self, "提示", "暂无可用分类")
            return

        menu = QMenu(self)
        for cat in self._categories:
            action = menu.addAction(cat)
            action.triggered.connect(lambda checked=False, c=cat: self._apply_batch_category(c))

        menu.exec(
            self._btn_batch_category.mapToGlobal(
                QPoint(0, self._btn_batch_category.height())
            )
        )

    def _apply_batch_category(self, category: str):
        # 优先应用到选中的行，若没有选中则应用到所有已勾选行
        selected = self._table.selectionModel().selectedRows()
        if selected:
            rows = [idx.row() for idx in selected]
        else:
            rows = [i for i, item in enumerate(self._model.get_items()) if item.confirmed]

        if rows:
            self._model.set_category_for_rows(rows, category)
            self.items_changed.emit()

    def _on_auto_classify(self):
        if self._repo is None:
            QMessageBox.warning(self, "提示", "未提供仓库实例，无法推断分类")
            return

        selected = self._table.selectionModel().selectedRows()
        if selected:
            rows = [idx.row() for idx in selected]
        else:
            rows = [i for i, item in enumerate(self._model.get_items()) if item.confirmed]

        if not rows:
            QMessageBox.information(self, "提示", "请先勾选需要推断分类的条目")
            return

        self._btn_auto_classify.setEnabled(False)
        self._btn_auto_classify.setText("推断中...")

        try:
            for row in rows:
                item = self._model.get_items()[row]
                if self._vault_type == 'accounts':
                    key_text = item.app
                else:
                    key_text = item.url or item.title
                if key_text:
                    try:
                        new_cat = self._repo.auto_classify(key_text)
                        item.category = new_cat
                        if "已推断分类" not in item.status:
                            item.status = f"已推断分类：{new_cat}"
                    except Exception:
                        pass

            # 刷新所有变动的行
            self._model.dataChanged.emit(
                self._model.index(min(rows), 0),
                self._model.index(max(rows), self._model.columnCount() - 1)
            )
            self._update_stats()
            self.items_changed.emit()
        finally:
            self._btn_auto_classify.setEnabled(True)
            self._btn_auto_classify.setText("智能推断分类")

    def set_preview_data(self, preview_data: dict):
        """接收标准 preview_data，转换为 BatchItem 列表后渲染

        Args:
            preview_data: 标准 preview_data 字典，包含 operation_type, target_vault, items 等
        """
        items = preview_data.get("items", [])
        target_vault = preview_data.get("target_vault", "account")
        vault_type = 'urls' if 'url' in str(target_vault).lower() else 'accounts'

        batch_items: List[BatchItem] = []
        for item in items:
            raw_data = item.get("raw_data", {}) or {}
            fields = item.get("fields", [])

            # 从 fields 中提取常用字段
            field_map = {f.get("field_name", ""): f.get("new_value", "") for f in fields}

            password = field_map.get("密码") or raw_data.get("password", "")
            url_val = (field_map.get("网址") or field_map.get("URL") or field_map.get("url")
                       or raw_data.get("url", ""))

            if vault_type == 'accounts':
                batch_items.append(BatchItem(
                    app=item.get("display_name", ""),
                    account=item.get("secondary_name", ""),
                    password=password,
                    url=url_val,
                    category=raw_data.get("category", "其他"),
                    remark=raw_data.get("remark", ""),
                    tags=raw_data.get("tags", []),
                    raw_data=raw_data,
                    confirmed=True,
                    status="就绪",
                ))
            else:
                batch_items.append(BatchItem(
                    title=item.get("display_name", ""),
                    url=url_val,
                    category=raw_data.get("category", "其他"),
                    remark=raw_data.get("remark", ""),
                    tags=raw_data.get("tags", []),
                    raw_data=raw_data,
                    confirmed=True,
                    status="就绪",
                ))

        # 使用现有 set_items 渲染
        categories = list(set(it.category for it in batch_items if it.category)) or ["其他"]
        self.set_items(batch_items, vault_type, categories)

    def get_items(self) -> List[BatchItem]:
        """获取所有条目"""
        if self._model is None:
            return []
        return self._model.get_items()

    def get_confirmed_items(self) -> List[Dict]:
        """获取用户勾选的 raw_data 列表（与 ActionPreviewWidget 接口一致）"""
        return [item.raw_data for item in self.get_items() if item.confirmed]

    def _on_toggle_password(self):
        """切换密码显示/掩码"""
        if self._model is None:
            return
        visible = not self._model._password_visible
        self._model.set_password_visible(visible)
        self._btn_toggle_password.setText("🙈 隐藏密码" if visible else "👁 显示密码")
