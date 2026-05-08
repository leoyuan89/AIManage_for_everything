"""
主题管理模块
提供 qt-material 主题加载 + ThemeColors 色板系统 + 图标管理
"""
import logging
import threading
from dataclasses import dataclass
from typing import Dict
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QIcon

logger = logging.getLogger(__name__)


@dataclass
class ThemeColors:
    """主题色板 —— 覆盖项目中所有视觉颜色"""

    # === 背景 ===
    bg_primary: str          # 主背景 (white / #1E1E1E)
    bg_secondary: str        # 面板/bar 背景 (#f5f5f5 / #252525)
    bg_tertiary: str         # 按钮/控件背景 (#f0f0f0 / #2D2D2D)
    bg_surface: str          # 侧边栏/AI面板 (#fafafa / #1A1A1A)
    bg_hover: str            # hover 态 (#eeeeee / #353535)
    bg_card: str             # 卡片/浮层 (#f9f9f9 / #212121)

    # === 强调色背景 ===
    accent_blue_bg: str          # 蓝色选中/highlight (#E3F2FD / #1A3A5C)
    accent_blue_bg_hover: str    # 蓝色 hover (#BBDEFB / #1E4A70)
    accent_blue_bg_light: str    # 浅蓝底 badge (#E8F4FD / #0D2B4A)
    accent_orange_bg: str        # 橙色底 badge (#FEF2EA / #3E2723)
    accent_red_bg: str           # 红色底 (#FFEBEE / #3E1A1A)
    accent_green_bg: str         # 绿色底 (#E8F5E9 / #1B3D1B)

    # === 文字 ===
    text_primary: str        # 主要文字 (#1A1A1A / #E0E0E0)
    text_secondary: str      # 次要文字 (#666666 / #AAAAAA)
    text_tertiary: str       # 三级文字 (#999999 / #777777)
    text_disabled: str       # 禁用文字 (#CCCCCC / #555555)
    text_on_accent: str      # 强调色上的文字 (white / #E0E0E0)
    text_on_dark: str        # 深色底上的文字 (white / white)

    # === 边框 ===
    border_default: str      # 默认边框 (#DDDDDD / #3D3D3D)
    border_medium: str       # 中色边框 (#CCCCCC / #444444)
    border_light: str        # 浅色边框 (#E5E5E5 / #333333)
    border_subtle: str       # 极浅边框 (#F0F0F0 / #2A2A2A)

    # === 品牌/强调色 ===
    accent_blue: str         # 主蓝色 (#1976D2 / #64B5F6)
    accent_blue_dark: str    # 深蓝 (#1565C0 / #42A5F5)
    accent_blue_light: str   # 浅蓝 (#90CAF9 / #2196F3)
    accent_blue_text: str    # 蓝色文字 (#1565C0 / #90CAF9)

    accent_red: str          # 红色 (#F44336 / #EF5350)
    accent_red_dark: str     # 深红 (#D32F2F / #E57373)
    accent_orange: str       # 橙色 (#FF6B35 / #FF8A65)
    accent_orange_dark: str  # 深橙 (#E55A2B / #FF7043)
    accent_orange_text: str  # 橙色文字 (#E65100 / #FFAB91)

    accent_green: str        # 绿色 (#4CAF50 / #66BB6A)
    accent_green_dark: str   # 深绿 (#45A049 / #81C784)

    # === AI 面板特殊色 ===
    ai_thinking_bg: str      # AI思考区背景 (#FFF8E1 / #2D2818)
    ai_thinking_text: str    # AI思考区文字 (#F57F17 / #FFD54F)
    ai_result_bg: str        # AI结果区背景 (#F1F8E9 / #1B2E1B)
    ai_result_text: str      # AI结果区文字 (#33691E / #A5D6A7)
    ai_mode_plan_bg: str     # Plan 模式 (#E3F2FD / #1A3A5C)
    ai_mode_build_bg: str    # Build 模式 (#FFF3E0 / #3E2723)

    # === 欢迎卡片色（原iOS风格 → Material风格）===
    welcome_title: str       # 欢迎标题 (#1D1D1F / #E0E0E0)
    welcome_sub: str         # 欢迎副标题 (#86868B / #AAAAAA)
    welcome_card_bg: str     # 卡片背景 (#FAFAFA / #252525)
    welcome_card_border: str # 卡片边框 (#E5E5E5 / #3D3D3D)
    welcome_example_text: str # 示例文字 (#515154 / #BBBBBB)


# ============================================================
# 预设色板
# ============================================================

