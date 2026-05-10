"""
AI 一句话备注生成服务
根据应用名、网址、分类生成账号用途描述
"""
import logging

logger = logging.getLogger(__name__)


class OllamaUnavailableError(Exception):
    """Ollama 服务不可用异常"""
    pass


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

        Raises:
            OllamaUnavailableError: Ollama 服务不可用时
            ValueError: 应用名称为空时
        """
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            raise OllamaUnavailableError("Ollama 服务不可用，请确保本地 Ollama 已启动")

        if not app_name:
            raise ValueError("应用名称不能为空")

        return ai_manager.generate_remark_async(app_name, url, category, remark)

    def generate_remark_direct(self, app_name: str, url: str = "", category: str = "", remark: str = "") -> str:
        """
        直接同步生成 AI 一句话备注（不经过 QEventLoop，直接调用 OllamaClient）

        适用于后台线程中直接调用，避免嵌套事件循环风险。
        """
        from ai.ollama_client import OllamaClient
        from services.ai_service_manager import AIServiceManager

        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            raise OllamaUnavailableError("Ollama 服务不可用，请确保本地 Ollama 已启动")

        if not app_name:
            raise ValueError("应用名称不能为空")

        state = ai_manager.get_state()
        client = OllamaClient(model=state.model_name or "gemma4:4b", timeout=300)

        prompt = f"""根据应用名称、网址、分类和用户手动备注，生成一句简洁的账号用途描述。

要求：
- 只生成一句话，20字以内
- 简洁明了
- 直接返回描述内容，不要加引号或任何前缀
- 不要包含任何说明性文字

应用名称：{app_name}
网址：{url or '无'}
分类：{category or '未分类'}
用户手动备注：{remark or '无'}

用途描述："""

        result = client.generate(prompt=prompt, temperature=0.3)
        ai_remark = str(result).strip().strip('"').strip("'")
        if not ai_remark:
            raise Exception("AI 返回了空内容，请重试")
        return ai_remark

    def generate_ai_remark(self, app_name: str, url: str = "", category: str = "", remark: str = "") -> str:
        """
        生成 AI 一句话备注（已废弃，请使用 generate_remark_direct 或 generate_ai_remark_async）

        .. deprecated::
            此方法在主线程同步调用会阻塞 UI，请改用 generate_remark_direct（后台线程）或 generate_ai_remark_async（异步）。
        """
        logger.warning(
            "AIRemarkService.generate_ai_remark() is deprecated and will be removed. "
            "Use generate_remark_direct() instead."
        )
        return self.generate_remark_direct(app_name, url, category, remark)
