"""
主窗口模块
包含：分类导航、账号列表、搜索框、底部工具栏
"""
import sys
import time
import json
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from collections import defaultdict
from enum import Enum
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem,
    QLabel, QFrame, QSplitter, QMessageBox, QApplication,
    QMenu, QCheckBox, QDialog, QInputDialog, QTextBrowser, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QDateEdit, QComboBox, QStackedWidget, QCalendarWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal, QPoint, QStringListModel, QDate
from PyQt6.QtGui import QIcon, QFont, QColor, QTextCursor, QPainter, QPixmap, QBrush, QPen
from PyQt6.QtWidgets import QCompleter


from core.database import DatabaseManager
from core.clipboard import ClipboardManager
from core.constants import DATA_DIR, BACKUP_DIR, VAULT_DB_PATH, VAULT_URLS_DB_PATH, CONFIG_PATH, COMPACT_VIEW_PATH
from core.theme_manager import (
    ThemeManager, ThemeColors, style_button_primary, style_button_danger,
    style_bar, style_panel, style_input, style_scrollbar, get_icon
)
from core.icon_manager import IconManager
from services.account_service import AccountService
from services.category_service import CategoryService
from services.ai_classification_service import AIClassificationService
from services.export_service import ExportService
from services.search_service import SearchService, SearchResult, SearchFilter
from services.ai_assistant_service import AIAssistantService
from services.ai_service_manager import AIServiceManager
from services.ai_worker_thread import AIStatus
from models.account import Account
from .account_dialog import AccountDialog
from .url_dialog import URLEditDialog
from .export_dialog import ExportDialog
from .settings_dialog import SettingsDialog
from .dialogs.health_check_dialog import HealthCheckDialog
from .dialogs.help_dialog import HelpDialog
from .batch_add_preview_widget import BatchAddPreviewWidget
from .lock_screen import LockScreen, IdleTimer
from .widgets.account_list_item import AccountListItem
from .widgets.url_list_item import URLListItem
from .widgets.dashboard_widget import DashboardWidget
from .widgets.search_history_panel import SearchHistoryPanel

logger = logging.getLogger(__name__)


class AIQueryThread(QThread):
    """AI 查询后台线程：支持流式和非流式两种模式
    
    注意：使用 pyqtSignal(str) 传递 JSON 字符串，而非 dict。
    PyQt 的 pyqtSignal(dict) 在传递包含大字符串的 dict 时，
    C++ 层序列化可能触发栈缓冲区溢出（0xC0000409）。
    """
    result_ready = pyqtSignal(str)
    thinking_token = pyqtSignal(str)  # 思考过程 token
    result_token = pyqtSignal(str)    # 最终结果 token
    
    def __init__(self, ai_assistant, query: str, accounts: list, mode: str = 'plan', vault_type: str = 'accounts'):
        colors = ThemeManager.instance().colors
        super().__init__()
        self.ai_assistant = ai_assistant
        self.query = query
        self.accounts = accounts
        self.mode = mode
        self.vault_type = vault_type
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        """在线程中执行 AI 查询：使用分段输出（打字机效果）"""
        import json as _json
        logger.debug(f" 开始处理查询: {self.query[:50]}...")
        try:
            # 分段输出：先获取完整响应，再逐段发射到 UI（每 250ms 一段）
            # 比完全流式更稳定（避免高频 Signal），比完全非流式体验更好
            self._run_segmented()
        except Exception as e:
            import traceback
            logger.debug(f" 异常: {e}")
            logger.exception("Unhandled exception")
            error_result = {
                "success": False,
                "thinking": "",
                "action": "explain",
                "params": {},
                "response": f"调用失败：{str(e)}",
                "error": str(e)
            }
            self.result_ready.emit(_json.dumps(error_result, ensure_ascii=False))
    
    def _run_segmented(self):
        """分段输出：先获取完整响应，再逐段发射到 UI（每 250ms 一段）"""
        import json as _json
        import time
        
        logger.debug("[AIThread] _run_segmented started")
        
        # 1. 获取完整响应（非流式，更稳定）
        try:
            result = self.ai_assistant.process_react_query(
                self.query, self.accounts, mode=self.mode, vault_type=self.vault_type
            )
            logger.debug(f" process_query done, action={result.get('action')}")
        except Exception as e:
            import traceback
            logger.debug(f" process_query error: {e}")
            logger.exception("Unhandled exception")
            result = {
                "success": False,
                "thinking": "",
                "action": "explain",
                "params": {},
                "response": f"调用失败：{str(e)}",
                "error": str(e)
            }
        
        # 2. 将 response 文本分割成段落
        # ReAct 模式：跳过 result_token 分段发射，避免与 _on_react_result 重复追加回复
        is_react = 'done' in result or 'awaiting_confirm' in result
        response_text = result.get('response', '')
        if response_text and not self._cancelled and not is_react:
            segments = self._split_into_segments(response_text, max_chunk=30)
            logger.debug(f" Split into {len(segments)} segments")
            
            # 3. 逐段发射，每段间隔 250ms（每秒 4 次，安全频率）
            for i, segment in enumerate(segments):
                if self._cancelled:
                    logger.info("[AIThread] Cancelled, stopping emission")
                    break
                logger.debug(f" Emit segment {i+1}/{len(segments)} ({len(segment)} chars)")
                self.result_token.emit(segment)
                time.sleep(0.25)  # 250ms 间隔
        
        # 4. 发射最终结果
        json_str = _json.dumps(result, ensure_ascii=False)
        logger.debug(f" Emitting result_ready, json_len={len(json_str)}")
        self.result_ready.emit(json_str)
    
    def _split_into_segments(self, text: str, max_chunk: int = 30) -> list:
        """将文本分割成适合逐段显示的段落（优先按标点分割）"""
        if len(text) <= max_chunk:
            return [text]
        
        segments = []
        current = ""
        
        for char in text:
            current += char
            # 遇到标点且当前段足够长，就切分
            if char in '。！？.!?\n' and len(current) >= 10:
                segments.append(current)
                current = ""
            elif len(current) >= max_chunk:
                segments.append(current)
                current = ""
        
        if current:
            segments.append(current)
        
        return segments if segments else [text]
    
    def _run_stream(self):
        """流式执行 AI 查询（带批量节流，防止高频跨线程 signal 导致 0xC0000409）"""
        import json as _json
        import time
        
        thinking_buffer = []
        result_buffer = []
        last_emit_time = [time.time()]  # list 用于闭包修改
        
        def on_token(token, section):
            if self._cancelled:
                return
            if section == 'thinking':
                thinking_buffer.append(token)
            elif section == 'result':
                result_buffer.append(token)
            
            # 批量节流：每 50ms 或积累超过 200 字符才发射一次
            now = time.time()
            t_len = sum(len(t) for t in thinking_buffer)
            r_len = sum(len(t) for t in result_buffer)
            if now - last_emit_time[0] > 0.05 or t_len > 200 or r_len > 200:
                try:
                    if thinking_buffer:
                        batch = ''.join(thinking_buffer)
                        logger.debug(f" Emit thinking batch ({len(batch)} chars)")
                        self.thinking_token.emit(batch)
                        thinking_buffer.clear()
                    if result_buffer:
                        batch = ''.join(result_buffer)
                        logger.debug(f" Emit result batch ({len(batch)} chars)")
                        self.result_token.emit(batch)
                        result_buffer.clear()
                except Exception as e:
                    logger.warning(f" Emit error: {e}")
                last_emit_time[0] = now
        
        logger.debug(f" Entering process_query_stream, mode={self.mode}")
        result = self.ai_assistant.process_query_stream(
            self.query, self.accounts, mode=self.mode, on_token=on_token, vault_type=self.vault_type
        )
        logger.debug(f" process_query_stream finished, action={result.get('action')}, success={result.get('success')}")
        
        # 发射剩余 buffer
        try:
            if thinking_buffer:
                batch = ''.join(thinking_buffer)
                logger.debug(f" Final thinking emit ({len(batch)} chars)")
                self.thinking_token.emit(batch)
            if result_buffer:
                batch = ''.join(result_buffer)
                logger.debug(f" Final result emit ({len(batch)} chars)")
                self.result_token.emit(batch)
        except Exception as e:
            logger.warning(f" Final emit error: {e}")
        
        json_str = _json.dumps(result, ensure_ascii=False)
        logger.debug(f" Emitting result_ready, json_len={len(json_str)}")
        self.result_ready.emit(json_str)
    
    def _run_legacy(self):
        """非流式执行 AI 查询（降级兼容）"""
        import json as _json
        result = self.ai_assistant.process_query(self.query, self.accounts, vault_type=self.vault_type)
        json_str = _json.dumps(result, ensure_ascii=False)
        self.result_ready.emit(json_str)


class ReActState(Enum):
    """ReAct 状态机"""
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_PREVIEW = "awaiting_preview"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


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


