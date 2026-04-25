"""
主题管理模块
提供 qt-material 主题加载和应用功能
"""
from PyQt6.QtWidgets import QApplication


def apply_theme_to_app(app: QApplication, theme: str = 'light'):
    """
    应用 qt-material 主题到 QApplication
    
    Args:
        app: QApplication 实例
        theme: 'light' 或 'dark'
    """
    try:
        from qt_material import apply_stylesheet
        if theme == 'dark':
            apply_stylesheet(app, theme='dark_blue.xml')
        else:
            apply_stylesheet(app, theme='light_blue.xml')
        print(f"[INFO] Applied qt-material theme: {theme}")
    except ImportError:
        print("[WARNING] qt-material not installed, using default style")
    except Exception as e:
        print(f"[WARNING] Failed to apply theme: {e}")
        print("[INFO] Using default style")
