"""
AI 一句话备注生成服务
根据应用名、网址、分类生成账号用途描述
"""
import logging

logger = logging.getLogger(__name__)


class AIRemarkService:
    """AI 备注生成服务"""

    def __init__(self):
        """初始化服务"""
        pass

    def is_available(self) -> bool:
        """检查 AI 服务是否可用"""
        from services.ai_service_manager import AIServiceManager
        return AIServiceManager.instance().is_available()

    @property
    def task_finished(self):
        """AI 任务完成信号（代理自 AIServiceManager）"""
        from services.ai_service_manager import AIServiceManager
        return AIServiceManager.instance().task_finished

    @property
    def task_failed(self):
        """AI 任务失败信号（代理自 AIServiceManager）"""
        from services.ai_service_manager import AIServiceManager
        return AIServiceManager.instance().task_failed

    def generate_ai_remark_async(self, app_name: str, url: str = "", category: str = "", remark: str = "") -> str:
        """
        异步生成 AI 一句话备注

        Args:
            app_name: 应用名称
            url: 网址
            category: 分类
            remark: 用户手动备注

        Returns:
            task_id，通过 task_finished / task_failed 信号接收结果
        """
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            raise Exception("Ollama 服务不可用，请确保本地 Ollama 已启动")

        if not app_name:
            raise ValueError("应用名称不能为空")

        return ai_manager.generate_remark_async(app_name, url, category, remark)

    def generate_ai_remark(self, app_name: str, url: str = "", category: str = "", remark: str = "") -> str:
        """
        生成 AI 一句话备注（已废弃，请使用 generate_ai_remark_async）

        .. deprecated::
            此方法在主线程同步调用会阻塞 UI，请改用 generate_ai_remark_async。
        """
        logger.warning(
            "AIRemarkService.generate_ai_remark() is deprecated and will be removed. "
            "Use generate_ai_remark_async() instead."
        )

        # 向后兼容：通过 QEventLoop 包装异步调用
        # 注意：此方法不应在新代码中使用
        from PyQt6.QtCore import QEventLoop
        from services.ai_service_manager import AIServiceManager

        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            raise Exception("Ollama 服务不可用，请确保本地 Ollama 已启动")

        if not app_name:
            raise ValueError("应用名称不能为空")

        loop = QEventLoop()
        result = [None]
        error = [None]
        task_id = [None]

        def on_finished(finished_task_id, res):
            if finished_task_id == task_id[0]:
                result[0] = res
                loop.quit()

        def on_failed(failed_task_id, err):
            if failed_task_id == task_id[0]:
                error[0] = err
                loop.quit()

        ai_manager.task_finished.connect(on_finished)
        ai_manager.task_failed.connect(on_failed)

        try:
            task_id[0] = ai_manager.generate_remark_async(app_name, url, category, remark)
            loop.exec()

            if error[0] is not None:
                raise Exception(f"AI 备注生成失败: {error[0]}")

            ai_remark = str(result[0]).strip().strip('"').strip("'")
            if not ai_remark:
                raise Exception("AI 返回了空内容，请重试")
            return ai_remark

        finally:
            try:
                ai_manager.task_finished.disconnect(on_finished)
            except Exception:
                pass
            try:
                ai_manager.task_failed.disconnect(on_failed)
            except Exception:
                pass
