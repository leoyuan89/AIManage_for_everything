"""
图标管理模块
集中加载 SVG 图标，支持动态着色，所有图标文件存放于 assets/icons/ 目录。
"""
from pathlib import Path
from typing import Dict
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import Qt, QByteArray


class IconManager:
    """图标管理器：负责从 assets/icons/ 加载 SVG 图标"""

    ICONS_DIR = Path(__file__).parent.parent / 'assets' / 'icons'
    _icon_cache: Dict[str, QIcon] = {}

    @classmethod
    def load_svg(cls, name: str, size: int = 24, color: str = None) -> QIcon:
        """
        加载 SVG 文件并渲染为 QIcon。

        Args:
            name: SVG 文件名（如 'icon_help.svg'）
            size: 输出图标尺寸（正方形）
            color: 若提供，将替换 SVG 中的 'currentColor' 为此颜色

        Returns:
            QIcon，加载失败返回空 QIcon
        """
        cache_key = f"{name}:{size}:{color}"
        if cache_key in cls._icon_cache:
            return cls._icon_cache[cache_key]

        svg_path = cls.ICONS_DIR / name
        if not svg_path.exists():
            return QIcon()

        svg_content = svg_path.read_text(encoding='utf-8')
        if color:
            svg_content = svg_content.replace('currentColor', color)

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        renderer = QSvgRenderer(QByteArray(svg_content.encode('utf-8')))
        painter = QPainter(pixmap)
        try:
            renderer.render(painter)
        finally:
            painter.end()

        icon = QIcon(pixmap)
        cls._icon_cache[cache_key] = icon
        return icon

    @classmethod
    def app_icon(cls) -> QIcon:
        """加载应用主图标（用于任务栏和弹窗标题栏）"""
        return cls.load_svg('app_icon.svg', size=256)

    @classmethod
    def help_icon(cls, size: int = 24, color: str = '#FF6B35') -> QIcon:
        """加载帮助灯泡图标"""
        return cls.load_svg('icon_help.svg', size=size, color=color)

    @classmethod
    def compact_icon(cls, size: int = 20, color: str = '#666666') -> QIcon:
        """加载紧凑视图列表图标"""
        return cls.load_svg('icon_compact.svg', size=size, color=color)
