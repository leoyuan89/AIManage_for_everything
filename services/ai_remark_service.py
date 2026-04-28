"""
AI 一句话备注生成服务
根据应用名、网址、分类生成账号用途描述
"""
class AIRemarkService:
    """AI 备注生成服务"""
    
    def __init__(self):
        """初始化服务"""
        pass
    
    def is_available(self) -> bool:
        """检查 AI 服务是否可用"""
        from services.ai_service_manager import AIServiceManager
        return AIServiceManager.instance().is_available()
    
    def generate_ai_remark(self, app_name: str, url: str = "", category: str = "", remark: str = "") -> str:
        """
        生成 AI 一句话备注
        
        Args:
            app_name: 应用名称
            url: 网址
            category: 分类
            remark: 用户手动备注
            
        Returns:
            生成的一句话备注（不超过20个字）
        """
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            raise Exception("Ollama 服务不可用，请确保本地 Ollama 已启动")
        
        if not app_name:
            raise ValueError("应用名称不能为空")
        
        prompt = f"""根据应用名称、网址、分类和用户手动备注，用一句话描述这个账号的用途。

要求：
- 只输出一句话，20个字以内
- 简洁明了
- 直接返回描述内容，不要加引号或额外解释
- 不要输出任何其他文字、说明、分析

应用名称：{app_name}
网址：{url or '无'}
分类：{category or '未分类'}
用户手动备注：{remark or '无'}

用途描述："""
        
        try:
            from ai.ollama_client import OllamaClient
            state = ai_manager.get_state()
            ollama = OllamaClient(model=state.model_name or "gemma4:4b")
            result = ollama.generate(
                prompt=prompt,
                temperature=0.3
            )
            
            # 清洗结果
            ai_remark = result.strip()
            # 移除可能的引号
            ai_remark = ai_remark.strip('"').strip("'").strip()
            if not ai_remark:
                raise Exception("AI 返回了空内容，请重试")
            # 备注完整保留，不做截断
            
            return ai_remark
            
        except Exception as e:
            raise Exception(f"AI 备注生成失败: {str(e)}")
