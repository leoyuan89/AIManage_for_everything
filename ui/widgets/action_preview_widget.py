"""ActionPreviewWidget - Build 模式操作预览 Widget"""
from typing import List, Dict
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton
)
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtCore import Qt, pyqtSignal
from core.theme_manager import ThemeManager

class ActionPreviewWidget(QFrame):
    """Build 模式操作预览 Widget（支持标准 preview_data）"""
    
    confirmed = pyqtSignal()
    cancelled = pyqtSignal()
    
    def __init__(self, action: str = 'explain', params: dict = None, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self.action = action
        self.params = params or {}
        self.preview_items = []
        self.total_count = 0
        self._preview_data = None
        self._is_build_mode = False
        self.setup_ui()
    
    def setup_ui(self):
        colors = ThemeManager.instance().colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        self.setStyleSheet(f"""
            ActionPreviewWidget {{
                background-color: {colors.ai_thinking_bg};
                border: 2px solid {colors.accent_orange};
                border-radius: 8px;
            }}
        """)
        
        # 标题
        title = QLabel("🔧 操作预览")
        font = QFont()
        font.setBold(True)
        font.setPointSize(12)
        title.setFont(font)
        title.setStyleSheet(f"color: {colors.accent_orange_text};")
        layout.addWidget(title)
        
        # 空数据提示（默认隐藏）
        self._empty_label = QLabel("⚠️ 未找到符合条件的条目")
        self._empty_label.setStyleSheet(f"color: {colors.accent_red}; font-size: 14px; padding: 20px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.hide()
        layout.addWidget(self._empty_label)
        
        # 表格
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self.table.setWordWrap(True)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                border: 1px solid {colors.border_light};
                background-color: {colors.bg_primary};
            }}
            QHeaderView::section {{
                background-color: {colors.accent_orange_bg};
                padding: 6px;
                border: 1px solid {colors.border_light};
                font-weight: bold;
            }}
        """)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
        # 影响范围（必须先创建，避免 setCheckState 触发 itemChanged 时访问不到）
        self.lbl_scope = QLabel("")
        self.lbl_scope.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px;")
        
        self.table.itemChanged.connect(self._on_item_check_changed)
        self.table.cellChanged.connect(self._on_cell_edited)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.lbl_scope)
        
        # 警告
        lbl_warning = QLabel("⚠️ 此操作不可撤销")
        lbl_warning.setStyleSheet(f"color: {colors.accent_red}; font-size: 11px; font-weight: bold;")
        layout.addWidget(lbl_warning)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(32)
        btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(self.cancelled.emit)
        btn_layout.addWidget(btn_cancel)
        
        btn_confirm = QPushButton("✅ 确认执行")
        btn_confirm.setFixedHeight(32)
        btn_confirm.setFixedWidth(110)
        btn_confirm.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_orange};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_orange_dark};
            }}
        """)
        btn_confirm.clicked.connect(self.confirmed.emit)
        btn_layout.addWidget(btn_confirm)
        
        layout.addLayout(btn_layout)
    
    def set_preview_data(self, preview_data: dict):
        """接收标准化 preview_data，动态构建表格"""
        colors = ThemeManager.instance().colors
        self._preview_data = preview_data
        self._is_build_mode = True
        operation_type = preview_data.get("operation_type", "add")
        items = preview_data.get("items", [])
        total = preview_data.get("total_items", len(items))
        self.total_count = total
        
        # 空数据降级
        if total == 0 or not items:
            self.table.hide()
            self._empty_label.show()
            self.lbl_scope.setText("共影响 0 条，已勾选 0 条")
            return
        
        self._empty_label.hide()
        self.table.show()
        
        headers, rows, raw_data_list = self._build_rows(operation_type, items)
        
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        
        # 确定可编辑列
        # add 类型：所有数据列都可编辑（除勾选框和序号）
        # 其他类型：按 editable_col 单列编辑
        editable_cols = set()
        if operation_type == 'add':
            editable_cols = {2, 3, 4, 5, 6, 7}  # 应用名、用户名、密码、网址、分类、备注
        elif operation_type == 'update':
            editable_cols = {5}  # 新值列
        elif operation_type == 'reorganize':
            editable_cols = {4}  # 新分类列
        elif operation_type == 'classify':
            editable_cols = {4}  # 建议分类列
        
        for i, (row_data, raw) in enumerate(zip(rows, raw_data_list)):
            for j, val in enumerate(row_data):
                cell = QTableWidgetItem(str(val))
                if j == 0:
                    cell.setFlags(cell.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    cell.setCheckState(Qt.CheckState.Checked)
                    cell.setData(Qt.ItemDataRole.UserRole, raw)
                elif j in editable_cols:
                    cell.setFlags(cell.flags() | Qt.ItemFlag.ItemIsEditable)
                else:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                
                if operation_type == 'delete':
                    cell.setForeground(QColor(colors.accent_red_dark))
                
                text = str(val)
                cell.setToolTip(text)
                
                if self._is_password_column(operation_type, j, headers):
                    actual = text
                    cell.setText("***")
                    cell.setToolTip(actual)
                
                self.table.setItem(i, j, cell)
        
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.resizeColumnsToContents()
        self.lbl_scope.setText(self._get_scope_text())
    
    def _build_rows(self, operation_type: str, items: list):
        """根据 operation_type 构建行数据"""
        headers = []
        rows = []
        raw_data_list = []
        
        if operation_type == 'add':
            headers = ['☑', '序号', '应用名', '用户名', '密码', '网址', '分类', '备注']
            for idx, item in enumerate(items, 1):
                raw = item.get("raw_data", {}) or {}
                fields = {f.get("field_name", ""): f.get("new_value", "") for f in item.get("fields", [])}
                rows.append([
                    '', str(idx), item.get("display_name", ""),
                    raw.get("username", fields.get("用户名", "")),
                    raw.get("password", fields.get("密码", "")),
                    raw.get("url", fields.get("网址", "")),
                    raw.get("category", fields.get("分类", "其他")),
                    raw.get("remark", fields.get("备注", "")),
                ])
                raw_data_list.append(raw)
        
        elif operation_type == 'update':
            headers = ['☑', '序号', '名称', '变更字段', '原值', '新值']
            for idx, item in enumerate(items, 1):
                raw = item.get("raw_data", {}) or {}
                fields = item.get("fields", [])
                changed = [f for f in fields if f.get("old_value") != f.get("new_value")]
                if changed:
                    field_names = ', '.join(f.get("field_name", "") for f in changed)
                    old_vals = ', '.join(str(f.get("old_value", "-")) for f in changed)
                    new_vals = ', '.join(str(f.get("new_value", "")) for f in changed)
                else:
                    field_names = old_vals = new_vals = '-'
                rows.append(['', str(idx), item.get("display_name", ""), field_names, old_vals, new_vals])
                raw_data_list.append(raw)
        
        elif operation_type == 'delete':
            headers = ['☑', '序号', '名称', '分类', '操作', '状态']
            for idx, item in enumerate(items, 1):
                raw = item.get("raw_data", {}) or {}
                rows.append(['', str(idx), item.get("display_name", ""),
                             raw.get("category", "其他"), '移入回收站(30天)', '待删除'])
                raw_data_list.append(raw)
        
        elif operation_type == 'reorganize':
            headers = ['☑', '序号', '名称', '原分类', '新分类']
            for idx, item in enumerate(items, 1):
                raw = item.get("raw_data", {}) or {}
                fields = item.get("fields", [])
                cat_field = next((f for f in fields if f.get("field_name") in ("分类", "category")), None)
                old_cat = cat_field.get("old_value", "-") if cat_field else "-"
                new_cat = cat_field.get("new_value", "") if cat_field else raw.get("category", "")
                rows.append(['', str(idx), item.get("display_name", ""), old_cat, new_cat])
                raw_data_list.append(raw)
        
        elif operation_type == 'classify':
            headers = ['☑', '序号', '名称', '原分类', '建议分类']
            for idx, item in enumerate(items, 1):
                raw = item.get("raw_data", {}) or {}
                fields = item.get("fields", [])
                cat_field = next((f for f in fields if f.get("field_name") in ("分类", "category")), None)
                old_cat = cat_field.get("old_value", "-") if cat_field else raw.get("category", "其他")
                new_cat = cat_field.get("new_value", "") if cat_field else ""
                rows.append(['', str(idx), item.get("display_name", ""), old_cat, new_cat])
                raw_data_list.append(raw)
        
        elif operation_type == 'merge':
            headers = ['☑', '序号', '名称', '主条目', '被合并条目', '合并后字段']
            for idx, item in enumerate(items, 1):
                raw = item.get("raw_data", {}) or {}
                rows.append(['', str(idx), item.get("display_name", ""),
                             item.get("primary_name", ""), item.get("merged_name", ""),
                             item.get("merged_fields", "")])
                raw_data_list.append(raw)
        
        else:
            headers = ['☑', '序号', '内容']
            for idx, item in enumerate(items, 1):
                raw = item.get("raw_data", {}) or {}
                rows.append(['', str(idx), str(item)])
                raw_data_list.append(raw)
        
        return headers, rows, raw_data_list
    
    def _is_password_column(self, operation_type: str, col: int, headers: list) -> bool:
        # 预览时密码显示明文，方便用户确认
        return False
    
    def get_confirmed_items(self) -> List[Dict]:
        """返回用户勾选确认的 raw_data 列表"""
        confirmed = []
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                raw = item.data(Qt.ItemDataRole.UserRole)
                if raw is not None:
                    confirmed.append(raw)
        return confirmed
    
    # ---- 兼容旧接口 ----
    
    def update_action(self, action: str, params: dict, preview_items: list = None):
        """更新操作内容（兼容旧代码）"""
        self.action = action
        self.params = params
        self.preview_items = preview_items or []
        self.total_count = len(preview_items) if preview_items else 0
        self._is_build_mode = False
        self._preview_data = None
        self._empty_label.hide()
        self.table.show()
        self._fill_table()
        self.lbl_scope.setText(self._get_scope_text())
    
    def _fill_table(self):
        """根据 action 和 params 填充预览表格（兼容旧代码）"""
        colors = ThemeManager.instance().colors
        rows = []
        delete_mode = self.action == 'delete'
        source = self.preview_items if self.preview_items else None
        
        if self.action == 'reorganize':
            if source:
                for item in source:
                    rows.append([
                        item.get('app_name', f"#{item.get('target_id', '?')}"),
                        item.get('field', 'category'),
                        item.get('old_value', '-'),
                        item.get('new_value', '')
                    ])
            else:
                changes = self.params.get('changes', [])
                if changes:
                    for change in changes:
                        tid = change.get('target_id', '?')
                        field = change.get('field', 'category')
                        new_val = change.get('new_value', '')
                        rows.append([f"#{tid}", field, "-", str(new_val)])
                else:
                    suggestions = self.params.get('suggestions', [])
                    for i, sug in enumerate(suggestions):
                        rows.append([f"建议 {i+1}", "分类", "-", str(sug)])
        
        elif self.action == 'add_remark':
            if source:
                for item in source:
                    rows.append([
                        item.get('app_name', f"#{item.get('target_id', '?')}"),
                        item.get('field', 'ai_remark'),
                        item.get('old_value', '-'),
                        item.get('new_value', '')
                    ])
            else:
                target_ids = self.params.get('target_ids', [])
                remark = self.params.get('remark', '')
                for tid in target_ids:
                    rows.append([f"账号 #{tid}", "备注", "-", str(remark)])
        
        elif self.action == 'delete':
            if source:
                for item in source:
                    rows.append([
                        item.get('app_name', f"#{item.get('target_id', '?')}"),
                        item.get('item_type', 'account'),
                        "-",
                        "移入回收站(30天)"
                    ])
            else:
                target_ids = self.params.get('target_ids', [])
                item_type = self.params.get('item_type', 'account')
                for tid in target_ids:
                    rows.append([f"#{tid}", item_type, "-", "移入回收站(30天)"])
        
        elif self.action == 'add':
            if source:
                for item in source:
                    rows.append([
                        item.get('app_name', item.get('title', '新条目')),
                        item.get('item_type', 'account'),
                        "-",
                        "新增入库"
                    ])
            else:
                fields = self.params.get('fields', {})
                item_type = self.params.get('item_type', 'account')
                rows.append([fields.get('app_name', fields.get('title', '新条目')), item_type, "-", "新增入库"])
        
        else:
            rows.append([str(self.action), "-", "-", str(self.params)[:100]])
        
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["目标条目", "字段", "原值", "新值"])
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                cell = QTableWidgetItem(str(val))
                if delete_mode:
                    cell.setForeground(QColor(colors.accent_red_dark))
                if j == 0:
                    cell.setFlags(cell.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    cell.setCheckState(Qt.CheckState.Checked)
                self.table.setItem(i, j, cell)
    
    def _on_item_check_changed(self, item):
        """勾选状态变化时更新影响范围文字"""
        if item.column() == 0:
            self.lbl_scope.setText(self._get_scope_text())
    
    def _on_cell_edited(self, row: int, col: int):
        """用户编辑单元格后，同步更新 raw_data 中的值"""
        if col == 0:
            return
        if row < 0 or row >= self.table.rowCount():
            return
        check_item = self.table.item(row, 0)
        if not check_item:
            return
        raw = check_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(raw, dict):
            return
        edited_item = self.table.item(row, col)
        if not edited_item:
            return
        new_val = edited_item.text()
        updated = False
        
        op_type = self._preview_data.get("operation_type") if self._preview_data else None
        
        if op_type == 'add':
            # add 类型：按列映射到字段名
            col_to_field = {2: 'app_name', 3: 'username', 4: 'password',
                            5: 'url', 6: 'category', 7: 'remark'}
            field = col_to_field.get(col)
            if field:
                raw[field] = new_val
                updated = True
        elif (self._is_build_mode and self._preview_data
                and self._preview_data.get("operation_type") == "classify"):
            raw['new_value'] = new_val
            updated = True
        else:
            if 'updates' in raw and isinstance(raw['updates'], dict):
                for field in list(raw['updates'].keys()):
                    raw['updates'][field] = new_val
                    updated = True
            if 'new_value' in raw:
                raw['new_value'] = new_val
                updated = True
            if 'content' in raw:
                raw['content'] = new_val
                updated = True
            if 'field' in raw and 'new_value' not in raw:
                raw['new_value'] = new_val
                updated = True
        if updated:
            check_item.setData(Qt.ItemDataRole.UserRole, raw)
            logger.debug(f" Row {row} col {col} edited, raw_data updated: {raw}")
    
    def get_selected_items(self) -> List[Dict]:
        """获取用户勾选的条目（兼容旧代码）"""
        if not self.preview_items:
            return []
        selected = []
        for i, item in enumerate(self.preview_items):
            if i < self.table.rowCount():
                table_item = self.table.item(i, 0)
                if table_item and table_item.checkState() == Qt.CheckState.Checked:
                    selected.append(item)
            else:
                selected.append(item)
        return selected
    
    def _get_scope_text(self) -> str:
        selected_count = 0
        total_count = self.total_count if self.total_count else self.table.rowCount()
        
        if self._is_build_mode and self._preview_data:
            confirmed = self.get_confirmed_items()
            selected_count = len(confirmed)
            op_type = self._preview_data.get("operation_type", "update")
            return f"共影响 {total_count} 条，已勾选 {selected_count} 条 | 操作类型：{op_type}"
        
        selected = self.get_selected_items()
        selected_count = len(selected)
        
        if self.action == 'delete':
            return f"影响范围：{selected_count}/{total_count} 条记录 | 操作类型：删除（移入回收站）"
        elif self.action == 'add':
            return f"影响范围：新增 {selected_count} 条记录 | 操作类型：创建"
        return f"影响范围：{selected_count}/{total_count} 条记录 | 操作类型：批量更新 ({self.action})"

