"""
标签编辑对话框
支持：AI 生成、手动添加、删除
"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit,
    QMessageBox, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont

from typing import List
from models.account import Account
from services.tag_service import TagService
from core.theme_manager import ThemeManager, ThemeColors


class TagButton(QPushButton):
    """标签按钮（带删除功能）"""
    
    def __init__(self, text: str, removable: bool = True, parent=None):
        super().__init__(text, parent)
        colors = ThemeManager.instance().colors
        self.setFixedHeight(28)
        self.removable = removable
        
        if removable:
            self.setText(f"{text}  ×")
        
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
                border: 1px solid {colors.accent_blue_light};
                border-radius: 14px;
                padding: 2px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg_hover};
                border-color: {colors.accent_blue_light};
            }}
            QPushButton:pressed {{
                background-color: {colors.accent_blue_light};
            }}
        """)


class TagEditorDialog(QDialog):
    """标签编辑对话框"""
    
    def __init__(self, account: Account, tag_service: TagService = None, parent=None):
        super().__init__(parent)
        self.account = account
        self.tag_service = tag_service or TagService()
        self.tags = account.get_tags_list().copy()
        
        self.setup_ui()
        self.refresh_tags_display()
    
    def setup_ui(self):
        """设置界面"""
        colors = ThemeManager.instance().colors
        self.setWindowTitle(f"编辑标签 - {self.account.app_name}")
        self.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        lbl_title = QLabel("账号标签管理")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        lbl_title.setFont(font)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        # 说明
        lbl_desc = QLabel("标签用于快速分类和搜索，最多 5 个")
        lbl_desc.setStyleSheet(f"color: {colors.text_secondary}; font-size: 11px;")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)
        
        # 当前标签区域
        lbl_current = QLabel("当前标签：")
        lbl_current.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(lbl_current)
        
        self.tags_container = QWidget()
        self.tags_layout = QHBoxLayout(self.tags_container)
        self.tags_layout.setSpacing(8)
        self.tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tags_container)
        
        # 添加新标签
        add_layout = QHBoxLayout()
        
        self.txt_new_tag = QLineEdit()
        self.txt_new_tag.setPlaceholderText("输入新标签（2-10字）")
        self.txt_new_tag.setFixedHeight(32)
        self.txt_new_tag.returnPressed.connect(self.on_add_tag)
        add_layout.addWidget(self.txt_new_tag)
        
        btn_add = QPushButton("添加")
        btn_add.setFixedHeight(32)
        btn_add.setFixedWidth(60)
        btn_add.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_dark};
            }}
        """)
        btn_add.clicked.connect(self.on_add_tag)
        add_layout.addWidget(btn_add)
        
        layout.addLayout(add_layout)
        
        # AI 生成按钮
        self.btn_ai_generate = QPushButton("✨ AI 智能生成标签")
        self.btn_ai_generate.setFixedHeight(36)
        self.btn_ai_generate.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_blue};
                color: {colors.text_on_dark};
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_dark};
            }}
            QPushButton:disabled {{
                background-color: {colors.text_disabled};
            }}
        """)
        self.btn_ai_generate.clicked.connect(self.on_ai_generate)
        layout.addWidget(self.btn_ai_generate)
        
        # 绑定 AI 状态变化信号，动态更新按钮可用性
        from services.ai_service_manager import AIServiceManager
        from services.ai_worker_thread import AIStatus
        self._ai_manager = AIServiceManager.instance()
        self._ai_manager.state_changed.connect(self._update_ai_button)
        self._update_ai_button(self._ai_manager.get_state())
        
        layout.addStretch()
        
        # 按钮区
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancel)
        
        button_layout.addSpacing(10)
        
        btn_ok = QPushButton("确定")
        btn_ok.setFixedHeight(36)
        btn_ok.setFixedWidth(80)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_green};
                color: {colors.text_on_accent};
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_green_dark};
            }}
        """)
        btn_ok.clicked.connect(self.on_ok)
        button_layout.addWidget(btn_ok)
        
        layout.addLayout(button_layout)
    
    def refresh_tags_display(self):
        """刷新标签显示"""
        colors = ThemeManager.instance().colors
        # 清除现有标签按钮
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not self.tags:
            lbl_empty = QLabel("暂无标签")
            lbl_empty.setStyleSheet(f"color: {colors.text_tertiary}; font-style: italic;")
            self.tags_layout.addWidget(lbl_empty)
            return
        
        for tag in self.tags:
            btn_tag = TagButton(tag, removable=True)
            btn_tag.clicked.connect(lambda checked, t=tag: self.on_remove_tag(t))
            self.tags_layout.addWidget(btn_tag)
        
        # 添加弹性空间
        self.tags_layout.addStretch()
    
    def on_add_tag(self):
        """添加标签"""
        tag = self.txt_new_tag.text().strip()
        
        if not tag:
            return
        
        # 验证标签
        if not self.tag_service.validate_tag(tag):
            QMessageBox.warning(self, "验证失败", "标签无效（长度 2-10，不含特殊字符）")
            return
        
        # 检查重复
        if tag in self.tags:
            QMessageBox.information(self, "提示", "该标签已存在")
            return
        
        # 检查数量限制
        if len(self.tags) >= 5:
            QMessageBox.warning(self, "提示", "最多只能添加 5 个标签")
            return
        
        self.tags.append(tag)
        self.txt_new_tag.clear()
        self.refresh_tags_display()
    
    def on_remove_tag(self, tag: str):
        """移除标签"""
        if tag in self.tags:
            self.tags.remove(tag)
            self.refresh_tags_display()
    
    def on_ai_generate(self):
        """AI 生成标签"""
        self.btn_ai_generate.setEnabled(False)
        self.btn_ai_generate.setText("生成中...")
        
        try:
            new_tags = self.tag_service.generate_tags(
                self.account.app_name,
                self.account.url,
                self.account.category
            )
            
            # 合并标签（保留用户已有的，添加 AI 生成的）
            for tag in new_tags:
                if tag not in self.tags and len(self.tags) < 5:
                    self.tags.append(tag)
            
            self.refresh_tags_display()
            
            if new_tags:
                QMessageBox.information(
                    self, "生成完成",
                    f"AI 生成了 {len(new_tags)} 个标签建议，\n"
                    f"已添加到列表中（未重复的）。\n\n"
                    f"生成标签：{', '.join(new_tags)}"
                )
            else:
                QMessageBox.information(self, "提示", "未能生成合适的标签")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"标签生成失败：{str(e)}")
        finally:
            self.btn_ai_generate.setEnabled(True)
            self.btn_ai_generate.setText("✨ AI 智能生成标签")
    
    def _update_ai_button(self, state):
        """根据 AI 状态更新按钮可用性"""
        from services.ai_worker_thread import AIStatus
        enabled = state.status == AIStatus.ONLINE
        self.btn_ai_generate.setEnabled(enabled)
        if enabled:
            self.btn_ai_generate.setToolTip("根据应用信息 AI 智能生成标签")
        else:
            self.btn_ai_generate.setToolTip(f"AI 服务不可用 ({state.error_message})")
    
    def closeEvent(self, event):
        """关闭时清理信号连接"""
        try:
            self._ai_manager.state_changed.disconnect(self._update_ai_button)
        except Exception:
            pass
        event.accept()
    
    def on_ok(self):
        """确定保存"""
        # 更新账号标签
        self.account.set_tags_list(self.tags)
        self.accept()
    
    def get_tags(self) -> List[str]:
        """获取当前标签列表"""
        return self.tags.copy()
