from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QCheckBox, QPushButton
from PyQt6.QtCore import Qt

from core.theme_manager import ThemeManager
from core.clipboard import ClipboardManager

import logging

logger = logging.getLogger(__name__)

# 模块级单例，避免每个列表项都创建一个 ClipboardManager
_clipboard_manager = ClipboardManager()


class AccountListItem(QWidget):
    """自定义账号列表项（支持标识徽章、选择模式）"""
    
    def __init__(self, account, badges: list = None, selection_mode: bool = False, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self.setObjectName("accountListItem")
        self.account = account
        self.badges = badges or []
        self._compact_mode = False
        self._checkbox_clicked = False  # 标记 checkbox 是否被直接点击（避免 itemClicked 重复翻转）
        self._clipboard = _clipboard_manager
        self.on_check_changed = None  # 外部传入的回调: callable(checked: bool)
        self.setup_ui(selection_mode)
    
    def set_compact_mode(self, enabled: bool):
        if enabled == self._compact_mode:
            return
        self._compact_mode = enabled

        if enabled:
            self.setFixedHeight(32)
            self.icon_label.hide()
            self.lbl_category.hide()
            self.lbl_arrow.hide()
            if hasattr(self, 'lbl_time'):
                self.lbl_time.hide()
            self.layout().setContentsMargins(6, 0, 6, 0)
        else:
            self.setFixedHeight(56)
            self.icon_label.show()
            self.lbl_category.show()
            self.lbl_arrow.show()
            if hasattr(self, 'lbl_time'):
                self.lbl_time.show()
            self.layout().setContentsMargins(10, 0, 10, 0)

        self.on_theme_changed()
    
    def setup_ui(self, selection_mode: bool):
        colors = ThemeManager.instance().colors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(10)
        
        # 复选框
        self.checkbox = QCheckBox(self)
        self.checkbox.setFixedSize(24, 24)
        self.checkbox.toggled.connect(self._on_check_state_changed)
        layout.addWidget(self.checkbox)
        self.checkbox.setVisible(selection_mode)
        
        # 收藏星标
        if self.account.is_favorite:
            star = QLabel("⭐")
            star.setStyleSheet("font-size: 12px;")
            layout.addWidget(star)
        
        # 圆形图标
        self.icon_label = QLabel(self._get_initial(self.account.app_name))
        self.icon_label.setObjectName("icon_label")
        self.icon_label.setFixedSize(36, 36)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)
        
        # 文字区（垂直）
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setContentsMargins(0, 0, 0, 0)
        
        # 主标题行（包含徽章）
        title_layout = QHBoxLayout()
        title_layout.setSpacing(4)
        
        self.lbl_name = QLabel(self.account.app_name)
        self.lbl_name.setObjectName("lbl_name")
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
        
        # 密码强度徽章（动态评估）
        self._strength_label = None
        if self.account.password:
            try:
                from core.password_strength import evaluate_password_strength
                result = evaluate_password_strength(self.account.password)
                level = result['label']
                level_colors = {
                    "弱": colors.accent_red,
                    "中": colors.accent_orange,
                    "强": colors.accent_green,
                    "极强": colors.accent_blue,
                }
                level_color = level_colors.get(level, colors.text_tertiary)
                self._strength_label = QLabel(level)
                self._strength_label.setStyleSheet(f"""
                    color: {level_color};
                    font-size: 9px;
                    font-weight: bold;
                    background-color: {level_color}20;
                    border-radius: 4px;
                    padding: 1px 6px;
                """)
                title_layout.addWidget(self._strength_label)
            except Exception:
                logger.exception("Failed to evaluate password strength")
        
        title_layout.addStretch()
        text_layout.addLayout(title_layout)
        
        # 副标题：脱敏账号 + 时间
        sub_layout = QHBoxLayout()
        sub_layout.setSpacing(6)
        sub_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_account = QLabel(self.account.mask_username())
        self.lbl_account.setObjectName("lbl_account")
        sub_layout.addWidget(self.lbl_account)

        time_parts = []
        created = self.account.created_at
        updated = self.account.updated_at
        if created:
            time_parts.append(f"创建:{self._format_db_time(created)}")
        if updated:
            time_parts.append(f"修改:{self._format_db_time(updated)}")
        if time_parts:
            self.lbl_time = QLabel("  ".join(time_parts))
            self.lbl_time.setObjectName("lbl_time")
            sub_layout.addWidget(self.lbl_time)
        else:
            self.lbl_time = QLabel("")
            self.lbl_time.setObjectName("lbl_time")
            sub_layout.addWidget(self.lbl_time)
        sub_layout.addStretch()

        text_layout.addLayout(sub_layout)
        
        layout.addLayout(text_layout, 1)
        
        # 分类标签 Pill
        self.lbl_category = QLabel(self.account.category or '其他')
        self.lbl_category.setObjectName("lbl_category")
        layout.addWidget(self.lbl_category)
        
        # 右箭头
        self.lbl_arrow = QLabel("›")
        self.lbl_arrow.setObjectName("lbl_arrow")
        layout.addWidget(self.lbl_arrow)
        
        # 复制按钮容器
        self._copy_btn_container = QWidget()
        self._copy_btn_container.setStyleSheet("background: transparent;")
        btn_layout = QHBoxLayout(self._copy_btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        
        btn_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.text_tertiary};
                border: none;
                border-radius: 13px;
                font-size: 9px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
            }}
        """
        
        self.btn_copy_url = QPushButton("URL")
        self.btn_copy_url.setObjectName("btn_copy_url")
        self.btn_copy_url.setFixedSize(26, 26)
        self.btn_copy_url.setToolTip("复制网址")
        self.btn_copy_url.clicked.connect(self._on_copy_url)
        btn_layout.addWidget(self.btn_copy_url)
        
        self.btn_copy_username = QPushButton("ID")
        self.btn_copy_username.setObjectName("btn_copy_username")
        self.btn_copy_username.setFixedSize(26, 26)
        self.btn_copy_username.setToolTip("复制账号")
        self.btn_copy_username.clicked.connect(self._on_copy_username)
        btn_layout.addWidget(self.btn_copy_username)
        
        self.btn_copy_password = QPushButton("PW")
        self.btn_copy_password.setObjectName("btn_copy_password")
        self.btn_copy_password.setFixedSize(26, 26)
        self.btn_copy_password.setToolTip("复制密码")
        self.btn_copy_password.clicked.connect(self._on_copy_password)
        btn_layout.addWidget(self.btn_copy_password)
        
        layout.addWidget(self._copy_btn_container)
        
        self.setFixedHeight(56)
        self.setStyleSheet(self._build_stylesheet(colors))
    
    def _build_stylesheet(self, colors) -> str:
        """生成完整的样式表字符串（合并所有子控件样式，减少 setStyleSheet 调用次数）"""
        color = self._generate_icon_color(self.account.app_name)
        font_size = 13 if self._compact_mode else 15
        return f"""
            #accountListItem {{
                background-color: {colors.bg_primary};
                border: none;
                border-bottom: 1px solid {colors.border_light};
            }}
            #accountListItem QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 3px;
            }}
            #accountListItem QCheckBox::indicator:unchecked {{
                background-color: {colors.bg_primary};
                border: 2px solid {colors.text_secondary};
            }}
            #accountListItem QCheckBox::indicator:unchecked:hover {{
                border: 2px solid {colors.accent_blue};
            }}
            #accountListItem QCheckBox::indicator:checked {{
                background-color: {colors.accent_blue};
                border: 2px solid {colors.accent_blue};
            }}
            #accountListItem #icon_label {{
                background-color: {color};
                color: {colors.text_on_accent};
                border-radius: 18px;
                font-size: 14px;
                font-weight: bold;
            }}
            #accountListItem #lbl_name {{
                color: {colors.text_primary};
                font-size: {font_size}px;
                font-weight: 600;
            }}
            #accountListItem #lbl_account {{
                color: {colors.text_tertiary};
                font-size: 12px;
            }}
            #accountListItem #lbl_time {{
                color: {colors.text_disabled};
                font-size: 10px;
            }}
            #accountListItem #lbl_category {{
                color: {colors.text_secondary};
                font-size: 11px;
                background-color: {colors.bg_secondary};
                border-radius: 10px;
                padding: 2px 8px;
            }}
            #accountListItem #lbl_arrow {{
                color: {colors.text_disabled};
                font-size: 18px;
            }}
            #accountListItem QPushButton#btn_copy_url,
            #accountListItem QPushButton#btn_copy_username,
            #accountListItem QPushButton#btn_copy_password {{
                background-color: transparent;
                color: {colors.text_tertiary};
                border: none;
                border-radius: 13px;
                font-size: 9px;
                font-weight: bold;
                padding: 0px;
            }}
            #accountListItem QPushButton#btn_copy_url:hover,
            #accountListItem QPushButton#btn_copy_username:hover,
            #accountListItem QPushButton#btn_copy_password:hover {{
                background-color: {colors.accent_blue_bg};
                color: {colors.accent_blue};
            }}
        """

    def on_theme_changed(self):
        """主题切换时高效更新自身样式（合并为一次 setStyleSheet 调用）"""
        colors = ThemeManager.instance().colors
        self.setStyleSheet(self._build_stylesheet(colors))

        # 密码强度徽章（颜色映射随主题变化，需单独处理）
        if self._strength_label and self.account.password:
            try:
                from core.password_strength import evaluate_password_strength
                result = evaluate_password_strength(self.account.password)
                level = result['label']
                level_colors = {
                    "弱": colors.accent_red,
                    "中": colors.accent_orange,
                    "强": colors.accent_green,
                    "极强": colors.accent_blue,
                }
                level_color = level_colors.get(level, colors.text_tertiary)
                self._strength_label.setStyleSheet(f"""
                    color: {level_color};
                    font-size: 9px;
                    font-weight: bold;
                    background-color: {level_color}20;
                    border-radius: 4px;
                    padding: 1px 6px;
                """)
            except Exception as e:
                logger.warning("密码强度评估失败: %s", e)

    def set_selection_mode(self, enabled: bool):
        self.checkbox.setVisible(enabled)
        self._copy_btn_container.setVisible(not enabled)
    
    def is_checked(self) -> bool:
        return self.checkbox.isChecked()
    
    def set_checked(self, checked: bool):
        self._checkbox_clicked = False
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)
    
    def _on_check_state_changed(self, state):
        """checkbox 状态变化时回调外部"""
        self._checkbox_clicked = True
        if self.on_check_changed:
            self.on_check_changed(bool(state))
    
    def set_column_visible(self, column, visible):
        mapping = {
            'icon': getattr(self, 'icon_label', None),
            'app_name': getattr(self, 'lbl_name', None),
            'username': getattr(self, 'lbl_account', None),
            'strength': getattr(self, '_strength_label', None),
            'category': getattr(self, 'lbl_category', None),
            'arrow': getattr(self, 'lbl_arrow', None),
            'time': getattr(self, 'lbl_time', None),
        }
        widget = mapping.get(column)
        if widget:
            widget.setVisible(visible)

    def _on_copy_url(self):
        try:
            url = self.account.url or ''
            if url:
                self._clipboard.copy_text(url)
                self._show_copy_toast("网址")
        except Exception as e:
            logger.warning("复制网址失败: %s", e)
    
    def _on_copy_username(self):
        try:
            username = self.account.username or ''
            if username:
                self._clipboard.copy_text(username)
                self._show_copy_toast("账号")
        except Exception as e:
            logger.warning("复制账号失败: %s", e)
    
    def _on_copy_password(self):
        try:
            password = self.account.password or ''
            if password:
                self._clipboard.copy_text(password, is_password=True)
                self._show_copy_toast("密码", is_password=True)
        except Exception as e:
            logger.warning("复制密码失败: %s", e)
    
    def _show_copy_toast(self, label, is_password=False):
        try:
            parent = self.window()
            if parent and hasattr(parent, 'show_copy_toast'):
                parent.show_copy_toast(f"{label}已复制", is_password=is_password)
        except Exception as e:
            logger.debug("显示复制提示失败: %s", e)
    
    @staticmethod
    def _format_db_time(value) -> str:
        """将数据库 UTC 时间转换为本地日期字符串"""
        if not value:
            return ''
        if hasattr(value, 'strftime'):
            # datetime 对象（可能是 naive，按 UTC 处理）
            try:
                from datetime import timezone
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone().strftime('%Y-%m-%d')
            except Exception as e:
                logger.debug("时间格式化失败: %s", e)
                return value.strftime('%Y-%m-%d')
        # 字符串格式
        try:
            from datetime import datetime, timezone
            s = str(value).replace('Z', '+00:00')
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.astimezone().strftime('%Y-%m-%d')
        except Exception as e:
            logger.debug("时间格式化失败: %s", e)
            return str(value)[:10]

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
