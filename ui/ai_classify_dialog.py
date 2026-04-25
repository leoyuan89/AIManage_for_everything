"""
AI分类确认对话框
显示AI生成的类别提议，支持用户确认、重命名、合并
"""
from typing import List, Optional
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QCheckBox,
    QMessageBox, QScrollArea, QFrame, QProgressBar,
    QTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QGroupBox,
    QComboBox, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from services.ai_classification_service import (
    AIClassificationService, CategoryProposal, ClassificationChange
)
from models.account import Account
from models.url_item import URLItem


class PreAnalysisWorker(QThread):
    """预分析后台线程"""
    finished = pyqtSignal(list)   # 返回 CategoryProposal 列表
    error = pyqtSignal(str)       # 错误信息
    
    def __init__(self, service, items, existing_categories, item_type):
        super().__init__()
        self.service = service
        self.items = items
        self.existing_categories = existing_categories
        self.item_type = item_type
    
    def run(self):
        try:
            if self.item_type == 'account':
                proposals = self.service.pre_analyze_accounts(
                    self.items, self.existing_categories
                )
            else:
                proposals = self.service.pre_analyze_urls(
                    self.items, self.existing_categories
                )
            self.finished.emit(proposals)
        except Exception as e:
            self.error.emit(str(e))


class ClassificationWorker(QThread):
    """分类执行工作线程"""
    progress = pyqtSignal(int, int)  # 当前进度, 总数
    finished = pyqtSignal(list)      # 变更列表
    error = pyqtSignal(str)          # 错误信息
    
    def __init__(self, service: AIClassificationService, items: List,
                 categories: List[str], item_type: str):
        super().__init__()
        self.service = service
        self.items = items
        self.categories = categories
        self.item_type = item_type
        self._is_running = True
    
    def run(self):
        try:
            def on_progress(current, total):
                if self._is_running:
                    self.progress.emit(current, total)
            
            changes = self.service.execute_classification(
                self.items, self.categories, self.item_type, on_progress
            )
            
            if self._is_running:
                self.finished.emit(changes)
        except Exception as e:
            if self._is_running:
                self.error.emit(str(e))
    
    def stop(self):
        self._is_running = False


class SnapshotSelectionDialog(QDialog):
    """快照选择对话框"""
    
    def __init__(self, snapshots: List, parent=None):
        super().__init__(parent)
        self.snapshots = snapshots
        self.selected_snapshot_id = None
        self.setup_ui()
    
    def setup_ui(self):
        self.setWindowTitle("选择要回滚的快照")
        self.setMinimumSize(450, 350)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        lbl = QLabel("请选择要回滚的快照：")
        lbl.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        layout.addWidget(lbl)
        
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        for snapshot in self.snapshots:
            created_at = snapshot.created_at if hasattr(snapshot, 'created_at') else snapshot.get('created_at', '')
            change_count = len(snapshot.changes) if hasattr(snapshot, 'changes') else len(snapshot.get('changes', []))
            item_text = f"{created_at} — {change_count} 条变更"
            self.list_widget.addItem(item_text)
        
        if self.snapshots:
            self.list_widget.setCurrentRow(0)
        
        layout.addWidget(self.list_widget)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_ok = QPushButton("回滚")
        btn_ok.setFixedHeight(36)
        btn_ok.setFixedWidth(100)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        btn_ok.clicked.connect(self.on_ok)
        btn_layout.addWidget(btn_ok)
        
        layout.addLayout(btn_layout)
    
    def on_ok(self):
        idx = self.list_widget.currentRow()
        if 0 <= idx < len(self.snapshots):
            snapshot = self.snapshots[idx]
            self.selected_snapshot_id = snapshot.snapshot_id if hasattr(snapshot, 'snapshot_id') else snapshot.get('snapshot_id')
            self.accept()
        else:
            QMessageBox.warning(self, "提示", "请选择一个快照")


