"""
剪贴板管理模块
安全复制密码，支持定时自动清空
"""
import threading
import time
import pyperclip


class ClipboardManager:
    """剪贴板管理器：安全复制，定时清空密码"""
    
    def __init__(self, clear_delay: int = 20):
        """
        初始化剪贴板管理器
        
        Args:
            clear_delay: 密码清空延迟时间（秒），默认 20 秒
        """
        self.clear_delay = clear_delay
        self._timer = None
        self._last_password = None
    
    def copy_text(self, text: str, is_password: bool = False):
        """
        复制文本到剪贴板
        
        Args:
            text: 要复制的文本
            is_password: 是否是密码（密码会启动定时清空）
        """
        pyperclip.copy(text)
        
        if is_password and text:
            self._last_password = text
            self._start_timer()
    
    def _start_timer(self):
        """启动清空定时器"""
        # 取消之前的定时器
        if self._timer and self._timer.is_alive():
            self._timer.cancel()
        
        # 创建新定时器
        self._timer = threading.Timer(self.clear_delay, self._clear_password)
        self._timer.daemon = True
        self._timer.start()
    
    def _clear_password(self):
        """清空剪贴板中的密码"""
        try:
            current = pyperclip.paste()
            # 只有当剪贴板内容仍是该密码时才清空
            if current == self._last_password:
                pyperclip.copy('')
        except Exception:
            pass
        finally:
            self._last_password = None
    
    def clear(self):
        """立即清空剪贴板"""
        if self._timer and self._timer.is_alive():
            self._timer.cancel()
        pyperclip.copy('')
        self._last_password = None
    
    def __del__(self):
        """析构时清理"""
        if self._timer and self._timer.is_alive():
            self._timer.cancel()
