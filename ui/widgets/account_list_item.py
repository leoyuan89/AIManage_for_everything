from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QCheckBox
from PyQt6.QtCore import Qt

from core.theme_manager import ThemeManager


class AccountListItem(QWidget):
    """自定义账号列表项（支持标识徽章、选择模式）"""
    
    def __init__(self, account, badges: list = None, selection_mode: bool = False, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self.setObjectName("accountListItem")
        self.account = account
        self.badges = badges or []
        self.setup_ui(selection_mode)
    
    def setup_ui(self, selection_mode: bool):
        colors = ThemeManager.instance().colors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(10)
        
        # 复选框
        self.checkbox = QCheckBox()
        self.checkbox.setFixedSize(24, 24)
        self.checkbox.setVisible(selection_mode)
        layout.addWidget(self.checkbox)
        
        # 圆形图标
        self.icon_label = QLabel(self._get_initial(self.account.app_name))
        self.icon_label.setFixedSize(36, 36)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color = self._generate_icon_color(self.account.app_name)
        self.icon_label.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: {colors.text_on_accent};
                border-radius: 18px;
                font-size: 14px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(self.icon_label)
        
        # 文字区（垂直）
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setContentsMargins(0, 0, 0, 0)
        
        # 主标题行（包含徽章）
        title_layout = QHBoxLayout()
        title_layout.setSpacing(4)
        
        self.lbl_name = QLabel(self.account.app_name)
        self.lbl_name.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 600;")
        title_layout.addWidget(self.lbl_name)
        
        # 徽章标签（如 炽阳推荐）
        for badge_text, badge_color in self.badges:
            lbl_badge = QLabel(badge_text)
            lbl_badge.setStyleSheet(f"""
                color: {badge_color};
                font-size: 9px;
                font-weight: bold;
                background-color: {badge_color}20;
                border-radius: 4px;
                padding: 1px 6px;
            """)
            title_layout.addWidget(lbl_badge)
        
        # 密码强度徽章
        if self.account.security_level:
            level_colors = {
                "弱": "#f44336",
                "中": "#FF9800",
                "强": "#4CAF50",
                "极强": "#2196F3"
            }
            level_color = level_colors.get(self.account.security_level, colors.text_tertiary)
            lbl_sec = QLabel(self.account.security_level)
            lbl_sec.setStyleSheet(f"""
                color: {level_color};
                font-size: 9px;
                font-weight: bold;
                background-color: {level_color}20;
                border-radius: 4px;
                padding: 1px 6px;
            """)
            title_layout.addWidget(lbl_sec)
        
        title_layout.addStretch()
        text_layout.addLayout(title_layout)
        
        # 副标题：脱敏账号
        self.lbl_account = QLabel(self.account.mask_username())
        self.lbl_account.setStyleSheet(f"color: {colors.text_tertiary}; font-size: 12px;")
        text_layout.addWidget(self.lbl_account)
        
        layout.addLayout(text_layout, 1)
        
        # 分类标签 Pill
        self.lbl_category = QLabel(self.account.category or '其他')
        self.lbl_category.setStyleSheet(f"""
            color: {colors.text_secondary};
            font-size: 11px;
            background-color: {colors.bg_secondary};
            border-radius: 10px;
            padding: 2px 8px;
        """)
        layout.addWidget(self.lbl_category)
        
        # 右箭头
        self.lbl_arrow = QLabel("›")
        self.lbl_arrow.setStyleSheet(f"color: {colors.text_disabled}; font-size: 18px;")
        layout.addWidget(self.lbl_arrow)
        
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            #accountListItem {{
                background-color: {colors.bg_primary};
                border: none;
                border-bottom: 1px solid {colors.border_light};
            }}
        """)
    
    def set_selection_mode(self, enabled: bool):
        self.checkbox.setVisible(enabled)
    
    def is_checked(self) -> bool:
        return self.checkbox.isChecked()
    
    def set_checked(self, checked: bool):
        self.checkbox.setChecked(checked)
    
    @staticmethod
    def _generate_icon_color(text: str) -> str:
        colors = ['#E57373', '#F06292', '#BA68C8', '#9575CD', '#7986CB', '#64B5F6', '#4FC3F7', '#4DD0E1', '#4DB6AC', '#81C784', '#AED581', '#FFD54F', '#FFB74D', '#FF8A65', '#A1887F']
        hash_val = sum(ord(c) for c in text) if text else 0
        return colors[hash_val % len(colors)]
    
    @staticmethod
    def _get_initial(text: str) -> str:
        if not text:
            return '?'
        return text[0].upper()