LIGHT_COLORS = ThemeColors(
    bg_primary="#FFFFFF",
    bg_secondary="#F5F5F5",
    bg_tertiary="#F0F0F0",
    bg_surface="#FAFAFA",
    bg_hover="#EEEEEE",
    bg_card="#F9F9F9",

    accent_blue_bg="#E3F2FD",
    accent_blue_bg_hover="#BBDEFB",
    accent_blue_bg_light="#E8F4FD",
    accent_orange_bg="#FEF2EA",
    accent_red_bg="#FFEBEE",
    accent_green_bg="#E8F5E9",

    text_primary="#1A1A1A",
    text_secondary="#666666",
    text_tertiary="#999999",
    text_disabled="#CCCCCC",
    text_on_accent="#FFFFFF",
    text_on_dark="#FFFFFF",

    border_default="#DDDDDD",
    border_medium="#CCCCCC",
    border_light="#E5E5E5",
    border_subtle="#F0F0F0",

    accent_blue="#1976D2",
    accent_blue_dark="#1565C0",
    accent_blue_light="#90CAF9",
    accent_blue_text="#1565C0",

    accent_red="#F44336",
    accent_red_dark="#D32F2F",
    accent_orange="#FF6B35",
    accent_orange_dark="#E55A2B",
    accent_orange_text="#E65100",

    accent_green="#4CAF50",
    accent_green_dark="#45A049",

    ai_thinking_bg="#FFF8E1",
    ai_thinking_text="#F57F17",
    ai_result_bg="#F1F8E9",
    ai_result_text="#33691E",
    ai_mode_plan_bg="#E3F2FD",
    ai_mode_build_bg="#FFF3E0",

    welcome_title="#1D1D1F",
    welcome_sub="#86868B",
    welcome_card_bg="#FAFAFA",
    welcome_card_border="#E5E5E5",
    welcome_example_text="#515154",
)

DARK_COLORS = ThemeColors(
    bg_primary="#1E1E1E",
    bg_secondary="#252525",
    bg_tertiary="#2D2D2D",
    bg_surface="#1A1A1A",
    bg_hover="#353535",
    bg_card="#212121",

    accent_blue_bg="#1A3A5C",
    accent_blue_bg_hover="#1E4A70",
    accent_blue_bg_light="#0D2B4A",
    accent_orange_bg="#3E2723",
    accent_red_bg="#3E1A1A",
    accent_green_bg="#1B3D1B",

    text_primary="#E0E0E0",
    text_secondary="#AAAAAA",
    text_tertiary="#777777",
    text_disabled="#555555",
    text_on_accent="#E0E0E0",
    text_on_dark="#E0E0E0",

    border_default="#3D3D3D",
    border_medium="#444444",
    border_light="#333333",
    border_subtle="#2A2A2A",

    accent_blue="#64B5F6",
    accent_blue_dark="#42A5F5",
    accent_blue_light="#2196F3",
    accent_blue_text="#90CAF9",

    accent_red="#EF5350",
    accent_red_dark="#E57373",
    accent_orange="#FF8A65",
    accent_orange_dark="#FF7043",
    accent_orange_text="#FFAB91",

    accent_green="#66BB6A",
    accent_green_dark="#81C784",

    ai_thinking_bg="#2D2818",
    ai_thinking_text="#FFD54F",
    ai_result_bg="#1B2E1B",
    ai_result_text="#A5D6A7",
    ai_mode_plan_bg="#1A3A5C",
    ai_mode_build_bg="#3E2723",

    welcome_title="#E0E0E0",
    welcome_sub="#AAAAAA",
    welcome_card_bg="#252525",
    welcome_card_border="#3D3D3D",
    welcome_example_text="#BBBBBB",
)


# ============================================================
# 主题管理器（单例）
# ============================================================

class ThemeManager(QObject):
    """全局主题管理器 —— 单例"""

    theme_changed = pyqtSignal(str)
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> 'ThemeManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._current = 'light'
        self._colors = LIGHT_COLORS
        self._app = None

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    @property
    def current_theme(self) -> str:
        return self._current

    @property
    def is_dark(self) -> bool:
        return self._current == 'dark'

    def init_app(self, app: QApplication, theme: str = 'light'):
        """应用启动时初始化主题"""
        self._app = app
        self._current = theme
        self._colors = DARK_COLORS if theme == 'dark' else LIGHT_COLORS
        self._apply_qt_material(app, theme)

    def apply_theme(self, theme: str):
        """切换主题（用户在设置中触发）"""
        self._current = theme
        self._colors = DARK_COLORS if theme == 'dark' else LIGHT_COLORS

        if self._app:
            self._apply_qt_material(self._app, theme)

        self.theme_changed.emit(theme)

    def _apply_qt_material(self, app: QApplication, theme: str):
        """应用 qt-material 底层样式"""
        try:
            from qt_material import apply_stylesheet
            if theme == 'dark':
                apply_stylesheet(app, theme='dark_blue.xml')
            else:
                apply_stylesheet(app, theme='light_blue.xml')
            logger.info("Applied qt-material theme: %s", theme)
        except ImportError:
            logger.warning("qt-material not installed, using default style")
        except Exception as e:
            logger.warning("Failed to apply theme: %s", e)


