"""
网址添加/编辑弹窗
集成：手动输入 + AI 智能分类 + 标签/备注管理
"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTextEdit,
    QMessageBox, QFrame
)
from PyQt6.QtCore import Qt

from models.url_item import URLItem
from services.url_service import URLService
from core.repositories import RepositoryFactory, URLRepository
from services.ai_service_manager import AIServiceManager
from services.ai_worker_thread import AIStatus


class URLEditDialog(QDialog):
    """网址添加/编辑弹窗"""
    
    def __init__(self, url_service: URLService, url_item: URLItem = None, parent=None):
        super().__init__(parent)
        self.url_service = url_service
        self.url_item = url_item or URLItem()
        self.is_edit_mode = url_item is not None and url_item.id is not None
        
        self._ai_manager = AIServiceManager.instance()
        self._pending_tags_task = None
        self._pending_remark_task = None
        
        self.setup_ui()
        
        if self.is_edit_mode:
            self.load_url_data()
        
        # 绑定 AI 任务结果信号
        self._ai_manager.task_finished.connect(self._on_ai_task_finished)
        self._ai_manager.task_failed.connect(self._on_ai_task_failed)
    
    def _ensure_repository_registered(self):
        """确保 URLRepository 已在工厂中注册"""
        try:
            RepositoryFactory.get_repository('urls')
        except KeyError:
            from core.url_database import URLDatabaseManager
            repo = URLRepository(
                db=self.url_service.db,
                url_service=self.url_service
            )
            RepositoryFactory.register('urls', repo)
    
    def _get_categories(self) -> list:
        """通过 RepositoryFactory 获取分类列表（确保与数据库同步）"""
        self._ensure_repository_registered()
        try:
            cats = RepositoryFactory.get_repository('urls').get_categories()
            return cats
        except Exception as e:
            print(f"[URLEditDialog] RepositoryFactory 获取分类失败: {e}")
            return self.url_service.get_categories()
    
    def setup_ui(self):
        """设置界面"""
        if self.is_edit_mode:
            self.setWindowTitle(f"编辑网址 - {self.url_item.title or self.url_item.url}")
        else:
            self.setWindowTitle("添加网址")
        
        self.setMinimumSize(600, 500)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # ===== 标题 =====
        title_layout = QHBoxLayout()
        lbl_title = QLabel("标题：")
        lbl_title.setFixedWidth(80)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_layout.addWidget(lbl_title)
        
        self.txt_title = QLineEdit()
        self.txt_title.setPlaceholderText("例如：GitHub、知乎")
        self.txt_title.setFixedHeight(36)
        title_layout.addWidget(self.txt_title)
        layout.addLayout(title_layout)
        
        # ===== 网址 =====
        url_layout = QHBoxLayout()
        lbl_url = QLabel("网址：*")
        lbl_url.setFixedWidth(80)
        lbl_url.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        url_layout.addWidget(lbl_url)
        
        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("例如：https://github.com")
        self.txt_url.setFixedHeight(36)
        url_layout.addWidget(self.txt_url)
        layout.addLayout(url_layout)
        
        # ===== 分类 + AI 按钮 =====
        category_layout = QHBoxLayout()
        lbl_category = QLabel("分类：")
        lbl_category.setFixedWidth(80)
        lbl_category.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        category_layout.addWidget(lbl_category)
        
        self.cmb_category = QLineEdit()
        self.cmb_category.setPlaceholderText("选择或输入分类")
        self.cmb_category.setFixedHeight(36)
        category_layout.addWidget(self.cmb_category)
        
        self.btn_ai_categorize = QPushButton("AI 智能分类")
        self.btn_ai_categorize.setFixedHeight(36)
        self.btn_ai_categorize.setToolTip("自动分析网址类型并分类")
        self.btn_ai_categorize.clicked.connect(self.on_ai_categorize)
        category_layout.addWidget(self.btn_ai_categorize)
        
        layout.addLayout(category_layout)
        
        # 分类下拉提示标签
        categories = self._get_categories()
        if categories:
            lbl_cats = QLabel(f"可用分类：{', '.join(categories[:10])}")
            lbl_cats.setStyleSheet("color: #999; font-size: 11px;")
            lbl_cats.setIndent(84)
            layout.addWidget(lbl_cats)
        
        # ===== 标签（带 AI 生成按钮）=====
        tags_layout = QHBoxLayout()
        lbl_tags = QLabel("标签：")
        lbl_tags.setFixedWidth(80)
        lbl_tags.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tags_layout.addWidget(lbl_tags)
        
        self.txt_tags = QLineEdit()
        self.txt_tags.setPlaceholderText("逗号分隔，如: 工作, 常用, 开源")
        self.txt_tags.setFixedHeight(36)
        tags_layout.addWidget(self.txt_tags)
        
        self.btn_ai_tags = QPushButton("AI生成标签")
        self.btn_ai_tags.setFixedHeight(36)
        self.btn_ai_tags.setToolTip("根据标题和网址自动生成标签")
        self.btn_ai_tags.clicked.connect(self.on_ai_generate_tags)
        tags_layout.addWidget(self.btn_ai_tags)
        
        layout.addLayout(tags_layout)
        
        # ===== 用户备注 =====
        remark_layout = QHBoxLayout()
        lbl_remark = QLabel("备注：")
        lbl_remark.setFixedWidth(80)
        lbl_remark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        remark_layout.addWidget(lbl_remark)
        
        self.txt_remark = QTextEdit()
        self.txt_remark.setPlaceholderText("输入用户备注...")
        self.txt_remark.setMinimumHeight(60)
        self.txt_remark.setMaximumHeight(100)
        remark_layout.addWidget(self.txt_remark)
        layout.addLayout(remark_layout)
        
        # ===== AI 备注（只读 + 重新生成按钮）=====
        ai_remark_layout = QHBoxLayout()
        lbl_ai_remark = QLabel("AI 备注：")
        lbl_ai_remark.setFixedWidth(80)
        lbl_ai_remark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        ai_remark_layout.addWidget(lbl_ai_remark)
        
        self.txt_ai_remark = QTextEdit()
        self.txt_ai_remark.setPlaceholderText("点击右侧按钮生成 AI 备注...")
        self.txt_ai_remark.setReadOnly(True)
        self.txt_ai_remark.setMinimumHeight(60)
        self.txt_ai_remark.setMaximumHeight(100)
        ai_remark_layout.addWidget(self.txt_ai_remark)
        
        self.btn_ai_remark = QPushButton("生成 AI 备注")
        self.btn_ai_remark.setFixedHeight(36)
        self.btn_ai_remark.setToolTip("根据标题和网址生成一句话备注")
        self.btn_ai_remark.clicked.connect(self.on_ai_generate_remark)
        ai_remark_layout.addWidget(self.btn_ai_remark)
        
        layout.addLayout(ai_remark_layout)
        
        # 更新 AI 按钮状态
        self._update_ai_buttons(self._ai_manager.get_state())
        self._ai_manager.state_changed.connect(self._update_ai_buttons)
        
        layout.addStretch()
        
        # ===== 底部按钮区 =====
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(40)
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancel)
        
        button_layout.addSpacing(10)
        
        btn_save = QPushButton("保存")
        btn_save.setFixedHeight(40)
        btn_save.setFixedWidth(100)
        btn_save.setStyleSheet("""
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
        btn_save.clicked.connect(self.on_save)
        button_layout.addWidget(btn_save)
        
        layout.addLayout(button_layout)
        
        # 删除按钮（仅编辑模式）
        if self.is_edit_mode:
            btn_delete = QPushButton("删除网址")
            btn_delete.setFixedHeight(40)
            btn_delete.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #d32f2f;
                }
            """)
            btn_delete.clicked.connect(self.on_delete)
            layout.addWidget(btn_delete, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def _update_ai_buttons(self, state):
        """根据 AI 状态更新按钮可用性"""
        enabled = state.status == AIStatus.ONLINE
        if hasattr(self, 'btn_ai_categorize'):
            self.btn_ai_categorize.setEnabled(enabled)
        if hasattr(self, 'btn_ai_tags'):
            self.btn_ai_tags.setEnabled(enabled)
        if hasattr(self, 'btn_ai_remark'):
            self.btn_ai_remark.setEnabled(enabled)
    
    def load_url_data(self):
        """加载网址数据（编辑模式）"""
        self.txt_title.setText(self.url_item.title)
        self.txt_url.setText(self.url_item.url)
        self.cmb_category.setText(self.url_item.category or '其他')
        self.txt_remark.setText(self.url_item.remark)
        self.txt_ai_remark.setText(self.url_item.ai_remark)
        
        tags = self.url_item.get_tags_list()
        self.txt_tags.setText(", ".join(tags))
    
    def on_ai_categorize(self):
        """AI 智能分类"""
        url = self.txt_url.text().strip()
        title = self.txt_title.text().strip()
        
        if not url and not title:
            QMessageBox.warning(self, "提示", "请先输入网址或标题")
            return
        
        category = self.url_service.auto_categorize(url, title)
        self.cmb_category.setText(category)
        QMessageBox.information(self, "分类成功", f"AI 识别分类：{category}")
    
    def on_ai_generate_tags(self):
        """AI 生成标签：复用 generate_remark_async，结果按逗号拆分作为标签"""
        title = self.txt_title.text().strip()
        url = self.txt_url.text().strip()
        
        if not title and not url:
            QMessageBox.warning(self, "提示", "请先输入标题或网址")
            return
        
        self.btn_ai_tags.setEnabled(False)
        self.btn_ai_tags.setText("生成中...")
        
        # 复用 generate_remark_async，在回调中按逗号解析为标签
        task_id = self._ai_manager.generate_remark_async(title, url)
        self._pending_tags_task = task_id
    
    def on_ai_generate_remark(self):
        """AI 生成备注"""
        title = self.txt_title.text().strip()
        url = self.txt_url.text().strip()
        
        if not title and not url:
            QMessageBox.warning(self, "提示", "请先输入标题或网址")
            return
        
        self.btn_ai_remark.setEnabled(False)
        self.btn_ai_remark.setText("生成中...")
        
        task_id = self._ai_manager.generate_remark_async(title, url)
        self._pending_remark_task = task_id
    
    def _on_ai_task_finished(self, task_id, result):
        """AI 任务完成统一分发"""
        if task_id == self._pending_tags_task:
            self._pending_tags_task = None
            self._on_tags_result(result)
        elif task_id == self._pending_remark_task:
            self._pending_remark_task = None
            self._on_remark_result(result)
    
    def _on_ai_task_failed(self, task_id, error_message):
        """AI 任务失败统一分发"""
        if task_id == self._pending_tags_task:
            self._pending_tags_task = None
            self._on_tags_failed(error_message)
        elif task_id == self._pending_remark_task:
            self._pending_remark_task = None
            self._on_remark_failed(error_message)
    
    def _on_tags_result(self, result):
        """标签生成完成"""
        self.btn_ai_tags.setEnabled(True)
        self.btn_ai_tags.setText("AI生成标签")
        self.txt_tags.setText(result)
    
    def _on_tags_failed(self, error):
        """标签生成失败"""
        self.btn_ai_tags.setEnabled(True)
        self.btn_ai_tags.setText("AI生成标签")
        QMessageBox.warning(self, "生成失败", f"AI 标签生成失败：{error}")
    
    def _on_remark_result(self, result):
        """备注生成完成"""
        self.btn_ai_remark.setEnabled(True)
        self.btn_ai_remark.setText("生成 AI 备注")
        self.txt_ai_remark.setText(result)
    
    def _on_remark_failed(self, error):
        """备注生成失败"""
        self.btn_ai_remark.setEnabled(True)
        self.btn_ai_remark.setText("生成 AI 备注")
        QMessageBox.warning(self, "生成失败", f"AI 备注生成失败：{error}")
    
    def on_save(self):
        """保存网址"""
        url = self.txt_url.text().strip()
        title = self.txt_title.text().strip()
        
        if not url:
            QMessageBox.warning(self, "验证失败", "请输入网址")
            self.txt_url.setFocus()
            return
        
        # 如果没有标题，使用域名作为标题
        if not title:
            from urllib.parse import urlparse
            try:
                title = urlparse(url).netloc or url
            except Exception:
                title = url
        
        # 解析标签
        tags_text = self.txt_tags.text().strip()
        tags = [t.strip() for t in tags_text.split(",") if t.strip()]
        
        self.url_item.title = title
        self.url_item.url = url
        self.url_item.category = self.cmb_category.text().strip() or '其他'
        self.url_item.remark = self.txt_remark.toPlainText().strip()
        self.url_item.ai_remark = self.txt_ai_remark.toPlainText().strip()
        self.url_item.set_tags_list(tags)
        
        try:
            if self.is_edit_mode:
                self.url_service.update_url(self.url_item)
                QMessageBox.information(self, "成功", "网址已更新")
            else:
                new_id = self.url_service.add_url(self.url_item)
                self.url_item.id = new_id
                QMessageBox.information(self, "成功", "网址已添加")
            
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：{str(e)}")
    
    def on_delete(self):
        """删除网址"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除网址「{self.url_item.title or self.url_item.url}」吗？\n删除后将移至回收站。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from core.database import DatabaseManager
                # 软删除：先备份到主库回收站，再删除网址表记录
                db = DatabaseManager()
                db.soft_delete_url(self.url_item.id, self.url_item.to_dict())
                self.url_service.delete_url(self.url_item.id)
                QMessageBox.information(self, "成功", "网址已移至回收站")
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败：{str(e)}")
    
    def closeEvent(self, event):
        """关闭时清理"""
        try:
            self._ai_manager.state_changed.disconnect(self._update_ai_buttons)
            self._ai_manager.task_finished.disconnect(self._on_ai_task_finished)
            self._ai_manager.task_failed.disconnect(self._on_ai_task_failed)
        except Exception:
            pass
        event.accept()
