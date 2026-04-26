"""
分类服务模块
管理 AI 智能分类和分类缓存
"""
from typing import Optional
from core.database import DatabaseManager


class CategoryService:
    """分类服务：AI 智能分类 + 缓存管理"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化分类服务
        
        Args:
            db_manager: 数据库管理器
        """
        self.db = db_manager
    
    def get_category(self, app_name: str, url: str = "", use_cache: bool = True) -> str:
        """
        获取应用分类（优先缓存，其次 AI）
        
        Args:
            app_name: 应用名称
            url: 网址
            use_cache: 是否使用缓存
            
        Returns:
            分类名称
        """
        if not app_name:
            return '其他'
        
        # 1. 检查缓存
        if use_cache:
            app_name_hash = self._hash_app_name(app_name)
            cached = self.db.get_cached_category(app_name_hash)
            if cached:
                return cached
        
        # 2. 规则匹配（常见应用直接分类）
        rule_category = self._rule_based_categorize(app_name, url)
        if rule_category:
            # 存入缓存
            if use_cache:
                self.cache_category(app_name, rule_category)
            return rule_category
        
        # 3. AI 分类
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        if ai_manager.is_available():
            try:
                from ai.ollama_client import OllamaClient
                state = ai_manager.get_state()
                ollama = OllamaClient(model=state.model_name or "gemma4:4b")
                ai_category = ollama.categorize(app_name, url)
                # 存入缓存
                if use_cache:
                    self.cache_category(app_name, ai_category)
                return ai_category
            except Exception as e:
                print(f"AI 分类失败: {e}")
        
        return '其他'
    
    def cache_category(self, app_name: str, category: str):
        """
        缓存分类结果
        
        Args:
            app_name: 应用名称
            category: 分类
        """
        app_name_hash = self._hash_app_name(app_name)
        self.db.cache_category(app_name_hash, category)
    
    def update_cached_category(self, app_name: str, category: str):
        """
        更新缓存的分类（用户修正后）
        
        Args:
            app_name: 应用名称
            category: 新的分类
        """
        self.cache_category(app_name, category)
    
    def batch_categorize_uncategorized(self) -> int:
        """
        批量分类未分类的账号
        
        Returns:
            成功分类的数量
        """
        from services.ai_service_manager import AIServiceManager
        if not AIServiceManager.instance().is_available():
            print("Ollama 不可用，无法批量分类")
            return 0
        
        # 获取所有账号
        accounts = self.db.get_all_accounts()
        
        # 筛选出分类为"其他"或空的账号
        uncategorized = [a for a in accounts if a.get('category') in ['其他', '', None]]
        
        count = 0
        for account in uncategorized:
            try:
                app_name = account.get('app_name', '')
                url = account.get('url', '')
                
                if not app_name:
                    continue
                
                # 检查缓存
                app_name_hash = self._hash_app_name(app_name)
                cached = self.db.get_cached_category(app_name_hash)
                
                if cached:
                    category = cached
                else:
                    from ai.ollama_client import OllamaClient
                    state = AIServiceManager.instance().get_state()
                    ollama = OllamaClient(model=state.model_name or "gemma4:4b")
                    category = ollama.categorize(app_name, url)
                    self.cache_category(app_name, category)
                
                # 更新账号分类
                if category != '其他':
                    self.db.update_account(account['id'], {'category': category})
                    count += 1
                    
            except Exception as e:
                print(f"批量分类账号 {account.get('id')} 失败: {e}")
                continue
        
        return count
    
    def _hash_app_name(self, app_name: str) -> str:
        """计算应用名的哈希（用于缓存表）"""
        import hashlib
        return hashlib.sha256(app_name.encode('utf-8')).hexdigest()
    
    def _rule_based_categorize(self, app_name: str, url: str = "") -> Optional[str]:
        """
        基于规则的快速分类
        
        Returns:
            分类名或 None（返回完整路径，如 '工作>开发工具'）
        """
        app_lower = app_name.lower()
        url_lower = url.lower()
        
        # 金融类关键词
        finance_keywords = ['银行', '支付', '宝', '财富', '证券', '保险', 'paypal', 
                           'bank', 'pay', 'alipay', 'wechatpay', 'wallet']
        for kw in finance_keywords:
            if kw in app_lower or kw in url_lower:
                return '金融'
        
        # 社交类关键词
        social_keywords = ['微信', 'QQ', '微博', '抖音', '小红书', '知乎', '贴吧',
                          'wechat', 'weibo', 'douyin', 'xiaohongshu', 'zhihu']
        for kw in social_keywords:
            if kw in app_lower or kw in url_lower:
                return '社交'
        
        # 邮箱类关键词
        email_keywords = ['邮箱', 'mail', 'email', 'gmail', 'outlook', '163', '126', 'qq.com']
        for kw in email_keywords:
            if kw in app_lower or kw in url_lower:
                return '邮箱'
        
        # 游戏类关键词
        game_keywords = ['游戏', 'game', 'steam', 'epic', 'blizzard', 'riot', '腾讯游戏',
                        '网易游戏', '米哈游', 'miHoYo']
        for kw in game_keywords:
            if kw in app_lower or kw in url_lower:
                return '游戏'
        
        # 工作类细分（返回完整路径）
        if 'github' in app_lower or 'gitlab' in app_lower:
            return '工作>开发工具'
        if 'figma' in app_lower or 'sketch' in app_lower:
            return '工作>设计'
        
        # 工作类（无法细分的返回一级）
        work_keywords = ['工作', '办公', '企业', 'jira', 'confluence',
                        'slack', '飞书', '钉钉', '企业微信', 'work', 'office']
        for kw in work_keywords:
            if kw in app_lower or kw in url_lower:
                return '工作'
        
        return None
    
    def get_all_categories(self) -> list:
        """获取所有分类列表（只从数据库动态读取，不再硬编码默认分类）"""
        db_cats = set()
        try:
            db_cats = set(self.db.get_categories())
        except Exception as e:
            print(f"[CategoryService] Failed to read categories from DB: {e}")
        
        # 只返回数据库中真实存在的分类
        all_cats = db_cats
        result = sorted(all_cats - {'其他'})
        if '其他' in all_cats:
            result.append('其他')
        return result