class DropZoneWidget(QLabel):
    """重组模式下的固定顶部拖放区域"""
    
    dropped = pyqtSignal(str)  # (source_path)
    
    def __init__(self, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__("📌 将类别拖至此处成为一级类别", parent)
        self.setFixedHeight(40)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"""
            DropZoneWidget {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
                border: 2px dashed {colors.border_medium};
                border-radius: 6px;
                font-size: 12px;
                margin: 4px 6px;
            }}
        """)
        self.setAcceptDrops(True)
    
    def dragEnterEvent(self, event):
        colors = ThemeManager.instance().colors
        source = event.source()
        if isinstance(source, CategoryTreeWidget) and source._dragging_item:
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                DropZoneWidget {{
                    background-color: {colors.accent_blue_bg};
                    color: {colors.accent_blue};
                    border: 2px dashed {colors.accent_blue_light};
                    border-radius: 6px;
                    font-size: 12px;
                    margin: 4px 6px;
                }}
            """)
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        colors = ThemeManager.instance().colors
        self.setStyleSheet(f"""
            DropZoneWidget {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
                border: 2px dashed {colors.border_medium};
                border-radius: 6px;
                font-size: 12px;
                margin: 4px 6px;
            }}
        """)
    
    def dropEvent(self, event):
        colors = ThemeManager.instance().colors
        self.setStyleSheet(f"""
            DropZoneWidget {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
                border: 2px dashed {colors.border_medium};
                border-radius: 6px;
                font-size: 12px;
                margin: 4px 6px;
            }}
        """)
        source = event.source()
        if isinstance(source, CategoryTreeWidget) and source._dragging_item:
            category = source._dragging_item.data(0, Qt.ItemDataRole.UserRole)
            if category and category not in ('全部', '__DROP_TO_ROOT__'):
                self.dropped.emit(category)
            event.acceptProposedAction()
        else:
            event.ignore()


class CategoryTreeWidget(QTreeWidget):
    """支持受限制拖拽排序和重组的分类树
    
    - 一级分类：只能在顶层之间移动
    - 二级分类：只能在同一父节点下移动，禁止跨父节点
    - 重组模式：支持跨层级拖拽重组
    """
    
    reorganize_requested = pyqtSignal(str, str)  # (source_path, target_parent)
    
    def __init__(self, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self._dragging_item = None
        self._edit_mode = False
        self._reorganize_mode = False
        self._normal_style = ""
        self._auto_scroll_direction = 0
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(50)
        self._auto_scroll_timer.timeout.connect(self._perform_auto_scroll)
        import os
        _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._branch_closed_svg = os.path.join(_base_dir, 'assets', 'icons', 'branch_closed.svg').replace('\\', '/')
        self._branch_open_svg = os.path.join(_base_dir, 'assets', 'icons', 'branch_open.svg').replace('\\', '/')
    
    def _perform_auto_scroll(self):
        scrollbar = self.verticalScrollBar()
        if self._auto_scroll_direction == -1:
            new_value = scrollbar.value() - 18
            scrollbar.setValue(max(scrollbar.minimum(), new_value))
        elif self._auto_scroll_direction == 1:
            new_value = scrollbar.value() + 18
            scrollbar.setValue(min(scrollbar.maximum(), new_value))
    
    def set_normal_style(self, style: str):
        """保存正常模式下的样式表，用于退出编辑模式时恢复"""
        self._normal_style = style
        if not self._edit_mode and not self._reorganize_mode:
            self.setStyleSheet(style)
    
    def set_edit_mode(self, enabled: bool):
        colors = ThemeManager.instance().colors
        self._edit_mode = enabled
        if enabled:
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.viewport().setAcceptDrops(True)
            self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
            # 编辑模式样式：拖拽指示器更明显
            self.setStyleSheet(f"""
                QTreeWidget {{
                    background-color: {colors.bg_secondary};
                    border: none;
                    outline: none;
                }}
                QTreeWidget::item {{
                    height: 38px;
                    padding-left: 12px;
                    border-radius: 6px;
                    margin: 2px 6px;
                    border: 1px dashed transparent;
                }}
                QTreeWidget::item:selected {{
                    background-color: {colors.accent_blue_bg};
                    color: {colors.accent_blue};
                    border: 1px dashed {colors.accent_blue_light};
                }}
                QTreeWidget::item:hover {{
                    background-color: {colors.bg_hover};
                }}
                QTreeWidget::branch:has-children:!has-siblings:closed,
                QTreeWidget::branch:closed:has-children:has-siblings {{
                    image: url("{self._branch_closed_svg}");
                }}
                QTreeWidget::branch:open:has-children:!has-siblings,
                QTreeWidget::branch:open:has-children:has-siblings {{
                    image: url("{self._branch_open_svg}");
                }}
            """)
        else:
            self.setDragEnabled(False)
            self.setAcceptDrops(False)
            self.viewport().setAcceptDrops(False)
            self.setDragDropMode(QTreeWidget.DragDropMode.NoDragDrop)
            self.setDefaultDropAction(Qt.DropAction.IgnoreAction)
            # 恢复正常样式
            self.setStyleSheet(self._normal_style)
    
    def set_reorganize_mode(self, enabled: bool):
        colors = ThemeManager.instance().colors
        self._reorganize_mode = enabled
        if enabled:
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.viewport().setAcceptDrops(True)
            self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.setStyleSheet(f"""
                QTreeWidget {{
                    background-color: {colors.bg_secondary};
                    border: none;
                    outline: none;
                }}
                QTreeWidget::item {{
                    height: 38px;
                    padding-left: 12px;
                    border-radius: 6px;
                    margin: 2px 6px;
                    border: 1px dashed transparent;
                }}
                QTreeWidget::item:selected {{
                    background-color: {colors.accent_blue_bg};
                    color: {colors.accent_blue};
                    border: 1px dashed {colors.accent_blue_light};
                }}
                QTreeWidget::item:hover {{
                    background-color: {colors.bg_hover};
                }}
                QTreeWidget::branch:has-children:!has-siblings:closed,
                QTreeWidget::branch:closed:has-children:has-siblings {{
                    image: url("{self._branch_closed_svg}");
                }}
                QTreeWidget::branch:open:has-children:!has-siblings,
                QTreeWidget::branch:open:has-children:has-siblings {{
                    image: url("{self._branch_open_svg}");
                }}
            """)
        else:
            self.setDragEnabled(False)
            self.setAcceptDrops(False)
            self.viewport().setAcceptDrops(False)
            self.setDragDropMode(QTreeWidget.DragDropMode.NoDragDrop)
            self.setDefaultDropAction(Qt.DropAction.IgnoreAction)
            self.setStyleSheet(self._normal_style)
    
    def startDrag(self, supportedActions):
        # 开始拖拽前清理可能残留的状态
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        
        self._dragging_item = self.currentItem()
        super().startDrag(supportedActions)
        
        # drag 结束后（无论成功、取消或异常）强制清理
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        self._dragging_item = None
    
    def dragMoveEvent(self, event):
        if not self._dragging_item:
            event.ignore()
            return
        
        if not self._edit_mode and not self._reorganize_mode:
            event.ignore()
            return

        # 自动滚动检测
        y = event.position().toPoint().y()
        height = self.viewport().height()
        if y < height * 0.2:
            self._auto_scroll_direction = -1
            if not self._auto_scroll_timer.isActive():
                self._auto_scroll_timer.start()
        elif y > height * 0.8:
            self._auto_scroll_direction = 1
            if not self._auto_scroll_timer.isActive():
                self._auto_scroll_timer.start()
        else:
            self._auto_scroll_direction = 0
            self._auto_scroll_timer.stop()

        source_item = self._dragging_item
        source_parent = source_item.parent()
        source_data = source_item.data(0, Qt.ItemDataRole.UserRole)

        pos = event.position().toPoint()
        target_item = self.itemAt(pos)
        drop_indicator = self.dropIndicatorPosition()

        if self._reorganize_mode:
            # 重组模式规则
            # 1. 源是"全部"或"成为一级"特殊条目 → 拒绝
            if source_data in ('全部', '__DROP_TO_ROOT__', '__favorites__', '__recent__'):
                event.ignore()
                return
            
            # 2. Above/Below → 接受（同级排序）
            if drop_indicator in (QTreeWidget.DropIndicatorPosition.AboveItem,
                                  QTreeWidget.DropIndicatorPosition.BelowItem):
                # 一级只能在顶层之间排序
                if source_parent is None:
                    if target_item and target_item.parent() is not None:
                        event.ignore()
                        return
                else:
                    # 源是二级，目标必须在同一父节点下
                    if target_item and target_item.parent() != source_parent:
                        event.ignore()
                        return
                event.acceptProposedAction()
                return
            
            # 3. OnItem 情况
            if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem:
                if target_item is None:
                    event.ignore()
                    return
                
                target_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                
                # 目标是二级节点 → 拒绝（避免三级）
                if target_item.parent() is not None:
                    event.ignore()
                    return
                
                # 目标是一级节点
                # 源是一级（有子类）→ 拒绝（避免产生三级）
                if source_parent is None and source_item.childCount() > 0:
                    event.ignore()
                    return
                
                # 其他情况：源是一级（无子类）或二级，目标是一级 → 接受
                event.acceptProposedAction()
                return
            
            event.ignore()
            return

        # 原有排序逻辑
        # 先计算原始 target_parent
        if target_item:
            if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem:
                target_parent = target_item
            elif drop_indicator in (QTreeWidget.DropIndicatorPosition.AboveItem,
                                    QTreeWidget.DropIndicatorPosition.BelowItem):
                target_parent = target_item.parent() or self.invisibleRootItem()
            else:
                target_parent = self.invisibleRootItem()
        else:
            target_parent = self.invisibleRootItem()

        # 修正 OnItem：同级排序时 target_parent 应视为父容器
        if source_parent is None:                       # 一级分类
            if (target_item and target_item.parent() is None and
                    drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                target_parent = self.invisibleRootItem()
        else:                                           # 二级分类
            if (target_item and target_item.parent() == source_parent and
                    drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                target_parent = source_parent

        # 规则检查
        if source_parent is None:
            if target_parent != self.invisibleRootItem():
                event.ignore()
                return
        else:
            if target_parent != source_parent:
                event.ignore()
                return

        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        colors = ThemeManager.instance().colors
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        colors = ThemeManager.instance().colors
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        if not self._dragging_item:
            event.ignore()
            return
        
        if not self._edit_mode and not self._reorganize_mode:
            event.ignore()
            return

        source_item = self._dragging_item
        source_parent = source_item.parent()
        source_data = source_item.data(0, Qt.ItemDataRole.UserRole)

        # 计算目标位置
        pos = event.position().toPoint()
        target_item = self.itemAt(pos)
        drop_indicator = self.dropIndicatorPosition()

        if self._reorganize_mode:
            # 先处理 OnItem 跨层级重组
            if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem and target_item:
                target_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                
                # 目标是一级节点（二级节点已在 dragMoveEvent 中拒绝）
                if target_item.parent() is None:
                    if source_parent is None and source_item.childCount() > 0:
                        event.ignore()
                        self._dragging_item = None
                        return
                    
                    event.ignore()
                    self.reorganize_requested.emit(source_data, target_data)
                    self._dragging_item = None
                    return
            
            # 以下是 Above/Below 同级排序逻辑，和排序模式相同
            if target_item:
                if drop_indicator == QTreeWidget.DropIndicatorPosition.AboveItem:
                    target_parent = target_item.parent() or self.invisibleRootItem()
                    target_row = target_parent.indexOfChild(target_item)
                elif drop_indicator == QTreeWidget.DropIndicatorPosition.BelowItem:
                    target_parent = target_item.parent() or self.invisibleRootItem()
                    target_row = target_parent.indexOfChild(target_item) + 1
                else:
                    target_parent = self.invisibleRootItem()
                    target_row = self.topLevelItemCount()
            else:
                target_parent = self.invisibleRootItem()
                target_row = self.topLevelItemCount()
            
            # 修正 OnItem：同级排序时按 BelowItem 处理
            if source_parent is None:                       # 一级分类
                if (target_item and target_item.parent() is None and
                        drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                    target_parent = self.invisibleRootItem()
                    target_row = self.invisibleRootItem().indexOfChild(target_item) + 1
            else:                                           # 二级分类
                if (target_item and target_item.parent() == source_parent and
                        drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                    target_parent = source_parent
                    target_row = source_parent.indexOfChild(target_item) + 1
            
            # 规则限制
            if source_parent is None:
                if target_parent != self.invisibleRootItem():
                    event.ignore()
                    self._dragging_item = None
                    return
            else:
                if target_parent != source_parent:
                    event.ignore()
                    self._dragging_item = None
                    return
            
            # 手动移动
            event.ignore()
            _source_item = source_item
            _source_parent = source_parent
            _target_parent = target_parent
            _target_row = target_row

            def do_move():
                if _source_parent is None:
                    old_row = self.indexOfTopLevelItem(_source_item)
                    if old_row < 0:
                        return
                    taken = self.takeTopLevelItem(old_row)
                    if taken is None:
                        return
                    tr = _target_row
                    if old_row < tr:
                        tr -= 1
                    self.insertTopLevelItem(tr, taken)
                    self.setCurrentItem(taken)
                else:
                    old_row = _source_parent.indexOfChild(_source_item)
                    if old_row < 0:
                        return
                    taken = _source_parent.takeChild(old_row)
                    if taken is None:
                        return
                    tr = _target_row
                    if old_row < tr:
                        tr -= 1
                    _target_parent.insertChild(tr, taken)
                    self.setCurrentItem(taken)
                self.viewport().update()

            QTimer.singleShot(0, do_move)
            self._dragging_item = None
            return

        # 原有排序模式逻辑
        if target_item:
            if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem:
                target_parent = target_item
                target_row = 0
            elif drop_indicator == QTreeWidget.DropIndicatorPosition.AboveItem:
                target_parent = target_item.parent() or self.invisibleRootItem()
                target_row = target_parent.indexOfChild(target_item)
            elif drop_indicator == QTreeWidget.DropIndicatorPosition.BelowItem:
                target_parent = target_item.parent() or self.invisibleRootItem()
                target_row = target_parent.indexOfChild(target_item) + 1
            else:
                target_parent = self.invisibleRootItem()
                target_row = self.topLevelItemCount()
        else:
            target_parent = self.invisibleRootItem()
            target_row = self.topLevelItemCount()

        # 修正 OnItem：同级排序时按 BelowItem 处理
        if source_parent is None:                       # 一级分类
            if (target_item and target_item.parent() is None and
                    drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                target_parent = self.invisibleRootItem()
                target_row = self.invisibleRootItem().indexOfChild(target_item) + 1
        else:                                           # 二级分类
            if (target_item and target_item.parent() == source_parent and
                    drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                target_parent = source_parent
                target_row = source_parent.indexOfChild(target_item) + 1

        # 规则限制
        if source_parent is None:
            if target_parent != self.invisibleRootItem():
                event.ignore()
                self._dragging_item = None
                return
        else:
            if target_parent != source_parent:
                event.ignore()
                self._dragging_item = None
                return

        # 拒绝 Qt 默认 drop 处理，避免其内部 drag 清理逻辑与手动移动冲突
        event.ignore()

        # 延迟到下一帧再执行移动，等 Qt drag 状态完全结束
        _source_item = source_item
        _source_parent = source_parent
        _target_parent = target_parent
        _target_row = target_row

        def do_move():
            if _source_parent is None:
                old_row = self.indexOfTopLevelItem(_source_item)
                if old_row < 0:
                    return
                taken = self.takeTopLevelItem(old_row)
                if taken is None:
                    return
                tr = _target_row
                if old_row < tr:
                    tr -= 1
                self.insertTopLevelItem(tr, taken)
                self.setCurrentItem(taken)
            else:
                old_row = _source_parent.indexOfChild(_source_item)
                if old_row < 0:
                    return
                taken = _source_parent.takeChild(old_row)
                if taken is None:
                    return
                tr = _target_row
                if old_row < tr:
                    tr -= 1
                _target_parent.insertChild(tr, taken)
                self.setCurrentItem(taken)
            self.viewport().update()

        QTimer.singleShot(0, do_move)
        self._dragging_item = None


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self, db_manager: DatabaseManager, config_path: str = None):
        colors = ThemeManager.instance().colors
        super().__init__()
        self.setWindowIcon(IconManager.app_icon())
        self.db = db_manager
        self.config_path = config_path
        self._ai_manager = AIServiceManager.instance()
        self.account_service = AccountService(db_manager)
        self.category_service = CategoryService(db_manager)
        self.export_service = ExportService(db_manager)
        self.clipboard = ClipboardManager()
        
        # 搜索服务
        self.search_service = SearchService(db_manager)
        
        # AI智能分类服务（延迟初始化，避免启动时网络请求）
        
        # 炽阳 服务
        self.ai_assistant = AIAssistantService(db_manager)
        self._ai_panel_visible = False
        self._ai_thinking_expanded = {}  # msg_index -> bool，思考过程展开状态
        self._ai_welcome_shown = False   # 欢迎语是否已显示
        self._ai_query_running = False   # 是否正在查询中
        self._ai_mode = 'plan'           # 'plan' = 只建议不操作, 'build' = 可执行但需确认
        self._pending_action = None      # 待用户确认的操作 (action, params, description)
        self._highlight_matched_ids = None  # Plan 模式高亮的账号 ID 集合
        self._highlight_reasoning = ""      # Plan 模式高亮的推理文本
        self._view_mode = 'default'         # 'default' | 'search' | 'ai_highlight'
        
        # AI 查询状态
        self._ai_query_start_time = None  # 查询开始时间
        self._ai_refresh_timer = None     # 聊天区域防抖定时器
        self._ai_last_elapsed = 0.0    # 上次回答用时（秒）
        self._ai_query_cancelled = False  # 用户是否取消了本次查询
        
        # ReAct 状态机
        self._react_state = ReActState.IDLE
        self._pending_tool = None
        self._current_preview_widget = None
        self._react_turns_used = 0
        self._react_max_turns = 5
        
        self.current_category = '全部'
        self.selected_account: Optional[Account] = None
        
        # 账号列表全量缓存（一次加载，内存过滤，避免反复解密和 service 调用）
        self._all_accounts_cache: List[Account] = []
        self._accounts_cache_dirty = True
        
        # 会话安全：锁定界面
        self._lock_screen = None
        self._idle_timer = None
        
        # 库切换状态
        self.current_vault = 'accounts'  # 'accounts' | 'urls'
        self._all_urls_cache: List = []
        self._urls_cache_dirty = True
        self._mode_change_guard = False
        
        # 网址服务（延迟初始化）
        self._url_service = None
        self._url_db = None
        
        # 批量选择模式（主条目）
        self._selection_mode = False
        self._selected_ids = set()
        self._last_selected_index = None
        self._drag_selecting = False
        self._drag_checked_ids = set()  # 拖动过程中已处理过的条目ID（避免重复触发）
        self._drag_in_progress = False  # 标记是否正在进行拖动选择（用于屏蔽 itemClicked）
        self._normal_title = ""  # 保存正常模式下的列表标题
        
        # 类别批量删除模式
        self._category_selection_mode = False
        self._selected_categories = set()
        
        # 撤销横幅数据
        self._undo_deleted_items = []
        
        self.setup_ui()
        self._reload_categories()
        self._setup_session_security()
        self._session_version = self.db.get_session_version()
        self.load_accounts()
        
        # 初始化网址库
        from core.url_database import URLDatabaseManager
        from services.url_service import URLService
        
        data_dir = DATA_DIR
        data_dir.mkdir(exist_ok=True)
        url_db_path = data_dir / 'vault_urls.db'
        self._url_db = URLDatabaseManager(str(url_db_path))
        self._url_service = URLService(self._url_db)
        self.ai_assistant.url_db = self._url_db
        
        # 现在创建仪表盘（_url_service 已就绪）
        self.dashboard = DashboardWidget(self.account_service, self._url_service, self.current_vault)
        self.dashboard.set_callback(self._on_dashboard_action)
        self.list_stack.addWidget(self.dashboard)
        
        # 统一注册 RepositoryFactory（确保 URLRepository 有 main_db 引用用于回收站备份）
        from core.repositories import RepositoryFactory, AccountRepository, URLRepository
        RepositoryFactory.register('accounts', AccountRepository(
            db=self.db,
            category_service=CategoryService(self.db),
            classification_service=AIClassificationService()
        ))
        RepositoryFactory.register('urls', URLRepository(
            db=self._url_db,
            url_service=self._url_service,
            main_db=self.db
        ))
        
        # AIServiceManager 后台已自动探测，UI 初始化时直接读缓存
        self._on_ai_state_changed(self._ai_manager.get_state())
        # 若 1 秒后缓存仍为 UNKNOWN，触发一次刷新
        QTimer.singleShot(1000, lambda: self._ai_manager.request_refresh() if self._ai_manager.get_state().status == AIStatus.UNKNOWN else None)
        
        # 对话上下文过期检测（每30秒）
        self._context_expiry_timer = QTimer(self)
        self._context_expiry_timer.timeout.connect(self._check_conversation_context_expiry)
        self._context_expiry_timer.start(30000)

        # 初始化完成后主动同步一次样式（确保初始主题正确）
        self._reapply_styles(ThemeManager.instance().colors)
        
        # 注册键盘快捷键
        self._register_shortcuts()
    
    def _register_shortcuts(self):
        """注册全局键盘快捷键"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        
        shortcuts = [
            (QKeySequence("Ctrl+F"), self._shortcut_focus_search),
            (QKeySequence("Ctrl+N"), self.on_add_item),
            (QKeySequence("Delete"), self._shortcut_delete_current),
            (QKeySequence("Escape"), self._shortcut_escape),
            (QKeySequence("Ctrl+D"), self._shortcut_toggle_theme),
            (QKeySequence("Ctrl+L"), self._shortcut_lock),
            (QKeySequence("Ctrl+1"), lambda: self._on_vault_tab_changed(0)),
            (QKeySequence("Ctrl+2"), lambda: self._on_vault_tab_changed(1)),
            (QKeySequence("Ctrl+Z"), self._shortcut_undo),
            (QKeySequence("Ctrl+M"), self._shortcut_toggle_selection_mode),
        ]
        for key_seq, slot in shortcuts:
            QShortcut(key_seq, self).activated.connect(slot)
    
    def _shortcut_focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()
    
    def _shortcut_delete_current(self):
        if self._selection_mode:
            self._execute_batch_delete()
        else:
            item = self.account_list.currentItem()
            if item:
                self._enter_selection_mode()
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and hasattr(data, 'id'):
                    self._selected_ids.add(data.id)
                elif data and isinstance(data, dict) and 'id' in data:
                    self._selected_ids.add(data['id'])
                self._update_bottom_bar_for_selection()
                self._execute_batch_delete()
    
    def _shortcut_escape(self):
        if self._selection_mode:
            self._exit_selection_mode()
        elif self.search_box.text().strip():
            self.search_box.clear()
            if self.current_vault == 'accounts':
                self.load_accounts()
            else:
                self.load_urls()
        elif self._ai_panel_visible:
            self.on_ai_toggle_panel()
    
    def _shortcut_toggle_theme(self):
        current = ThemeManager.instance().current_theme
        new_theme = 'dark' if current == 'light' else 'light'
        self.setUpdatesEnabled(False)
        try:
            ThemeManager.instance().apply_theme(new_theme)
        finally:
            self.setUpdatesEnabled(True)
        # 持久化主题配置（与设置对话框行为一致）
        if self.config_path:
            try:
                import json
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                config['theme'] = new_theme
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
    
    def _shortcut_lock(self):
        self.show_lock_screen()
    
    def _shortcut_undo(self):
        """Ctrl+Z 撤销最近的批量删除"""
        if hasattr(self, '_undo_banner') and self._undo_banner and self._undo_banner.isVisible():
            self._undo_delete(self._undo_deleted_items)
    
    def _shortcut_toggle_selection_mode(self):
        """Ctrl+M 切换批量选择模式"""
        if self._selection_mode:
            self._exit_selection_mode()
        else:
            self._enter_selection_mode()
    
    def setup_ui(self):
        """设置界面"""
        colors = ThemeManager.instance().colors
        self.setWindowTitle("本地密码保险箱")
        self.setMinimumSize(900, 600)
        self.showMaximized()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # ==================== 顶部工具栏 ====================
        self.top_bar = QWidget()
        self.top_bar.setStyleSheet(f"background-color: {colors.bg_secondary}; border-bottom: 1px solid {colors.border_default};")
        self.top_bar.setFixedHeight(60)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(15, 10, 15, 10)
        
        # 搜索框（按回车搜索）
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索账号（应用名/网址/备注），按回车搜索...")
        self.search_box.setFixedHeight(36)
        self.search_box.setStyleSheet(style_input(colors))
        self.search_box.returnPressed.connect(self.on_search)
        top_layout.addWidget(self.search_box, 1)
        
        # 搜索历史下拉补全
        self._search_completer = QCompleter(self.search_box)
        self._search_model = QStringListModel()
        self._search_completer.setModel(self._search_model)
        self._search_completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.search_box.setCompleter(self._search_completer)
        
        self.search_box.installEventFilter(self)
        self._search_completer.activated.connect(self.on_search)
        
        # 搜索历史面板（弹出层，设为独立窗口避免 Qt 子 widget 层级冲突）
        self.search_history_panel = SearchHistoryPanel(None)
        self.search_history_panel.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.search_history_panel.search_requested.connect(self._on_history_search)
        self.search_history_panel.delete_requested.connect(self._on_history_delete)
        self.search_history_panel.clear_all_requested.connect(self._on_history_clear_all)
        
        # 输入文字时隐藏历史面板（让 QCompleter 接管）
        self.search_box.textChanged.connect(self._on_search_text_changed)
        
        # 筛选切换按钮
        self.btn_toggle_filter = QPushButton("🔍筛选")
        self.btn_toggle_filter.setFixedWidth(100)
        self.btn_toggle_filter.setCheckable(True)
        self.btn_toggle_filter.setToolTip("展开/收起高级筛选")
        self.btn_toggle_filter.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                font-size: 14px;
            }}
            QPushButton:checked {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_accent};
                border: 1px solid {colors.accent_blue};
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
            }}
            QPushButton:checked:hover {{
                background-color: {colors.accent_blue_dark};
            }}
        """)
        self.btn_toggle_filter.clicked.connect(lambda checked: self._on_filter_toggle(checked))
        top_layout.addWidget(self.btn_toggle_filter)
        
        # 筛选条件已启用标签
        self.lbl_filter_active = QLabel("筛选条件已启用")
        self.lbl_filter_active.setStyleSheet(f"color: {colors.accent_orange_text}; font-size: 11px; font-weight: bold; padding: 0 4px;")
        self.lbl_filter_active.hide()
        top_layout.addWidget(self.lbl_filter_active)
        
        top_layout.addSpacing(10)
        
        # 库切换按钮组
        from PyQt6.QtWidgets import QButtonGroup
        self.tab_group = QButtonGroup(self)
        self.btn_vault_accounts = QPushButton("密码库")
        self.btn_vault_urls = QPushButton("网址库")
        self.btn_vault_accounts.setCheckable(True)
        self.btn_vault_urls.setCheckable(True)
        self.btn_vault_accounts.setChecked(True)
        self.btn_vault_accounts.setFixedHeight(36)
        self.btn_vault_urls.setFixedHeight(36)
        # 统一样式：checked 时白字深色背景，unchecked 时深色字浅色背景
        tab_style = f"""
            QPushButton {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_medium};
                border-radius: 4px;
                font-weight: bold;
                padding: 0 14px;
            }}
            QPushButton:checked {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_accent};
                border: 1px solid {colors.accent_blue};
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg};
            }}
            QPushButton:checked:hover {{
                background-color: {colors.accent_blue_dark};
            }}
        """
        self.btn_vault_accounts.setStyleSheet(tab_style)
        self.btn_vault_urls.setStyleSheet(tab_style)
        self.tab_group.addButton(self.btn_vault_accounts, 0)
        self.tab_group.addButton(self.btn_vault_urls, 1)
        self.tab_group.idClicked.connect(self._on_vault_tab_changed)
        
        top_layout.addWidget(self.btn_vault_accounts)
        top_layout.addWidget(self.btn_vault_urls)
        top_layout.addSpacing(10)
        
        # 添加按钮（文字随当前库动态变化）
        self.btn_add = QPushButton("+ 添加账号")
        self.btn_add.setFixedHeight(36)
        self.btn_add.setFixedWidth(120)
        self.btn_add.setStyleSheet(style_button_primary(colors))
        self.btn_add.clicked.connect(self.on_add_item)
        top_layout.addWidget(self.btn_add)
        
        top_layout.addSpacing(10)
        
        # 炽阳按钮
        self.btn_ai_toggle = QPushButton("炽阳")
        self.btn_ai_toggle.setFixedHeight(36)
        self.btn_ai_toggle.setFixedWidth(80)
        self.btn_ai_toggle.setStyleSheet(f"""
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
        self.btn_ai_toggle.setToolTip("打开/关闭 炽阳 面板")
        self.btn_ai_toggle.clicked.connect(self.on_ai_toggle_panel)
        top_layout.addWidget(self.btn_ai_toggle)
        
        top_layout.addSpacing(10)
        
        # 设置按钮
        self.btn_settings = QPushButton("设置")
        self.btn_settings.setFixedSize(60, 36)
        self.btn_settings.setToolTip("设置")
        self.btn_settings.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
            }}
        """)
        self.btn_settings.clicked.connect(self.on_settings)
        top_layout.addWidget(self.btn_settings)
        
        top_layout.addSpacing(10)
        
        # 帮助按钮（SVG 灯泡图标，默认透明背景融入工具栏）
        colors = ThemeManager.instance().colors
        self.btn_help = QPushButton()
        self.btn_help.setToolTip("使用帮助")
        self.btn_help.setFixedSize(32, 32)
        self.btn_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_help.setIcon(IconManager.help_icon(size=20, color=colors.accent_orange))
        self.btn_help.setIconSize(QSize(20, 20))
        self.btn_help.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_orange_bg};
                border-color: {colors.accent_orange};
            }}
            QPushButton:pressed {{
                background-color: {colors.accent_orange_bg};
            }}
        """)
        self.btn_help.clicked.connect(self._on_show_help)
        top_layout.addWidget(self.btn_help)
        
        top_layout.addSpacing(8)
        
        main_layout.addWidget(self.top_bar)
        
        # ==================== 高级筛选面板 ====================
        self.filter_panel = QWidget()
        self.filter_panel.setVisible(False)
        self.filter_panel.setMaximumHeight(44)
        self.filter_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.filter_panel.setStyleSheet(f"background-color: {colors.bg_secondary}; border-bottom: 1px solid {colors.border_default};")
        filter_wrap_layout = QHBoxLayout(self.filter_panel)
        filter_wrap_layout.setContentsMargins(8, 4, 8, 4)
        filter_wrap_layout.setSpacing(8)
        
        label_style = f"color: {colors.text_primary}; font-size: 12px;"
        combo_style = f"""
            QComboBox {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 2px 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
            }}
        """
        date_style = f"""
            QDateEdit {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 2px 8px;
            }}
            QDateEdit::drop-down {{
                border: none;
            }}
        """
        
        self.lbl_filter_category = QLabel("分类:")
        self.lbl_filter_category.setStyleSheet(label_style)
        filter_wrap_layout.addWidget(self.lbl_filter_category)
        self.filter_category = QComboBox()
        self.filter_category.setStyleSheet(combo_style)
        self.filter_category.setMinimumWidth(80)
        self.filter_category.addItem("全部", None)
        filter_wrap_layout.addWidget(self.filter_category)
        
        self.lbl_filter_created = QLabel("创建:")
        self.lbl_filter_created.setStyleSheet(label_style)
        filter_wrap_layout.addWidget(self.lbl_filter_created)
        self.filter_date_from = QDateEdit()
        self.filter_date_from.setStyleSheet(date_style)
        self.filter_date_from.setCalendarPopup(True)
        self.filter_date_from.setDate(QDate.currentDate().addYears(-1))
        self.filter_date_from.setMinimumWidth(95)
        self.filter_date_from.setDisplayFormat("yyyy-MM-dd")
        self.filter_date_from.setToolTip("默认起始时间将自动设为数据最早记录")
        filter_wrap_layout.addWidget(self.filter_date_from)
        self.lbl_filter_to = QLabel("至")
        self.lbl_filter_to.setStyleSheet(label_style)
        filter_wrap_layout.addWidget(self.lbl_filter_to)
        self.filter_date_to = QDateEdit()
        self.filter_date_to.setStyleSheet(date_style)
        self.filter_date_to.setCalendarPopup(True)
        self.filter_date_to.setDate(QDate.currentDate())
        self.filter_date_to.setMinimumWidth(95)
        self.filter_date_to.setDisplayFormat("yyyy-MM-dd")
        filter_wrap_layout.addWidget(self.filter_date_to)
        
        self.lbl_filter_strength = QLabel("强度:")
        self.lbl_filter_strength.setStyleSheet(label_style)
        filter_wrap_layout.addWidget(self.lbl_filter_strength)
        self.filter_strength = QComboBox()
        self.filter_strength.setStyleSheet(combo_style)
        self.filter_strength.setMinimumWidth(70)
        self.filter_strength.addItems(["全部", "弱", "中", "强", "极强"])
        filter_wrap_layout.addWidget(self.filter_strength)
        
        self.btn_apply_filter = QPushButton("筛选")
        self.btn_apply_filter.setMinimumWidth(60)
        self.btn_apply_filter.setStyleSheet(style_button_primary(colors))
        self.btn_apply_filter.clicked.connect(self._on_apply_filter)
        filter_wrap_layout.addWidget(self.btn_apply_filter)
        
        self.btn_clear_filter = QPushButton("清除")
        self.btn_clear_filter.setMinimumWidth(60)
        self.btn_clear_filter.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
            }}
        """)
        self.btn_clear_filter.clicked.connect(self._on_clear_filter)
        filter_wrap_layout.addWidget(self.btn_clear_filter)
        
        filter_wrap_layout.addStretch()
        main_layout.addWidget(self.filter_panel)

        self._calendar_style_applied = False
        self._filter_earliest_date = QDate.currentDate().addYears(-1)
        
        # ==================== 中间内容区 ====================
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ---- 左侧分类导航 ----
        self.left_panel = QWidget()
        self.left_panel.setStyleSheet(f"background-color: {colors.bg_surface}; border-right: 1px solid {colors.border_default};")
        self.left_panel.setFixedWidth(230)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 10, 0, 10)
        left_layout.setSpacing(0)
        
        # 类别标题栏（标题 + 排序按钮）
        category_header = QHBoxLayout()
        category_header.setContentsMargins(12, 12, 12, 8)
        category_header.setSpacing(5)
        
        lbl_category = QLabel("类别")
        lbl_category.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                color: {colors.accent_blue};
                font-size: 13px;
                padding-left: 4px;
                border-left: 3px solid {colors.accent_blue_light};
            }}
        """)
        category_header.addWidget(lbl_category)
        category_header.addStretch()
        
        self.btn_category_sort = QPushButton("排序")
        self.btn_category_sort.setFixedSize(56, 26)
        self.btn_category_sort.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border: 1px solid {colors.accent_blue_light};
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg_hover};
            }}
        """)
        self.btn_category_sort.setToolTip("编辑类别顺序")
        self.btn_category_sort.clicked.connect(self._on_category_edit_toggle)
        category_header.addWidget(self.btn_category_sort)
        
        # 类别重组按钮
        self.btn_category_reorganize = QPushButton("重组")
        self.btn_category_reorganize.setFixedSize(56, 26)
        self.btn_category_reorganize.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border: 1px solid {colors.accent_blue_light};
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg_hover};
            }}
        """)
        self.btn_category_reorganize.setToolTip("重组分类结构")
        self.btn_category_reorganize.clicked.connect(self._on_category_reorganize_toggle)
        category_header.addWidget(self.btn_category_reorganize)
        
        # 类别批量删除按钮
        self.btn_category_batch_delete = QPushButton("删除")
        self.btn_category_batch_delete.setFixedSize(56, 26)
        self.btn_category_batch_delete.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_red_bg};
                color: {colors.accent_red_dark};
                border: 1px solid {colors.accent_red};
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_red_bg};
            }}
        """)
        self.btn_category_batch_delete.setToolTip("批量删除类别")
        self.btn_category_batch_delete.clicked.connect(self._on_category_batch_delete_toggle)
        category_header.addWidget(self.btn_category_batch_delete)
        left_layout.addLayout(category_header)
        
        # 重组模式顶部固定拖放区域
        self.drop_zone_widget = DropZoneWidget()
        self.drop_zone_widget.hide()
        self.drop_zone_widget.dropped.connect(self._on_drop_zone_dropped)
        left_layout.addWidget(self.drop_zone_widget)
        
        # 分类树
        self.category_tree = CategoryTreeWidget()
        self.category_tree.setFrameShape(QFrame.Shape.NoFrame)
        self.category_tree.setHeaderHidden(True)
        self.category_tree.setColumnCount(1)
        # 新增：占满父容器高度
        self.category_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        import os
        _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._branch_closed_svg = os.path.join(_base_dir, 'assets', 'icons', 'branch_closed.svg').replace('\\', '/')
        self._branch_open_svg = os.path.join(_base_dir, 'assets', 'icons', 'branch_open.svg').replace('\\', '/')
        self._category_tree_normal_style = f"""
            QTreeWidget {{
                background-color: {colors.bg_surface};
                border: none;
            }}
            QTreeWidget::item {{
                padding: 12px 15px;
                border-radius: 0;
            }}
            QTreeWidget::item:selected {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border-left: 3px solid {colors.accent_blue_light};
            }}
            QTreeWidget::item:hover {{
                background-color: {colors.bg_hover};
                border-left: 3px solid {colors.accent_blue_light};
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                image: url("{self._branch_closed_svg}");
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                image: url("{self._branch_open_svg}");
            }}
        """
        
        self._category_tree_checkbox_style = f"""
            QTreeWidget {{
                background-color: {colors.bg_surface};
                border: none;
            }}
            QTreeWidget::item {{
                padding: 12px 15px;
                border-radius: 0;
            }}
            QTreeWidget::item:selected {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border-left: 3px solid {colors.accent_blue_light};
            }}
            QTreeWidget::indicator {{
                width: 16px;
                height: 16px;
            }}
            QTreeWidget::indicator:unchecked {{
                border: 2px solid {colors.text_secondary};
                background-color: {colors.bg_primary};
                border-radius: 3px;
            }}
            QTreeWidget::indicator:checked {{
                background-color: {colors.accent_blue};
                border: 2px solid {colors.accent_blue};
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                image: url("{self._branch_closed_svg}");
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                image: url("{self._branch_open_svg}");
            }}
        """
        
        self.category_tree.set_normal_style(self._category_tree_normal_style)
        self.category_tree.setStyleSheet(self._category_tree_normal_style)
        self.category_tree.itemClicked.connect(self._on_category_clicked)
        self.category_tree.reorganize_requested.connect(self._on_reorganize_requested)
        self.category_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.category_tree.customContextMenuRequested.connect(self._on_category_context_menu)
        self.category_tree.setDragDropMode(QTreeWidget.DragDropMode.NoDragDrop)
        self.category_tree.itemChanged.connect(self._on_category_check_changed)
        
        left_layout.addWidget(self.category_tree, 1)  # stretch factor=1，占满剩余高度
        
        # 类别批量删除底部操作栏
        self.category_sel_bar = QWidget()
        self.category_sel_bar.setStyleSheet(f"background-color: {colors.bg_secondary}; border-top: 1px solid {colors.border_default};")
        self.category_sel_bar.setFixedHeight(44)
        cat_sel_layout = QHBoxLayout(self.category_sel_bar)
        cat_sel_layout.setContentsMargins(10, 5, 10, 5)
        cat_sel_layout.setSpacing(8)
        
        self.btn_cat_sel_all = QPushButton("全选")
        self.btn_cat_sel_all.setFixedHeight(32)
        self.btn_cat_sel_all.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border: 1px solid {colors.accent_blue_light};
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg_hover};
            }}
        """)
        self.btn_cat_sel_all.clicked.connect(self._toggle_category_select_all)
        cat_sel_layout.addWidget(self.btn_cat_sel_all)
        
        self.btn_cat_sel_delete = QPushButton("删除(0)")
        self.btn_cat_sel_delete.setFixedHeight(32)
        self.btn_cat_sel_delete.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_red};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_red_dark};
            }}
        """)
        self.btn_cat_sel_delete.clicked.connect(self._execute_category_batch_delete)
        cat_sel_layout.addWidget(self.btn_cat_sel_delete)
        
        self.category_sel_bar.hide()
        left_layout.addWidget(self.category_sel_bar)
        
        splitter.addWidget(self.left_panel)
        
        # ---- 中间账号列表 ----
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(15, 15, 15, 15)
        center_layout.setSpacing(10)
        
        # 账号列表标题 + 紧凑视图切换按钮
        title_header = QHBoxLayout()
        title_header.setContentsMargins(0, 0, 0, 0)
        title_header.setSpacing(6)
        
        self.lbl_list_title = QLabel("全部账号")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self.lbl_list_title.setFont(font)
        self.lbl_list_title.setStyleSheet(f"color: {colors.text_primary}; padding-bottom: 10px;")
        title_header.addWidget(self.lbl_list_title, 1)
        
        self.btn_compact_view = QPushButton()
        self.btn_compact_view.setFixedSize(28, 28)
        self.btn_compact_view.setCheckable(True)
        self.btn_compact_view.setToolTip("切换紧凑视图")
        self.btn_compact_view.setIcon(IconManager.compact_icon(size=16, color=colors.text_secondary))
        self.btn_compact_view.setIconSize(QSize(16, 16))
        self.btn_compact_view.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {colors.border_default};
                background-color: {colors.bg_tertiary};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
                border-color: {colors.border_medium};
            }}
            QPushButton:checked {{
                background-color: {colors.accent_blue_bg};
                border-color: {colors.accent_blue};
            }}
        """)
        self.btn_compact_view.clicked.connect(self._toggle_compact_view)
        title_header.addWidget(self.btn_compact_view)
        
        self.btn_column_settings = QPushButton()
        self.btn_column_settings.setFixedSize(28, 28)
        self.btn_column_settings.setToolTip("设置列表显示内容")
        self.btn_column_settings.setIcon(IconManager.settings_icon(size=16, color=colors.text_secondary))
        self.btn_column_settings.setIconSize(QSize(16, 16))
        self.btn_column_settings.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {colors.border_default};
                background-color: {colors.bg_tertiary};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
                border-color: {colors.border_medium};
            }}
        """)
        self.btn_column_settings.clicked.connect(self._on_column_settings_clicked)
        title_header.addWidget(self.btn_column_settings)
        
        center_layout.addLayout(title_header)
        
        # AI 筛选横幅
        self.ai_filter_banner = QWidget()
        self.ai_filter_banner.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.accent_blue_bg};
                border: none;
                border-radius: 4px;
            }}
        """)
        filter_banner_layout = QHBoxLayout(self.ai_filter_banner)
        filter_banner_layout.setContentsMargins(10, 6, 10, 6)
        
        self.lbl_ai_filter = QLabel("")
        self.lbl_ai_filter.setStyleSheet(f"color: {colors.accent_blue_dark}; font-size: 12px;")
        filter_banner_layout.addWidget(self.lbl_ai_filter, 1)
        
        self.btn_clear_ai_filter = QPushButton("清除筛选")
        self.btn_clear_ai_filter.setFixedHeight(24)
        self.btn_clear_ai_filter.setFixedWidth(90)
        self.btn_clear_ai_filter.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_light};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 3px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue};
            }}
        """)
        self.btn_clear_ai_filter.clicked.connect(self.clear_account_highlight)
        filter_banner_layout.addWidget(self.btn_clear_ai_filter)
        
        self.ai_filter_banner.hide()
        center_layout.addWidget(self.ai_filter_banner)
        
        # 撤销删除横幅（默认隐藏）
        self._undo_banner = QWidget()
        self._undo_banner.setObjectName("undoBanner")
        undo_layout = QHBoxLayout(self._undo_banner)
        undo_layout.setContentsMargins(12, 6, 12, 6)
        
        self._undo_msg = QLabel("")
        self._undo_msg.setStyleSheet(f"color: {colors.text_on_dark}; font-size: 13px;")
        undo_layout.addWidget(self._undo_msg)
        
        undo_layout.addStretch()
        
        self._undo_btn = QPushButton("撤销")
        self._undo_btn.setFixedWidth(60)
        self._undo_btn.setStyleSheet(f"""
            QPushButton {{ background: {colors.bg_card}; color: {colors.text_primary}; border-radius: 4px; padding: 4px 12px; font-weight: bold; }}
            QPushButton:hover {{ background: {colors.bg_hover}; }}
        """)
        undo_layout.addWidget(self._undo_btn)
        
        close_btn = QPushButton("\u2715")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(f"color: {colors.text_on_dark}; border: none; font-size: 14px;")
        close_btn.clicked.connect(self._dismiss_undo_banner)
        undo_layout.addWidget(close_btn)
        
        self._undo_banner.setStyleSheet(f"""
            #undoBanner {{ background-color: {colors.bg_secondary}; border-radius: 8px; }}
        """)
        self._undo_banner.setFixedHeight(42)
        self._undo_banner.hide()
        center_layout.addWidget(self._undo_banner)
        
        # 账号列表 + 字母导航条
        list_container = QWidget()
        list_row = QHBoxLayout(list_container)
        list_row.setContentsMargins(0, 0, 0, 0)
        list_row.setSpacing(0)
        
        self.account_list = QListWidget()
        self.account_list.setFrameShape(QFrame.Shape.NoFrame)
        self.account_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {colors.bg_secondary};
                border: none;
            }}
            QListWidget::item {{
                background-color: transparent;
                border: none;
                padding: 0px;
            }}
        """)
        self.account_list.setSpacing(0)
        self.account_list.itemClicked.connect(self.on_account_clicked)
        self.account_list.itemDoubleClicked.connect(self.on_account_double_clicked)
        self.account_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.account_list.customContextMenuRequested.connect(self._on_list_item_context_menu)
        self.account_list.viewport().installEventFilter(self)
        
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.account_list)
        # dashboard 在 _url_service 初始化后创建（见 __init__ 末尾）
        self.dashboard = None
        self.list_stack.setCurrentIndex(0)
        
        list_row.addWidget(self.list_stack, 1)
        
        # 字母索引导航条
        self.alpha_nav = self._build_alpha_nav()
        list_row.addWidget(self.alpha_nav)
        
        center_layout.addWidget(list_container)
        
        splitter.addWidget(center_panel)
        
        # ---- 右侧 炽阳 面板 ----
        self.ai_panel = QWidget()
        self.ai_panel.setStyleSheet(f"background-color: {colors.bg_surface}; border-left: 1px solid {colors.border_default};")
        self.ai_panel.setMinimumWidth(0)
        self.ai_panel.setMaximumWidth(0)  # 默认隐藏
        ai_layout = QVBoxLayout(self.ai_panel)
        ai_layout.setContentsMargins(10, 10, 10, 10)
        ai_layout.setSpacing(8)
        
        # 炽阳标题栏
        ai_header = QHBoxLayout()
        lbl_ai_title = QLabel("炽阳")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        lbl_ai_title.setFont(font)
        lbl_ai_title.setStyleSheet(f"""
            QLabel {{
                color: {colors.accent_orange_dark};
                padding: 2px 4px;
            }}
            QLabel:hover {{
                color: {colors.accent_orange_dark};
                text-decoration: underline;
            }}
        """)
        lbl_ai_title.setCursor(Qt.CursorShape.PointingHandCursor)
        lbl_ai_title.setToolTip("点击查看 炽阳 使用说明")
        lbl_ai_title.mousePressEvent = lambda e: self.on_ai_show_help()
        ai_header.addWidget(lbl_ai_title)
        ai_header.addStretch()
        
        btn_ai_clear = QPushButton("清空")
        btn_ai_clear.setFixedHeight(28)
        btn_ai_clear.setFixedWidth(80)
        btn_ai_clear.setStyleSheet("font-size: 11px;")
        btn_ai_clear.clicked.connect(self.on_ai_clear_history)
        ai_header.addWidget(btn_ai_clear)
        ai_layout.addLayout(ai_header)
        
        # 模式切换栏（Plan / Build）
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(6)
        
        self.btn_mode_plan = QPushButton("🛡️ Plan")
        self.btn_mode_plan.setFixedHeight(28)
        self.btn_mode_plan.setCheckable(True)
        self.btn_mode_plan.setChecked(True)
        self.btn_mode_plan.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border: 1px solid {colors.accent_blue};
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 10px;
            }}
            QPushButton:checked {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_accent};
            }}
        """)
        self.btn_mode_plan.clicked.connect(lambda: self._on_ai_mode_changed('plan'))
        mode_layout.addWidget(self.btn_mode_plan)
        
        self.btn_mode_build = QPushButton("🔨 Build")
        self.btn_mode_build.setFixedHeight(28)
        self.btn_mode_build.setCheckable(True)
        self.btn_mode_build.setChecked(False)
        self.btn_mode_build.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_orange_bg};
                color: {colors.accent_orange_text};
                border: 1px solid {colors.accent_orange_text};
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                padding: 0 10px;
            }}
            QPushButton:checked {{
                background-color: {colors.accent_orange_text};
                color: {colors.text_on_accent};
            }}
        """)
        self.btn_mode_build.clicked.connect(lambda: self._on_ai_mode_changed('build'))
        mode_layout.addWidget(self.btn_mode_build)
        
        self.lbl_mode_hint = QLabel("只提供建议，不操作数据")
        self.lbl_mode_hint.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 10px;")
        mode_layout.addWidget(self.lbl_mode_hint)
        mode_layout.addStretch()
        ai_layout.addLayout(mode_layout)
        
        # 模式横幅
        self.ai_mode_banner = QLabel("🔍 规划模式 — 只读查询")
        self.ai_mode_banner.setFixedHeight(32)
        self.ai_mode_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ai_mode_banner.setStyleSheet(f"""
            QLabel {{
                background-color: {colors.accent_blue_light};
                color: {colors.text_on_accent};
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }}
        """)
        ai_layout.addWidget(self.ai_mode_banner)
        
        # 对话显示区（thinking + result + preview）
        chat_container = QWidget()
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(6)
        
        # 思考区
        self.thinking_area = QTextEdit()
        self.thinking_area.setPlaceholderText("思考过程...")
        self.thinking_area.setReadOnly(True)
        self.thinking_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_light};
                border-radius: 6px;
                padding: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                color: {colors.text_secondary};
            }}
        """)
        self.thinking_area.setMaximumHeight(180)
        self.thinking_area.hide()
        chat_layout.addWidget(self.thinking_area, 1)
        
        # 结果区（历史对话 + 当前结果）
        self.result_area = QTextBrowser()
        self.result_area.setOpenLinks(False)
        self.result_area.anchorClicked.connect(self._on_ai_anchor_clicked)
        self.result_area.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_light};
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                line-height: 1.6;
            }}
        """)
        self.result_area.setPlaceholderText("炽阳 对话将显示在这里...")
        chat_layout.addWidget(self.result_area, 3)
        
        # 操作按钮（复制、重新生成）
        self.ai_action_buttons = QWidget()
        btn_layout = QHBoxLayout(self.ai_action_buttons)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addStretch()
        
        btn_copy = QPushButton("📋 复制")
        btn_copy.setFixedHeight(28)
        btn_copy.setFixedWidth(90)
        btn_copy.setStyleSheet("font-size: 11px;")
        btn_copy.clicked.connect(self._on_ai_copy_result)
        btn_layout.addWidget(btn_copy)
        
        btn_regenerate = QPushButton("🔄 重新生成")
        btn_regenerate.setFixedHeight(28)
        btn_regenerate.setFixedWidth(110)
        btn_regenerate.setStyleSheet("font-size: 11px;")
        btn_regenerate.clicked.connect(self._on_ai_regenerate)
        btn_layout.addWidget(btn_regenerate)
        
        chat_layout.addWidget(self.ai_action_buttons)
        self.ai_action_buttons.hide()
        
        # Build 模式操作预览 Widget
        self.action_preview_widget = ActionPreviewWidget('explain', {}, parent=self)
        self.action_preview_widget.hide()
        self.action_preview_widget.confirmed.connect(self._on_action_preview_confirmed)
        self.action_preview_widget.cancelled.connect(self._on_action_preview_cancelled)
        chat_layout.addWidget(self.action_preview_widget)
        
        ai_layout.addWidget(chat_container, 1)
        
        # 输入区（多行文本框，支持自动换行）
        ai_input_layout = QHBoxLayout()
        
        class AIInputEdit(QTextEdit):
            """AI 输入框：Enter 发送，Shift+Enter 换行，最多显示5行"""
            def __init__(self, parent=None, send_callback=None):
                colors = ThemeManager.instance().colors
                super().__init__(parent)
                self.send_callback = send_callback
                self.setPlaceholderText("输入指令，如：查找支付类账号")
                # 最小高度约1行，最大高度约5行
                self.setMinimumHeight(40)
                self.setMaximumHeight(110)
                self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
                self.setStyleSheet(f"""
                    QTextEdit {{
                        background-color: {colors.bg_primary};
                        color: {colors.text_primary};
                        border: 1px solid {colors.border_default};
                        border-radius: 6px;
                        padding: 6px 10px;
                        font-size: 13px;
                        line-height: 1.4;
                    }}
                """)
                self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            
            def keyPressEvent(self, event):
                colors = ThemeManager.instance().colors
                if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    # Enter（不带Shift）→ 发送
                    if self.send_callback:
                        self.send_callback()
                    return
                super().keyPressEvent(event)
        
        self.ai_input = AIInputEdit(send_callback=self.on_ai_send_message)
        ai_input_layout.addWidget(self.ai_input, 1)
        
        self.btn_ai_send = QPushButton("发送")
        self.btn_ai_send.setMinimumHeight(40)
        self.btn_ai_send.setMaximumHeight(110)
        self.btn_ai_send.setFixedWidth(60)
        self._update_send_button_style(False)
        self.btn_ai_send.clicked.connect(self._on_ai_send_or_stop)
        ai_input_layout.addWidget(self.btn_ai_send)
        
        ai_layout.addLayout(ai_input_layout)
        
        # 确认执行区域（Build 模式下，危险操作需要用户确认）
        self.ai_confirm_widget = QWidget()
        self.ai_confirm_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.ai_thinking_bg};
                border: 1px solid {colors.border_light};
                border-radius: 6px;
            }}
        """)
        self.ai_confirm_widget.hide()
        confirm_layout = QHBoxLayout(self.ai_confirm_widget)
        confirm_layout.setContentsMargins(8, 6, 8, 6)
        confirm_layout.setSpacing(8)
        
        self.lbl_confirm_desc = QLabel("")
        self.lbl_confirm_desc.setStyleSheet(f"color: {colors.accent_orange_text}; font-size: 11px;")
        confirm_layout.addWidget(self.lbl_confirm_desc, 1)
        
        btn_confirm_cancel = QPushButton("取消")
        btn_confirm_cancel.setFixedHeight(28)
        btn_confirm_cancel.setFixedWidth(50)
        btn_confirm_cancel.setStyleSheet("font-size: 11px;")
        btn_confirm_cancel.clicked.connect(self._on_ai_confirm_cancel)
        confirm_layout.addWidget(btn_confirm_cancel)
        
        btn_confirm_ok = QPushButton("✅ 确认执行")
        btn_confirm_ok.setFixedHeight(28)
        btn_confirm_ok.setFixedWidth(80)
        btn_confirm_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_green};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_green_dark};
            }}
        """)
        btn_confirm_ok.clicked.connect(self._on_ai_confirm_execute)
        confirm_layout.addWidget(btn_confirm_ok)
        
        ai_layout.addWidget(self.ai_confirm_widget)
        
        # 初始化 AI 模式横幅和样式
        self._on_ai_mode_changed('plan')
        
        splitter.addWidget(self.ai_panel)
        splitter.setSizes([230, 570, 0])
        
        main_layout.addWidget(splitter)
        
        # ==================== 底部工具栏 ====================
        self.bottom_bar = QWidget()
        self.bottom_bar.setStyleSheet(f"background-color: {colors.bg_secondary}; border-top: 1px solid {colors.border_default};")
        self.bottom_bar.setFixedHeight(50)
        bottom_layout = QHBoxLayout(self.bottom_bar)
        bottom_layout.setContentsMargins(15, 5, 15, 5)
        
        # 锁定按钮
        btn_lock = QPushButton("锁定")
        btn_lock.setFixedHeight(36)
        btn_lock.clicked.connect(self.on_lock)
        bottom_layout.addWidget(btn_lock)
        
        bottom_layout.addStretch()
        
        # Ollama状态显示（可点击刷新）
        self.lbl_ollama_status = QLabel("AI模型: 检测中...")
        self.lbl_ollama_status.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px;")
        self.lbl_ollama_status.setToolTip("点击刷新AI模型状态")
        self.lbl_ollama_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_ollama_status.mousePressEvent = lambda event: self._ai_manager.request_refresh()
        # 绑定状态变化信号
        self._ai_manager.state_changed.connect(self._on_ai_state_changed)
        # 初始化显示
        self._on_ai_state_changed(self._ai_manager.get_state())
        bottom_layout.addWidget(self.lbl_ollama_status)
        
        bottom_layout.addSpacing(20)
        
        # 批量导入按钮
        btn_import = QPushButton("批量导入")
        btn_import.setFixedHeight(36)
        btn_import.clicked.connect(self.on_batch_import)
        bottom_layout.addWidget(btn_import)
        
        bottom_layout.addSpacing(10)
        
        # 导出按钮
        btn_export = QPushButton("导出")
        btn_export.setFixedHeight(36)
        btn_export.clicked.connect(self.on_export)
        bottom_layout.addWidget(btn_export)
        
        bottom_layout.addSpacing(10)
        
        # 回收站按钮
        btn_recycle = QPushButton("回收站")
        btn_recycle.setFixedHeight(36)
        btn_recycle.clicked.connect(self.on_recycle_bin)
        bottom_layout.addWidget(btn_recycle)
        
        bottom_layout.addSpacing(10)
        
        # 批量操作按钮
        self.btn_batch_delete = QPushButton("批量操作")
        self.btn_batch_delete.setFixedHeight(36)
        self.btn_batch_delete.setToolTip("批量删除、移动分类、编辑标签等")
        self.btn_batch_delete.clicked.connect(self._enter_selection_mode)
        bottom_layout.addWidget(self.btn_batch_delete)
        
        bottom_layout.addSpacing(10)
        
        # 同步按钮
        self.btn_sync = QPushButton("同步到手机")
        self.btn_sync.setFixedHeight(36)
        self.btn_sync.clicked.connect(self.on_sync_to_mobile)
        self.btn_sync.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_sync.customContextMenuRequested.connect(self._on_sync_button_context_menu)
        bottom_layout.addWidget(self.btn_sync)
        
        main_layout.addWidget(self.bottom_bar)
        
        # ==================== 选择模式底部工具栏 ====================
        self.selection_bottom_bar = QWidget()
        self.selection_bottom_bar.setStyleSheet(f"background-color: {colors.bg_secondary}; border-top: 1px solid {colors.border_default};")
        self.selection_bottom_bar.setFixedHeight(50)
        selection_layout = QHBoxLayout(self.selection_bottom_bar)
        selection_layout.setContentsMargins(15, 5, 15, 5)
        
        self.btn_sel_cancel = QPushButton("取消")
        self.btn_sel_cancel.setFixedHeight(36)
        self.btn_sel_cancel.clicked.connect(self._exit_selection_mode)
        selection_layout.addWidget(self.btn_sel_cancel)
        
        selection_layout.addStretch()
        
        self.btn_sel_all = QPushButton("全选")
        self.btn_sel_all.setFixedHeight(36)
        self.btn_sel_all.clicked.connect(self._toggle_select_all)
        selection_layout.addWidget(self.btn_sel_all)
        
        selection_layout.addSpacing(10)
        
        self.btn_sel_delete = QPushButton("删除(0)")
        self.btn_sel_delete.setFixedHeight(36)
        self.btn_sel_delete.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_red};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_red_dark};
            }}
        """)
        self.btn_sel_delete.clicked.connect(self._execute_batch_delete)
        selection_layout.addWidget(self.btn_sel_delete)
        
        selection_layout.addSpacing(10)
        
        self.btn_batch_categorize = QPushButton("批量分类")
        self.btn_batch_categorize.setFixedHeight(36)
        self.btn_batch_categorize.clicked.connect(self._execute_batch_categorize)
        selection_layout.addWidget(self.btn_batch_categorize)
        
        self.btn_batch_tag = QPushButton("批量标签")
        self.btn_batch_tag.setFixedHeight(36)
        self.btn_batch_tag.clicked.connect(self._execute_batch_tag)
        selection_layout.addWidget(self.btn_batch_tag)
        
        self.selection_bottom_bar.hide()
        main_layout.addWidget(self.selection_bottom_bar)
    
    def _build_alpha_nav(self):
        """构建右侧字母索引导航条"""
        colors = ThemeManager.instance().colors
        nav = QWidget()
        nav.setFixedWidth(40)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 5, 0, 5)
        nav_layout.setSpacing(3)
        nav_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        letters = list('ABCDEFGHIJKLMNOPQRSTUVWXYZ#')
        for letter in letters:
            lbl = QLabel(letter)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"""
                QLabel {{
                    color: {colors.accent_blue_light};
                    font-size: 12px;
                    font-weight: bold;
                    padding: 2px 4px;
                }}
                QLabel:hover {{
                    color: {colors.accent_blue};
                    background-color: {colors.accent_blue_bg};
                    border-radius: 10px;
                }}
            """)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.setFixedSize(28, 20)
            lbl.mousePressEvent = lambda e, l=letter: self._on_alpha_clicked(l)
            nav_layout.addWidget(lbl)
        
        nav_layout.addStretch()
        return nav
    
    def _get_alpha_key(self, text: str) -> str:
        """获取文本的首字母（英文直接取，中文转拼音首字母，其他归为#）"""
        if not text:
            return '#'
        first_char = text[0]
        # 英文字母
        if 'a' <= first_char.lower() <= 'z':
            return first_char.upper()
        # 中文 CJK 范围
        if '\u4e00' <= first_char <= '\u9fff':
            from core.pinyin import PinyinConverter
            initials = PinyinConverter.get_pinyin_initials(first_char)
            if initials:
                return initials[0].upper()
        # 数字、符号等其他字符归为 #
        return '#'
    
    def _on_alpha_clicked(self, letter: str):
        """点击字母导航，滚动到对应首字母的条目"""
        for i in range(self.account_list.count()):
            item = self.account_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data is None:
                continue
            
            key = ''
            if self.current_vault == 'accounts':
                app_name = getattr(data, 'app_name', '') or ''
                key = self._get_alpha_key(app_name)
            else:
                title = getattr(data, 'title', '') or ''
                if isinstance(data, dict):
                    title = data.get('title', '') or ''
                key = self._get_alpha_key(title)
            
            if key == letter:
                self.account_list.scrollToItem(item, self.account_list.ScrollHint.PositionAtTop)
                return
    
    def load_accounts(self):
        """加载账号列表（搜索框为空时调用）"""
        self._view_mode = 'default'
        self.lbl_list_title.show()
        self.account_list.clear()
        
        # 全量缓存：只在数据变更时从 service 加载一次，类别切换只做内存过滤
        if self._accounts_cache_dirty or not self._all_accounts_cache:
            self._all_accounts_cache = self.account_service.get_all_accounts()
            self._accounts_cache_dirty = False
        
        if self.current_category == '__favorites__':
            accounts = [a for a in self._all_accounts_cache if a.is_favorite]
        elif self.current_category == '__recent__':
            accounts = sorted(self._all_accounts_cache, key=lambda a: a.updated_at or datetime.min, reverse=True)[:20]
        elif self.current_category == '全部':
            accounts = self._all_accounts_cache.copy()
        else:
            from core.category_utils import get_prefix_matcher
            matcher = get_prefix_matcher(self.current_category)
            accounts = [a for a in self._all_accounts_cache if matcher(a.category)]
        
        # 扁平列表显示（按拼音首字母排序：英文/中文排前面，数字符号归为#排最后）
        # 最近使用页面保持按 updated_at 排序，不重新按字母排序
        if not accounts:
            self.btn_compact_view.setChecked(False)
            item = QListWidgetItem("暂无账号")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.account_list.addItem(item)
            return
        
        if self.current_category != '__recent__':
            from core.pinyin import PinyinConverter
            def _account_sort_key(acc):
                text = acc.app_name or ''
                if not text:
                    return (1, '')
                fc = text[0]
                if ('a' <= fc.lower() <= 'z') or ('\u4e00' <= fc <= '\u9fff'):
                    return (0, PinyinConverter.get_pinyin_initials(text).lower())
                return (1, text.lower())
            
            accounts.sort(key=_account_sort_key)
        
        is_compact = self._load_compact_preference()
        item_height = 32 if is_compact else 56
        col_config = self._load_column_config()
        item_width = max(self.account_list.width() - 20, 50)
        
        # 批量添加时禁用更新与信号，避免 O(n²) 布局重算
        self.account_list.setUpdatesEnabled(False)
        self.account_list.blockSignals(True)
        try:
            for idx, account in enumerate(accounts):
                item = QListWidgetItem()
                item.setSizeHint(QSize(item_width, item_height))
                item.setData(Qt.ItemDataRole.UserRole, account)
                self.account_list.addItem(item)
                
                widget = AccountListItem(account, selection_mode=self._selection_mode, parent=self.account_list)
                widget.hide()  # 防止无parent时短暂显示为独立窗口
                if self._selection_mode:
                    widget.on_check_changed = lambda checked, aid=account.id: self._on_item_checkbox_changed(aid, checked)
                if self._selection_mode and account.id in self._selected_ids:
                    widget.set_checked(True)
                if is_compact:
                    widget.set_compact_mode(True)
                self.account_list.setItemWidget(item, widget)
                for key, visible in col_config.items():
                    if not visible:
                        widget.set_column_visible(key, False)
        finally:
            self.account_list.blockSignals(False)
            self.account_list.setUpdatesEnabled(True)
            self.account_list.update()
        
        self.btn_compact_view.setChecked(is_compact)
        
        # 更新标题
        count = len(accounts)
        if self.current_category == '__favorites__':
            title = '收藏'
        elif self.current_category == '__recent__':
            title = '最近使用'
        elif self.current_category == '__dashboard__':
            title = '首页'
        elif self.current_category == '全部':
            title = '全部账号'
        else:
            title = self.current_category
        self.lbl_list_title.setText(f"{title} ({count})")
    
    def _on_vault_tab_changed(self, tab_id: int):
        """库切换事件"""
        # 如果处于分类编辑模式、重组模式或批量删除模式，先退出
        if getattr(self, '_category_edit_mode', False):
            self._on_category_edit_toggle()
        if getattr(self, '_category_reorganize_mode', False):
            self._on_category_reorganize_toggle()
        if getattr(self, '_category_selection_mode', False):
            self._on_category_batch_delete_toggle()
        
        if tab_id == 0:
            self.current_vault = 'accounts'
            self.lbl_list_title.setText("全部账号")
            self.search_box.setPlaceholderText("搜索账号（应用名/网址/备注），按回车搜索...")
            self.btn_add.setText("+ 添加账号")
        else:
            self.current_vault = 'urls'
            self.lbl_list_title.setText("全部网址")
            self.search_box.setPlaceholderText("搜索网址（标题/网址/备注）...")
            self.btn_add.setText("+ 添加网址")
        
        if self.dashboard is not None:
            self.dashboard.set_vault(self.current_vault)
        
        # 重置对话上下文和欢迎语状态
        self.ai_assistant.conversation_context.reset()
        self._ai_welcome_shown = False
        self.ai_assistant.clear_history('plan')
        self.ai_assistant.clear_history('build')
        self.result_area.clear()
        self.thinking_area.clear()
        self._ai_update_chat_display()
        self._ai_show_welcome()
        
        # 更新分类导航
        self._reload_categories()
        # 加载列表
        if self.current_vault == 'accounts':
            self.load_accounts()
        else:
            self.load_urls()
    
    def _get_total_count(self) -> int:
        """获取当前模式下总条目数"""
        if self.current_vault == 'accounts':
            return len(self.account_service.get_all_accounts())
        else:
            return len(self._url_service.get_all_urls())
    
    def _get_category_count(self, category: str) -> int:
        """获取指定分类（含子类）的条目数"""
        if self.current_vault == 'accounts':
            items = self.account_service.get_accounts_by_category(category)
        else:
            items = self._url_service.get_urls_by_category(category)
        return len(items)
    
    def _iter_category_tree_items(self):
        """遍历分类树中所有节点（排除'全部'根节点）"""
        root = self.category_tree.invisibleRootItem()
        for i in range(root.childCount()):
            top_item = root.child(i)
            cat = top_item.data(0, Qt.ItemDataRole.UserRole)
            if cat != '全部':
                yield top_item
            for j in range(top_item.childCount()):
                yield top_item.child(j)
    
    def _reload_categories(self):
        """重新加载分类导航（树形结构）"""
        saved_category = self.current_category  # Bug #1: 保存当前分类
        # 重建树期间断开 itemChanged，避免 setCheckState/clear 触发信号修改 _selected_categories
        try:
            self.category_tree.itemChanged.disconnect(self._on_category_check_changed)
        except Exception:
            pass
        self.category_tree.clear()
        
        # 获取当前模式的分类树
        if self.current_vault == 'accounts':
            tree_data = self.account_service.get_category_tree()
        else:
            tree_data = self._url_service.get_category_tree()
        
        edit_mode = getattr(self, '_category_edit_mode', False)
        cat_sel_mode = getattr(self, '_category_selection_mode', False)
        reorg_mode = getattr(self, '_category_reorganize_mode', False)
        
        # 预计算所有分类计数（一次查询，避免每个节点都查库）
        category_counts = defaultdict(int)
        if self.current_vault == 'accounts':
            all_items = self.account_service.get_all_accounts()
            fav_count = sum(1 for a in all_items if a.is_favorite)
        else:
            all_items = self._url_service.get_all_urls()
            fav_count = sum(1 for u in all_items if u.is_favorite)
        
        for item in all_items:
            cat = getattr(item, 'category', None) or '其他'
            category_counts[cat] += 1
            if '>' in cat:
                parent = cat.split('>')[0].strip()
                category_counts[parent] += 1
        
        total_count = len(all_items)
        category_counts['全部'] = total_count
        
        # 添加"🏠 首页"节点
        home_item = QTreeWidgetItem(self.category_tree)
        home_item.setText(0, "🏠 首页")
        home_item.setData(0, Qt.ItemDataRole.UserRole, '__dashboard__')
        if edit_mode or reorg_mode:
            home_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        elif cat_sel_mode:
            home_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # 添加"⭐ 收藏"节点
        root_fav = QTreeWidgetItem(self.category_tree)
        root_fav.setText(0, f"⭐ 收藏 ({fav_count})")
        root_fav.setData(0, Qt.ItemDataRole.UserRole, "__favorites__")
        if edit_mode or reorg_mode:
            root_fav.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        elif cat_sel_mode:
            root_fav.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # 添加"全部"节点
        root_all = QTreeWidgetItem(self.category_tree)
        root_all.setText(0, f"全部 ({total_count})")
        root_all.setData(0, Qt.ItemDataRole.UserRole, "全部")
        if edit_mode or reorg_mode:
            root_all.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        elif cat_sel_mode:
            root_all.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # 添加"🕐 最近使用"节点
        recent_item = QTreeWidgetItem(self.category_tree)
        recent_item.setText(0, "🕐 最近使用")
        recent_item.setData(0, Qt.ItemDataRole.UserRole, "__recent__")
        if edit_mode or reorg_mode:
            recent_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        elif cat_sel_mode:
            recent_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # 添加一级节点
        for parent_name in tree_data.keys():
            info = tree_data[parent_name]
            count = category_counts.get(parent_name, 0)
            
            # 过滤空分类（保留"全部"和"其他"，以及编辑/选择/重组模式下的所有分类）
            if not edit_mode and not cat_sel_mode and not reorg_mode and parent_name not in ('全部', '其他') and count == 0 and not info['children']:
                continue
            
            display_text = f"{parent_name} ({count})"
            if edit_mode or reorg_mode:
                display_text = f"☰  {display_text}"
            parent_item = QTreeWidgetItem(self.category_tree)
            parent_item.setText(0, display_text)
            parent_item.setData(0, Qt.ItemDataRole.UserRole, parent_name)
            
            if edit_mode or reorg_mode:
                parent_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            elif cat_sel_mode:
                if parent_name != '全部':
                    parent_item.setFlags(parent_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    if parent_name in self._selected_categories:
                        parent_item.setCheckState(0, Qt.CheckState.Checked)
                    else:
                        parent_item.setCheckState(0, Qt.CheckState.Unchecked)
            
            # 添加子节点（已按自定义排序排好序）
            for child_name in info['children']:
                full_path = f"{parent_name}>{child_name}"
                child_count = category_counts.get(full_path, 0)
                
                # 导航栏过滤空子类：非编辑/选择/重组模式下，count==0 的子类不显示
                # 但下拉框中仍保留（由 get_categories() 保证）
                if not edit_mode and not cat_sel_mode and not reorg_mode and child_count == 0:
                    continue
                
                child_text = f"{child_name} ({child_count})"
                if edit_mode or reorg_mode:
                    child_text = f"☰  {child_text}"
                child_item = QTreeWidgetItem(parent_item)
                child_item.setText(0, child_text)
                child_item.setData(0, Qt.ItemDataRole.UserRole, full_path)
                
                if edit_mode or reorg_mode:
                    child_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                elif cat_sel_mode:
                    child_item.setFlags(child_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    if full_path in self._selected_categories:
                        child_item.setCheckState(0, Qt.CheckState.Checked)
                    else:
                        child_item.setCheckState(0, Qt.CheckState.Unchecked)
            
            # 父节点默认展开
            parent_item.setExpanded(True)
        
        # 恢复之前的选中分类（或默认选择"全部"）
        restored = False
        root = self.category_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            cat = item.data(0, Qt.ItemDataRole.UserRole)
            if cat == saved_category:
                self.category_tree.setCurrentItem(item)
                self.current_category = saved_category
                restored = True
                break
        if not restored:
            self.category_tree.setCurrentItem(root_all)
            self.current_category = '全部'
        
        if self.filter_panel.isVisible():
            self._populate_filter_categories()
        
        # 重建完成后重新连接 itemChanged
        self.category_tree.itemChanged.connect(self._on_category_check_changed)
    
    def _on_category_edit_toggle(self):
        """切换分类编辑排序模式"""
        self._category_edit_mode = not getattr(self, '_category_edit_mode', False)
        
        if self._category_edit_mode:
            # 进入编辑模式，退出重组模式
            if getattr(self, '_category_reorganize_mode', False):
                self._on_category_reorganize_toggle()
            self.btn_category_sort.setText("✓")
            self.btn_category_sort.setToolTip("完成")
            # 启用受限制的拖拽排序
            self.category_tree.set_edit_mode(True)
            # 刷新显示
            self._reload_categories()
        else:
            # 退出编辑模式，保存顺序（一级 + 二级）
            self._save_category_order()
            self.btn_category_sort.setText("排序")
            self.btn_category_sort.setToolTip("编辑分类顺序")
            self.category_tree.set_edit_mode(False)
            # 刷新显示
            self._reload_categories()
    
    def _save_category_order(self):
        """保存分类自定义排序到数据库（支持一级 + 二级节点）"""
        orders = {}
        idx_top = 0
        root = self.category_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            category = item.data(0, Qt.ItemDataRole.UserRole)
            if category == '全部' or category == '__DROP_TO_ROOT__' or category == '__favorites__' or category == '__recent__' or category == '__dashboard__':
                continue
            orders[category] = idx_top
            idx_top += 1
            
            # 保存二级分类顺序
            idx_child = 0
            for j in range(item.childCount()):
                child_item = item.child(j)
                child_cat = child_item.data(0, Qt.ItemDataRole.UserRole)
                orders[child_cat] = idx_child
                idx_child += 1
        
        if self.current_vault == 'accounts':
            self.account_service.save_category_orders(orders)
        else:
            self._url_service.save_category_orders(orders)
    
    def _on_category_batch_delete_toggle(self):
        """切换类别批量删除模式"""
        self._category_selection_mode = not getattr(self, '_category_selection_mode', False)
        
        if self._category_selection_mode:
            # 进入批量删除模式，退出编辑/重组模式
            if getattr(self, '_category_edit_mode', False):
                self._on_category_edit_toggle()
            if getattr(self, '_category_reorganize_mode', False):
                self._on_category_reorganize_toggle()
            self.btn_category_batch_delete.setText("取消")
            self.btn_category_sort.hide()
            self.btn_category_reorganize.hide()
            self.category_sel_bar.show()
            self.category_tree.setStyleSheet(self._category_tree_checkbox_style)
            self._selected_categories.clear()
        else:
            self.btn_category_batch_delete.setText("删除")
            self.btn_category_sort.show()
            self.btn_category_reorganize.show()
            self.category_sel_bar.hide()
            self.category_tree.setStyleSheet(self._category_tree_normal_style)
            self._selected_categories.clear()
        self._reload_categories()
        self._update_category_sel_bar()
    
    def _on_category_reorganize_toggle(self):
        """切换分类重组模式"""
        self._category_reorganize_mode = not getattr(self, '_category_reorganize_mode', False)
        
        if self._category_reorganize_mode:
            # 进入重组模式，退出其他模式
            if getattr(self, '_category_edit_mode', False):
                self._on_category_edit_toggle()
            if getattr(self, '_category_selection_mode', False):
                self._on_category_batch_delete_toggle()
            self.btn_category_reorganize.setText("✓")
            self.btn_category_reorganize.setToolTip("完成")
            self.category_tree.set_reorganize_mode(True)
            self.drop_zone_widget.show()
        else:
            # 退出重组模式，保存顺序
            self._save_category_order()
            self.btn_category_reorganize.setText("重组")
            self.btn_category_reorganize.setToolTip("重组分类结构")
            self.category_tree.set_reorganize_mode(False)
            self.drop_zone_widget.hide()
        self._reload_categories()
    
    def _on_drop_zone_dropped(self, source_path: str):
        """外部拖放区域收到 drop，将类别变为一级"""
        self.category_tree.reorganize_requested.emit(source_path, "")
    
    def _on_reorganize_requested(self, source_path: str, target_parent: str):
        """处理重组拖拽请求
        
        source_path: 旧分类路径，如 "其他>学习" 或 "代码算法"
        target_parent: 目标一级分类名，空字符串表示变为一级
        """
        if '>' in source_path:
            child_name = source_path.split('>', 1)[1].strip()
        else:
            child_name = source_path.strip()
        
        if target_parent:
            new_path = f"{target_parent}>{child_name}"
        else:
            new_path = child_name
        
        if new_path == source_path:
            return
        
        reply = QMessageBox.question(
            self,
            "确认重组",
            f"确定将「{source_path}」移动到「{new_path}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.current_vault == 'accounts':
                success = self.account_service.reparent_category(source_path, target_parent)
                self._accounts_cache_dirty = True
            else:
                success = self._url_service.reparent_category(source_path, target_parent)
                self._urls_cache_dirty = True
            
            if success:
                # 如果当前正查看被移动的旧分类，重置为"全部"避免显示空列表
                if self.current_category == source_path:
                    self.current_category = '全部'
                self._reload_categories()
                if self.current_vault == 'accounts':
                    self.load_accounts()
                else:
                    self.load_urls()
    
    def _on_category_check_changed(self, item, column):
        """类别复选框状态变化"""
        category = item.data(0, Qt.ItemDataRole.UserRole)
        if category in ('全部', '__favorites__', '__recent__', '__dashboard__'):
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self._selected_categories.add(category)
        else:
            self._selected_categories.discard(category)
        self._update_category_sel_bar()
    
    def _update_category_sel_bar(self):
        """更新类别批量删除操作栏"""
        count = len(self._selected_categories)
        self.btn_cat_sel_delete.setText(f"删除({count})")
        # 更新全选按钮文字
        total_selectable = sum(1 for _ in self._iter_category_tree_items())
        if count == total_selectable and total_selectable > 0:
            self.btn_cat_sel_all.setText("取消全选")
        else:
            self.btn_cat_sel_all.setText("全选")
    
    def _toggle_category_select_all(self):
        """全选/取消全选类别"""
        total_selectable = sum(1 for _ in self._iter_category_tree_items())
        if len(self._selected_categories) == total_selectable and total_selectable > 0:
            # 取消全选
            self._selected_categories.clear()
        else:
            # 全选
            self._selected_categories.clear()
            for item in self._iter_category_tree_items():
                category = item.data(0, Qt.ItemDataRole.UserRole)
                if category != '全部':
                    self._selected_categories.add(category)
        self._reload_categories()
        self._update_category_sel_bar()
    
    def _execute_category_batch_delete(self):
        """执行类别批量删除：将选中类别下的所有条目移到'其他'（不进回收站）"""
        if not self._selected_categories:
            QMessageBox.information(self, "提示", "请先选择要删除的类别")
            return
        
        reply = QMessageBox.question(
            self, "确认删除",
            f'确定删除选中的 {len(self._selected_categories)} 个类别？\n这些类别下的所有条目将移至"其他"。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self._save_scroll_state()
        
        try:
            if self.current_vault == 'accounts':
                db = self.account_service.db
            else:
                db = self._url_service.db
            with db.transaction():
                for category in self._selected_categories:
                    if self.current_vault == 'accounts':
                        self.account_service._delete_category_no_commit(category)
                    else:
                        self._url_service._delete_category_no_commit(category)
        except Exception as e:
            logger.error("批量删除类别事务失败: %s", e)
            QMessageBox.critical(
                self,
                "删除失败",
                "删除失败，所有变更已回滚"
            )
            self._restore_scroll_state()
            return
        
        self._selected_categories.clear()
        self._on_category_batch_delete_toggle()  # 退出选择模式
        self._accounts_cache_dirty = True
        self._urls_cache_dirty = True
        self.current_category = '全部'
        self._reload_categories()
        if self.current_vault == 'accounts':
            self.load_accounts()
        else:
            self.load_urls()
        self._restore_scroll_state()
        QMessageBox.information(self, "完成", f"已成功删除类别，相关条目已移至'其他'。")
    
    def load_urls(self):
        """加载网址列表"""
        self._view_mode = 'default'
        self.lbl_list_title.show()
        self.account_list.clear()
        
        # 全量缓存：只在数据变更时从 service 加载一次
        if self._urls_cache_dirty or not self._all_urls_cache:
            self._all_urls_cache = self._url_service.get_all_urls()
            self._urls_cache_dirty = False
        
        if self.current_category == '__favorites__':
            urls = [u for u in self._all_urls_cache if (u.get('is_favorite') if isinstance(u, dict) else getattr(u, 'is_favorite', False))]
        elif self.current_category == '__recent__':
            urls = sorted(self._all_urls_cache, key=lambda u: (getattr(u, 'updated_at', None) or (u.get('updated_at') if isinstance(u, dict) else None) or datetime.min), reverse=True)[:20]
        elif self.current_category == '全部':
            urls = self._all_urls_cache.copy()
        else:
            from core.category_utils import get_prefix_matcher
            matcher = get_prefix_matcher(self.current_category)
            urls = [u for u in self._all_urls_cache if matcher(u.get('category', '') if isinstance(u, dict) else getattr(u, 'category', ''))]
        
        if not urls:
            self.btn_compact_view.setChecked(False)
            item = QListWidgetItem("暂无网址")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.account_list.addItem(item)
            return
        
        # 最近使用页面保持按 updated_at 排序，不重新按字母排序
        if self.current_category != '__recent__':
            # 按拼音首字母排序（英文/中文排前面，数字符号归为#排最后）
            from core.pinyin import PinyinConverter
            def _url_sort_key(url_item):
                text = (url_item.get('title', '') if isinstance(url_item, dict) else getattr(url_item, 'title', '')) or ''
                if not text:
                    return (1, '')
                fc = text[0]
                if ('a' <= fc.lower() <= 'z') or ('\u4e00' <= fc <= '\u9fff'):
                    return (0, PinyinConverter.get_pinyin_initials(text).lower())
                return (1, text.lower())
            
            urls.sort(key=_url_sort_key)
        
        is_compact = self._load_compact_preference()
        item_height = 32 if is_compact else 56
        col_config = self._load_column_config()
        item_width = max(self.account_list.width() - 20, 50)
        
        # 批量添加时禁用更新与信号，避免 O(n²) 布局重算
        self.account_list.setUpdatesEnabled(False)
        self.account_list.blockSignals(True)
        try:
            for url_item in urls:
                list_item = QListWidgetItem()
                list_item.setSizeHint(QSize(item_width, item_height))
                list_item.setData(Qt.ItemDataRole.UserRole, url_item)
                self.account_list.addItem(list_item)
                
                widget = URLListItem(url_item, selection_mode=self._selection_mode, parent=self.account_list)
                widget.hide()  # 防止无parent时短暂显示为独立窗口
                if self._selection_mode:
                    uid = getattr(url_item, 'id', None) or (url_item.get('id') if isinstance(url_item, dict) else None)
                    if uid:
                        widget.on_check_changed = lambda checked, id=uid: self._on_item_checkbox_changed(id, checked)
                    if uid and uid in self._selected_ids:
                        widget.set_checked(True)
                if is_compact:
                    widget.set_compact_mode(True)
                self.account_list.setItemWidget(list_item, widget)
                for key, visible in col_config.items():
                    if not visible:
                        widget.set_column_visible(key, False)
        finally:
            self.account_list.blockSignals(False)
            self.account_list.setUpdatesEnabled(True)
            self.account_list.update()
        
        self.btn_compact_view.setChecked(is_compact)
        
        count = len(urls)
        if self.current_category == '__favorites__':
            title = '收藏'
        elif self.current_category == '__recent__':
            title = '最近使用'
        elif self.current_category == '__dashboard__':
            title = '首页'
        elif self.current_category == '全部':
            title = '全部网址'
        else:
            title = self.current_category
        self.lbl_list_title.setText(f"{title} ({count})")
    
    def _toggle_compact_view(self, checked: bool):
        self._save_compact_preference(checked)
        # 直接修改当前列表中所有 widget，避免全部重建（比 _smart_refresh 快得多）
        self._apply_compact_mode_to_current_list(checked)
    
    def _apply_compact_mode_to_current_list(self, enabled: bool):
        """直接修改现有列表项的紧凑模式，不重建控件"""
        item_height = 32 if enabled else 56
        width = max(self.account_list.width() - 20, 50)
        
        self.account_list.setUpdatesEnabled(False)
        try:
            for i in range(self.account_list.count()):
                item = self.account_list.item(i)
                if item.flags() == Qt.ItemFlag.NoItemFlags:
                    continue  # 跳过提示性 item（如"暂无账号"）
                widget = self.account_list.itemWidget(item)
                if widget and hasattr(widget, 'set_compact_mode'):
                    widget.set_compact_mode(enabled)
                item.setSizeHint(QSize(width, item_height))
        finally:
            self.account_list.setUpdatesEnabled(True)
            self.account_list.update()
        
        self.btn_compact_view.setChecked(enabled)
    
    def _save_compact_preference(self, enabled: bool):
        import json, os, threading
        config_path = str(COMPACT_VIEW_PATH)
        config = {}
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception:
            pass
        config[self.current_vault] = enabled
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        def _do_save():
            try:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f)
            except Exception as e:
                logger.warning("保存紧凑视图配置失败: %s", e)
        
        threading.Thread(target=_do_save, daemon=True).start()
    
    def _load_compact_preference(self) -> bool:
        import json, os
        config_path = str(COMPACT_VIEW_PATH)
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get(self.current_vault, False)
        except Exception:
            return False
    
    def _save_scroll_state(self):
        """保存当前列表的滚动位置和选中项ID"""
        if self.current_vault == 'accounts':
            list_widget = self.account_list
            cached = self._all_accounts_cache
        else:
            list_widget = self.account_list
            cached = self._all_urls_cache
        
        self._scroll_state = {
            'vault_type': self.current_vault,
            'selected_id': None,
            'scroll_value': list_widget.verticalScrollBar().value()
        }
        
        current_row = list_widget.currentRow()
        if 0 <= current_row < len(cached):
            item = cached[current_row]
            self._scroll_state['selected_id'] = getattr(item, 'id', None) or (item.get('id') if isinstance(item, dict) else None)
    
    def _restore_scroll_state(self):
        """恢复滚动位置和选中项"""
        if not hasattr(self, '_scroll_state'):
            return
        if self._scroll_state.get('vault_type') != self.current_vault:
            return
        
        if self.current_vault == 'accounts':
            list_widget = self.account_list
            cached = self._all_accounts_cache
        else:
            list_widget = self.account_list
            cached = self._all_urls_cache
        
        selected_id = self._scroll_state.get('selected_id')
        if selected_id is not None:
            for idx, item in enumerate(cached):
                item_id = getattr(item, 'id', None) or (item.get('id') if isinstance(item, dict) else None)
                if item_id == selected_id:
                    list_widget.setCurrentRow(idx)
                    list_widget.scrollToItem(list_widget.item(idx), QListWidget.ScrollHint.PositionAtCenter)
                    return
        
        scroll_value = self._scroll_state.get('scroll_value', 0)
        list_widget.verticalScrollBar().setValue(scroll_value)
    
    def on_account_double_clicked(self, item):
        """双击账号/网址条目打开编辑弹窗"""
        self.on_account_clicked(item)
    
    def _display_url_search_results(self, results):
        """展示网址搜索结果"""
        self.account_list.clear()
        if not results:
            item = QListWidgetItem("未找到匹配的网址")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.account_list.addItem(item)
            self.lbl_list_title.setText("搜索结果 (0)")
            return
        
        for url_item in results:
            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(self.account_list.width() - 20, 56))
            list_item.setData(Qt.ItemDataRole.UserRole, url_item)
            self.account_list.addItem(list_item)
            widget = URLListItem(url_item, selection_mode=self._selection_mode, parent=self.account_list)
            if self._selection_mode:
                uid = getattr(url_item, 'id', None) or (url_item.get('id') if isinstance(url_item, dict) else None)
                if uid:
                    widget.on_check_changed = lambda checked, id=uid: self._on_item_checkbox_changed(id, checked)
                if uid and uid in self._selected_ids:
                    widget.set_checked(True)
            self.account_list.setItemWidget(list_item, widget)
            col_config = self._load_column_config()
            for key, visible in col_config.items():
                if not visible:
                    widget.set_column_visible(key, False)
        
        self.lbl_list_title.setText(f"搜索结果 ({len(results)})")
    
    def _on_category_clicked(self, item, column):
        """分类选择事件"""
        if item is None:
            return
        if getattr(self, '_category_selection_mode', False):
            return
        
        new_category = item.data(0, Qt.ItemDataRole.UserRole)
        if new_category == self.current_category:
            return
        
        self._view_mode = 'default'
        self.current_category = new_category
        
        if self.current_category == '__dashboard__':
            if self.dashboard is not None:
                self.list_stack.setCurrentIndex(1)
                self.dashboard.set_vault(self.current_vault)
            self.alpha_nav.hide()
            self.lbl_list_title.hide()
            self.btn_compact_view.hide()
            self.btn_column_settings.hide()
            return
        
        self.list_stack.setCurrentIndex(0)
        if self.current_category == '__recent__':
            self.alpha_nav.hide()
        else:
            self.alpha_nav.show()
        self.lbl_list_title.show()
        self.btn_compact_view.show()
        self.btn_column_settings.show()
        if self.current_vault == 'accounts':
            self._accounts_cache_dirty = True
            self.load_accounts()
        else:
            self._urls_cache_dirty = True
            self.load_urls()
    
    def _rename_parent_category(self, old_name: str, new_name: str):
        """重命名一级分类：批量修改所有旧名称和旧名称>xxx的前缀"""
        if self.current_vault == 'accounts':
            db = self.db
        else:
            db = self._url_db
        
        TABLE_MAP = {'accounts': 'accounts', 'urls': 'urls'}
        table = TABLE_MAP.get('accounts' if self.current_vault == 'accounts' else 'urls')
        if table not in TABLE_MAP.values():
            raise ValueError(f"Invalid table: {table}")
        
        with db._lock:
            cursor = db.conn.cursor()
            # 1. 精确匹配的旧名称
            cursor.execute(f"UPDATE {table} SET category = ? WHERE category = ?", (new_name, old_name))
            # 2. 前缀匹配：old_name>xxx → new_name>xxx
            cursor.execute(
                f"UPDATE {table} SET category = ? || SUBSTR(category, ?) WHERE category LIKE ?",
                (new_name, len(old_name) + 1, f"{old_name}>%")
            )
            db.conn.commit()
    
    def _on_category_context_menu(self, pos: QPoint):
        """分类右键菜单：点击条目显示重命名/删除；点击空白处显示新建类别"""
        # 批量删除模式下不显示右键菜单
        if getattr(self, '_category_selection_mode', False):
            return
        
        item = self.category_tree.itemAt(pos)
        
        if not item:
            # 空白处：新建一级分类
            menu = QMenu(self)
            action_new = menu.addAction("➕ 新建一级分类")
            action = menu.exec(self.category_tree.mapToGlobal(pos))
            
            if action == action_new:
                new_name, ok = QInputDialog.getText(self, "新建一级分类", "分类名称：")
                if ok and new_name and new_name.strip():
                    new_name = new_name.strip()
                    if new_name in ('全部', '其他'):
                        QMessageBox.warning(self, "提示", "不能使用保留名称")
                        return
                    from core.category_utils import validate_category_name
                    if not validate_category_name(new_name):
                        QMessageBox.warning(self, "提示", "分类名不能包含 /、>、· 或首尾空格")
                        return
                    if self.current_vault == 'accounts':
                        success = self.account_service.add_category(new_name)
                    else:
                        success = self._url_service.add_category(new_name)
                    if success:
                        self._reload_categories()
                        QMessageBox.information(self, "成功", f'分类 "{new_name}" 已创建')
                    else:
                        QMessageBox.warning(self, "提示", "该分类已存在")
            return
        
        category = item.data(0, Qt.ItemDataRole.UserRole)
        if category in ('全部', '__favorites__', '__recent__', '__dashboard__'):
            return  # 特殊节点不提供操作
        
        # 判断是一级节点还是二级节点
        parent = item.parent()
        is_parent_node = parent is None  # 顶级节点是一级分类
        
        menu = QMenu(self)
        if is_parent_node:
            action_new_child = menu.addAction("➕ 新建子类")
            action_rename = menu.addAction("📝 重命名")
            action_delete = menu.addAction("🗑️ 删除")
        else:
            action_promote = menu.addAction("⬆️ 升级为一级")
            action_rename = menu.addAction("📝 重命名")
            action_delete = menu.addAction("🗑️ 删除")
        
        action = menu.exec(self.category_tree.mapToGlobal(pos))
        
        if is_parent_node and action == action_new_child:
            new_child, ok = QInputDialog.getText(self, "新建子类", f"在「{category}」下新建子类：")
            if ok and new_child and new_child.strip():
                new_child = new_child.strip()
                from core.category_utils import validate_category_name, format_category_path
                if not validate_category_name(new_child):
                    QMessageBox.warning(self, "提示", "子分类名不能包含 /、>、· 或首尾空格")
                    return
                full_path = format_category_path(category, new_child)
                if self.current_vault == 'accounts':
                    success = self.account_service.add_category(full_path)
                else:
                    success = self._url_service.add_category(full_path)
                if success:
                    self._reload_categories()
                    QMessageBox.information(self, "成功", f'子类 "{full_path}" 已创建')
                else:
                    QMessageBox.warning(self, "提示", "该子类已存在")
            return
        
        if action == action_rename:
            if is_parent_node:
                # 一级分类：直接编辑完整名称
                new_name, ok = QInputDialog.getText(self, "重命名分类", "新名称：", text=category)
                if ok and new_name and new_name != category:
                    new_name = new_name.strip()
                    from core.category_utils import validate_category_name
                    if not validate_category_name(new_name):
                        QMessageBox.warning(self, "提示", "分类名不能包含 /、>、· 或首尾空格")
                        return
                    self._rename_parent_category(category, new_name)
                    self._reload_categories()
                    self._accounts_cache_dirty = True
                    self._urls_cache_dirty = True
                    if self.current_category == category:
                        self.current_category = new_name
                    self.load_accounts() if self.current_vault == 'accounts' else self.load_urls()
            else:
                # 二级分类：只编辑子类名
                parent_data = parent.data(0, Qt.ItemDataRole.UserRole)
                child_name = category.split('>', 1)[1] if '>' in category else category
                new_child, ok = QInputDialog.getText(self, "重命名子类", "新名称：", text=child_name)
                if ok and new_child and new_child.strip():
                    new_child = new_child.strip()
                    if new_child == child_name:
                        return
                    from core.category_utils import validate_category_name, format_category_path
                    if not validate_category_name(new_child):
                        QMessageBox.warning(self, "提示", "子分类名不能包含 /、>、· 或首尾空格")
                        return
                    new_name = format_category_path(parent_data, new_child)
                    if self.current_vault == 'accounts':
                        self.account_service.rename_category(category, new_name)
                    else:
                        self._url_service.rename_category(category, new_name)
                    self._reload_categories()
                    self._accounts_cache_dirty = True
                    self._urls_cache_dirty = True
                    if self.current_category == category:
                        self.current_category = new_name
                    self.load_accounts() if self.current_vault == 'accounts' else self.load_urls()
        
        elif action == action_delete:
            # 获取该分类下条目数量
            count = self._get_category_count(category)
            
            if is_parent_node:
                reply = QMessageBox.question(
                    self, "删除分类",
                    f'删除分类 "{category}"？\n该分类及其子类下的 {count} 个条目将移至"其他"。',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
            else:
                reply = QMessageBox.question(
                    self, "删除分类",
                    f'删除分类 "{category}"？\n该分类下的 {count} 个条目将保留一级分类，去掉二级分类。',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
            
            if reply == QMessageBox.StandardButton.Yes:
                if self.current_vault == 'accounts':
                    self.account_service.delete_category(category)
                else:
                    self._url_service.delete_category(category)
                self._reload_categories()
                self._accounts_cache_dirty = True
                self._urls_cache_dirty = True
                self.current_category = '全部'
                self.load_accounts() if self.current_vault == 'accounts' else self.load_urls()
        
        elif not is_parent_node and action == action_promote:
            child_name = category.split('>', 1)[1].strip()
            service = self.account_service if self.current_vault == 'accounts' else self._url_service
            all_cats = service.get_categories()
            
            # 仅检测一级分类同名冲突
            has_conflict = child_name in all_cats
            
            if has_conflict:
                QMessageBox.warning(self, "提示", f"一级分类「{child_name}」已存在，无法升级")
                return
            
            # 确认对话框
            reply = QMessageBox.question(
                self, "确认升级",
                f'确定将「{category}」升级为一级分类「{child_name}」吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            success = service.promote_category(category)
            if success:
                self._reload_categories()
                self._accounts_cache_dirty = True
                self._urls_cache_dirty = True
                self.current_category = '全部'
                self.load_accounts() if self.current_vault == 'accounts' else self.load_urls()
                QMessageBox.information(self, "成功", f'「{category}」已升级为一级分类「{child_name}」')
            else:
                QMessageBox.warning(self, "提示", "升级失败，请重试")
    
    def _on_list_item_context_menu(self, pos: QPoint):
        """列表项右键菜单：切换收藏"""
        item = self.account_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        item_id = getattr(data, 'id', None) or (data.get('id') if isinstance(data, dict) else None)
        is_fav = getattr(data, 'is_favorite', False) or (data.get('is_favorite', False) if isinstance(data, dict) else False)
        
        menu = QMenu(self)
        if is_fav:
            action_fav = menu.addAction("⭐ 取消收藏")
        else:
            action_fav = menu.addAction("⭐ 添加到收藏")
        
        action = menu.exec(self.account_list.mapToGlobal(pos))
        
        if action == action_fav and item_id:
            if self.current_vault == 'accounts':
                new_status = self.account_service.toggle_favorite(item_id)
            else:
                new_status = self._url_service.toggle_favorite(item_id)
            # Update the cached data in-place
            if isinstance(data, dict):
                data['is_favorite'] = int(new_status)
            else:
                data.is_favorite = new_status
            # Refresh the list to show updated state
            self._accounts_cache_dirty = True
            self._urls_cache_dirty = True
            if self.current_vault == 'accounts':
                self.load_accounts()
            else:
                self.load_urls()
            # Also refresh category tree to update favorite count
            self._reload_categories()

    def _get_column_config_path(self):
        data_dir = DATA_DIR
        vault = self.current_vault
        return data_dir / f'columns_{vault}.json'

    def _load_column_config(self):
        path = self._get_column_config_path()
        if self.current_vault == 'accounts':
            defaults = {'icon': True, 'app_name': True, 'username': True, 'strength': True, 'category': True, 'arrow': True}
        else:
            defaults = {'icon': True, 'app_name': True, 'url': True, 'category': True, 'arrow': True}
        try:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                return {**defaults, **saved}
        except Exception:
            pass
        return defaults

    def _save_column_config(self, config):
        path = self._get_column_config_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)

    def _show_column_menu(self, pos):
        menu = QMenu(self)
        if self.current_vault == 'accounts':
            columns = [
                ('icon', '首字母图标'),
                ('app_name', '应用名'),
                ('username', '账号（脱敏）'),
                ('strength', '密码强度'),
                ('category', '分类标签'),
                ('arrow', '右箭头'),
            ]
        else:
            columns = [
                ('icon', '首字母图标'),
                ('app_name', '网址标题'),
                ('url', '网址地址'),
                ('category', '分类标签'),
                ('arrow', '右箭头'),
            ]

        col_config = self._load_column_config()

        for key, label in columns:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(col_config.get(key, True))
            action.setData(key)
            action.toggled.connect(lambda checked, k=key: self._toggle_column(k, checked))

        app_name_action = None
        for action in menu.actions():
            if action.data() == 'app_name':
                app_name_action = action
                app_name_action.setEnabled(False)
                app_name_action.setChecked(True)
                break

        menu.exec(self.lbl_list_title.mapToGlobal(pos))

    def _on_column_settings_clicked(self):
        """点击列设置按钮弹出菜单"""
        btn = self.btn_column_settings
        pos = btn.rect().bottomLeft()
        # 复用 _show_column_menu，但使用按钮位置
        menu = QMenu(self)
        if self.current_vault == 'accounts':
            columns = [
                ('icon', '首字母图标'),
                ('app_name', '应用名'),
                ('username', '账号（脱敏）'),
                ('strength', '密码强度'),
                ('category', '分类标签'),
                ('arrow', '右箭头'),
            ]
        else:
            columns = [
                ('icon', '首字母图标'),
                ('app_name', '网址标题'),
                ('url', '网址地址'),
                ('category', '分类标签'),
                ('arrow', '右箭头'),
            ]

        col_config = self._load_column_config()

        for key, label in columns:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(col_config.get(key, True))
            action.setData(key)
            action.toggled.connect(lambda checked, k=key: self._toggle_column(k, checked))

        for action in menu.actions():
            if action.data() == 'app_name':
                action.setEnabled(False)
                action.setChecked(True)
                break

        menu.exec(btn.mapToGlobal(pos))

    def _toggle_column(self, key, visible):
        config = self._load_column_config()
        config[key] = visible
        self._save_column_config(config)
        for i in range(self.account_list.count()):
            widget = self.account_list.itemWidget(
                self.account_list.item(i))
            if widget and hasattr(widget, 'set_column_visible'):
                widget.set_column_visible(key, visible)

    def _enter_selection_mode(self):
        """进入批量选择模式"""
        self._selection_mode = True
        self._selected_ids.clear()
        self._normal_title = self.lbl_list_title.text()
        
        # 遍历现有 item，只切换 checkbox 显示状态，不再重建列表
        for i in range(self.account_list.count()):
            item = self.account_list.item(i)
            widget = self.account_list.itemWidget(item)
            if widget and hasattr(widget, 'set_selection_mode'):
                widget.set_selection_mode(True)
                # 补设置 checkbox 回调（列表若在非选择模式下加载，on_check_changed 为 None）
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and hasattr(widget, 'on_check_changed'):
                    item_id = getattr(data, 'id', None) or (data.get('id') if isinstance(data, dict) else None)
                    if item_id is not None:
                        widget.on_check_changed = lambda checked, id=item_id: self._on_item_checkbox_changed(id, checked)
        
        self._update_bottom_bar_for_selection()
    
    def _exit_selection_mode(self):
        """退出批量选择模式"""
        self._selection_mode = False
        self._selected_ids.clear()
        
        # 遍历现有 item，只隐藏 checkbox，不再重建列表
        for i in range(self.account_list.count()):
            item = self.account_list.item(i)
            widget = self.account_list.itemWidget(item)
            if widget and hasattr(widget, 'set_selection_mode'):
                widget.set_selection_mode(False)
                if hasattr(widget, 'set_checked'):
                    widget.set_checked(False)
        
        self.lbl_list_title.setText(self._normal_title)
        self._update_bottom_bar_for_normal()
    
    def _update_bottom_bar_for_selection(self):
        """更新底部工具栏为选择模式"""
        count = len(self._selected_ids)
        self.btn_sel_delete.setText(f"删除({count})")
        self.lbl_list_title.setText(f"已选择 {count} 项")
        # 全选按钮文字切换
        total = len(self._all_accounts_cache) if self.current_vault == 'accounts' else len(self._all_urls_cache)
        self.btn_sel_all.setText("取消全选" if count == total and total > 0 else "全选")
        self.bottom_bar.hide()
        self.selection_bottom_bar.show()
    
    def _update_bottom_bar_for_normal(self):
        """恢复底部工具栏为正常模式"""
        self.bottom_bar.show()
        self.selection_bottom_bar.hide()
    
    def _toggle_select_all(self):
        """全选/取消全选"""
        if self.current_vault == 'accounts':
            accounts = self._all_accounts_cache
            if len(self._selected_ids) == len(accounts):
                self._selected_ids.clear()
            else:
                self._selected_ids = {acc.id for acc in accounts if acc.id}
        else:
            urls = self._all_urls_cache
            if len(self._selected_ids) == len(urls):
                self._selected_ids.clear()
            else:
                self._selected_ids = set()
                for u in urls:
                    uid = getattr(u, 'id', None) or (u.get('id') if isinstance(u, dict) else None)
                    if uid:
                        self._selected_ids.add(uid)
        # 刷新复选框状态
        self._update_selection_checkboxes()
        self._update_bottom_bar_for_selection()
    
    def _on_item_checkbox_changed(self, item_id: int, checked: bool):
        """列表项 checkbox 状态变化时同步更新选中集合"""
        if checked:
            self._selected_ids.add(item_id)
        else:
            self._selected_ids.discard(item_id)
        self._update_bottom_bar_for_selection()
    
    def _update_selection_checkboxes(self):
        """更新列表中所有复选框的显示状态"""
        for i in range(self.account_list.count()):
            item = self.account_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not data:
                continue
            data_id = getattr(data, 'id', None) or (data.get('id') if isinstance(data, dict) else None)
            if data_id is not None:
                widget = self.account_list.itemWidget(item)
                if widget and hasattr(widget, 'set_checked'):
                    widget.set_checked(data_id in self._selected_ids)
    
    def _execute_batch_delete(self):
        """执行批量删除"""
        if not self._selected_ids:
            QMessageBox.information(self, "提示", "请先选择要删除的条目")
            return
        
        count = len(self._selected_ids)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除已选中的 {count} 个条目？\n删除后将移至回收站。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self._save_scroll_state()
        
        # 删除前保存数据快照（用于撤销）
        deleted_items_data = []
        deleted = 0
        db = self.db if self.current_vault == 'accounts' else self._url_db
        with db.transaction():
            for item_id in self._selected_ids:
                try:
                    if self.current_vault == 'accounts':
                        account = self.account_service.get_account(item_id)
                        if account:
                            deleted_items_data.append(('account', account.to_dict()))
                            self.db.soft_delete_account(item_id, account.to_dict())
                            deleted += 1
                    else:
                        url_item = self._url_service.get_url(item_id)
                        if url_item:
                            deleted_items_data.append(('url', url_item.to_dict()))
                            self._url_db.soft_delete_url(item_id, url_item.to_dict())
                            deleted += 1
                except Exception as e:
                    logger.warning(f" Failed to delete {item_id}: {e}")
        
        self._selection_mode = False
        self._selected_ids.clear()
        self._update_bottom_bar_for_normal()
        self._smart_refresh()
        self._restore_scroll_state()
        self._reload_categories()
        
        if deleted > 0:
            self.show_undo_banner(deleted, deleted_items_data)
    
    def _execute_batch_categorize(self):
        """执行批量分类"""
        if not self._selected_ids:
            QMessageBox.information(self, "提示", "请先勾选要操作的条目")
            return
        
        if self.current_vault == 'accounts':
            categories = self.account_service.get_categories()
        else:
            categories = self._url_service.get_categories()
        
        category, ok = QInputDialog.getItem(
            self, "批量分类",
            f"为 {len(self._selected_ids)} 个条目选择目标分类：",
            categories, 0, False
        )
        
        if not ok or not category:
            return
        
        reply = QMessageBox.question(
            self, "确认",
            f"确定将 {len(self._selected_ids)} 个条目移动到「{category}」？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        affected_ids = []
        count = 0
        db = self.db if self.current_vault == 'accounts' else self._url_db
        with db.transaction():
            for item_id in self._selected_ids:
                try:
                    if self.current_vault == 'accounts':
                        acc = self.account_service.get_account(item_id)
                        if acc:
                            acc.category = category
                            self.account_service.update_account(acc)
                            affected_ids.append(item_id)
                            count += 1
                    else:
                        url = self._url_service.get_url(item_id)
                        if url:
                            url.category = category
                            self._url_service.update_url(url)
                            affected_ids.append(item_id)
                            count += 1
                except Exception as e:
                    logger.warning(f"Batch categorize failed for {item_id}: {e}")
        
        self._exit_selection_mode()
        self._smart_refresh()
        self._reload_categories()
        if affected_ids:
            self.highlight_matched_accounts(affected_ids, query_text=f"批量分类 → {category}")
        QMessageBox.information(self, "完成", f"已成功移动 {count} 个条目到「{category}」")
    
    def _execute_batch_tag(self):
        """执行批量标签"""
        if not self._selected_ids:
            QMessageBox.information(self, "提示", "请先勾选要操作的条目")
            return
        
        mode, ok = QInputDialog.getItem(
            self, "批量标签",
            "选择操作模式：",
            ["添加标签", "移除标签"], 0, False
        )
        if not ok:
            return
        
        tag, ok = QInputDialog.getText(self, "批量标签", "输入标签：")
        if not ok or not tag.strip():
            return
        tag = tag.strip()
        
        action = "添加" if "添加" in mode else "移除"
        reply = QMessageBox.question(
            self, "确认",
            f"确定{action} {len(self._selected_ids)} 个条目的标签「{tag}」？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        affected_ids = []
        count = 0
        db = self.db if self.current_vault == 'accounts' else self._url_db
        with db.transaction():
            for item_id in self._selected_ids:
                try:
                    if self.current_vault == 'accounts':
                        acc = self.account_service.get_account(item_id)
                        if acc:
                            if '添加' in mode:
                                acc.add_tag(tag)
                            else:
                                acc.remove_tag(tag)
                            self.account_service.update_account(acc)
                            affected_ids.append(item_id)
                            count += 1
                    else:
                        url = self._url_service.get_url(item_id)
                        if url:
                            if '添加' in mode:
                                url.add_tag(tag)
                            else:
                                url.remove_tag(tag)
                            self._url_service.update_url(url)
                            affected_ids.append(item_id)
                            count += 1
                except Exception as e:
                    logger.warning(f"Batch tag failed for {item_id}: {e}")
        
        self._exit_selection_mode()
        self._smart_refresh()
        if affected_ids:
            self.highlight_matched_accounts(affected_ids, query_text=f"批量标签 → {action}「{tag}」")
        QMessageBox.information(self, "完成", f"已成功{action} {count} 个条目的标签")
    
    def show_undo_banner(self, count, deleted_items):
        """显示撤销横幅（60 秒后自动消失）"""
        self._dismiss_undo_banner()
        
        # 保存待恢复数据
        self._undo_deleted_items = deleted_items
        
        self._undo_msg.setText(f"已删除 {count} 个条目至回收站")
        self._undo_btn.clicked.disconnect() if self._undo_btn.receivers(self._undo_btn.clicked) else None
        self._undo_btn.clicked.connect(lambda: self._undo_delete(self._undo_deleted_items))
        self._undo_banner.show()
        
        # 60 秒后自动消失
        if hasattr(self, '_undo_timer') and self._undo_timer:
            self._undo_timer.stop()
            self._undo_timer.deleteLater()
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.timeout.connect(self._dismiss_undo_banner)
        self._undo_timer.start(60000)
    
    def _undo_delete(self, deleted_items):
        """撤销批量删除，恢复条目"""
        restored = 0
        account_items = [d for t, d in deleted_items if t == 'account']
        url_items = [d for t, d in deleted_items if t == 'url']
        
        with self.db.transaction():
            for item_data in account_items:
                try:
                    data = dict(item_data)
                    data.pop('id', None)
                    data.pop('created_at', None)
                    data.pop('updated_at', None)
                    data.pop('last_password_change', None)
                    self.db.insert_account(data)
                    restored += 1
                except Exception as e:
                    logger.warning(f"Failed to restore account: {e}")
        
        with self._url_db.transaction():
            for item_data in url_items:
                try:
                    data = dict(item_data)
                    data.pop('id', None)
                    data.pop('created_at', None)
                    data.pop('updated_at', None)
                    self._url_db.insert_url(data)
                    restored += 1
                except Exception as e:
                    logger.warning(f"Failed to restore url: {e}")
        
        self._dismiss_undo_banner()
        self._accounts_cache_dirty = True
        self._urls_cache_dirty = True
        self._smart_refresh()
        self._reload_categories()
        logger.info(f"Undo: restored {restored} items")
    
    def _dismiss_undo_banner(self):
        """关闭撤销横幅"""
        if hasattr(self, '_undo_timer') and self._undo_timer:
            self._undo_timer.stop()
            self._undo_timer = None
        if hasattr(self, '_undo_banner') and self._undo_banner:
            self._undo_banner.hide()
        self._undo_deleted_items = []
    
    def on_account_clicked(self, item):
        """账号/网址点击事件"""
        # 拖动选择过程中屏蔽 itemClicked，避免与 _on_drag_select_move 冲突
        if self._drag_in_progress:
            return
        
        if self._selection_mode:
            # 选择模式下：点击条目任意位置都切换勾选状态
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                widget = self.account_list.itemWidget(item)
                if widget and hasattr(widget, 'set_checked') and hasattr(widget, 'is_checked'):
                    # 如果 checkbox 被直接点击，它的 toggled 信号已经翻转过状态，
                    # _on_check_state_changed 会设置 _checkbox_clicked = True，
                    # 这里只需要同步 _selected_ids，不要再翻一次
                    if not getattr(widget, '_checkbox_clicked', False):
                        widget.set_checked(not widget.is_checked())
                    widget._checkbox_clicked = False  # 重置标志
                    
                    # 同步选中状态（以 checkbox 当前状态为准）
                    item_id = getattr(data, 'id', None) or (data.get('id') if isinstance(data, dict) else None)
                    if item_id is not None:
                        if widget.is_checked():
                            self._selected_ids.add(item_id)
                        else:
                            self._selected_ids.discard(item_id)
                        self._last_selected_index = self.account_list.row(item)
                        self._update_bottom_bar_for_selection()
            return
        
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        if self.current_vault == 'accounts':
            self.show_account_detail(data)
        else:
            self.show_url_detail(data)
    
    def show_account_detail(self, account: Account):
        """显示账号详情"""
        if not self._verify_session():
            return
        self.selected_account = account
        old_category = account.category
        
        # 创建详情弹窗
        t0 = time.perf_counter()
        dialog = AccountDialog(self.db, account, parent=self)
        t1 = time.perf_counter()
        logger.debug(f" AccountDialog construct: {(t1-t0)*1000:.1f} ms")
        result = dialog.exec()
        t2 = time.perf_counter()
        logger.debug(f" AccountDialog exec: {(t2-t1)*1000:.1f} ms")
        if result == AccountDialog.DialogCode.Accepted:
            self._smart_refresh()
            self.show_copy_toast("保存成功")
            # 仅在分类变化时重建分类树
            if dialog.account and dialog.account.category != old_category:
                self._reload_categories()
    
    def show_url_detail(self, url_item):
        """显示网址详情/编辑"""
        if not self._verify_session():
            return
        from models.url_item import URLItem
        
        if isinstance(url_item, dict):
            url_item = URLItem.from_dict(url_item)
        
        old_category = url_item.category if hasattr(url_item, 'category') else url_item.get('category', '')
        
        dialog = URLEditDialog(self._url_service, url_item, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._smart_refresh()
            self.show_copy_toast("保存成功")
            # 仅在分类变化时重建分类树
            new_cat = dialog.url_item.category if hasattr(dialog.url_item, 'category') else dialog.url_item.get('category', '')
            if new_cat != old_category:
                self._reload_categories()
    
    def on_add_item(self):
        """添加账号/网址"""
        self._save_scroll_state()
        if self.current_vault == 'accounts':
            t0 = time.perf_counter()
            dialog = AccountDialog(self.db, parent=self)
            t1 = time.perf_counter()
            logger.debug(f" AccountDialog construct: {(t1-t0)*1000:.1f} ms")
            result = dialog.exec()
            t2 = time.perf_counter()
            logger.debug(f" AccountDialog exec: {(t2-t1)*1000:.1f} ms")
            if result == AccountDialog.DialogCode.Accepted:
                new_id = dialog.account.id if dialog.account else None
                self._accounts_cache_dirty = True
                self.current_category = '全部'
                self._view_mode = 'default'
                self._highlight_matched_ids = None
                self._highlight_reasoning = ""
                if hasattr(self, 'ai_filter_banner'):
                    self.ai_filter_banner.hide()
                self.lbl_list_title.show()
                self.search_box.clear()
                self.load_accounts()
                if new_id:
                    self.highlight_matched_accounts([new_id], query_text="AI本次修改")
                self._restore_scroll_state()
                self._reload_categories()
        else:
            from models.url_item import URLItem
            dialog = URLEditDialog(self._url_service, URLItem(), parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_id = dialog.url_item.id if dialog.url_item else None
                self._urls_cache_dirty = True
                self.current_category = '全部'
                self._view_mode = 'default'
                self._highlight_matched_ids = None
                self._highlight_reasoning = ""
                if hasattr(self, 'ai_filter_banner'):
                    self.ai_filter_banner.hide()
                self.lbl_list_title.show()
                self.search_box.clear()
                self.load_urls()
                if new_id:
                    self.highlight_matched_accounts([new_id], query_text="AI本次修改")
                self._restore_scroll_state()
                self._reload_categories()
    
    # ==================== 高级筛选方法 ====================
    
    def _on_filter_toggle(self, checked: bool):
        try:
            self.filter_panel.setVisible(checked)
            if checked:
                self._populate_filter_categories()
                self._fix_calendar_style()
                self._set_filter_earliest_date()
            else:
                self.lbl_filter_active.hide()
                self._view_mode = 'default'
                if self.current_vault == 'accounts':
                    self.load_accounts()
                else:
                    self.load_urls()
        except Exception as e:
            logger.error("筛选面板切换失败: %s", e, exc_info=True)
    
    def _fix_calendar_style(self):
        if self._calendar_style_applied:
            return
        try:
            cal_from = self.filter_date_from.calendarWidget()
            cal_to = self.filter_date_to.calendarWidget()
            calendar_style = """
                QCalendarWidget {
                    font-size: 13px;
                    min-width: 360px;
                }
                QCalendarWidget QToolButton {
                    font-size: 14px;
                    padding: 4px 8px;
                }
                QCalendarWidget QWidget#qt_calendar_navigationbar {
                    min-height: 36px;
                }
                QCalendarWidget QAbstractItemView {
                    font-size: 13px;
                    min-width: 340px;
                    selection-background-color: #1976D2;
                }
            """
            for cal in [cal_from, cal_to]:
                if cal:
                    cal.setStyleSheet(calendar_style)
                    cal.setGridVisible(True)
                    cal.setVerticalHeaderFormat(
                        QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers
                        if hasattr(QCalendarWidget, 'VerticalHeaderFormat') else 1
                    )
            self._calendar_style_applied = True
        except Exception as e:
            logger.debug("设置日历样式失败: %s", e)
    
    def _set_filter_earliest_date(self):
        try:
            if self.current_vault == 'accounts':
                items = self.account_service.get_all_accounts()
            else:
                items = self._url_service.get_all_urls()
            earliest = None
            for item in items:
                created = item.created_at if hasattr(item, 'created_at') else item.get('created_at')
                if created:
                    if isinstance(created, str):
                        created = created.replace('Z', '+00:00')
                        from datetime import datetime as _dt
                        created = _dt.fromisoformat(created)
                    if earliest is None or created < earliest:
                        earliest = created
            if earliest:
                qd = QDate(earliest.year, earliest.month, earliest.day)
            else:
                qd = QDate.currentDate().addYears(-1)
            self.filter_date_from.setMinimumDate(QDate(2000, 1, 1))
            self.filter_date_from.setDate(qd)
            self._filter_earliest_date = qd
        except Exception as e:
            logger.debug("设置筛选最早日期失败: %s", e)
    
    def _populate_filter_categories(self):
        self.filter_category.blockSignals(True)
        self.filter_category.clear()
        self.filter_category.addItem("全部分类", None)
        cats = []
        try:
            if self.current_vault == 'accounts':
                cats = self.account_service.get_categories()
            else:
                cats = self._url_service.get_categories()
        except Exception:
            pass
        for cat in cats:
            if cat != '全部':
                self.filter_category.addItem(cat, cat)
        self.filter_category.blockSignals(False)
    
    def _has_active_filters(self):
        if not self.filter_panel.isVisible():
            return False
        if self.filter_category.currentData() is not None:
            return True
        if self.filter_strength.currentText() != '全部':
            return True
        if self.filter_date_from.date() != self._filter_earliest_date:
            return True
        if self.filter_date_to.date() != QDate.currentDate():
            return True
        return False
    
    def _on_apply_filter(self):
        try:
            if not self._has_active_filters():
                self.lbl_filter_active.hide()
                return
            self.lbl_filter_active.show()
            text = self.search_box.text().strip()
            self._view_mode = 'search'
            self._search_with_filters(text)
        except Exception as e:
            logger.error("筛选执行失败: %s", e, exc_info=True)
    
    def _on_clear_filter(self):
        self.filter_category.setCurrentIndex(0)
        self.filter_date_from.setDate(self._filter_earliest_date)
        self.filter_date_to.setDate(QDate.currentDate())
        self.filter_strength.setCurrentIndex(0)
        self.lbl_filter_active.hide()
        self._view_mode = 'default'
        if self.current_vault == 'accounts':
            self.load_accounts()
        else:
            self.load_urls()
    
    def _search_with_filters(self, text: str):
        import datetime as dt

        is_accounts = self.current_vault == 'accounts'
        if is_accounts:
            all_items = self.account_service.get_all_accounts()
        else:
            all_items = self._url_service.get_all_urls()

        flt_category = self.filter_category.currentData()
        flt_strength = self.filter_strength.currentText() if self.filter_strength.currentText() != '全部' else None

        from_date = self.filter_date_from.date()
        to_date = self.filter_date_to.date()
        flt_date_from = None
        flt_date_to = None
        if from_date != self._filter_earliest_date:
            flt_date_from = dt.datetime(from_date.year(), from_date.month(), from_date.day()).isoformat()
        if to_date != QDate.currentDate():
            nxt = to_date.addDays(1)
            flt_date_to = dt.datetime(nxt.year(), nxt.month(), nxt.day()).isoformat()

        if is_accounts and text:
            flt = SearchFilter()
            if flt_category:
                flt.category = flt_category
            if flt_strength:
                flt.strength = flt_strength
            if flt_date_from:
                flt.date_from = flt_date_from
            if flt_date_to:
                flt.date_to = flt_date_to
            results = self.search_service.search_advanced(text, all_items, flt)
            self._display_search_results(results, all_accounts=all_items)
            return

        results = []
        for item in all_items:
            match = True
            if flt_category and (item.category if hasattr(item, 'category') else item.get('category', '')) != flt_category:
                match = False
            if match and flt_strength and is_accounts:
                from core.password_strength import evaluate_password_strength
                s = evaluate_password_strength(item.password or '')
                if s['label'] != flt_strength:
                    match = False
            if match and flt_date_from:
                created = item.created_at if hasattr(item, 'created_at') else item.get('created_at')
                if created:
                    if isinstance(created, str):
                        created = dt.datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if created < dt.datetime.fromisoformat(flt_date_from):
                        match = False
            if match and flt_date_to:
                created = item.created_at if hasattr(item, 'created_at') else item.get('created_at')
                if created:
                    if isinstance(created, str):
                        created = dt.datetime.fromisoformat(created.replace('Z', '+00:00'))
                    dt_to = dt.datetime.fromisoformat(flt_date_to).replace(hour=23, minute=59, second=59)
                    if created > dt_to:
                        match = False
            if match:
                from services.search_service import SearchResult
                account_obj = item if is_accounts else item
                results.append(SearchResult(account=account_obj, match_type='filter', confidence=1.0, matched_field='filter'))

        if is_accounts:
            self._display_search_results(results, all_accounts=all_items)
        else:
            self._display_url_filter_results(results)

    def _display_url_filter_results(self, results):
        colors = ThemeManager.instance().colors
        self.account_list.clear()
        total_displayed = 0
        if results:
            header = QListWidgetItem("  筛选结果")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            header.setFont(font)
            header.setBackground(QColor(colors.accent_blue_bg))
            header.setForeground(QColor(colors.accent_blue))
            self.account_list.addItem(header)
            for result in results:
                url_item = result.account
                item = QListWidgetItem()
                item.setSizeHint(QSize(max(self.account_list.width() - 20, 50), 48))
                item.setData(Qt.ItemDataRole.UserRole, url_item)
                self.account_list.addItem(item)
                widget = URLListItem(url_item, parent=self.account_list)
                widget.hide()  # 防止无parent时短暂显示为独立窗口
                if self._selection_mode:
                    uid = getattr(url_item, 'id', None) or (url_item.get('id') if isinstance(url_item, dict) else None)
                    if uid:
                        widget.on_check_changed = lambda checked, id=uid: self._on_item_checkbox_changed(id, checked)
                self.account_list.setItemWidget(item, widget)
                total_displayed += 1
        if total_displayed == 0:
            item = QListWidgetItem("未找到匹配的网址")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.account_list.addItem(item)
        count = len(results)
        self.lbl_list_title.setText(f"筛选结果  |  共 {count} 个")
    
    def on_search(self):
        """搜索 - 按回车触发
        
        分层搜索策略：
        1. 精确区：精确匹配 + 拼音匹配（同步，立即渲染）
        2. AI增强区：大模型语义推理（异步，结果返回后追加）
        """
        # 隐藏搜索历史面板
        self.search_history_panel.hide()
        
        text = self.search_box.text().strip()
        
        if not text:
            self._view_mode = 'default'
            if self.current_vault == 'accounts':
                self.load_accounts()
            else:
                self.load_urls()
            return
        
        # 搜索框仅使用精确匹配
        self._view_mode = 'search'
        
        if self.current_vault == 'accounts':
            all_accounts = self.account_service.get_all_accounts()
            query = text
            
            # 同步搜索：精确 + 拼音
            sync_results = self.search_service.search(query, all_accounts)
            exact_results = [r for r in sync_results if r.match_type in ('exact', 'pinyin')]
            
            # 渲染搜索结果
            self._display_search_results(exact_results, all_accounts=all_accounts)
        else:
            # 网址搜索
            results = self._url_service.search_urls(text)
            self._display_url_search_results(results)
    
    def _on_search_text_changed(self, text: str):
        """搜索框文本变化时：有文字则隐藏历史面板，空文字且获得焦点则显示面板"""
        if text.strip():
            self.search_history_panel.hide()
        elif self.search_box.hasFocus():
            history = self.search_service.get_search_history()
            if history:
                self._show_search_history_panel()

    def _show_search_history_panel(self):
        """显示搜索历史面板（定位在搜索框下方）"""
        history = self.search_service.get_search_history()
        if not history:
            self.search_history_panel.hide()
            return
        self.search_history_panel.set_history(history)
        # 全局坐标定位（Popup 窗口使用屏幕坐标）
        pos = self.search_box.mapToGlobal(self.search_box.rect().bottomLeft())
        self.search_history_panel.setFixedWidth(self.search_box.width())
        self.search_history_panel.move(pos.x(), pos.y() + 2)
        self.search_history_panel.show()
    
    def _hide_search_history_panel(self):
        """隐藏搜索历史面板（如果焦点不在面板内）"""
        # 如果焦点在搜索框或面板内，不隐藏
        focus_widget = self.focusWidget()
        if focus_widget in (self.search_box, self.search_history_panel):
            return
        # 检查焦点是否在面板的子控件上
        if focus_widget and self.search_history_panel.isAncestorOf(focus_widget):
            return
        self.search_history_panel.hide()
    
    def _on_history_search(self, text: str):
        """点击历史记录：填充搜索框并触发搜索"""
        self.search_box.setText(text)
        self.search_history_panel.hide()
        self.on_search()
    
    def _on_history_delete(self, text: str):
        """删除单条搜索历史"""
        self.search_service.remove_history_item(text)
        self.search_history_panel.set_history(self.search_service.get_search_history())
    
    def _on_history_clear_all(self):
        """清空全部搜索历史"""
        self.search_service.clear_history()
        self.search_history_panel.hide()
    
    def _display_search_results(self, exact_results, all_accounts):
        """展示搜索结果：精确匹配 + 拼音匹配"""
        colors = ThemeManager.instance().colors
        self.account_list.clear()
        
        total_displayed = 0
        
        # ---------- 精确匹配区 ----------
        if exact_results:
            header = QListWidgetItem("  搜索结果")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            header.setFont(font)
            header.setBackground(QColor(colors.accent_blue_bg))
            header.setForeground(QColor(colors.accent_blue))
            self.account_list.addItem(header)
            
            for result in exact_results[:30]:
                item = QListWidgetItem()
                item.setSizeHint(QSize(max(self.account_list.width() - 20, 50), 56))
                item.setData(Qt.ItemDataRole.UserRole, result.account)
                self.account_list.addItem(item)
                
                # 拼音匹配添加标识
                badges = []
                if result.match_type == 'pinyin':
                    badges.append(("拼音", "#FF9800"))
                
                widget = AccountListItem(result.account, badges=badges, selection_mode=self._selection_mode, parent=self.account_list)
                widget.hide()  # 防止无parent时短暂显示为独立窗口
                if self._selection_mode:
                    widget.on_check_changed = lambda checked, aid=result.account.id: self._on_item_checkbox_changed(aid, checked)
                if self._selection_mode and result.account.id in self._selected_ids:
                    widget.set_checked(True)
                self.account_list.setItemWidget(item, widget)
                col_config = self._load_column_config()
                for key, visible in col_config.items():
                    if not visible:
                        widget.set_column_visible(key, False)
                total_displayed += 1
        
        # ---------- 无结果提示 ----------
        if total_displayed == 0:
            item = QListWidgetItem("未找到匹配的账号")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.account_list.addItem(item)
        
        # 更新标题
        exact_count = len(exact_results)
        title_parts = [f"搜索结果"]
        if exact_count > 0:
            title_parts.append(f"共 {exact_count} 个")
        
        self.lbl_list_title.setText("  |  ".join(title_parts))
    
    def _ensure_ollama_available(self) -> bool:
        """
        确保 Ollama 服务可用。
        如果不可用，弹窗提醒用户手动启动，提供重试机制。
        
        Returns:
            True 表示 Ollama 可用，False 表示用户取消或未启动
        """
        if self._ai_manager.is_available():
            return True
        
        reply = QMessageBox.question(
            self,
            "AI 服务未启动",
            "AI增强搜索需要本地 Ollama 服务。\n\n"
            "请按以下步骤操作：\n"
            "1. 打开终端或命令提示符\n"
            "2. 运行命令：ollama run gemma4:4b\n"
            "3. 保持窗口运行\n\n"
            "完成后点击\"重试\"，或点击\"取消\"仅使用精确搜索。",
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Retry
        )
        
        if reply == QMessageBox.StandardButton.Retry:
            # 重新检测
            if self._ai_manager.is_available():
                return True
            else:
                QMessageBox.warning(
                    self,
                    "仍未检测到",
                    "Ollama 服务仍未启动，请确认已正确运行命令后重试。\n"
                    "提示：首次启动模型可能需要下载，请耐心等待。"
                )
        
        return False
    
    def on_url_manager(self):
        """切换到网址库"""
        self.tab_group.button(1).setChecked(True)
        self._on_vault_tab_changed(1)
    
    def on_batch_import(self):
        """批量导入账号"""
        from ui.import_dialog import ImportDialog
        
        self._save_scroll_state()
        
        dialog = ImportDialog(self.account_service, parent=self)
        result = dialog.exec()
        
        if result == ImportDialog.DialogCode.Accepted:
            # 刷新账号列表
            self._accounts_cache_dirty = True
            self.load_accounts()
            self._restore_scroll_state()
            self._reload_categories()
    
    def _on_import_from_manager(self):
        """从其他密码管理器导入（Bitwarden/LastPass/1Password/KeePass CSV/JSON/XML）"""
        from services.import_service import ManagerImportService
        from PyQt6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择导入文件",
            "", "所有支持格式 (*.csv *.json *.xml);;CSV 文件 (*.csv);;JSON 文件 (*.json);;XML 文件 (*.xml)"
        )
        if not file_path:
            return

        fmt = ManagerImportService.detect_format(file_path)
        if fmt == 'unknown':
            QMessageBox.warning(self, "无法识别", "无法识别该文件格式，请确认文件来自 Bitwarden、LastPass、1Password 或 KeePass")
            return

        fmt_labels = {
            'bitwarden_csv': 'Bitwarden CSV',
            'bitwarden_json': 'Bitwarden JSON',
            'lastpass_csv': 'LastPass CSV',
            '1password_csv': '1Password CSV',
            'keepass_xml': 'KeePass XML',
        }

        try:
            fmt, items = ManagerImportService.parse(file_path)
        except Exception as e:
            QMessageBox.critical(self, "解析失败", f"无法解析文件：\n{str(e)}")
            return

        if not items:
            QMessageBox.information(self, "提示", "文件中没有找到可导入的条目")
            return

        reply = QMessageBox.question(
            self, "确认导入",
            f"检测到 {fmt_labels.get(fmt, fmt)} 格式，共 {len(items)} 个条目。\n确定导入吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        imported = 0
        for item in items:
            try:
                acc = Account(
                    app_name=item['app_name'],
                    url=item.get('url', ''),
                    username=item.get('username', ''),
                    password=item.get('password', ''),
                    category=item.get('category', '其他'),
                    remark=item.get('remark', ''),
                )
                self.account_service.add_account(acc)
                imported += 1
            except Exception as e:
                logger.warning("Manager import failed for %s: %s", item.get('app_name', '?'), e)

        self._accounts_cache_dirty = True
        self.load_accounts()
        self._reload_categories()
        QMessageBox.information(self, "导入完成", f"成功导入 {imported} 个条目")

    def on_export(self):
        """导出账号/网址"""
        if not self._verify_session():
            return
        dialog = ExportDialog(self.db, self.account_service, self.export_service,
                              vault_type=self.current_vault, url_service=self._url_service, parent=self)
        dialog.exec()
    
    def _apply_theme(self, theme_name: str):
        """应用主题（由设置对话框触发）

        样式重刷统一由 ThemeManager.theme_changed → _on_theme_changed 触发，
        避免 _apply_theme 与信号回调重复调用 _reapply_styles。
        """
        self.setUpdatesEnabled(False)
        try:
            ThemeManager.instance().apply_theme(theme_name)
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _on_theme_changed(self, theme_name: str):
        """主题切换后重建 UI 样式（由 ThemeManager 信号触发）"""
        self._reapply_styles(ThemeManager.instance().colors)
        # 批量更新列表项，冻结列表避免中间重绘
        self.account_list.setUpdatesEnabled(False)
        try:
            for i in range(self.account_list.count()):
                item = self.account_list.item(i)
                widget = self.account_list.itemWidget(item)
                if widget and hasattr(widget, 'on_theme_changed'):
                    widget.on_theme_changed()
        finally:
            self.account_list.setUpdatesEnabled(True)
        # 更新搜索历史面板主题
        if hasattr(self, 'search_history_panel'):
            self.search_history_panel.on_theme_changed()
        # AI 聊天区域需要全量重建以应用新主题色
        self._ai_update_chat_display()

    def _reapply_styles(self, colors: ThemeColors):
        """重新应用所有静态样式（主题切换时调用）"""
        # === 栏和面板 ===
        self.top_bar.setStyleSheet(style_bar(colors, 'bottom'))
        self.left_panel.setStyleSheet(style_panel(colors, 'right'))
        self.category_sel_bar.setStyleSheet(style_bar(colors, 'top'))
        self.ai_panel.setStyleSheet(style_panel(colors, 'left'))
        self.bottom_bar.setStyleSheet(style_bar(colors, 'top'))
        self.selection_bottom_bar.setStyleSheet(style_bar(colors, 'top'))

        # === 分类树样式（重新生成 + 重新应用） ===
        self._category_tree_normal_style = f"""
            QTreeWidget {{
                background-color: {colors.bg_surface};
                border: none;
            }}
            QTreeWidget::item {{
                padding: 12px 15px;
                border-radius: 0;
            }}
            QTreeWidget::item:selected {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border-left: 3px solid {colors.accent_blue_light};
            }}
            QTreeWidget::item:hover {{
                background-color: {colors.bg_hover};
                border-left: 3px solid {colors.accent_blue_light};
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                image: url("{self._branch_closed_svg}");
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                image: url("{self._branch_open_svg}");
            }}
        """
        self._category_tree_checkbox_style = f"""
            QTreeWidget {{
                background-color: {colors.bg_surface};
                border: none;
            }}
            QTreeWidget::item {{
                padding: 12px 15px;
                border-radius: 0;
            }}
            QTreeWidget::item:selected {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border-left: 3px solid {colors.accent_blue_light};
            }}
            QTreeWidget::indicator {{
                width: 16px;
                height: 16px;
            }}
            QTreeWidget::indicator:unchecked {{
                border: 2px solid {colors.text_secondary};
                background-color: {colors.bg_primary};
                border-radius: 3px;
            }}
            QTreeWidget::indicator:checked {{
                background-color: {colors.accent_blue};
                border: 2px solid {colors.accent_blue};
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                image: url("{self._branch_closed_svg}");
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                image: url("{self._branch_open_svg}");
            }}
        """
        
        self.category_tree.set_normal_style(self._category_tree_normal_style)
        if self._category_selection_mode:
            self.category_tree.setStyleSheet(self._category_tree_checkbox_style)
        elif getattr(self, '_category_edit_mode', False):
            self.category_tree.set_edit_mode(True)
        elif getattr(self, '_category_reorganize_mode', False):
            self.category_tree.set_reorganize_mode(True)
        else:
            self.category_tree.setStyleSheet(self._category_tree_normal_style)

        # === 分类栏按钮 ===
        self.btn_category_sort.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                font-size: 12px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
            }}
        """)
        self.btn_category_reorganize.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                font-size: 12px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_orange_bg};
                color: {colors.accent_orange};
            }}
        """)
        self.btn_category_batch_delete.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_red_bg};
                color: {colors.accent_red};
                border: 1px solid {colors.accent_red};
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_red};
                color: {colors.text_on_accent};
            }}
        """)

        # === 分类选择栏按钮 ===
        self.btn_cat_sel_all.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border: 1px solid {colors.accent_blue_light};
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg_hover};
            }}
        """)
        self.btn_cat_sel_delete.setStyleSheet(style_button_danger(colors))

        # === 选择工具栏删除按钮 ===
        self.btn_sel_delete.setStyleSheet(style_button_danger(colors))

        # === 重新应用炽阳按钮样式（不切换面板状态） ===
        colors2 = colors
        if self._ai_panel_visible:
            self.btn_ai_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors2.accent_orange_dark};
                    color: {colors2.text_on_accent};
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {colors2.accent_orange_dark};
                }}
            """)
        else:
            self.btn_ai_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors2.accent_orange};
                    color: {colors2.text_on_accent};
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {colors2.accent_orange_dark};
                }}
            """)

        # === 库切换按钮 ===
        tab_style = f"""
            QPushButton {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_medium};
                border-radius: 4px;
                font-weight: bold;
                padding: 0 14px;
            }}
            QPushButton:checked {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_accent};
                border: 1px solid {colors.accent_blue};
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg};
            }}
            QPushButton:checked:hover {{
                background-color: {colors.accent_blue_dark};
            }}
        """
        self.btn_vault_accounts.setStyleSheet(tab_style)
        self.btn_vault_urls.setStyleSheet(tab_style)

        # === AI 面板内部控件 ===
        self.thinking_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.bg_secondary};
                border: 1px solid {colors.border_light};
                border-radius: 6px;
                padding: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                color: {colors.text_secondary};
            }}
        """)
        self.result_area.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_light};
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                line-height: 1.6;
            }}
        """)
        # AI 输入框
        self.ai_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
                line-height: 1.4;
            }}
        """)
        # AI 模式横幅和提示文字
        self._on_ai_mode_changed(self._ai_mode)
        self._update_send_button_style(self._ai_query_running)
        self._on_ai_state_changed(self._ai_manager.get_state())

        # === 列表区域样式 ===
        self.account_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {colors.bg_secondary};
                border: none;
            }}
            QListWidget::item {{
                background-color: transparent;
                border: none;
                padding: 0px;
            }}
        """)
        self.lbl_list_title.setStyleSheet(f"color: {colors.text_primary}; padding-bottom: 10px;")
        self.ai_filter_banner.setStyleSheet(f"""
            QWidget {{
                background-color: {colors.accent_blue_bg};
                border: none;
                border-radius: 4px;
            }}
        """)
        self.lbl_ai_filter.setStyleSheet(f"color: {colors.accent_blue_text}; font-size: 12px;")

        # === 字母导航条 ===
        for i in range(self.alpha_nav.layout().count()):
            w = self.alpha_nav.layout().itemAt(i)
            if w and w.widget():
                lbl = w.widget()
                if isinstance(lbl, QLabel):
                    lbl.setStyleSheet(f"""
                        QLabel {{
                            color: {colors.accent_blue_light};
                            font-size: 12px;
                            font-weight: bold;
                            padding: 2px 4px;
                        }}
                        QLabel:hover {{
                            color: {colors.accent_blue};
                            background-color: {colors.accent_blue_bg};
                            border-radius: 10px;
                        }}
                    """)

        # === 顶部工具栏控件 ===
        self.search_box.setStyleSheet(style_input(colors))
        self.btn_toggle_filter.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                font-size: 14px;
            }}
            QPushButton:checked {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_accent};
                border: 1px solid {colors.accent_blue};
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
            }}
            QPushButton:checked:hover {{
                background-color: {colors.accent_blue_dark};
            }}
        """)
        self.lbl_filter_active.setStyleSheet(f"color: {colors.accent_orange_text}; font-size: 11px; font-weight: bold; padding: 0 4px;")
        self.btn_add.setStyleSheet(style_button_primary(colors))
        self.btn_settings.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
            }}
        """)
        self.btn_compact_view.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {colors.border_default};
                background-color: {colors.bg_tertiary};
                border-radius: 4px;
                font-size: 14px;
                color: {colors.text_secondary};
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
                border-color: {colors.border_medium};
            }}
            QPushButton:checked {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border-color: {colors.accent_blue};
            }}
        """)
        self.btn_compact_view.setIcon(IconManager.compact_icon(size=16, color=colors.text_secondary))
        self.btn_column_settings.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {colors.border_default};
                background-color: {colors.bg_tertiary};
                border-radius: 4px;
                font-size: 14px;
                color: {colors.text_secondary};
            }}
            QPushButton:hover {{
                background-color: {colors.bg_hover};
                border-color: {colors.border_medium};
            }}
        """)
        self.btn_column_settings.setIcon(IconManager.settings_icon(size=16, color=colors.text_secondary))
        self.btn_help.setIcon(IconManager.help_icon(size=20, color=colors.accent_orange))

        # === 筛选面板 ===
        self.filter_panel.setStyleSheet(f"background-color: {colors.bg_secondary}; border-bottom: 1px solid {colors.border_default};")
        label_style = f"color: {colors.text_primary}; font-size: 12px;"
        combo_style = f"""
            QComboBox {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 2px 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
            }}
        """
        date_style = f"""
            QDateEdit {{
                background-color: {colors.bg_primary};
                color: {colors.text_primary};
                border: 1px solid {colors.border_default};
                border-radius: 4px;
                padding: 2px 8px;
            }}
            QDateEdit::drop-down {{
                border: none;
            }}
        """
        self.lbl_filter_category.setStyleSheet(label_style)
        self.lbl_filter_created.setStyleSheet(label_style)
        self.lbl_filter_to.setStyleSheet(label_style)
        self.lbl_filter_strength.setStyleSheet(label_style)
        self.filter_category.setStyleSheet(combo_style)
        self.filter_date_from.setStyleSheet(date_style)
        self.filter_date_to.setStyleSheet(date_style)
        self.filter_strength.setStyleSheet(combo_style)

        # === AI 筛选横幅清除按钮 ===
        self.btn_clear_ai_filter.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_light};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 3px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue};
            }}
        """)

        # === Dashboard ===
        if self.dashboard:
            self.dashboard.refresh()

        # 列表项样式已在 _on_theme_changed 中通过遍历更新，不再重建

    def on_settings(self):
        """打开设置对话框"""
        if not self._verify_session():
            return
        if not self.config_path:
            QMessageBox.warning(self, "提示", "配置文件路径未设置")
            return
        
        t0 = time.perf_counter()
        dialog = SettingsDialog(
            self.db, self.config_path,
            parent=self
        )
        t1 = time.perf_counter()
        logger.debug(f" SettingsDialog construct: {(t1-t0)*1000:.1f} ms")
        
        # 连接主题切换信号
        dialog.theme_changed.connect(self._apply_theme)
        
        result = dialog.exec()
        t2 = time.perf_counter()
        logger.debug(f" SettingsDialog exec: {(t2-t1)*1000:.1f} ms")
        
        # 更新会话版本（密码修改后会递增）
        self._session_version = self.db.get_session_version()

        # 主题切换的样式重刷已由 _on_theme_changed 统一处理
        self.repaint()
    
    def _on_show_help(self):
        """打开使用帮助对话框"""
        dialog = HelpDialog(self)
        dialog.exec()
    
    def _on_ai_state_changed(self, state):
        """AI 状态变化回调：更新底部状态栏"""
        colors = ThemeManager.instance().colors
        if state.status == AIStatus.ONLINE:
            self.lbl_ollama_status.setText(f"AI模型: {state.model_name} 运行中")
            self.lbl_ollama_status.setStyleSheet(f"color: {colors.accent_green}; font-size: 11px;")
        elif state.status == AIStatus.OFFLINE:
            self.lbl_ollama_status.setText("AI模型: 未连接")
            self.lbl_ollama_status.setStyleSheet(f"color: {colors.accent_red}; font-size: 11px;")
        elif state.status == AIStatus.ERROR:
            self.lbl_ollama_status.setText("AI模型: 错误")
            self.lbl_ollama_status.setStyleSheet(f"color: {colors.accent_red}; font-size: 11px;")
        else:
            self.lbl_ollama_status.setText("AI模型: 检测中...")
            self.lbl_ollama_status.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px;")

    def _show_ollama_warning(self, feature_name: str = "此功能"):
        """显示Ollama未启动的警告"""
        QMessageBox.warning(
            self,
            "AI服务不可用",
            f"{feature_name}需要本地Ollama服务支持。\n\n"
            f"请按以下步骤操作：\n"
            f"1. 安装Ollama：https://ollama.com/download\n"
            f"2. 启动Ollama并加载模型：ollama run gemma4:4b\n"
            f"3. 保持终端窗口运行\n\n"
            f"提示：未开启Ollama时，软件仍可使用基础功能。"
        )
    
    # ==================== 炽阳 面板 ====================
    
    def _check_conversation_context_expiry(self):
        """检查对话上下文是否过期，过期则重置"""
        if hasattr(self, 'ai_assistant') and self.ai_assistant.conversation_context.is_expired():
            self.ai_assistant.conversation_context.reset()
    
    def _on_ai_mode_changed(self, mode: str):
        """切换 AI 模式：plan / build"""
        colors = ThemeManager.instance().colors
        if getattr(self, '_mode_change_guard', False):
            return
        self._mode_change_guard = True
        try:
            if mode == 'build':
                reply = QMessageBox.question(
                    self, "切换到 Build 模式",
                    "切换到 Build 模式后，AI 可以执行删除、新增等写操作。\n\n"
                    "所有操作在执行前都会要求你确认，是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    self.btn_mode_plan.setChecked(True)
                    self.btn_mode_build.setChecked(False)
                    self._ai_mode = 'plan'
                    return
            
            self._ai_mode = mode
            # 重置对话上下文
            self.ai_assistant.conversation_context.reset()
            if mode == 'plan':
                self.btn_mode_plan.setChecked(True)
                self.btn_mode_build.setChecked(False)
                self.lbl_mode_hint.setText("只提供建议，不操作数据")
                self.lbl_mode_hint.setStyleSheet(f"color: {colors.accent_blue}; font-size: 10px;")
                # 更新横幅
                self.ai_mode_banner.setText("🔍 规划模式 — 只读查询")
                self.ai_mode_banner.setStyleSheet(f"""
                    QLabel {{
                        background-color: {colors.accent_blue_light};
                        color: {colors.text_on_accent};
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 12px;
                    }}
                """)
                self.ai_input.setPlaceholderText("输入指令，如：查找支付类账号")
            else:
                self.btn_mode_plan.setChecked(False)
                self.btn_mode_build.setChecked(True)
                self.lbl_mode_hint.setText("可执行操作，危险操作需确认")
                self.lbl_mode_hint.setStyleSheet(f"color: {colors.accent_orange_text}; font-size: 10px;")
                # 更新横幅
                self.ai_mode_banner.setText("🔧 构建模式 — 可执行写操作（整理 / 备注 / 删除 / 新增）")
                self.ai_mode_banner.setStyleSheet(f"""
                    QLabel {{
                        background-color: {colors.accent_orange};
                        color: {colors.text_on_accent};
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 12px;
                    }}
                """)
                self.ai_input.setPlaceholderText("Build 模式：可以执行增删改操作，所有变更需确认后生效")
        finally:
            self._mode_change_guard = False
    
    def _is_ai_action_safe(self, action: str) -> bool:
        """判断 AI 操作是否安全（无需确认）"""
        return action in ('search', 'filter', 'list', 'explain')
    
    def _on_ai_confirm_execute(self):
        """用户确认执行待处理的操作"""
        if not self._pending_action:
            return
        action, params, query = self._pending_action
        self._pending_action = None
        self.ai_confirm_widget.hide()
        
        # 执行操作
        if action in ('search', 'filter', 'list'):
            action_result = self.ai_assistant.execute_action(action, params, self._all_accounts_cache)
            matched = action_result.get('matched_accounts', [])
            if matched:
                self._ai_display_results_in_list(matched, query)
        
        # 在对话中追加执行结果
        from services.ai_assistant_service import ConversationMessage
        from datetime import datetime
        self.ai_assistant._history.append(ConversationMessage(
            role='assistant',
            content="✅ 已按您的确认执行操作。",
            timestamp=datetime.now().strftime("%H:%M:%S")
        ))
        self._ai_update_chat_display()
    
    def _on_ai_confirm_cancel(self):
        """用户取消待处理的操作"""
        self._pending_action = None
        self.ai_confirm_widget.hide()
        
        from services.ai_assistant_service import ConversationMessage
        from datetime import datetime
        self.ai_assistant._history.append(ConversationMessage(
            role='assistant',
            content="❌ 操作已取消。",
            timestamp=datetime.now().strftime("%H:%M:%S")
        ))
        self._ai_update_chat_display()
    
    def on_ai_toggle_panel(self):
        """展开/收起 炽阳 面板"""
        colors = ThemeManager.instance().colors
        self._ai_panel_visible = not self._ai_panel_visible
        
        if self._ai_panel_visible:
            self.ai_panel.setMaximumWidth(600)
            self.ai_panel.setMinimumWidth(400)
            self.btn_ai_toggle.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.accent_orange_dark};
                    color: {colors.text_on_accent};
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {colors.accent_orange_dark};
                }}
            """)
            # 如果对话区为空，显示欢迎语
            if not self.result_area.toPlainText().strip():
                self._ai_show_welcome()
        else:
            self.ai_panel.setMaximumWidth(0)
            self.ai_panel.setMinimumWidth(0)
            self.btn_ai_toggle.setStyleSheet(f"""
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
    
    def _ai_show_welcome(self):
        """显示 炽阳 个性化欢迎语（纯文本，根据当前库切换内容）"""
        if self._ai_welcome_shown:
            return
        self._ai_welcome_shown = True
        if self.current_vault == 'accounts':
            welcome_text = (
                "🦁🔥 密码库模式\n\n"
                "炽阳 已觉醒\n\n"
                "你好，狮子座的主人。\n\n"
                "⚡ 首次同步：请发送任意消息完成神经连接预热，预热完成后即可执行操作。"
            )
        else:
            welcome_text = (
                "🦁🔥 网址库模式\n\n"
                "炽阳 已觉醒\n\n"
                "你好，狮子座的主人。\n\n"
                "⚡ 首次同步：请发送任意消息完成神经连接预热，预热完成后即可执行操作。"
            )
        self.result_area.setPlainText(welcome_text)
    
    def _update_send_button_style(self, is_stop: bool):
        """切换发送按钮样式：发送(橙色) / 停止(灰色)"""
        colors = ThemeManager.instance().colors
        if is_stop:
            self.btn_ai_send.setText("停止")
            self.btn_ai_send.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.border_medium};
                    color: {colors.text_on_accent};
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {colors.text_tertiary};
                }}
            """)
        else:
            self.btn_ai_send.setText("发送")
            self.btn_ai_send.setStyleSheet(f"""
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
    
    def _on_ai_send_or_stop(self):
        """发送/停止按钮的统一入口"""
        if self._ai_query_running:
            self._on_ai_stop_query()
        else:
            self.on_ai_send_message()
    
    def _on_ai_stop_query(self):
        """用户手动停止当前 AI 查询"""
        self._ai_query_cancelled = True
        self._ai_query_running = False
        self._update_send_button_style(False)
        
        # 停止线程
        if hasattr(self, '_ai_thread') and self._ai_thread:
            self._ai_thread.cancel()
        
        # 隐藏流式输出区域
        self.thinking_area.hide()
        self.ai_action_buttons.show()
        
        # 在对话中追加取消提示
        from services.ai_assistant_service import ConversationMessage
        from datetime import datetime
        self.ai_assistant._history.append(ConversationMessage(
            role='system', content='⏹ 用户已停止本次查询',
            timestamp=datetime.now().strftime("%H:%M:%S")
        ))
        self._ai_update_chat_display()
    
    def _on_thinking_token(self, token: str):
        """接收 thinking token，实时追加到思考区
        
        安全保护：如果查询已结束（_ai_query_running=False），忽略延迟到达的 token，
        防止 C++ 层内存损坏（0xC0000409）。
        """
        if not getattr(self, '_ai_query_running', False):
            return
        try:
            self.thinking_area.insertPlainText(token)
            scrollbar = self.thinking_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception as e:
            logger.exception(f" _on_thinking_token error: {e}")
    
    def _on_result_token(self, segment: str):
        """接收 result 段落，追加到对话历史并刷新 UI

        增量追加模式：将段落追加到历史最后一条 assistant 消息，
        使用 QTextCursor 直接插入 HTML，避免高频 setHtml 导致 CPU 飙升。
        流式输出期间完全依赖增量追加，不触发全量重建。
        """
        if not getattr(self, '_ai_query_running', False):
            return
        try:
            if (self.ai_assistant._history and
                self.ai_assistant._history[-1].role == 'assistant'):
                self.ai_assistant._history[-1].content += segment
                # 增量追加：直接插入 HTML，避免全量重建
                self._ai_append_token_html(segment)
            else:
                logger.warning(" _on_result_token: no assistant msg to append")
        except Exception as e:
            logger.exception(f" _on_result_token error: {e}")
    
    def _on_ai_copy_result(self):
        """复制 AI 回复到剪贴板"""
        text = self.result_area.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self._append_ai_system_msg("✅ 已复制到剪贴板")
    
    def _on_ai_regenerate(self):
        """重新生成上一条回复"""
        query = getattr(self, '_current_ai_query', '')
        if query:
            self.ai_input.setPlainText(query)
            self.on_ai_send_message()
    
    def _on_action_preview_confirmed(self):
        """Build 模式：用户确认执行操作预览（使用事务提交）"""
        import traceback
        logger.debug("[MainWindow] _on_action_preview_confirmed called")
        self.action_preview_widget.hide()
        
        # ReAct 模式：走新流程
        if self._react_state == ReActState.AWAITING_PREVIEW:
            self._on_react_preview_confirmed()
            return
        
        if not self._pending_action:
            logger.debug("[MainWindow] No pending action, returning")
            return
        action, params, query = self._pending_action
        self._pending_action = None
        
        self._save_scroll_state()
        
        # 执行操作（事务方式）
        try:
            logger.info(f" Building action_preview for action={action}")
            # 1. 生成结构化操作预览（根据当前 vault 传正确缓存）
            context_items = self._all_accounts_cache if self.current_vault == 'accounts' else self._all_urls_cache
            action_preview = self.ai_assistant.build_action_preview(
                action, params, context_items, self.current_vault
            )
            logger.info(f" action_preview built: preview_items={len(action_preview.get('preview_items', []))}")
            
            # 1.5 过滤用户取消勾选的条目
            selected_items = self.action_preview_widget.get_selected_items()
            action_preview['preview_items'] = selected_items
            action_preview['affected_count'] = len(selected_items)
            logger.info(f" User selected {len(selected_items)} items after filtering")
            
            # 2. 执行操作
            logger.debug("[MainWindow] Calling execute_build_action_with_transaction")
            result = self.ai_assistant.execute_build_action_with_transaction(
                action_preview, user_query=query
            )
            logger.info(f" Execution result: success={result.get('success')}, affected={result.get('affected_count')}")
            
            # 处理超量删除的二次确认
            if result.get('needs_confirmation'):
                reply = QMessageBox.question(
                    self, "二次确认",
                    result.get('message', '即将删除大量记录，是否确认执行？'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    result = self.ai_assistant.execute_build_action_with_transaction(
                        action_preview, user_query=query, _force=True
                    )
                else:
                    result = {'success': False, 'error': '用户取消执行'}
            
            if result.get('success'):
                item_name = '账号' if self.current_vault == 'accounts' else '网址'
                affected_count = result.get('affected_count', 0)
                result_msg = f"✅ AI 本次修改完成，共影响 {affected_count} 个{item_name}\n"
                
                # 列出每个修改的详细信息
                for idx, item in enumerate(selected_items, 1):
                    raw = item if isinstance(item, dict) else {}
                    target_id = raw.get('target_id', '?')
                    
                    # 从缓存中查找显示名
                    display_name = f"ID:{target_id}"
                    if self.current_vault == 'accounts':
                        for acc in self._all_accounts_cache or []:
                            if getattr(acc, 'id', None) == target_id:
                                display_name = getattr(acc, 'app_name', display_name)
                                break
                    else:
                        for url in self._all_urls_cache or []:
                            if getattr(url, 'id', None) == target_id:
                                display_name = getattr(url, 'title', display_name)
                                break
                    
                    # 获取变更详情
                    if 'updates' in raw and isinstance(raw['updates'], dict):
                        change_str = '，'.join(f"{k}: {v}" for k, v in raw['updates'].items())
                    elif 'field' in raw and 'new_value' in raw:
                        change_str = f"{raw['field']}: {raw['new_value']}"
                    elif 'content' in raw:
                        change_str = f"备注: {raw['content']}"
                    elif 'tags' in raw and 'mode' in raw:
                        change_str = f"标签({raw['mode']}): {raw['tags']}"
                    else:
                        change_str = str(raw)
                    
                    result_msg += f"\n{idx}. {display_name} → {change_str}"
            else:
                error = result.get('error', '未知错误')
                if error == '用户取消执行':
                    result_msg = "⏹️ 已取消执行"
                else:
                    result_msg = f"❌ 执行失败：{error}"
            
            # 刷新列表和分类导航（根据当前 vault）
            self.clear_account_highlight()
            self._reload_categories()
            
            # 高亮显示受影响的条目（删除操作除外，已移入回收站）
            if action != 'delete':
                affected_ids = []
                for item in selected_items:
                    if isinstance(item, dict):
                        tid = item.get('target_id')
                        if tid:
                            affected_ids.append(int(tid))
                if affected_ids:
                    self.highlight_matched_accounts(affected_ids, query_text="AI本次修改")
        except Exception as e:
            logger.error(f" _on_action_preview_confirmed exception: {e}")
            logger.exception("Unhandled exception")
            result_msg = f"❌ 执行失败：{str(e)}"
        
        self._restore_scroll_state()
        
        # 追加结果到历史
        from services.ai_assistant_service import ConversationMessage
        from datetime import datetime
        self.ai_assistant._history.append(ConversationMessage(
            role='assistant', content=result_msg,
            timestamp=datetime.now().strftime("%H:%M:%S")
        ))
        self._ai_update_chat_display()
        self.ai_action_buttons.show()
    
    def _on_action_preview_cancelled(self):
        """Build 模式：用户取消操作预览"""
        self.action_preview_widget.hide()
        
        # ReAct 模式：走新流程
        if self._react_state == ReActState.AWAITING_PREVIEW:
            self._on_react_preview_cancelled()
            return
        
        self._pending_action = None
        
        from services.ai_assistant_service import ConversationMessage
        from datetime import datetime
        self.ai_assistant._history.append(ConversationMessage(
            role='assistant', content="❌ 操作已取消。",
            timestamp=datetime.now().strftime("%H:%M:%S")
        ))
        self._ai_update_chat_display()
        self.ai_action_buttons.show()
    
    def _on_react_result(self, result_json: str):
        """ReAct 结果回调：解析 result_json，处理 awaiting_confirm / done 状态"""
        import json
        from services.ai_assistant_service import ConversationMessage
        
        self._ai_query_running = False
        self._update_send_button_style(False)
        
        # 断开流式信号，使用 deleteLater 安全销毁，避免在信号处理中直接回收 C++ 对象
        # 断开流式信号，使用 deleteLater 安全销毁，避免在信号处理中直接回收 C++ 对象
        if self._ai_thread is not None:
            try:
                self._ai_thread.thinking_token.disconnect(self._on_thinking_token)
            except Exception as e:
                logger.debug("断开 thinking_token 信号失败: %s", e)
            try:
                self._ai_thread.result_token.disconnect(self._on_result_token)
            except Exception as e:
                logger.debug("断开 result_token 信号失败: %s", e)
            self._ai_thread.deleteLater()
            self._ai_thread = None
        
        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            result = {"success": False, "response": "ReAct 返回数据解析失败", "done": True}
        
        now_str = datetime.now().strftime("%H:%M:%S")
        
        # 安全清理 UI
        self.result_area.clear()
        self.thinking_area.clear()
        self.thinking_area.hide()
        self._ai_update_chat_display()
        
        
        if result.get('awaiting_confirm'):
            # 暂停循环，展示预览组件
            self._react_state = ReActState.AWAITING_PREVIEW
            self._pending_tool = result.get('pending_tool')
            self._react_turns_used = result.get('turns_used', self._react_turns_used + 1)
            
            preview = result.get('preview', {}) or {}
            preview_data = preview.get('preview_data', {}) if isinstance(preview, dict) else {}
            if preview_data and preview_data.get('items'):
                self.action_preview_widget.set_preview_data(preview_data)
                self.action_preview_widget.show()
                self.ai_action_buttons.hide()
            else:
                # 没有预览数据，但仍需用户确认（可能是无需逐条预览的操作）
                # 显示一个简化的确认提示
                self.action_preview_widget.hide()
                self.ai_action_buttons.show()
            
            response = result.get('response', '请确认以下操作')
            
            # 分类工具：强制简洁回复，覆盖流式输出阶段可能已生成的长篇分析
            pending_tool = self._pending_tool or {}
            if pending_tool.get('tool') in ('smart_classify_accounts', 'smart_classify_urls'):
                response = result.get('response', '已生成分类预览，请确认')
                # 如果最后一条是 assistant 的流式输出，直接替换内容
                if (self.ai_assistant._history 
                        and self.ai_assistant._history[-1].role == 'assistant'):
                    self.ai_assistant._history[-1].content = response
                    self.ai_assistant._history[-1].timestamp = now_str
                    self._ai_update_chat_display()
                else:
                    self.ai_assistant._history.append(ConversationMessage(
                        role='assistant', content=response, timestamp=now_str
                    ))
                    self._ai_update_chat_display()
            else:
                self.ai_assistant._history.append(ConversationMessage(
                    role='assistant', content=response, timestamp=now_str
                ))
                self._ai_update_chat_display()
        elif result.get('done'):
            self._react_state = ReActState.IDLE
            self._pending_tool = None
            self._react_turns_used = result.get('turns_used', self._react_turns_used)
            
            response = result.get('response', '操作完成')
            self.ai_assistant._history.append(ConversationMessage(
                role='assistant', content=response, timestamp=now_str
            ))
            self._ai_update_chat_display()
            self.ai_action_buttons.show()
            
            # ReAct 模式：如果返回了匹配ID，高亮左侧列表
            matched_ids = result.get('matched_ids', [])
            if matched_ids:
                q = getattr(self, '_current_ai_query', '')
                self.highlight_matched_accounts(matched_ids, query_text=q)
        else:
            # 中间状态，继续循环
            self._react_turns_used = result.get('turns_used', self._react_turns_used)
    
    def _on_react_preview_confirmed(self):
        """ReAct 模式：用户确认预览后执行事务并写入 Observation"""
        import traceback
        from datetime import datetime
        from services.ai_assistant_service import ConversationMessage
        
        tool_info = self._pending_tool
        tool_name = tool_info.get('tool') if isinstance(tool_info, dict) else tool_info
        query = getattr(self, '_current_ai_query', '')
        confirmed_items = self.action_preview_widget.get_confirmed_items()
        
        try:
            result = self.ai_assistant.execute_build_action_with_transaction(
                confirmed_items, tool_name, user_query=query
            )
            
            # 处理超量删除的二次确认
            if result.get('needs_confirmation'):
                reply = QMessageBox.question(
                    self, "二次确认",
                    result.get('message', '即将删除大量记录，是否确认执行？'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    result = self.ai_assistant.execute_build_action_with_transaction(
                        confirmed_items, tool_name, user_query=query, _force=True
                    )
                else:
                    result = {'success': False, 'error': '用户取消执行'}
            
            if result.get('success'):
                item_name = '账号' if self.current_vault == 'accounts' else '网址'
                result_msg = result.get('result_msg', f"✅ 成功执行操作，共影响 {result.get('affected_count', 0)} 个{item_name}")
            else:
                error = result.get('error', '未知错误')
                result_msg = "⏹️ 已取消执行" if error == '用户取消执行' else f"❌ 执行失败：{error}"
            
            # 写入 Observation
            self.ai_assistant.conversation_context.add_observation(
                tool=tool_name or 'unknown',
                params={"confirmed_count": len(confirmed_items)},
                result=result,
                turn=self._react_turns_used
            )
            
            # 刷新列表和缓存
            self.clear_account_highlight()
            self._accounts_cache_dirty = True
            self._urls_cache_dirty = True
            self._reload_categories()
            if self.current_vault == 'accounts':
                self.load_accounts()
            else:
                self.load_urls()
            
            # 高亮显示受影响的账号（删除操作除外，已移入回收站）
            if tool_name not in ('batch_delete_accounts', 'batch_delete_urls'):
                try:
                    # 优先使用 result 中返回的 affected_ids（新增/修改操作会返回）
                    affected_ids = result.get('affected_ids', [])
                    if not affected_ids:
                        # 回退：从 confirmed_items 中提取 target_id/row_id
                        for item in confirmed_items:
                            if isinstance(item, dict):
                                item_id = item.get('target_id') or item.get('row_id')
                                if item_id:
                                    try:
                                        affected_ids.append(int(item_id))
                                    except ValueError:
                                        pass
                    if affected_ids:
                        self.highlight_matched_accounts(affected_ids, query_text="AI本次修改")
                except Exception as e:
                    logger.exception(f" Highlight affected items error: {e}")
        except Exception as e:
            logger.error(f" ReAct preview confirmed error: {e}")
            logger.exception("Unhandled exception")
            result_msg = f"❌ 执行失败：{str(e)}"
        
        now_str = datetime.now().strftime("%H:%M:%S")
        self.ai_assistant._history.append(ConversationMessage(
            role='assistant', content=result_msg, timestamp=now_str
        ))
        self._ai_update_chat_display()
        self.ai_action_buttons.show()
        
        # 操作已完成，结束 ReAct 循环，不再继续追问 AI
        self._react_state = ReActState.IDLE
        self._pending_tool = None
    
    def _on_react_preview_cancelled(self):
        """ReAct 模式：用户取消预览，记录 Observation 并恢复 IDLE"""
        from datetime import datetime
        from services.ai_assistant_service import ConversationMessage
        
        tool_info = self._pending_tool
        tool_name = tool_info.get('tool') if isinstance(tool_info, dict) else tool_info
        now_str = datetime.now().strftime("%H:%M:%S")
        
        self.ai_assistant.conversation_context.add_observation(
            tool=tool_name or 'unknown',
            params={"cancelled": True},
            result={"status": "cancelled_by_user"},
            turn=self._react_turns_used
        )
        
        self.ai_assistant._history.append(ConversationMessage(
            role='assistant', content="❌ 操作已取消。",
            timestamp=now_str
        ))
        self._ai_update_chat_display()
        self.ai_action_buttons.show()
        self._react_state = ReActState.IDLE
        self._pending_tool = None
        self._current_preview_widget = None
    
    def _continue_react_loop(self):
        """恢复 ReAct 循环：基于已有的 Observation 继续执行"""
        if self._react_turns_used >= self._react_max_turns:
            self._react_state = ReActState.IDLE
            return
        
        # 获取当前上下文
        if self.current_vault == 'accounts':
            if self._accounts_cache_dirty or not self._all_accounts_cache:
                self._all_accounts_cache = self.account_service.get_all_accounts()
                self._accounts_cache_dirty = False
            context = self._all_accounts_cache
            vault_type = 'accounts'
        else:
            if self._urls_cache_dirty or not self._all_urls_cache:
                self._all_urls_cache = self._url_service.get_all_urls()
                self._urls_cache_dirty = False
            context = self._all_urls_cache
            vault_type = 'urls'
        
        # 构造更丰富的上下文查询，让 AI 能精准继续
        original_query = getattr(self, '_current_ai_query', '')
        last_obs = None
        try:
            obs_list = list(self.ai_assistant.conversation_context.observations)
            if obs_list:
                last_obs = obs_list[-1]
        except Exception:
            pass
        
        if last_obs and original_query:
            cont_query = (
                f"上一步操作（{last_obs.tool}）已执行完毕。"
                f"请基于执行结果，继续回答用户的原始问题：「{original_query}」"
            )
        elif original_query:
            cont_query = f"上一步操作已完成。请继续处理用户的原始问题：「{original_query}」"
        else:
            cont_query = "上一步操作已完成。请继续处理。"
        
        self._react_state = ReActState.RUNNING
        self._ai_thread = AIQueryThread(
            self.ai_assistant, cont_query, context, self._ai_mode, vault_type
        )
        self._ai_thread.result_ready.connect(self._on_ai_query_finished)
        self._ai_thread.thinking_token.connect(self._on_thinking_token)
        self._ai_thread.result_token.connect(self._on_result_token)
        self._ai_thread.start()
    
    def _show_batch_add_dialog(self, batch_items, vault_type, query, action_preview):
        """显示批量导入预览对话框"""
        colors = ThemeManager.instance().colors
        from core.repositories import RepositoryFactory
        
        repo = RepositoryFactory.get_repository(vault_type)
        categories = repo.get_categories()
        
        dialog = QDialog(self)
        dialog.setWindowTitle("批量导入预览")
        dialog.setMinimumSize(800, 500)
        
        layout = QVBoxLayout(dialog)
        
        preview_widget = BatchAddPreviewWidget(parent=dialog, repo=repo)
        preview_widget.set_items(batch_items, vault_type, categories)
        layout.addWidget(preview_widget)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_confirm = QPushButton("✅ 确认导入")
        btn_confirm.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_green};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 4px 16px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_green_dark};
            }}
        """)
        btn_layout.addWidget(btn_confirm)
        layout.addLayout(btn_layout)
        
        def on_confirm():
            self._save_scroll_state()
            try:
                result = self.ai_assistant.execute_build_action_with_transaction(
                    action_preview, user_query=query
                )
                if result.get('success'):
                    result_msg = result.get('result_msg', f"✅ 成功导入 {result.get('affected_count', 0)} 条")
                else:
                    result_msg = f"❌ 导入失败：{result.get('error', '未知错误')}"
                
                self._accounts_cache_dirty = True
                self._urls_cache_dirty = True
                if vault_type == 'accounts':
                    self.load_accounts()
                else:
                    self.load_urls()
                
                # 高亮显示新导入的条目
                new_ids = result.get('affected_ids', [])
                if new_ids:
                    self.highlight_matched_accounts(new_ids, query_text="AI本次修改")
            except Exception as e:
                import traceback
                logger.exception("Unhandled exception")
                result_msg = f"❌ 导入失败：{str(e)}"
            
            self._restore_scroll_state()
            
            from services.ai_assistant_service import ConversationMessage
            from datetime import datetime
            self.ai_assistant._history.append(ConversationMessage(
                role='assistant', content=result_msg,
                timestamp=datetime.now().strftime("%H:%M:%S")
            ))
            self._ai_update_chat_display()
            self.ai_action_buttons.show()
            dialog.accept()
        
        btn_confirm.clicked.connect(on_confirm)
        
        result = dialog.exec()
        if result != QDialog.DialogCode.Accepted:
            # 用户取消
            from services.ai_assistant_service import ConversationMessage
            from datetime import datetime
            self.ai_assistant._history.append(ConversationMessage(
                role='assistant', content="❌ 批量导入已取消。",
                timestamp=datetime.now().strftime("%H:%M:%S")
            ))
            self._ai_update_chat_display()
            self.ai_action_buttons.show()
    
    def on_ai_send_message(self):
        """发送 AI 指令：启动后台线程避免阻塞 UI"""
        query = self.ai_input.toPlainText().strip()
        if not query:
            return
        
        # ReAct 状态检查：如果正在等待预览确认，禁止发送新消息
        if self._react_state == ReActState.AWAITING_PREVIEW:
            self._append_ai_system_msg("⚠️ 请先处理当前操作预览（确认或取消）")
            return
        
        # AI 预热机制：首次发送前预热 db_summary，预热后继续处理用户查询
        if not self.ai_assistant.conversation_context._db_summary_loaded:
            try:
                if self.current_vault == 'accounts':
                    accounts = (self._all_accounts_cache if self._all_accounts_cache and not self._accounts_cache_dirty
                                else self.account_service.get_all_accounts())
                    summary = self.ai_assistant.build_db_summary(accounts, vault_type='accounts')
                else:
                    urls = (self._all_urls_cache if self._all_urls_cache and not self._urls_cache_dirty
                            else self._url_service.get_all_urls())
                    summary = self.ai_assistant.build_db_summary(urls=urls, vault_type='urls')
                self.ai_assistant.conversation_context.set_db_summary(summary, self.current_vault)
            except Exception as e:
                logger.exception(f" Warmup error: {e}")
            # 预热完成后继续往下执行，不要 return，直接处理用户的查询
        
        # 防止重复提交（如果已有查询在进行中，忽略）
        if getattr(self, '_ai_query_running', False):
            return
        
        self._ai_query_running = True
        self._ai_query_cancelled = False
        self._update_send_button_style(True)
        
        # 记录查询开始时间
        self._ai_query_start_time = time.time()
        
        # 清空输入框
        self.ai_input.setPlainText("")
        
        # 保存当前查询（供线程回调使用）
        self._current_ai_query = query
        
        # 清除之前的流式状态和预览 widget
        # 非流式模式下隐藏 thinking_area，仅在 result_area 显示最终结果
        self.thinking_area.clear()
        self.thinking_area.hide()
        self.ai_action_buttons.hide()
        self.action_preview_widget.hide()
        self.ai_confirm_widget.hide()
        self._pending_action = None
        
        # 发送新 query 时清除左侧筛选
        self.clear_account_highlight()
        
        # 添加到对话历史：用户消息
        from services.ai_assistant_service import ConversationMessage
        from datetime import datetime
        now_str = datetime.now().strftime("%H:%M:%S")
        self.ai_assistant._history.append(ConversationMessage(
            role='user', content=query,
            timestamp=now_str
        ))
        
        # 标记为已交互（下次不再显示欢迎语）
        self._ai_interacted = True
        
        # 重新渲染（显示用户消息 + "思考中"）
        self._ai_update_chat_display()
        
        # 获取当前库上下文（AI 查询必须基于全部数据，不受 UI 筛选状态影响）
        if self.current_vault == 'accounts':
            context = self.account_service.get_all_accounts()
            vault_type = 'accounts'
        else:
            context = self._url_service.get_all_urls()
            vault_type = 'urls'
        
        # 启动后台线程执行 AI 查询（避免 GPU 满载阻塞主线程）
        self._react_state = ReActState.RUNNING
        self._ai_thread = AIQueryThread(self.ai_assistant, query, context, self._ai_mode, vault_type)
        self._ai_thread.result_ready.connect(self._on_ai_query_finished)
        self._ai_thread.thinking_token.connect(self._on_thinking_token)
        self._ai_thread.result_token.connect(self._on_result_token)
        self._ai_thread.start()
    
    def _on_ai_query_finished(self, result_json: str):
        """AI 查询完成后在主线程回调（更新 UI）
        
        安全设计：
        1. 立即标记 _ai_query_running = False，让延迟到达的流式 token 被丢弃
        2. 立即断开流式信号连接，防止后续 token 干扰 UI 清理
        3. 隐藏 thinking_area 后再操作 result_area，避免双区并发写入
        
        Plan 模式：只给建议，联动左侧列表高亮
        Build 模式：安全操作直接执行；危险操作显示 ActionPreviewWidget
        """
        import json
        import traceback
        logger.info(f" _on_ai_query_finished called, json_len={len(result_json)}")
        
        # 竞态保护：如果查询已经结束，忽略延迟到达的信号
        if not getattr(self, '_ai_query_running', False):
            return
        
        # ========== 第零步：安全关闸 ==========
        # 标记查询已结束，延迟 token 将被 _on_thinking_token/_on_result_token 丢弃
        self._ai_query_running = False
        
        # ReAct 模式：线程清理交给 _on_react_result，避免在信号处理中销毁 sender
        if self._react_state != ReActState.IDLE:
            self._on_react_result(result_json)
            return
        
        # 旧路径：断开流式信号连接，防止任何后续 token 触发 slot
        if self._ai_thread is not None:
            try:
                self._ai_thread.thinking_token.disconnect(self._on_thinking_token)
                logger.debug("[MainWindow] thinking_token disconnected")
            except Exception as e:
                logger.debug("断开 thinking_token 信号失败: %s", e)
            try:
                self._ai_thread.result_token.disconnect(self._on_result_token)
                logger.debug("[MainWindow] result_token disconnected")
            except Exception as e:
                logger.debug("断开 result_token 信号失败: %s", e)
            # 释放线程引用，允许 GC
            self._ai_thread = None
        
        # 解析结果
        try:
            result = json.loads(result_json)
            logger.info(f" Parsed result: action={result.get('action')}, mode={self._ai_mode}, success={result.get('success')}")
        except json.JSONDecodeError as e:
            logger.exception(f" JSON decode error: {e}")
            result = {
                "success": False,
                "thinking": "",
                "action": "explain",
                "params": {},
                "response": "AI 返回数据解析失败",
                "error": "JSON decode error"
            }
        
        self._ai_query_running = False
        self._update_send_button_style(False)
        
        # 如果用户已取消本次查询，忽略结果
        if self._ai_query_cancelled:
            self._ai_query_cancelled = False
            return
        
        # 计算回答用时
        if self._ai_query_start_time:
            self._ai_last_elapsed = time.time() - self._ai_query_start_time
        else:
            self._ai_last_elapsed = 0.0
        self._ai_query_start_time = None
        
        query = getattr(self, '_current_ai_query', '')
        action = result.get('action', 'explain')
        params = result.get('params', {})
        
        # 根据当前 vault 确定上下文数据
        context_items = self._all_accounts_cache if self.current_vault == 'accounts' else self._all_urls_cache
        vault_type = self.current_vault
        item_name = "账号" if self.current_vault == 'accounts' else "网址"
        
        # ========== 第一步：安全清理流式 UI ==========
        # 先清空流式追加的 plain text，再隐藏 thinking_area，最后 setHtml
        # 避免 insertPlainText 与 setHtml 的并发冲突
        try:
            self.result_area.clear()
            self.thinking_area.clear()
            self.thinking_area.hide()
            logger.debug("[MainWindow] Stream UI cleaned")
        except Exception as e:
            logger.exception(f" Stream UI clean error: {e}")
        
        # 重新渲染历史为 HTML
        self._ai_update_chat_display()
        
        # ========== Plan 模式：只建议，联动左侧列表 ==========
        if self._ai_mode == 'plan':
            logger.info(f" Plan mode handling action={action}, vault={vault_type}")
            try:
                # 统一尝试语义高亮（不依赖 action 类型，只要 semantic_result 有有效匹配就高亮）
                semantic_matched = False
                semantic_result = result.get('semantic_result')
                if semantic_result and semantic_result.get('matched_ids'):
                    matched_ids = semantic_result.get('matched_ids', [])
                    total_items = len(context_items)
                    # 防护：如果语义匹配返回了超过总数80%的ID，视为无效（模型理解偏差）
                    if total_items > 0 and len(matched_ids) <= total_items * 0.8:
                        matched_id_set = {str(m) for m in matched_ids}
                        matched = [item for item in context_items if getattr(item, 'id', None) is not None and str(item.id) in matched_id_set]
                        if matched:
                            matched_ids = [item.id for item in matched]
                            query_summary = result.get('query_summary', '') or getattr(self, '_current_ai_query', '')
                            self.highlight_matched_accounts(matched_ids, query_text=query_summary)
                            semantic_matched = True
                            # 只在 response 中还没有高亮提示时才追加
                            if "已找到" not in result['response'] and "已高亮" not in result['response']:
                                result['response'] += f"\n\n✅ 已找到 **{len(matched)}** 个相关{item_name}，左侧已高亮显示。"
                
                # 然后按 action 类型追加额外提示
                if action in ('search', 'filter'):
                    if not semantic_matched:
                        # Fallback：本地 Repository 关键词搜索兜底
                        try:
                            local_result = self.ai_assistant.execute_action(action, params, context_items, vault_type)
                            local_matched = local_result.get('matched_accounts', [])
                            if local_matched:
                                matched_ids = [item.id for item in local_matched]
                                query_summary = result.get('query_summary', '') or getattr(self, '_current_ai_query', '')
                                self.highlight_matched_accounts(matched_ids, query_text=query_summary)
                                # 清除模型回复中矛盾的"未找到"字样
                                import re
                                result['response'] = re.sub(r'[^\n]*(?:未找到|没有找到|暂未找到|不存在)[^\n]*', '', result['response'])
                                result['response'] = re.sub(r'\n{3,}', '\n\n', result['response']).strip()
                                result['response'] += f"\n\n✅ 已找到 **{len(local_matched)}** 个相关{item_name}，左侧已高亮显示。"
                            else:
                                result['response'] += f"\n\n❌ 未找到匹配的{item_name}"
                        except Exception as e:
                            logger.exception(f" Fallback search error: {e}")
                            result['response'] += f"\n\n❌ 未找到匹配的{item_name}"
                elif action == 'list':
                    scope = params.get('scope', 'all')
                    if scope == 'all':
                        result['response'] += f"\n\n📋 数据库中共有 **{len(context_items)}** 个{item_name}。"
                    elif scope == 'uncategorized':
                        uncategorized = [item for item in context_items if not getattr(item, 'category', '') or getattr(item, 'category', '') == '其他']
                        result['response'] += f"\n\n📋 未分类{item_name}共 **{len(uncategorized)}** 个。"
                    else:
                        result['response'] += f"\n\n📋 已列出{item_name}。"
                elif action in ('reorganize', 'add_remark'):
                    result['response'] += "\n\n> 💡 **Plan 模式**：以上是整理建议，切换到 **Build 模式** 并经你确认后可执行。"
                
                # 更新历史中的最后一条 assistant 消息
                if self.ai_assistant._history and self.ai_assistant._history[-1].role == 'assistant':
                    self.ai_assistant._history[-1].content = result['response']
                self._ai_update_chat_display()
                self.ai_action_buttons.show()
                
                if not result.get('success', True):
                    self._append_ai_system_msg(f"处理出错：{result.get('error', '未知错误')}")
            except Exception as e:
                logger.error(f" Plan mode handling error: {e}")
                logger.exception("Unhandled exception")
                self._append_ai_system_msg(f"处理出错：{str(e)}")
            return
        
        # ========== Build 模式 ==========
        logger.info(f" Build mode handling action={action}, vault={vault_type}")
        try:
            if self._is_ai_action_safe(action):
                # 安全操作：直接执行
                if action in ('search', 'filter', 'list'):
                    action_result = self.ai_assistant.execute_action(action, params, context_items, vault_type)
                    matched = action_result.get('matched_accounts', [])
                    if matched:
                        matched_ids = [item.id for item in matched]
                        query_summary = result.get('query_summary', '') or getattr(self, '_current_ai_query', '')
                        self.highlight_matched_accounts(matched_ids, query_text=query_summary)
                        result['response'] += f"\n\n✅ 已找到 **{len(matched)}** 个{item_name}，已高亮显示在左侧列表"
                    else:
                        result['response'] += f"\n\n❌ 未找到匹配的{item_name}"
                
                if self.ai_assistant._history and self.ai_assistant._history[-1].role == 'assistant':
                    self.ai_assistant._history[-1].content = result['response']
                self._ai_update_chat_display()
                self.ai_action_buttons.show()
                
                if not result.get('success', True):
                    self._append_ai_system_msg(f"处理出错：{result.get('error', '未知错误')}")
            else:
                WRITE_ACTIONS = {'reorganize', 'add_remark', 'delete', 'add'}
                BATCH_ADD_ACTIONS = {'batch_add_account', 'batch_add_url'}
                if action in BATCH_ADD_ACTIONS:
                    # 批量导入预览
                    vault_type = 'accounts' if action == 'batch_add_account' else 'urls'
                    context = self._all_accounts_cache if vault_type == 'accounts' else self._all_urls_cache
                    preview = self.ai_assistant.build_action_preview(action, params, context, vault_type)
                    batch_items = []
                    for item in preview.get('preview_items', []):
                        if item.get('type') == 'batch_add' and 'batch_item' in item:
                            batch_items.append(item['batch_item'])
                    if batch_items:
                        self.ai_action_buttons.hide()
                        # 更新历史显示建议文本
                        if self.ai_assistant._history and self.ai_assistant._history[-1].role == 'assistant':
                            self.ai_assistant._history[-1].content = result['response']
                        self._ai_update_chat_display()
                        self._show_batch_add_dialog(batch_items, vault_type, query, preview)
                    else:
                        result['response'] += "\n\n❌ 没有可导入的数据"
                        if self.ai_assistant._history and self.ai_assistant._history[-1].role == 'assistant':
                            self.ai_assistant._history[-1].content = result['response']
                        self._ai_update_chat_display()
                        self.ai_action_buttons.show()
                elif action in WRITE_ACTIONS:
                    # 统一生成预览（确保预览与执行数据一致）
                    logger.info(f" Showing ActionPreviewWidget for action={action}")
                    self.ai_action_buttons.hide()
                    preview = self.ai_assistant.build_action_preview(action, params, context_items, vault_type)
                    self.action_preview_widget.update_action(action, params, preview.get('preview_items', []))
                    self.action_preview_widget.show()
                    self._pending_action = (action, params, query)
                    
                    # 更新历史显示建议文本（但不追加执行结果，等待用户确认）
                    if self.ai_assistant._history and self.ai_assistant._history[-1].role == 'assistant':
                        self.ai_assistant._history[-1].content = result['response']
                    self._ai_update_chat_display()
                else:
                    # 未知的非安全操作，直接显示结果
                    if self.ai_assistant._history and self.ai_assistant._history[-1].role == 'assistant':
                        self.ai_assistant._history[-1].content = result['response']
                    self._ai_update_chat_display()
                    self.ai_action_buttons.show()
        except Exception as e:
            logger.error(f" Build mode handling error: {e}")
            logger.exception("Unhandled exception")
            self._append_ai_system_msg(f"处理出错：{str(e)}")
    
    def show_copy_toast(self, message, is_password=False):
        if hasattr(self, '_toast_timer') and self._toast_timer:
            self._toast_timer.stop()
            self._toast_timer = None
        if hasattr(self, '_toast_label') and self._toast_label:
            self._toast_label.hide()
            self._toast_label.deleteLater()
            self._toast_label = None
        
        colors = ThemeManager.instance().colors
        bg = QColor(colors.bg_secondary)
        bg.setAlpha(200)
        self._toast_label = QLabel(message, self)
        self._toast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha() / 255.0:.2f});
                color: {colors.text_primary};
                padding: 10px 24px;
                border-radius: 12px;
                font-size: 13px;
            }}
        """)
        self._toast_label.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self._toast_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._toast_label.adjustSize()
        self._position_toast()
        self._toast_label.show()
        self._toast_label.raise_()
        
        if is_password:
            import json, os
            delay = 20
            try:
                config_path = str(CONFIG_PATH)
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    delay = config.get('clipboard_clear_delay', 20)
            except Exception:
                pass
            
            self._countdown = delay
            self._toast_label.setText(f"密码已复制（{self._countdown} 秒后清除）")
            self._toast_label.adjustSize()
            self._position_toast()
            self._toast_label.show()
            self._toast_label.raise_()
            
            self._toast_timer = QTimer(self)
            def update_toast():
                self._countdown -= 1
                if self._countdown > 0:
                    self._toast_label.setText(f"密码已复制（{self._countdown} 秒后清除）")
                    self._toast_label.adjustSize()
                    self._position_toast()
                    self._toast_label.show()
                    self._toast_label.raise_()
                else:
                    self._toast_timer.stop()
                    self._toast_timer = None
                    from PyQt6.QtWidgets import QApplication
                    clipboard = QApplication.clipboard()
                    clipboard.clear()
                    try:
                        import pyperclip
                        pyperclip.copy('')
                    except Exception:
                        pass
                    if hasattr(self, 'clipboard') and self.clipboard:
                        self.clipboard.clear()
                    self._toast_label.setText("剪贴板已清空")
                    self._toast_label.adjustSize()
                    self._position_toast()
                    self._toast_label.show()
                    self._toast_label.raise_()
                    old_label = self._toast_label
                    self._toast_label = None
                    QTimer.singleShot(3000, old_label.deleteLater)
            self._toast_timer.timeout.connect(update_toast)
            self._toast_timer.start(1000)
        else:
            old_label = self._toast_label
            self._toast_label = None
            QTimer.singleShot(2000, old_label.deleteLater)
    
    def _position_toast(self):
        if not hasattr(self, '_toast_label') or not self._toast_label:
            return
        lw = self._toast_label.width()
        lh = self._toast_label.height()
        geo = self.geometry()
        x = geo.x() + (geo.width() - lw) // 2
        y = geo.y() + geo.height() - lh - 60
        if y < geo.y():
            y = geo.y() + 10
        self._toast_label.move(x, y)
    
    def _smart_refresh(self):
        """智能刷新：保持当前视图模式，不自动回退到默认视图"""
        if self.current_category == '__dashboard__':
            if hasattr(self, 'dashboard') and self.dashboard is not None:
                self.dashboard.refresh()
            return
        self._save_scroll_state()
        try:
            self._accounts_cache_dirty = True
            self._urls_cache_dirty = True
            
            if self._view_mode == 'search':
                text = self.search_box.text().strip()
                if text:
                    self.on_search()
                else:
                    self._view_mode = 'default'
                    if self.current_vault == 'accounts':
                        self.load_accounts()
                    else:
                        self.load_urls()
            elif self._view_mode == 'ai_highlight':
                if self._highlight_matched_ids:
                    self._reapply_ai_highlight()
                else:
                    self._view_mode = 'default'
                    if self.current_vault == 'accounts':
                        self.load_accounts()
                    else:
                        self.load_urls()
            else:
                if self.current_vault == 'accounts':
                    self.load_accounts()
                else:
                    self.load_urls()
        finally:
            self._restore_scroll_state()
    
    def _reapply_ai_highlight(self):
        """重新应用当前的 AI 高亮筛选（数据变更后刷新）"""
        self._accounts_cache_dirty = True
        self._urls_cache_dirty = True
        if self.current_vault == 'accounts':
            self._all_accounts_cache = self.account_service.get_all_accounts()
            self._accounts_cache_dirty = False
        else:
            self._all_urls_cache = self._url_service.get_all_urls()
            self._urls_cache_dirty = False
        
        matched_ids = list(self._highlight_matched_ids)
        self.highlight_matched_accounts(matched_ids, query_text=self._highlight_reasoning or "AI筛选")

    def _refresh_account_list(self):
        """刷新账号列表"""
        self._accounts_cache_dirty = True
        self.load_accounts()
    
    def _append_ai_system_msg(self, content: str):
        """追加系统消息到 AI 对话历史并增量显示"""
        from services.ai_assistant_service import ConversationMessage
        from datetime import datetime
        self.ai_assistant._history.append(ConversationMessage(
            role='system', content=content,
            timestamp=datetime.now().strftime("%H:%M:%S")
        ))
        colors = ThemeManager.instance().colors
        html = (
            f'<div style="margin:8px 0;padding:6px 10px;background:{colors.bg_secondary};'
            f'border-radius:4px;color:{colors.text_tertiary};font-size:12px;">'
            f'{self._escape_html(content)}</div>'
        )
        self._ai_append_message(html)

    def _ai_start_typing(self, full_text: str):
        """设置 assistant 消息内容并增量追加初始容器，为后续增量追加做准备"""
        if self.ai_assistant._history and self.ai_assistant._history[-1].role == 'assistant':
            self.ai_assistant._history[-1].content = full_text
        colors = ThemeManager.instance().colors
        html = (
            f'<div style="margin:8px 0;">'
            f'<div style="font-weight:bold;color:{colors.text_primary};margin-bottom:4px;">🦁 炽阳</div>'
            f'<span style="color:{colors.text_primary};">{self._escape_html(full_text)}</span>'
            f'</div>'
        )
        self._ai_append_message(html)

    def _ai_append_message(self, message_html: str):
        """使用 QTextCursor 在 result_area 末尾追加 HTML 消息，不触发全量重建"""
        cursor = self.result_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(message_html)
        # 自动滚动到底部
        scrollbar = self.result_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _ai_append_token_html(self, token: str):
        """使用 QTextCursor 在 result_area 末尾增量追加 HTML token"""
        colors = ThemeManager.instance().colors
        cursor = self.result_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        escaped = self._escape_html(token).replace('\n', '<br>')
        html = f'<span style="color: {colors.text_primary};">{escaped}</span>'
        cursor.insertHtml(html)
        # 自动滚动到底部
        scrollbar = self.result_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_ai_refresh_timeout(self):
        """AI 聊天防抖定时器超时：仅在查询结束（状态切换）时执行全量重建"""
        if not getattr(self, '_ai_query_running', False):
            self._ai_update_chat_display()
    
    def _ai_update_chat_display(self):
        """根据对话历史重新渲染整个聊天区域为 HTML"""
        colors = ThemeManager.instance().colors
        try:
            history = self.ai_assistant.get_history()
        except Exception as e:
            logger.exception(f" get_history error: {e}")
            return
        
        html_parts = []
        has_interaction = any(m.role == 'user' for m in history)
        
        # 显示欢迎语（如果还没有交互）
        if not has_interaction and not getattr(self, '_ai_interacted', False):
            try:
                welcome_html = self._markdown_to_html(self._ai_welcome_md())
                html_parts.append(f'<div style="padding:10px;">{welcome_html}</div>')
            except Exception as e:
                logger.exception(f" Welcome render error: {e}")
        
        # 渲染每条消息
        for idx, msg in enumerate(history):
            try:
                if msg.role == 'user':
                    user_html = self._markdown_to_html(self._render_user_md(msg.content))
                    html_parts.append(f'<div style="margin:8px 0;">{user_html}</div>')
                elif msg.role == 'assistant':
                    assistant_md = self._render_assistant_md(msg, idx, is_last=(idx == len(history) - 1))
                    assistant_html = self._markdown_to_html(assistant_md)
                    html_parts.append(f'<div style="margin:8px 0;">{assistant_html}</div>')
                elif msg.role == 'system':
                    html_parts.append(
                        f'<div style="margin:8px 0;padding:6px 10px;background:{colors.bg_secondary};border-radius:4px;color:{colors.text_tertiary};font-size:12px;">'
                        f'{self._escape_html(msg.content)}</div>'
                    )
            except Exception as e:
                logger.exception(f" Message render error at idx={idx}: {e}")
                # 跳过这条消息，继续渲染其他
                continue
        
        # 如果正在处理（最后一条是用户消息，没有 assistant 回复），显示"思考中"
        if history and history[-1].role == 'user':
            html_parts.append(
                f'<div style="margin:8px 0;padding:10px;color:{colors.text_tertiary};font-style:italic;">'
                '🤔 炽阳正在思考...</div>'
            )
        
        full_html = '\n'.join(html_parts)
        try:
            self.result_area.setHtml(full_html)
        except Exception as e:
            logger.exception(f" setHtml error: {e}")
            # 降级：只显示纯文本
            try:
                plain_text = '\n'.join(f"{m.role}: {m.content}" for m in history)
                self.result_area.setPlainText(plain_text)
            except Exception as e2:
                logger.exception(f" setPlainText fallback error: {e2}")
        
        # 滚动到底部
        try:
            scrollbar = self.result_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception as e:
            logger.exception(f" Scrollbar error: {e}")
    
    def _escape_html(self, text: str) -> str:
        """转义 HTML 特殊字符"""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))
    
    def _ai_welcome_md(self) -> str:
        """欢迎语 Markdown（根据当前库切换内容）"""
        if self.current_vault == 'accounts':
            return (
                "🦁🔥 **密码库模式**\n\n"
                "炽阳 已觉醒\n\n"
                "你好，狮子座的主人。\n\n"
                "⚡ **首次同步**：请发送任意消息完成神经连接预热，预热完成后即可执行操作。"
            )
        else:
            return (
                "🦁🔥 **网址库模式**\n\n"
                "炽阳 已觉醒\n\n"
                "你好，狮子座的主人。\n\n"
                "⚡ **首次同步**：请发送任意消息完成神经连接预热，预热完成后即可执行操作。"
            )
    
    def _render_user_md(self, text: str) -> str:
        """渲染用户消息（Markdown）"""
        # 用户消息用引用块显示在右侧
        lines = text.strip().split('\n')
        quoted = '\n'.join(f'> {line}' for line in lines)
        return f"**用户**：\n\n{quoted}"
    
    def _render_assistant_md(self, msg, msg_index: int, is_last: bool = False) -> str:
        """渲染 AI 消息（Markdown）—— 思考过程在回答上方，可展开/折叠"""
        parts = []
        
        # 思考过程（放在回答上方，参考图3 Thinking 风格；如果和回复重复则不显示）
        if msg.thinking and msg.thinking.strip() and not self._thinking_is_redundant(msg.thinking, msg.content):
            expanded = self._ai_thinking_expanded.get(msg_index, False)
            if expanded:
                thinking_lines = msg.thinking.strip().split('\n')
                quoted = '\n'.join(f'> {line}' for line in thinking_lines)
                parts.append(f"> 💡 [思考过程 ▲](thinking://{msg_index})\n>\n{quoted}")
            else:
                parts.append(f"> 💡 [思考过程 ▼](thinking://{msg_index})")
        
        parts.append(f"**🦁 炽阳**：\n")
        parts.append(msg.content)
        
        # 最后一条消息显示回答用时
        if is_last and self._ai_last_elapsed > 0:
            parts.append(f"\n_⏱️ 用时 {self._ai_last_elapsed:.1f}s_")
        
        return '\n\n'.join(parts)
    
    def _thinking_is_redundant(self, thinking: str, response: str) -> bool:
        """Check if thinking content is redundant with the response (same information)"""
        if not thinking or not response:
            return False
        # Normalize: strip whitespace, lowercase
        t = thinking.strip().lower()
        r = response.strip().lower()
        # If thinking is entirely contained in response, it's redundant
        if t in r:
            return True
        # If response is entirely contained in thinking, it's redundant
        if r in t:
            return True
        # If more than 70% of lines overlap
        t_lines = set(line.strip() for line in thinking.strip().split('\n') if line.strip())
        r_lines = set(line.strip() for line in response.strip().split('\n') if line.strip())
        if t_lines and r_lines:
            overlap = len(t_lines & r_lines)
            if overlap / min(len(t_lines), len(r_lines)) > 0.7:
                return True
        return False
    
    def _ai_display_results_in_list(self, accounts, query_text):
        """将 炽阳 搜索结果展示在左侧账号列表中"""
        colors = ThemeManager.instance().colors
        self.account_list.clear()
        
        if not accounts:
            item = QListWidgetItem("未找到匹配的账号")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.account_list.addItem(item)
            self.lbl_list_title.setText(f"炽阳 搜索结果")
            return
        
        # 标题
        header = QListWidgetItem(f"  炽阳 推荐结果")
        header.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        header.setFont(font)
        header.setBackground(QColor(colors.accent_blue_bg))
        header.setForeground(QColor(colors.accent_blue_text))
        self.account_list.addItem(header)
        
        for account in accounts:
            item = QListWidgetItem()
            item.setSizeHint(QSize(self.account_list.width() - 20, 56))
            item.setData(Qt.ItemDataRole.UserRole, account)
            self.account_list.addItem(item)
            
            badges = [("炽阳推荐", "#1565C0")]
            widget = AccountListItem(account, badges=badges, selection_mode=self._selection_mode, parent=self.account_list)
            widget.hide()  # 防止无parent时短暂显示为独立窗口
            if self._selection_mode:
                widget.on_check_changed = lambda checked, aid=account.id: self._on_item_checkbox_changed(aid, checked)
            if self._selection_mode and account.id in self._selected_ids:
                widget.set_checked(True)
            self.account_list.setItemWidget(item, widget)
            col_config = self._load_column_config()
            for key, visible in col_config.items():
                if not visible:
                    widget.set_column_visible(key, False)
        
        self.lbl_list_title.setText(f"炽阳 搜索结果 ({len(accounts)})")
    
    def highlight_matched_accounts(self, matched_ids: list, query_text: str = ""):
        """Plan 模式：高亮左侧列表中的匹配条目（支持密码库和网址库）"""
        colors = ThemeManager.instance().colors
        if not matched_ids:
            return
        
        self._view_mode = 'ai_highlight'
        
        # 统一转为整数集合，避免 LLM 返回的字符串 ID 与 SQLite 整数 ID 类型不匹配
        self._highlight_matched_ids = {int(m) for m in matched_ids}
        
        # 禁用更新避免大量 paint/layout 事件阻塞事件循环
        self.account_list.setUpdatesEnabled(False)
        self.account_list.clear()
        
        # 根据当前 vault 选择数据源和 Widget 类型
        # 注意：高亮筛选应基于全局数据，不受当前分类缓存限制
        if self.current_vault == 'accounts':
            all_items = self.account_service.get_all_accounts()
            item_name = "账号"
            ItemWidget = AccountListItem
            use_badges = True
        else:
            all_items = self._url_service.get_all_urls()
            item_name = "网址"
            ItemWidget = URLListItem
            use_badges = False
        
        matched_items = [item for item in all_items if getattr(item, 'id', None) in self._highlight_matched_ids]
        unmatched_items = [item for item in all_items if getattr(item, 'id', None) not in self._highlight_matched_ids]
        
        # 隐藏列表标题和紧凑视图按钮（筛选信息已在横幅中显示）
        self.lbl_list_title.hide()
        self.btn_compact_view.hide()
        self.btn_column_settings.hide()
        
        # 显示匹配项（置顶，蓝色边框）
        if matched_items:
            header = QListWidgetItem(f"  匹配{item_name}")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            header.setFont(font)
            header.setBackground(QColor(colors.accent_blue_bg))
            header.setForeground(QColor(colors.accent_blue_text))
            self.account_list.addItem(header)
            
            for idx, item_obj in enumerate(matched_items):
                item = QListWidgetItem()
                w = max(self.account_list.width() - 20, 50)
                item.setSizeHint(QSize(w, 56))
                item.setData(Qt.ItemDataRole.UserRole, item_obj)
                item.setBackground(QColor(colors.accent_blue_bg))
                self.account_list.addItem(item)
                
                badges = [("匹配", "#2196F3")]
                if use_badges:
                    widget = ItemWidget(item_obj, badges=badges, selection_mode=self._selection_mode)
                else:
                    widget = ItemWidget(item_obj, badges=badges, selection_mode=self._selection_mode)
                
                if self._selection_mode and str(getattr(item_obj, 'id', None)) in {str(s) for s in self._selected_ids}:
                    if hasattr(widget, 'set_checked'):
                        widget.set_checked(True)
                # 匹配条目高亮：用容器包裹，容器设背景色
                hl_color = "#BBDEFB" if not ThemeManager.instance().is_dark else "#2A3D55"
                container = QWidget()
                container.setStyleSheet(f"background-color: {hl_color};")
                container_layout = QVBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.addWidget(widget)
                # 让原 widget 背景透明（追加而非覆盖，保留所有子控件样式）
                old_ss = widget.styleSheet()
                widget.setStyleSheet(old_ss + f"\n#accountListItem {{ background-color: transparent; border: none; }}")
                widget.setAutoFillBackground(False)
                # 分类标签背景也透明
                if hasattr(widget, 'lbl_category'):
                    widget.lbl_category.setStyleSheet(
                        f"color: {colors.text_secondary}; font-size: 11px; background-color: transparent; border-radius: 10px; padding: 2px 8px;"
                    )
                # 用容器代替原 widget 放入列表
                col_config = self._load_column_config()
                for key, visible in col_config.items():
                    if not visible:
                        widget.set_column_visible(key, False)
                self.account_list.setItemWidget(item, container)
        
        # 显示未匹配项（灰色）
        if unmatched_items:
            header = QListWidgetItem(f"  其他{item_name}")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            header.setFont(font)
            header.setBackground(QColor(colors.bg_secondary))
            header.setForeground(QColor(colors.text_tertiary))
            self.account_list.addItem(header)
            
            for idx, item_obj in enumerate(unmatched_items):
                item = QListWidgetItem()
                w = max(self.account_list.width() - 20, 50)
                item.setSizeHint(QSize(w, 56))
                item.setData(Qt.ItemDataRole.UserRole, item_obj)
                item.setForeground(QColor(colors.text_disabled))
                self.account_list.addItem(item)
                
                widget = ItemWidget(item_obj, selection_mode=self._selection_mode)
                
                if self._selection_mode and str(getattr(item_obj, 'id', None)) in {str(s) for s in self._selected_ids}:
                    if hasattr(widget, 'set_checked'):
                        widget.set_checked(True)
                # 降低可见度
                if hasattr(widget, 'styleSheet'):
                    widget.setStyleSheet(widget.styleSheet() + f"QLabel {{ color: {colors.text_disabled}; }}")
                col_config = self._load_column_config()
                for key, visible in col_config.items():
                    if not visible:
                        widget.set_column_visible(key, False)
                self.account_list.setItemWidget(item, widget)
        
        # 横幅显示用户原始查询和匹配数量
        if query_text == "AI本次修改":
            banner_text = f"🔥 炽阳本次已修改 {len(matched_items)} 个{item_name}"
        else:
            banner_text = f"🔍 炽阳已找到 {len(matched_items)} 个与「{query_text}」相关的{item_name}"
        self.lbl_ai_filter.setText(banner_text)
        self.ai_filter_banner.show()
        
        # 恢复更新，一次性重绘
        self.account_list.setUpdatesEnabled(True)
        self.account_list.viewport().update()
    
    def clear_account_highlight(self):
        """清除左侧列表的高亮筛选"""
        self._highlight_matched_ids = None
        self._highlight_reasoning = ""
        self._view_mode = 'default'
        if hasattr(self, 'ai_filter_banner'):
            self.ai_filter_banner.hide()
        # 恢复列表标题和紧凑视图按钮显示
        self.lbl_list_title.show()
        self.btn_compact_view.show()
        self.btn_column_settings.show()
        if self.current_vault == 'accounts':
            self.load_accounts()
        else:
            self.load_urls()
    
    def _markdown_to_html(self, text: str) -> str:
        """将 Markdown 转为 HTML（安全可控，避免 Qt setMarkdown 崩溃）"""
        colors = ThemeManager.instance().colors
        import re
        
        # 安全清理：移除 NULL 字节和控制字符（这些可能导致 Qt 解析器崩溃）
        text = text.replace('\x00', '')
        text = ''.join(ch if ord(ch) >= 32 or ch in '\n\r\t' else ' ' for ch in text)
        
        # 先转义 HTML 特殊字符
        text = (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
        
        # 代码块 ```code```
        def code_block_repl(m):
            colors = ThemeManager.instance().colors
            code = m.group(1)
            return f'<pre style="background:{colors.bg_secondary};padding:8px;border-radius:4px;overflow-x:auto;font-size:12px;"><code>{code}</code></pre>'
        text = re.sub(r'```(.*?)```', code_block_repl, text, flags=re.DOTALL)
        
        # 行内代码 `code`
        text = re.sub(r'`([^`]+)`', rf'<code style="background:{colors.bg_secondary};padding:2px 4px;border-radius:3px;font-size:12px;">\1</code>', text)
        
        # 加粗 **text**
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        
        # 斜体 *text*（避免匹配已处理的 **）
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
        
        # 标题
        text = re.sub(r'^###\s+(.+)$', rf'<h4 style="margin:6px 0;color:{colors.text_primary};">\1</h4>', text, flags=re.MULTILINE)
        text = re.sub(r'^##\s+(.+)$', rf'<h3 style="margin:8px 0;color:{colors.text_primary};">\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^#\s+(.+)$', rf'<h2 style="margin:10px 0;color:{colors.text_primary};">\1</h2>', text, flags=re.MULTILINE)
        
        # 分隔线 ---
        text = re.sub(r'^---+\s*$', rf'<hr style="border:none;border-top:1px solid {colors.border_default};margin:8px 0;">', text, flags=re.MULTILINE)
        
        # 链接 [text](url)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', rf'<a href="\2" style="color:{colors.accent_orange};text-decoration:none;">\1</a>', text)
        
        # 列表项 - item
        def list_repl(m):
            items = m.group(0).strip().split('\n')
            lis = ''.join(f'<li style="margin:3px 0;">{item.lstrip("- ").strip()}</li>' for item in items)
            return f'<ul style="margin:6px 0;padding-left:18px;">{lis}</ul>'
        text = re.sub(r'(?:^-\s+.+\n?)+', list_repl, text, flags=re.MULTILINE)
        
        # 引用块 > text
        def quote_repl(m):
            colors = ThemeManager.instance().colors
            lines = m.group(0).strip().split('\n')
            content = '<br>'.join(line.lstrip('> ').strip() for line in lines)
            return f'<blockquote style="margin:6px 0;padding:6px 10px;border-left:3px solid {colors.accent_orange};color:{colors.text_secondary};background:{colors.ai_thinking_bg};border-radius:0 4px 4px 0;">{content}</blockquote>'
        text = re.sub(r'(?:^>\s*.+\n?)+', quote_repl, text, flags=re.MULTILINE)
        
        # 段落处理：保留换行
        paragraphs = text.split('\n\n')
        result = []
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            # 如果已经是块级元素，不加 p 包裹
            if p.startswith('<') and any(tag in p for tag in ['<pre', '<ul', '<blockquote', '<h', '<hr']):
                result.append(p)
            else:
                p = p.replace('\n', '<br>')
                result.append(f'<p style="margin:4px 0;">{p}</p>')
        
        return '\n'.join(result)
    
    def _on_ai_anchor_clicked(self, url):
        """处理聊天区域内的链接点击（思考过程展开/折叠）"""
        url_str = url.toString()
        if url_str.startswith("thinking://"):
            try:
                idx = int(url_str.split("://")[-1])
                current = self._ai_thinking_expanded.get(idx, False)
                self._ai_thinking_expanded[idx] = not current
                self._ai_update_chat_display()
            except ValueError:
                pass
    
    def _on_ai_confirm_dialog_finished(self, result_code: int, action: str, params: dict, desc: str):
        """确认对话框关闭后的回调（非模态，避免 exec() 崩溃）"""
        if result_code == int(QMessageBox.StandardButton.Yes):
            # 执行操作
            action_result = self.ai_assistant.execute_action(action, params, self._all_accounts_cache)
            result_msg = action_result.get('message', '✅ 已执行操作。')
            
            # 刷新列表（如果操作影响了数据）
            self._refresh_account_list()
        else:
            result_msg = "❌ 操作已取消。"
        
        # 追加结果消息到历史，并更新显示
        from services.ai_assistant_service import ConversationMessage
        from datetime import datetime
        self.ai_assistant._history.append(ConversationMessage(
            role='assistant', content=result_msg,
            timestamp=datetime.now().strftime("%H:%M:%S")
        ))
        self._ai_start_typing(result_msg)
    
    def on_ai_clear_history(self):
        """清空 AI 对话历史"""
        self.ai_assistant.clear_history()
        self.ai_assistant.conversation_context.reset()
        self._ai_thinking_expanded.clear()
        self._ai_interacted = False
        self._ai_update_chat_display()
    
    def on_ai_show_help(self):
        """显示 炽阳 使用说明对话框"""
        dialog = LocalHelpDialog(self)
        dialog.exec()
    
    def _setup_session_security(self):
        """设置会话安全：锁定界面 + 空闲检测"""
        # 创建锁定屏幕（作为中央部件的子控件，全屏覆盖）
        self._lock_screen = LockScreen(self.db, self.config_path, parent=self.centralWidget())
        self._lock_screen.unlocked.connect(self._on_unlocked)
        self._lock_screen.hide()
        
        # 创建空闲检测定时器（10分钟 = 600000ms）
        self._idle_timer = IdleTimer(timeout_ms=600000, parent=self)
        self._idle_timer.lock_requested.connect(self.show_lock_screen)
        self._idle_timer.start()
        
        # 安装事件过滤器到整个应用，捕获鼠标/键盘操作
        QApplication.instance().installEventFilter(self)
    
    def eventFilter(self, watched, event):
        """事件过滤器：检测用户活动，重置空闲定时器；更新搜索历史"""
        event_type = event.type()

        # 搜索框焦点处理：更新补全历史；点击时显示历史面板
        if watched == self.search_box:
            if event_type == event.Type.FocusIn:
                history = self.search_service.get_search_history()
                self._search_model.setStringList(history)
            elif event_type == event.Type.MouseButtonPress:
                # 点击搜索框时显示历史面板（避免启动时自动弹出）
                if not self.search_box.text().strip():
                    history = self.search_service.get_search_history()
                    if history:
                        self._show_search_history_panel()
            elif event_type == event.Type.FocusOut:
                # 延迟隐藏，给面板内按钮点击留出时间
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(200, self._hide_search_history_panel)

        # Popup 窗口会自动在点击外部时关闭，无需额外处理

        # 检测用户活动，重置空闲定时器
        if self._idle_timer and self._lock_screen and not self._lock_screen.isVisible():
            if event_type in (
                event.Type.MouseButtonPress,
                event.Type.MouseButtonRelease,
                event.Type.MouseMove,
                event.Type.KeyPress,
                event.Type.KeyRelease,
                event.Type.Wheel,
            ):
                self._idle_timer.reset()
        
        return super().eventFilter(watched, event)
    
    def _on_drag_select_move(self, pos):
        """拖动选择：根据鼠标位置切换条目选中状态"""
        item = self.account_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        item_id = getattr(data, 'id', None) or (data.get('id') if isinstance(data, dict) else None)
        if item_id is None or item_id in self._drag_checked_ids:
            return
        self._drag_checked_ids.add(item_id)
        
        widget = self.account_list.itemWidget(item)
        if widget and hasattr(widget, 'set_checked') and hasattr(widget, 'is_checked'):
            # 切换选中状态
            if widget.is_checked():
                widget.set_checked(False)
                self._selected_ids.discard(item_id)
            else:
                widget.set_checked(True)
                self._selected_ids.add(item_id)
            self._update_bottom_bar_for_selection()
    
    def show_lock_screen(self):
        """显示锁定屏幕"""
        if not self._lock_screen:
            return
        # 重置错误计数
        self._lock_screen.reset_lockout()
        # 调整大小覆盖整个中央部件
        self._lock_screen.setGeometry(self.centralWidget().rect())
        self._lock_screen.show()
        self._lock_screen.raise_()
    
    def _on_unlocked(self):
        """解锁后的回调：刷新会话版本、重置空闲定时器"""
        self._session_version = self.db.get_session_version()
        if self._idle_timer:
            self._idle_timer.reset()
    
    def on_lock(self):
        """手动锁定程序"""
        reply = QMessageBox.question(
            self, "锁定", "确定要锁定程序吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.show_lock_screen()
    
    def _verify_session(self) -> bool:
        """验证当前会话是否仍然有效（密码未被修改）"""
        current = self.db.get_session_version()
        if current != self._session_version:
            QMessageBox.warning(self, "会话过期",
                "密码已被修改，请重新登录以继续操作",
                QMessageBox.StandardButton.Ok)
            self.show_lock_screen()
            return False
        return True
    
    def _on_sync_button_context_menu(self, pos):
        """同步到手机按钮的右键菜单"""
        menu = QMenu(self)
        action_set_name = menu.addAction("✏️ 修改默认文件名")
        action = menu.exec(self.btn_sync.mapToGlobal(pos))
        if action == action_set_name:
            self._on_set_sync_default_filename()
    
    def _load_sync_default_filename(self) -> str:
        """读取同步到手机的默认文件名配置"""
        from core.constants import EXPORT_CONFIG_PATH
        try:
            if EXPORT_CONFIG_PATH.exists():
                with open(EXPORT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                return config.get('sync_default_filename', 'leopassword.html')
        except Exception:
            pass
        return 'leopassword.html'
    
    def _on_set_sync_default_filename(self):
        """修改同步到手机的默认文件名"""
        from core.constants import EXPORT_CONFIG_PATH
        current_name = self._load_sync_default_filename()
        new_name, ok = QInputDialog.getText(
            self, "修改默认文件名",
            "请输入同步到手机的默认文件名（含扩展名）：",
            text=current_name
        )
        if ok and new_name.strip():
            new_name = new_name.strip()
            try:
                config = {}
                if EXPORT_CONFIG_PATH.exists():
                    with open(EXPORT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                config['sync_default_filename'] = new_name
                with open(EXPORT_CONFIG_PATH, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "保存成功", f"默认文件名已修改为：{new_name}")
            except Exception as e:
                QMessageBox.warning(self, "保存失败", f"配置保存失败：{str(e)}")

    def on_sync_to_mobile(self):
        """同步到手机：生成加密 HTML 密包（同时导出密码库 + 网址库）"""
        try:
            # 检查是否有 crypto_manager
            if not self.db.crypto:
                QMessageBox.warning(self, "提示", "当前未启用加密，无法生成密包")
                return
            
            # 获取所有账号和网址（解密后的明文）
            accounts = self.account_service.get_all_accounts()
            urls = self._url_service.get_all_urls()
            
            total_count = len(accounts) + len(urls)
            if total_count == 0:
                reply = QMessageBox.question(
                    self, "提示",
                    "当前没有账号和网址数据，是否仍要生成空密包？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            # 弹出保存对话框
            default_name = self._load_sync_default_filename()
            from PyQt6.QtWidgets import QFileDialog
            output_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存密包文件",
                str(Path.home() / default_name),
                "HTML 文件 (*.html)"
            )
            if not output_path:
                return
            
            # 获取分类自定义排序
            account_category_orders = self.db.get_category_orders() if hasattr(self.db, 'get_category_orders') else {}
            url_category_orders = self._url_db.get_category_orders() if hasattr(self._url_db, 'get_category_orders') else {}
            
            # 生成密包
            from services.sync_service import SyncService
            sync_service = SyncService()
            sync_service.generate_pwa_package(
                self.db.crypto,
                accounts,
                urls,
                output_path,
                account_category_orders=account_category_orders,
                url_category_orders=url_category_orders
            )
            
            # 成功提示
            QMessageBox.information(
                self,
                "生成成功",
                f"密包已保存至：\n{output_path}\n\n"
                f"包含 {len(accounts)} 条账号数据 + {len(urls)} 条网址数据\n\n"
                f"📱 请手动将该 HTML 文件复制到手机，用手机浏览器打开即可查看。\n"
                f"打开后输入主密码即可本地解密。"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "生成失败", f"密包生成失败：{str(e)}")
            import traceback
            logger.exception("Unhandled exception")
    
    def _on_dashboard_action(self, action, data):
        """处理仪表盘的交互操作"""
        if action == 'strength':
            self.list_stack.setCurrentIndex(0)
            self.alpha_nav.show()
            self.current_category = '全部'
            self._accounts_cache_dirty = True
            self.load_accounts()
            if data in ('弱', '中', '强', '极强'):
                from core.password_strength import evaluate_password_strength
                matched = []
                for acc in self._all_accounts_cache:
                    try:
                        r = evaluate_password_strength(acc.password or '')
                        if r['label'] == data:
                            matched.append(acc.id)
                    except Exception:
                        pass
                if matched:
                    self.highlight_matched_accounts(matched, query_text=f"密码强度:{data}")
        elif action == 'edit':
            if self.current_vault == 'accounts':
                self.show_account_detail(data)
            else:
                self.show_url_detail(data)
        elif action == 'show_recent':
            self.list_stack.setCurrentIndex(0)
            self.alpha_nav.show()
            items = data.get('items', [])
            if items:
                self.current_category = '全部'
                self._accounts_cache_dirty = True
                self.load_accounts()
                ids = [acc.id for acc in items if hasattr(acc, 'id')]
                if ids:
                    self.highlight_matched_accounts(ids, query_text="本周新增")
        elif action == 'add':
            self.on_add_item()
            if self.current_category == '__dashboard__':
                self.dashboard.refresh()
        elif action == 'import':
            self.on_batch_import()
    
    def on_health_check(self):
        """打开密码健康检查对话框"""
        if not self._verify_session():
            return
        if not self.db.crypto:
            QMessageBox.warning(self, "提示", "当前未启用加密，无法进行密码健康检查")
            return

        dialog = HealthCheckDialog(
            self.account_service,
            self.db.crypto,
            ai_assistant=self.ai_assistant,
            parent=self
        )
        dialog.exec()
    
    def on_recycle_bin(self):
        """打开回收站（根据当前 tab 显示对应库的回收站）"""
        from ui.recycle_bin_dialog import RecycleBinDialog
        
        self._save_scroll_state()
        
        if self.current_vault == 'accounts':
            dialog = RecycleBinDialog(self.db, vault_type='accounts', parent=self)
        else:
            dialog = RecycleBinDialog(self._url_db, vault_type='urls', parent=self)
        dialog.exec()
        # 恢复后刷新
        self._accounts_cache_dirty = True
        self._urls_cache_dirty = True
        self._reload_categories()
        if self.current_vault == 'accounts':
            self.load_accounts()
        else:
            self.load_urls()
        self._restore_scroll_state()
    
    def closeEvent(self, event):
        """程序关闭时清理资源，并自动备份数据库"""
        self._auto_backup()

        if hasattr(self, '_ai_manager'):
            try:
                self._ai_manager.state_changed.disconnect(self._on_ai_state_changed)
            except Exception:
                pass
        if hasattr(self, '_context_expiry_timer') and self._context_expiry_timer is not None:
            self._context_expiry_timer.stop()
        if hasattr(self, '_idle_timer') and self._idle_timer:
            self._idle_timer.stop()
        if hasattr(self, '_url_db') and self._url_db:
            self._url_db.close()
        super().closeEvent(event)

    def _auto_backup(self):
        """自动备份数据库文件"""
        import shutil
        from datetime import datetime

        backup_dir = str(BACKUP_DIR)
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        vault_path = str(VAULT_DB_PATH)
        if os.path.exists(vault_path):
            backup_path = os.path.join(backup_dir, f'vault_backup_{timestamp}.db')
            shutil.copy2(vault_path, backup_path)

        urls_path = str(VAULT_URLS_DB_PATH)
        if os.path.exists(urls_path):
            backup_path = os.path.join(backup_dir, f'urls_backup_{timestamp}.db')
            shutil.copy2(urls_path, backup_path)

        self._cleanup_old_backups(backup_dir, 'vault_backup_', 5)
        self._cleanup_old_backups(backup_dir, 'urls_backup_', 5)

    def _cleanup_old_backups(self, backup_dir, prefix, keep_count):
        """保留最近 N 份备份，删除更旧的"""
        import glob
        pattern = os.path.join(backup_dir, f'{prefix}*.db')
        files = sorted(glob.glob(pattern))
        while len(files) > keep_count:
            os.remove(files[0])
            files.pop(0)


class LocalHelpDialog(QDialog):
    """炽阳 使用说明对话框（模块级类，避免每次调用重复定义）"""

    def __init__(self, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self.setWindowIcon(IconManager.app_icon())
        self.setWindowTitle("炽阳 使用说明")
        self.setMinimumSize(540, 620)
        self.resize(580, 700)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QWidget()
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(32, 24, 32, 16)
        h_layout.setSpacing(4)
        lbl_title = QLabel("炽阳")
        lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 22px; font-weight: 600;")
        h_layout.addWidget(lbl_title)
        lbl_sub = QLabel("你的本地密码库 AI 助手")
        lbl_sub.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 14px;")
        h_layout.addWidget(lbl_sub)
        main_layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {colors.border_light};")
        main_layout.addWidget(sep)

        from PyQt6.QtWidgets import QScrollArea
        from PyQt6.QtCore import Qt
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(32, 20, 32, 12)
        c_layout.setSpacing(0)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        intro = QLabel("基于 Ollama + gemma4:4b 本地运行，数据不会上传云端。\n"
                       "支持 Plan（只读查询）与 Build（确认后执行）两种模式。")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.7; padding-bottom: 24px;")
        c_layout.addWidget(intro)

        # Plan
        plan_header = QHBoxLayout()
        plan_header.setSpacing(10)
        plan_badge = QLabel("Plan")
        plan_badge.setStyleSheet(f"color: {colors.accent_blue}; background-color: {colors.accent_blue_bg_light}; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;")
        plan_name = QLabel("规划模式")
        plan_name.setStyleSheet(f"color: {colors.text_primary}; font-size: 17px; font-weight: 600;")
        plan_header.addWidget(plan_badge)
        plan_header.addWidget(plan_name)
        plan_header.addStretch()
        c_layout.addLayout(plan_header)

        desc_plan = QLabel("仅查询和分析现有数据，不会修改、添加或删除任何内容。")
        desc_plan.setWordWrap(True)
        desc_plan.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-top: 4px; padding-bottom: 18px;")
        c_layout.addWidget(desc_plan)

        features_plan = [
            ("语义搜索", "用自然语言描述你想找的内容，炽阳会理解意图并返回相关结果。",
             ["帮我找一下跟学习有关的账号", "有哪些支付类的网站"]),
            ("条件筛选", "按分类、标签等条件精确筛选条目。",
             ["列出分类是工作>开发工具的所有账号", "筛选标签包含「支付」的网址"]),
            ("分类与统计", "查看当前库的分类结构、统计信息和最近变更记录。",
             ["看一下我有哪些分类", "统计一下密码库里有多少条数据", "最近修改了哪些账号"]),
            ("密码强度检测", "分析密码强度等级，仅做检测不保存。",
             ["检测一下这个密码强不强：MyP@ssw0rd"]),
        ]
        for title, desc, examples in features_plan:
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500; padding-bottom: 4px; padding-top: 2px;")
            c_layout.addWidget(lbl_title)
            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-bottom: 8px;")
            c_layout.addWidget(lbl_desc)
            card = QWidget()
            card.setObjectName("helpCard")
            card.setStyleSheet(f"""
                #helpCard {{
                    background-color: {colors.bg_primary};
                    border-radius: 10px;
                    border: 1px solid {colors.border_subtle};
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(6)
            for ex in examples:
                ex_lbl = QLabel(f'"{ex}"')
                ex_lbl.setWordWrap(True)
                ex_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.7;")
                card_layout.addWidget(ex_lbl)
            c_layout.addWidget(card)
            c_layout.addSpacing(18)

        c_layout.addSpacing(24)
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div)
        c_layout.addSpacing(24)

        # Build
        build_header = QHBoxLayout()
        build_header.setSpacing(10)
        build_badge = QLabel("Build")
        build_badge.setStyleSheet(f"color: {colors.accent_orange_text}; background-color: {colors.accent_orange_bg}; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;")
        build_name = QLabel("构建模式")
        build_name.setStyleSheet(f"color: {colors.text_primary}; font-size: 17px; font-weight: 600;")
        build_header.addWidget(build_badge)
        build_header.addWidget(build_name)
        build_header.addStretch()
        c_layout.addLayout(build_header)

        desc_build = QLabel("执行增删改操作前会展示预览，经你确认后才会生效。")
        desc_build.setWordWrap(True)
        desc_build.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-top: 4px; padding-bottom: 18px;")
        c_layout.addWidget(desc_build)

        features_build = [
            ("批量新增", "一次性添加多条账号或网址。",
             ["批量添加：B站 username1 pass1，知乎 username2 pass2"]),
            ("批量更新与重组", "批量修改分类、标签、备注，或由 AI 智能调整分类结构。",
             ["把金融类的账号都改成金融与支付", "帮我把未分类的网址整理一下", "给刚才找到的账号都加上「重要」标签"]),
            ("AI 生成备注并应用", "为指定条目生成备注，预览确认后写入数据库。",
             ["给 GitHub 生成一条备注并加上", "帮刚才找到的账号都生成备注"]),
            ("智能整理", "AI 自动分析数据并建议分类方案，支持细分二级子类。",
             ["帮我把教育类的账号细分一下二级分类", "整理一下重复的网址"]),
            ("批量操作", "将条目移入回收站、批量修改分类或标签，超过 50 条时额外二次确认。",
             ["删除所有分类是测试的账号", "把刚才筛选出来的网址删掉"]),
            ("生成强密码", "生成随机高强度密码，可指定长度和字符类型。",
             ["生成一个 16 位的强密码", "帮我生成不含特殊字符的 12 位密码"]),
        ]
        for title, desc, examples in features_build:
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500; padding-bottom: 4px; padding-top: 2px;")
            c_layout.addWidget(lbl_title)
            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-bottom: 8px;")
            c_layout.addWidget(lbl_desc)
            card = QWidget()
            card.setObjectName("helpCard")
            card.setStyleSheet(f"""
                #helpCard {{
                    background-color: {colors.bg_primary};
                    border-radius: 10px;
                    border: 1px solid {colors.border_subtle};
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(6)
            for ex in examples:
                ex_lbl = QLabel(f'"{ex}"')
                ex_lbl.setWordWrap(True)
                ex_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.7;")
                card_layout.addWidget(ex_lbl)
            c_layout.addWidget(card)
            c_layout.addSpacing(18)

        c_layout.addSpacing(24)
        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div2)
        c_layout.addSpacing(20)

        # 小贴士
        tips_card = QWidget()
        tips_card.setObjectName("helpTipsCard")
        tips_card.setStyleSheet(f"""
            #helpTipsCard {{
                background-color: {colors.bg_primary};
                border-radius: 12px;
                border: 1px solid {colors.border_subtle};
            }}
        """)
        tips_layout = QVBoxLayout(tips_card)
        tips_layout.setContentsMargins(18, 16, 18, 16)
        tips_layout.setSpacing(10)
        tips_title = QLabel("使用小贴士")
        tips_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500;")
        tips_layout.addWidget(tips_title)
        tips = [
            "首次使用请发送任意消息完成「神经连接预热」。",
            "支持上下文对话，可用「刚才找到的」「前面那些」指代历史结果。",
            "Build 模式下所有操作先展示预览表格，可勾选后再确认执行。",
            "不确定操作是否安全时，先切到 Plan 模式询问。",
        ]
        for tip in tips:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("\u2022")
            dot.setStyleSheet(f"color: {colors.text_disabled}; font-size: 14px;")
            dot.setAlignment(Qt.AlignmentFlag.AlignTop)
            txt = QLabel(tip)
            txt.setWordWrap(True)
            txt.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.6;")
            row.addWidget(dot)
            row.addWidget(txt, 1)
            tips_layout.addLayout(row)
        c_layout.addWidget(tips_card)

        c_layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        footer = QWidget()
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(32, 8, 32, 18)
        f_layout.addStretch()
        btn = QPushButton("完成")
        btn.setFixedSize(120, 34)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_orange_dark}; color: {colors.text_on_accent}; border: none;
                border-radius: 17px; font-size: 14px; font-weight: 500;
            }}
            QPushButton:hover {{ background-color: {colors.accent_orange_dark}; }}
            QPushButton:pressed {{ background-color: {colors.accent_orange_dark}; }}
        """)
        btn.clicked.connect(self.accept)
        f_layout.addWidget(btn)
        f_layout.addStretch()
        main_layout.addWidget(footer)
