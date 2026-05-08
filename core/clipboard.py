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
        self._timer_lock = threading.Lock()
        self._last_password = None
        self._password_lock = threading.Lock()
    
    def copy_text(self, text: str, is_password: bool = False):
        """
        复制文本到剪贴板

        Args:
            text: 要复制的文本
            is_password: 是否是密码（密码会启动定时清空）
        """
        try:
            pyperclip.copy(text)
        except pyperclip.PyperclipException as e:
            import logging
            logging.getLogger(__name__).warning(f"剪贴板复制失败（可能被占用）: {e}")
            raise RuntimeError("剪贴板被占用，请稍后重试") from e
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"复制到剪贴板时发生未知错误: {e}")
            raise RuntimeError(f"复制失败: {e}") from e

        if is_password and text:
            with self._password_lock:
                self._last_password = text
            self._start_timer()
    
    def _start_timer(self):
        """启动清空定时器"""
        with self._timer_lock:
            # 取消之前的定时器
            if self._timer and self._timer.is_alive():
                self._timer.cancel()
            
            # 创建新定时器
            self._timer = threading.Timer(self.clear_delay, self._clear_password)
            self._timer.daemon = True
            self._timer.start()
    
    def _clear_password(self):
        """清空剪贴板中的密码"""
        with self._password_lock:
            last_pwd = self._last_password
        try:
            current = pyperclip.paste()
            # 只有当剪贴板内容仍是该密码时才清空
            if current == last_pwd:
                pyperclip.copy('')
        except Exception:
            import logging
            logging.getLogger(__name__).debug("清空剪贴板时发生异常", exc_info=True)
        finally:
            with self._password_lock:
                self._last_password = None
    
    def clear(self):
        """立即清空剪贴板"""
        with self._timer_lock:
            if self._timer and self._timer.is_alive():
                self._timer.cancel()
                self._timer = None
        pyperclip.copy('')
        self._last_password = None
    
    def __del__(self):
        """析构时清理"""
        try:
            with self._timer_lock:
                if self._timer and self._timer.is_alive():
                    self._timer.cancel()
        except Exception:
            pass
