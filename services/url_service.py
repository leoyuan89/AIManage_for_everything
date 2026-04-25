"""
网址服务模块
"""
from typing import List, Optional, Dict
from urllib.parse import urlparse

from core.url_database import URLDatabaseManager
from models.url_item import URLItem


class URLService:
    """网址服务"""
    
    CATEGORIES = ['全部', '开发工具', '云服务', '社交平台', '学习资源', '娱乐', '购物', '其他']
    
    def __init__(self, db_manager: URLDatabaseManager):
        """
        初始化网址服务
        
        Args:
            db_manager: 网址数据库管理器
        """
        self.db = db_manager
    
    def add_url(self, url_item: URLItem) -> int:
        """
        添加新网址
        
        Args:
            url_item: 网址对象
            
        Returns:
            新网址 ID
        """
        url_data = url_item.to_dict()
        url_data.pop('id', None)
        url_data.pop('created_at', None)
        url_data.pop('updated_at', None)
        
        return self.db.insert_url(url_data)
    
    def update_url(self, url_item: URLItem) -> bool:
        """
        更新网址
        
        Args:
            url_item: 网址对象（必须包含 id）
            
        Returns:
            是否成功
        """
        if not url_item.id:
            raise ValueError("URLItem ID is required for update")
        
        url_data = url_item.to_dict()
        url_data.pop('id', None)
        url_data.pop('created_at', None)
        url_data.pop('updated_at', None)
        
        return self.db.update_url(url_item.id, url_data)
    
    def delete_url(self, url_id: int) -> bool:
        """
        删除网址
        
        Args:
            url_id: 网址 ID
            
        Returns:
            是否成功
        """
        return self.db.delete_url(url_id)
    
    def get_url(self, url_id: int) -> Optional[URLItem]:
        """
        根据 ID 获取网址
        
        Args:
            url_id: 网址 ID
            
        Returns:
            网址对象，不存在返回 None
        """
        data = self.db.get_url_by_id(url_id)
        if data:
            return URLItem.from_dict(data)
        return None
    
    def get_all_urls(self) -> List[URLItem]:
        """
        获取所有网址
        
        Returns:
            网址列表
        """
        urls_data = self.db.get_all_urls()
        return [URLItem.from_dict(data) for data in urls_data]
    
    def get_urls_by_category(self, category: str) -> List[URLItem]:
        """
        按分类获取网址
        
        Args:
            category: 分类名称
            
        Returns:
            网址列表
        """
        if category == '全部':
            return self.get_all_urls()
        
        urls_data = self.db.get_urls_by_category(category)
        return [URLItem.from_dict(data) for data in urls_data]
    
    def search_urls(self, keyword: str) -> List[URLItem]:
        """
        搜索网址
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            匹配的网址列表
        """
        urls_data = self.db.search_urls(keyword)
        return [URLItem.from_dict(data) for data in urls_data]
    
    def get_related_urls(self, account_id: int) -> List[URLItem]:
        """
        获取关联到指定账号的网址
        
        Args:
            account_id: 账号 ID
            
        Returns:
            网址列表
        """
        urls_data = self.db.get_urls_by_account(account_id)
        return [URLItem.from_dict(data) for data in urls_data]
    
    def get_categories(self) -> List[str]:
        """
        获取所有分类（从数据库动态读取，合并默认分类，支持自定义排序）
        
        Returns:
            分类名称列表
        """
        # 从数据库读取实际存在的分类
        db_cats = set()
        try:
            db_cats = set(self.db.get_categories())
        except Exception as e:
            print(f"[URLService] Failed to read categories from DB: {e}")
        
        # 读取自定义排序
        orders = {}
        try:
            orders = self.db.get_category_orders()
        except Exception:
            pass
        
        # 合并默认分类和数据库中的分类
        all_cats = set(self.CATEGORIES) | db_cats
        
        # 排序：有自定义顺序的按 sort_index 排，没有的按字母排
        def sort_key(cat):
            return (orders.get(cat, 999999), cat.lower())
        
        # 确保"全部"在第一位
        result = ['全部']
        for cat in sorted(all_cats - {'全部'}, key=sort_key):
            result.append(cat)
        return result
    
    def get_category_orders(self) -> Dict[str, int]:
        """获取分类自定义排序"""
        return self.db.get_category_orders()
    
    def save_category_orders(self, orders: Dict[str, int]):
        """保存分类自定义排序"""
        self.db.save_category_orders(orders)
    
    def rename_category(self, old_name: str, new_name: str) -> int:
        return self.db.rename_category(old_name, new_name)
    
    def add_category(self, category_name: str) -> bool:
        """新建分类（插入排序表，不创建任何网址）"""
        return self.db.add_category_order(category_name)

    def delete_category(self, category_name: str) -> int:
        return self.db.delete_category(category_name)
    
    def get_favicon_url(self, url: str) -> str:
        """
        获取网站的 favicon 地址
        
        Args:
            url: 网址
            
        Returns:
            favicon URL
        """
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
        except:
            return ""
    
    @staticmethod
    def auto_categorize(url: str, title: str = "") -> str:
        """
        根据网址自动分类
        
        Args:
            url: 网址
            title: 标题
            
        Returns:
            分类名称
        """
        url_lower = url.lower()
        title_lower = title.lower()
        
        # 开发工具
        dev_keywords = ['github', 'gitlab', 'gitee', 'stackoverflow', 'docs.', 'api.', 'developer']
        if any(kw in url_lower for kw in dev_keywords):
            return '开发工具'
        
        # 云服务
        cloud_keywords = ['aliyun', 'tencent', 'cloud', 'aws', 'azure', 'vercel', 'heroku']
        if any(kw in url_lower for kw in cloud_keywords):
            return '云服务'
        
        # 社交平台
        social_keywords = ['weibo', 'twitter', 'facebook', 'linkedin', 'zhihu', 'reddit']
        if any(kw in url_lower for kw in social_keywords):
            return '社交平台'
        
        # 学习资源
        edu_keywords = ['coursera', 'mooc', 'tutorial', 'edu', 'academy', 'learn']
        if any(kw in url_lower for kw in edu_keywords):
            return '学习资源'
        
        # 娱乐
        ent_keywords = ['youtube', 'bilibili', 'tiktok', 'game', 'music', 'video']
        if any(kw in url_lower for kw in ent_keywords):
            return '娱乐'
        
        # 购物
        shop_keywords = ['taobao', 'jd', 'amazon', 'mall', 'shop', 'buy']
        if any(kw in url_lower for kw in shop_keywords):
            return '购物'
        
        return '其他'