class MigrationGroupWidget(QGroupBox):
    """迁移分组控件"""
    
    def __init__(self, category: str, changes: List[ClassificationChange],
                 all_categories: List[str], is_pending_group: bool = False, parent=None):
        super().__init__(parent)
        self.category = category
        self.changes = changes
        self.all_categories = all_categories
        self.is_pending_group = is_pending_group
        self.setup_ui()
    
    def setup_ui(self):
        if self.is_pending_group:
            self.setTitle(f"📋 待整理 ({len(self.changes)}条)")
            self.setStyleSheet("""
                QGroupBox {
                    border: 2px solid #FF9800;
                    border-radius: 8px;
                    margin-top: 10px;
                    font-weight: bold;
                    color: #E65100;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                }
            """)
        else:
            self.setTitle(f"{self.category} ({len(self.changes)}条)")
            self.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    margin-top: 10px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                }
            """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 20, 15, 15)
        
        # 顶部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_accept = QPushButton("采纳本组")
        btn_accept.setFixedHeight(28)
        btn_accept.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        btn_accept.clicked.connect(self.on_accept_group)
        btn_layout.addWidget(btn_accept)
        
        btn_revert = QPushButton("撤销本组")
        btn_revert.setFixedHeight(28)
        btn_revert.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        btn_revert.clicked.connect(self.on_revert_group)
        btn_layout.addWidget(btn_revert)
        
        layout.addLayout(btn_layout)
        
        # 条目列表
        self.rows = []
        for change in self.changes:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(5, 4, 5, 4)
            row_layout.setSpacing(10)
            
            # 名称
            lbl_name = QLabel(change.item_name)
            lbl_name.setFixedWidth(150)
            lbl_name.setToolTip(change.item_name)
            row_layout.addWidget(lbl_name)
            
            # 原分类
            lbl_old = QLabel(f"→ {change.old_category}")
            lbl_old.setStyleSheet("color: #666;")
            row_layout.addWidget(lbl_old)
            
            # 新分类（可编辑下拉框）
            cmb_new = QComboBox()
            cmb_new.addItems(self.all_categories)
            cmb_new.setCurrentText(change.new_category)
            cmb_new.setProperty("change", change)
            cmb_new.currentTextChanged.connect(self.on_category_changed)
            row_layout.addWidget(cmb_new)
            
            # 置信度
            conf_text = f"{change.confidence:.0%}"
            lbl_conf = QLabel(conf_text)
            if change.is_low_confidence:
                lbl_conf.setText(conf_text + " (低)")
                lbl_conf.setStyleSheet("color: #FF9800;")
            row_layout.addWidget(lbl_conf)
            
            row_layout.addStretch()
            layout.addWidget(row_widget)
            self.rows.append((change, cmb_new))
    
    def on_accept_group(self):
        """采纳本组所有变更"""
        for change, cmb in self.rows:
            change.user_override = False
            change.is_pending = False
        QMessageBox.information(self, "提示", f"已采纳 [{self.category}] 的全部变更")
    
    def on_revert_group(self):
        """撤销本组所有变更"""
        for change, cmb in self.rows:
            change.new_category = change.old_category
            change.user_override = True
            change.is_pending = False
            cmb.setCurrentText(change.old_category)
        QMessageBox.information(self, "提示", f"已撤销 [{self.category}] 的全部变更")
    
    def on_category_changed(self, text):
        """单条类别变更"""
        cmb = self.sender()
        change = cmb.property("change")
        if change:
            change.new_category = text
            change.user_override = True
            change.is_pending = (text == "待整理")


class CategoryProposalCard(QFrame):
    """类别提议卡片"""
    
    def __init__(self, proposal: CategoryProposal, existing_categories: List[str] = None, parent=None):
        super().__init__(parent)
        self.proposal = proposal
        self.existing_categories = existing_categories or []
        self.is_selected = True
        self.setup_ui()
    
    def setup_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            CategoryProposalCard {
                background-color: white;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                padding: 10px;
            }
            CategoryProposalCard:hover {
                border-color: #2196F3;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 顶部：复选框 + 类别名称
        top_layout = QHBoxLayout()
        
        self.chk_select = QCheckBox()
        self.chk_select.setChecked(True)
        self.chk_select.stateChanged.connect(self.on_selection_changed)
        top_layout.addWidget(self.chk_select)
        
        self.txt_name = QLineEdit(self.proposal.name)
        self.txt_name.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        top_layout.addWidget(self.txt_name, 1)
        
        # 预计数量标签
        lbl_count = QLabel(f"({self.proposal.estimated_count}条)")
        lbl_count.setStyleSheet("color: #666;")
        top_layout.addWidget(lbl_count)
        
        layout.addLayout(top_layout)
        
        # 描述
        if self.proposal.description:
            lbl_desc = QLabel(self.proposal.description)
            lbl_desc.setStyleSheet("color: #666; font-size: 12px;")
            lbl_desc.setWordWrap(True)
            layout.addWidget(lbl_desc)
        
        # 示例
        if self.proposal.examples:
            lbl_examples = QLabel(f"示例：{', '.join(self.proposal.examples[:3])}")
            lbl_examples.setStyleSheet("color: #888; font-size: 11px;")
            lbl_examples.setWordWrap(True)
            layout.addWidget(lbl_examples)
        
        # 冲突提示
        if self.proposal.conflicts:
            lbl_conflict = QLabel(f"⚠️ {'; '.join(self.proposal.conflicts)}")
            lbl_conflict.setStyleSheet("color: #f44336; font-size: 11px;")
            lbl_conflict.setWordWrap(True)
            layout.addWidget(lbl_conflict)
        
        # 合并至现有下拉框
        if self.existing_categories and self.proposal.is_new:
            merge_layout = QHBoxLayout()
            merge_layout.addWidget(QLabel("合并至现有："))
            self.cmb_merge = QComboBox()
            self.cmb_merge.addItem("-- 不合并 --")
            self.cmb_merge.addItems(self.existing_categories)
            self.cmb_merge.currentIndexChanged.connect(self.on_merge_changed)
            merge_layout.addWidget(self.cmb_merge, 1)
            layout.addLayout(merge_layout)
        
        # 强制新建复选框
        if self.proposal.is_new:
            self.chk_force_new = QCheckBox("强制新建（即使与现有类别冲突）")
            self.chk_force_new.setChecked(self.proposal.force_new)
            layout.addWidget(self.chk_force_new)
        
        # 是否新建标记
        if self.proposal.is_new and not getattr(self, 'chk_force_new', None):
            lbl_new = QLabel("[新建]")
            lbl_new.setStyleSheet("color: #4CAF50; font-size: 11px;")
            layout.addWidget(lbl_new)
    
    def on_selection_changed(self, state):
        self.is_selected = (state == 2)
    
    def on_merge_changed(self, index):
        """合并选择变更"""
        if hasattr(self, 'cmb_merge'):
            if index > 0:
                # 合并模式下禁用强制新建
                if hasattr(self, 'chk_force_new'):
                    self.chk_force_new.setChecked(False)
                    self.chk_force_new.setEnabled(False)
            else:
                if hasattr(self, 'chk_force_new'):
                    self.chk_force_new.setEnabled(True)
    
    def get_proposal(self) -> CategoryProposal:
        """获取当前编辑后的提议"""
        merge_target = None
        is_new = self.proposal.is_new
        
        if hasattr(self, 'cmb_merge') and self.cmb_merge.currentIndex() > 0:
            merge_target = self.cmb_merge.currentText()
            is_new = False
        
        force_new = getattr(self, 'chk_force_new', None)
        force_new_val = force_new.isChecked() if force_new else self.proposal.force_new
        
        return CategoryProposal(
            name=self.txt_name.text().strip() or self.proposal.name,
            description=self.proposal.description,
            estimated_count=self.proposal.estimated_count,
            examples=self.proposal.examples,
            is_new=is_new,
            conflicts=self.proposal.conflicts,
            merge_target=merge_target,
            force_new=force_new_val,
            source_items=self.proposal.source_items
        )


class AIClassifyDialog(QDialog):
    """AI智能分类对话框"""
    
    def __init__(self, service: AIClassificationService, items: List,
                 existing_categories: List[str], item_type: str = 'account',
                 parent=None):
        super().__init__(parent)
        self.service = service
        self.items = items
        self.existing_categories = existing_categories
        self.item_type = item_type
        self.approved_categories: List[str] = []
        self.changes: List[ClassificationChange] = []
        self.worker: Optional[ClassificationWorker] = None
        self.pre_analysis_worker: Optional[PreAnalysisWorker] = None
        
        self.setWindowTitle("AI智能分类")
        self.setMinimumSize(800, 700)
        self.setup_ui()
        # 不再直接调用 run_pre_analysis，而是启动后台线程
        self.start_pre_analysis()
    
    def setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        lbl_title = QLabel("AI智能分类")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        # 说明
        self.lbl_status = QLabel("正在分析数据...")
        self.lbl_status.setStyleSheet("color: #666;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_status)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 主内容区（分阶段显示）
        self.content_stack = QWidget()
        self.content_layout = QVBoxLayout(self.content_stack)
        layout.addWidget(self.content_stack, 1)
        
        # 阶段1：提议列表（滚动区域）
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        self.proposals_widget = QWidget()
        self.proposals_layout = QVBoxLayout(self.proposals_widget)
        self.proposals_layout.setSpacing(10)
        
        self.scroll_area.setWidget(self.proposals_widget)
        self.content_layout.addWidget(self.scroll_area)
        
        # 阶段2：差异视图（分组迁移视图）
        self.diff_container = QWidget()
        self.diff_layout = QVBoxLayout(self.diff_container)
        self.diff_layout.setSpacing(10)
        self.diff_layout.setContentsMargins(0, 0, 0, 0)
        self.diff_container.hide()
        self.content_layout.addWidget(self.diff_container)
        
        # 底部按钮
        self.button_layout = QHBoxLayout()
        self.button_layout.addStretch()
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.setFixedWidth(100)
        self.btn_cancel.clicked.connect(self.reject)
        self.button_layout.addWidget(self.btn_cancel)
        
        self.btn_next = QPushButton("确认并执行")
        self.btn_next.setFixedHeight(40)
        self.btn_next.setFixedWidth(120)
        self.btn_next.setStyleSheet("""
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
        """)
        self.btn_next.clicked.connect(self.on_next_clicked)
        self.btn_next.setEnabled(False)
        self.button_layout.addWidget(self.btn_next)
        
        self.btn_apply = QPushButton("正式生效")
        self.btn_apply.setFixedHeight(40)
        self.btn_apply.setFixedWidth(120)
        self.btn_apply.setStyleSheet("""
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
        self.btn_apply.clicked.connect(self.on_apply_clicked)
        self.btn_apply.hide()
        self.button_layout.addWidget(self.btn_apply)
        
        self.btn_rollback = QPushButton("回滚")
        self.btn_rollback.setFixedHeight(40)
        self.btn_rollback.setFixedWidth(100)
        self.btn_rollback.clicked.connect(self.on_rollback_clicked)
        self.btn_rollback.hide()
        self.button_layout.addWidget(self.btn_rollback)
        
        layout.addLayout(self.button_layout)
    
    def start_pre_analysis(self):
        """启动预分析后台线程"""
        self.lbl_status.setText(f"🤖 AI 正在深度分析您的 {len(self.items)} 条数据，请稍候...")
        self.lbl_status.setStyleSheet("color: #1976D2; font-weight: bold;")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(0)  # 无限循环动画
        self.progress_bar.setValue(0)
        self.btn_next.setEnabled(False)
        
        self.pre_analysis_worker = PreAnalysisWorker(
            self.service, self.items, self.existing_categories, self.item_type
        )
        self.pre_analysis_worker.finished.connect(self.on_pre_analysis_finished)
        self.pre_analysis_worker.error.connect(self.on_pre_analysis_error)
        self.pre_analysis_worker.start()
    
    def on_pre_analysis_finished(self, proposals: list):
        """预分析完成回调"""
        self.progress_bar.hide()
        self.show_proposals(proposals)
    
    def on_pre_analysis_error(self, error_msg: str):
        """预分析出错回调"""
        self.progress_bar.hide()
        self.lbl_status.setText(f"分析失败：{error_msg}")
        self.lbl_status.setStyleSheet("color: #f44336;")
        QMessageBox.critical(self, "错误", f"AI预分析失败：\n{error_msg}")
    
    def run_pre_analysis(self):
        """已由 start_pre_analysis + PreAnalysisWorker 替代"""
        pass
    
    def show_proposals(self, proposals: List[CategoryProposal]):
        """显示类别提议卡片"""
        # 清除所有内容
        while self.proposals_layout.count():
            item = self.proposals_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not proposals:
            self.lbl_status.setText("未生成分类建议")
            return
        
        self.lbl_status.setText(f"AI已生成 {len(proposals)} 个类别建议，请审核并确认")
        
        for proposal in proposals:
            card = CategoryProposalCard(proposal, self.existing_categories)
            self.proposals_layout.addWidget(card)
        
        # 添加自定义类别输入区域
        custom_widget = QWidget()
        custom_widget.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
                border-radius: 8px;
            }
        """)
        custom_layout = QHBoxLayout(custom_widget)
        custom_layout.setContentsMargins(15, 10, 15, 10)
        custom_layout.setSpacing(10)
        
        self.txt_custom_category = QLineEdit()
        self.txt_custom_category.setPlaceholderText("输入自定义类别名称...")
        custom_layout.addWidget(self.txt_custom_category, 1)
        
        btn_add_custom = QPushButton("添加")
        btn_add_custom.setFixedHeight(32)
        btn_add_custom.setFixedWidth(70)
        btn_add_custom.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        btn_add_custom.clicked.connect(self.on_add_custom_category)
        custom_layout.addWidget(btn_add_custom)
        
        self.proposals_layout.addWidget(custom_widget)
        self.proposals_layout.addStretch()
        
        self.btn_next.setEnabled(True)
    
    def on_add_custom_category(self):
        """添加自定义类别"""
        name = self.txt_custom_category.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入类别名称")
            return
        
        # 检查是否已存在
        for i in range(self.proposals_layout.count()):
            widget = self.proposals_layout.itemAt(i).widget()
            if isinstance(widget, CategoryProposalCard):
                if widget.txt_name.text().strip() == name:
                    QMessageBox.warning(self, "提示", f"类别 '{name}' 已存在")
                    return
        
        proposal = CategoryProposal(
            name=name,
            description="用户自定义类别",
            estimated_count=0,
            examples=[],
            is_new=True,
            conflicts=[]
        )
        card = CategoryProposalCard(proposal, self.existing_categories)
        # 插入到自定义输入框之前
        self.proposals_layout.insertWidget(self.proposals_layout.count() - 2, card)
        self.txt_custom_category.clear()
    
    def on_next_clicked(self):
        """确认提议，执行分类"""
        # 收集用户确认的类别
        self.approved_categories = []
        for i in range(self.proposals_layout.count()):
            widget = self.proposals_layout.itemAt(i).widget()
            if isinstance(widget, CategoryProposalCard) and widget.is_selected:
                proposal = widget.get_proposal()
                if proposal.merge_target:
                    # 使用合并目标作为类别名
                    if proposal.merge_target not in self.approved_categories:
                        self.approved_categories.append(proposal.merge_target)
                else:
                    if proposal.name not in self.approved_categories:
                        self.approved_categories.append(proposal.name)
        
        if not self.approved_categories:
            QMessageBox.warning(self, "提示", "请至少选择一个类别")
            return
        
        # 隐藏提议列表，显示进度
        self.scroll_area.hide()
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(self.items))
        self.progress_bar.setValue(0)
        self.lbl_status.setText("正在执行分类...")
        self.btn_next.setEnabled(False)
        
        # 启动工作线程
        self.worker = ClassificationWorker(
            self.service, self.items, self.approved_categories, self.item_type
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_classification_finished)
        self.worker.error.connect(self.on_classification_error)
        self.worker.start()
    
    def on_progress(self, current: int, total: int):
        """进度更新"""
        self.progress_bar.setValue(current)
        self.lbl_status.setText(f"正在分类... {current}/{total}")
    
    def on_classification_finished(self, changes: List[ClassificationChange]):
        """分类完成"""
        self.changes = changes
        self.progress_bar.hide()
        self.lbl_status.setText(f"分类完成，共 {len(changes)} 条变更")
        
        # 显示差异视图
        self.show_diff_view(changes)
    
    def on_classification_error(self, error_msg: str):
        """分类出错"""
        self.progress_bar.hide()
        self.lbl_status.setText("分类失败")
        QMessageBox.critical(self, "错误", f"分类执行失败：\n{error_msg}")
        self.btn_next.setEnabled(True)
    
    def show_diff_view(self, changes: List[ClassificationChange]):
        """显示分组迁移视图"""
        # 清空旧视图
        while self.diff_layout.count():
            item = self.diff_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 按新分类分组
        groups = {}
        pending_changes = []
        
        for change in changes:
            if change.is_low_confidence or change.is_pending:
                pending_changes.append(change)
            else:
                cat = change.new_category
                if cat not in groups:
                    groups[cat] = []
                groups[cat].append(change)
        
        # 收集所有可用类别（用于下拉框）
        all_cats = list(set(self.approved_categories + self.existing_categories + list(groups.keys())))
        all_cats = sorted([c for c in all_cats if c])
        if "待整理" not in all_cats:
            all_cats.append("待整理")
        
        # 先添加待整理组（始终置顶，橙色高亮）
        if pending_changes:
            pending_widget = MigrationGroupWidget(
                "待整理", pending_changes, all_cats, is_pending_group=True
            )
            self.diff_layout.addWidget(pending_widget)
        
        # 添加其他组（按类别名排序）
        for cat in sorted(groups.keys()):
            group_widget = MigrationGroupWidget(cat, groups[cat], all_cats)
            self.diff_layout.addWidget(group_widget)
        
        self.diff_layout.addStretch()
        self.diff_container.show()
        
        # 切换按钮
        self.btn_next.hide()
        self.btn_cancel.hide()
        self.btn_apply.show()
        self.btn_rollback.show()
    
    def on_apply_clicked(self):
        """正式生效"""
        # 先创建快照（记录修改前的状态）
        snapshot = self.service.create_snapshot(self.item_type, self.items)
        
        # 再应用变更到items并直接持久化到数据库
        change_map = {c.item_id: c for c in self.changes}
        
        for item in self.items:
            item_id = item.id if hasattr(item, 'id') else 0
            if item_id in change_map:
                new_category = change_map[item_id].new_category
                item.category = new_category
                # 直接写入数据库，确保持久化
                try:
                    if self.item_type == 'account' and self.service.db:
                        self.service.db.update_account(item_id, {'category': new_category})
                    elif self.item_type == 'url' and self.service.url_db:
                        self.service.url_db.update_url(item_id, {'category': new_category})
                except Exception as e:
                    print(f"[AIClassify] Failed to persist category for item {item_id}: {e}")
        
        QMessageBox.information(
            self, "生效成功",
            f"分类已正式生效！\n\n"
            f"快照ID：{snapshot.snapshot_id}\n"
            f"30天内可通过快照回滚。"
        )
        
        self.accept()
    
    def on_rollback_clicked(self):
        """回滚到历史快照"""
        snapshots = self.service.get_snapshots(self.item_type)
        if not snapshots:
            QMessageBox.information(self, "提示", "没有可用的快照")
            return
        
        dialog = SnapshotSelectionDialog(snapshots, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.selected_snapshot_id:
                success = self.service.rollback(dialog.selected_snapshot_id, self.items)
                if success:
                    QMessageBox.information(self, "回滚成功", "已回滚到选定快照状态")
                    self.accept()
                else:
                    QMessageBox.critical(self, "回滚失败", "无法找到指定的快照")
    
    def closeEvent(self, event):
        """关闭时停止工作线程"""
        if self.pre_analysis_worker and self.pre_analysis_worker.isRunning():
            self.pre_analysis_worker.terminate()
            self.pre_analysis_worker.wait(1000)
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)
        event.accept()
