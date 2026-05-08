"""
网址服务模块
"""
import logging
from typing import List, Optional, Dict
from urllib.parse import urlparse

from core.url_database import URLDatabaseManager
from models.url_item import URLItem

logger = logging.getLogger(__name__)


class URLService:
    """网址服务"""
    
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
        
        如果 category 不含 '>'，视为父节点，返回该父节点下所有条目
        （含直接条目和子类条目）。
        如果含 '>'，精确匹配。
        
        Args:
            category: 分类名称
            
        Returns:
            网址列表
        """
        if category == '全部':
            return self.get_all_urls()
        
        from core.category_utils import get_prefix_matcher
        matcher = get_prefix_matcher(category)
        all_urls = self.get_all_urls()
        return [u for u in all_urls if matcher(u.category)]
    
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
            logger.error("Failed to read categories from DB: %s", e)
        
        # 读取自定义排序
        orders = {}
        try:
            orders = self.db.get_category_orders()
        except Exception:
            logger.debug("读取分类排序失败", exc_info=True)
        
        # 只显示数据库中真实存在的分类（不再硬编码默认分类）
        all_cats = db_cats
        
        # 排序：有自定义顺序的按 sort_index 排，没有的按字母排
        def sort_key(cat):
            return (orders.get(cat, 999999), cat.lower())
        
        # 确保"全部"在第一位，"其他"在最后
        result = ['全部']
        for cat in sorted(all_cats - {'全部', '其他'}, key=sort_key):
            result.append(cat)
        if '其他' in all_cats:
            result.append('其他')
        return result
    
    def get_category_tree(self) -> dict:
        """
        获取分类树，用于 UI 级联选择和 AI 分类树注入。
        
        Returns:
            {parent: {'children': [sorted list], 'has_direct_items': bool}}
        """
        from core.category_utils import build_category_tree
        cats = self.get_categories()
        tree = build_category_tree([c for c in cats if c != '全部'])
        
        # 读取自定义排序
        orders = self.get_category_orders()
        
        # 一级节点按自定义排序排列（未设置的排最后，再按名称字母序兜底）
        sorted_parents = sorted(tree.keys(), key=lambda p: (orders.get(p, 999999), p.lower()))
        
        result = {}
        for parent_name in sorted_parents:
            info = tree[parent_name]
            def _child_sort_key(child_name: str):
                full_path = f"{parent_name}>{child_name}"
                return (orders.get(full_path, 999999), child_name.lower())
            info['children'] = sorted(info['children'], key=_child_sort_key)
            result[parent_name] = info
        
        return result
    
    def get_category_orders(self) -> Dict[str, int]:
        """获取分类自定义排序"""
        return self.db.get_category_orders()
    
    def save_category_orders(self, orders: Dict[str, int]):
        """保存分类自定义排序"""
        self.db.save_category_orders(orders)
    
    def rename_category(self, old_category: str, new_category: str) -> bool:
        """重命名分类（支持子类条目）"""
        from core.category_utils import get_prefix_matcher
        matcher = get_prefix_matcher(old_category)
        all_urls = self.get_all_urls()
        updated = False
        for url_item in all_urls:
            if matcher(url_item.category):
                if url_item.category == old_category:
                    new_cat = new_category
                else:
                    suffix = url_item.category[len(old_category):]
                    new_cat = new_category + suffix
                self.db.update_url(url_item.id, {'category': new_cat})
                updated = True
        # 同步更新 category_order 表（包括空分类）
        self.db.rename_category_order(old_category, new_category)
        return updated
    
    def add_category(self, category_name: str) -> bool:
        """新建分类（插入排序表，不创建任何网址）"""
        return self.db.add_category_order(category_name)

    def delete_category(self, category: str) -> bool:
        """删除分类：
        - 删除二级分类：精确匹配的条目去掉二级部分（保留一级）
        - 删除一级分类：该一级及其所有子类下的条目移至'其他'
        同时从 category_order 排序表中真正移除该分类
        """
        all_urls = self.get_all_urls()
        updated = False
        if '>' in category:
            # 删除二级分类：精确匹配，去掉二级部分
            parent = category.split('>')[0].strip()
            for url_item in all_urls:
                if url_item.category == category:
                    self.db.update_url(url_item.id, {'category': parent})
                    updated = True
        else:
            # 删除一级分类：匹配自身及所有子类，移到"其他"
            from core.category_utils import get_prefix_matcher
            matcher = get_prefix_matcher(category)
            for url_item in all_urls:
                if matcher(url_item.category):
                    self.db.update_url(url_item.id, {'category': '其他'})
                    updated = True
        # 同步从排序表中删除，确保该分类真正消失
        self.db.delete_category(category)
        return updated

    def promote_category(self, category_path: str) -> bool:
        """将二级分类升级为一级分类"""
        return self.db.promote_category(category_path)
    
    def reparent_category(self, old_path: str, new_parent: str = "") -> bool:
        """
        改变分类的父级
        old_path: 旧分类路径
        new_parent: 新的一级父分类名，空字符串表示变为一级
        """
        if '>' in old_path:
            child_name = old_path.split('>', 1)[1].strip()
        else:
            child_name = old_path.strip()
        
        if new_parent:
            new_path = f"{new_parent}>{child_name}"
        else:
            new_path = child_name
        
        return self.db.reparent_category(old_path, new_path) > 0
    
    def toggle_favorite(self, url_id: int) -> bool:
        """Toggle favorite status for a URL, returns new status"""
        current = self.get_url(url_id)
        if not current:
            return False
        new_status = not current.is_favorite
        self.db.update_url(url_id, {'is_favorite': int(new_status)})
        return new_status

    def get_favorites(self) -> list:
        """Get all favorited URLs"""
        return [u for u in self.get_all_urls() if u.is_favorite]
    
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
        except Exception:
            logger.debug("解析网址获取favicon失败: %s", url, exc_info=True)
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
