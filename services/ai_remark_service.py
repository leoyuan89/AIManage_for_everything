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
    
    def generate_ai_remark(self, app_name: str, url: str = "", category: str = "") -> str:
        """
        生成 AI 一句话备注
        
        Args:
            app_name: 应用名称
            url: 网址
            category: 分类
            
        Returns:
            生成的一句话备注（不超过20个字）
        """
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            raise Exception("Ollama 服务不可用，请确保本地 Ollama 已启动")
        
        if not app_name:
            raise ValueError("应用名称不能为空")
        
        prompt = f"""根据应用名称、网址和分类，用一句话描述这个账号的用途。

要求：
- 不超过20个字
- 简洁明了
- 直接返回描述内容，不要加引号或额外解释

应用名称：{app_name}
网址：{url or '无'}
分类：{category or '未分类'}

用途描述："""
        
        try:
            from ai.ollama_client import OllamaClient
            state = ai_manager.get_state()
            ollama = OllamaClient(model=state.model_name or "gemma4:4b")
            result = ollama.generate(
                prompt=prompt,
                temperature=0.3,
                num_predict=50
            )
            
            # 清洗结果
            remark = result.strip()
            # 移除可能的引号
            remark = remark.strip('"').strip("'").strip()
            # 限制长度
            if len(remark) > 30:
                remark = remark[:30]
            
            return remark
            
        except Exception as e:
            raise Exception(f"AI 备注生成失败: {str(e)}")