# ============================================================
# 图标管理
# ============================================================

_ICON_MAP: Dict[str, str] = {
    # 应用级图标
    "add": "fa5s.plus",
    "settings": "fa5s.cog",
    "lock": "fa5s.lock",
    "unlock": "fa5s.lock-open",
    "search": "fa5s.search",
    "delete": "fa5s.trash-alt",
    "export": "fa5s.file-export",
    "import": "fa5s.file-import",
    "sync": "fa5s.sync-alt",
    "recycle": "fa5s.recycle",
    "close": "fa5s.times",
    "edit": "fa5s.edit",
    "copy": "fa5s.copy",
    "eye": "fa5s.eye",
    "eye_slash": "fa5s.eye-slash",
    "check": "fa5s.check",
    "star": "fa5s.star",
    "ai": "fa5s.robot",
    "category": "fa5s.folder",
    "tag": "fa5s.tags",
    "url": "fa5s.globe",
    "password": "fa5s.key",
    "user": "fa5s.user",
    "arrow_right": "fa5s.chevron-right",
    "arrow_down": "fa5s.chevron-down",
    "refresh": "fa5s.redo-alt",
    "clear": "fa5s.eraser",
    "select_all": "fa5s.check-double",
    "deselect": "fa5s.times-circle",
    "sort": "fa5s.sort",
    "organize": "fa5s.sitemap",
    "warning": "fa5s.exclamation-triangle",
    "info": "fa5s.info-circle",
    "help": "fa5s.question-circle",
    "light_theme": "fa5s.sun",
    "dark_theme": "fa5s.moon",
}

# 图标颜色映射（根据主题获取）
def _icon_color(colors: ThemeColors, category: str = "default") -> str:
    """根据类别返回当前主题下的图标颜色"""
    mapping = {
        "default": colors.text_secondary,
        "primary": colors.accent_blue,
        "danger": colors.accent_red,
        "success": colors.accent_green,
        "warning": colors.accent_orange,
        "on_primary": colors.text_on_accent,
        "disabled": colors.text_disabled,
    }
    return mapping.get(category, colors.text_secondary)


def get_icon(name: str, color: str = "default") -> QIcon:
    """获取图标（qtawesome）"""
    import qtawesome as qta
    icon_name = _ICON_MAP.get(name, "fa5s.circle")
    colors = ThemeManager.instance().colors
    hex_color = _icon_color(colors, color)
    return qta.icon(icon_name, color=hex_color)


def get_icon_char(name: str, fallback: str = "") -> str:
    """如果 qtawesome 不可用，返回 fallback 字符"""
    try:
        import qtawesome as qta
        icon_name = _ICON_MAP.get(name)
        if icon_name:
            return ""
    except ImportError:
        pass
    return fallback


# ============================================================
# 便捷样式生成函数（常用预设）
# ============================================================

def style_button_primary(colors: ThemeColors) -> str:
    """主操作按钮（蓝色实心）"""
    return f"""
        QPushButton {{
            background-color: {colors.accent_blue};
            color: {colors.text_on_accent};
            border: none;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {colors.accent_blue_dark};
        }}
    """


def style_button_danger(colors: ThemeColors) -> str:
    """危险操作按钮（红色实心）"""
    return f"""
        QPushButton {{
            background-color: {colors.accent_red};
            color: {colors.text_on_dark};
            border: none;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {colors.accent_red_dark};
        }}
    """


def style_bar(colors: ThemeColors, border_side: str = "bottom") -> str:
    """工具/状态栏"""
    return f"background-color: {colors.bg_secondary}; border-{border_side}: 1px solid {colors.border_default};"


def style_panel(colors: ThemeColors, border_side: str = "right") -> str:
    """侧边面板"""
    return f"background-color: {colors.bg_surface}; border-{border_side}: 1px solid {colors.border_default};"


def style_input(colors: ThemeColors) -> str:
    """输入框统一风格"""
    return f"""
        QLineEdit {{
            background-color: {colors.bg_primary};
            color: {colors.text_primary};
            border: 1px solid {colors.border_default};
            border-radius: 4px;
            padding: 6px 10px;
        }}
        QLineEdit:focus {{
            border-color: {colors.accent_blue};
        }}
    """


def style_scrollbar(colors: ThemeColors) -> str:
    """滚动条"""
    return f"""
        QScrollBar:vertical {{
            background: {colors.bg_primary};
            width: 8px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {colors.border_default};
            border-radius: 4px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {colors.text_tertiary};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0;
        }}
    """
