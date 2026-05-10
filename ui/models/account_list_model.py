from PyQt6.QtCore import QAbstractListModel, Qt, QModelIndex
from typing import List, Optional, Any


class AccountListModel(QAbstractListModel):
    """账号/网址列表数据模型"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[dict] = []

    def set_items(self, items: List[dict]):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._items):
            return None
        item = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.get("display_text", "")
        if role == Qt.ItemDataRole.UserRole:
            return item
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        item = self._items[index.row()]
        if item.get("item_type") == "header":
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def get_item(self, row: int) -> Optional[dict]:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def get_row_for_data_id(self, data_id) -> int:
        """根据数据ID查找行号"""
        for row, item in enumerate(self._items):
            obj = item.get("data")
            if obj is None:
                continue
            obj_id = getattr(obj, "id", None) or (
                obj.get("id") if isinstance(obj, dict) else None
            )
            if obj_id == data_id:
                return row
        return -1
