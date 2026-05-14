"""
账号服务模块
处理账号的增删改查、排序等业务逻辑
"""
import functools
import logging
from typing import List, Optional, Dict
from datetime import datetime
from core.database import DatabaseManager
from models.account import Account

logger = logging.getLogger(__name__)


class AccountService:
    """账号服务：CRUD 操作"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化账号服务
        
        Args:
            db_manager: 数据库管理器实例
        """
        self.db = db_manager
    
    def add_account(self, account: Account) -> int:
        """
        添加新账号
        
        Args:
            account: 账号对象
            
        Returns:
            新账号 ID
        """
        account_data = account.to_dict()
        # 移除 id，让数据库自动生成
        account_data.pop('id', None)
        account_data.pop('created_at', None)
        account_data.pop('updated_at', None)
        
        result = self.db.insert_account(account_data)
        self.get_all_accounts.cache_clear()
        return result
    
    def update_account(self, account: Account) -> bool:
        """
        更新账号
        
        Args:
            account: 账号对象（必须包含 id）
            
        Returns:
            是否成功
        """
        if not account.id:
            raise ValueError("Account ID is required for update")
        
        account_data = account.to_dict()
        account_id = account_data.pop('id')
        account_data.pop('created_at', None)
        account_data.pop('updated_at', None)
        
        result = self.db.update_account(account_id, account_data)
        self.get_all_accounts.cache_clear()
        return result
    
    def delete_account(self, account_id: int) -> bool:
        """
        删除账号
        
        Args:
            account_id: 账号 ID
            
        Returns:
            是否成功
        """
        result = self.db.delete_account(account_id)
        self.get_all_accounts.cache_clear()
        return result
    
    def get_account(self, account_id: int) -> Optional[Account]:
        """
        根据 ID 获取账号
        
        Args:
            account_id: 账号 ID
            
        Returns:
            账号对象，不存在返回 None
        """
        data = self.db.get_account_by_id(account_id)
        if data:
            return Account.from_dict(data)
        return None
    
    @functools.lru_cache(maxsize=1)
    def get_all_accounts(self) -> List[Account]:
        """
        获取所有账号（按应用名首字母排序）
        
        Returns:
            账号列表
        """
        accounts_data = self.db.get_all_accounts()
        accounts = [Account.from_dict(data) for data in accounts_data]
        
        # 按应用名首字母排序
        accounts.sort(key=lambda x: x.app_name.lower())
        return accounts
    
    def get_accounts_by_category(self, category: str) -> List[Account]:
        """
        按分类获取账号
        
        如果 category 不含 '>'，视为父节点，返回该父节点下所有条目
        （含直接条目和子类条目）。
        如果含 '>'，精确匹配。
        
        Args:
            category: 分类名称（'全部' 返回所有）
            
        Returns:
            账号列表
        """
        if category == '全部':
            return self.get_all_accounts()
        
        from core.category_utils import get_prefix_matcher
        matcher = get_prefix_matcher(category)
        all_accounts = self.get_all_accounts()
        accounts = [a for a in all_accounts if matcher(a.category)]
        accounts.sort(key=lambda x: x.app_name.lower())
        return accounts
    
    def search_accounts(self, keyword: str) -> List[Account]:
        """
        关键词搜索账号
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            匹配的账号列表
        """
        if not keyword:
            return self.get_all_accounts()
        
        accounts_data = self.db.search_accounts([keyword])
        return [Account.from_dict(data) for data in accounts_data]
    
    def get_categories(self) -> List[str]:
        """
        获取所有分类列表（从数据库动态读取，合并默认分类，支持自定义排序）
        
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
            pass
        
        # 只显示数据库中真实存在的分类（不再硬编码默认分类）
        all_cats = db_cats
        
        # 排序：有自定义顺序的按 sort_index 排，没有的按字母排
        def sort_key(cat):
            return (orders.get(cat, 999999), cat.lower())
        
        # 确保"全部"在第一位，"其他"在最后
        result = ['全部']
        others = []
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
        all_accounts = self.get_all_accounts()
        updated = False
        with self.db.transaction():
            for account in all_accounts:
                if matcher(account.category):
                    if account.category == old_category:
                        new_cat = new_category
                    else:
                        suffix = account.category[len(old_category):]
                        new_cat = new_category + suffix
                    self.db.update_account(account.id, {'category': new_cat})
                    updated = True
            # 同步更新 category_order 表（包括空分类）
            self.db.rename_category_order(old_category, new_category)
        if updated:
            self.get_all_accounts.cache_clear()
        return updated
    
    def add_category(self, category_name: str) -> bool:
        """新建分类（插入排序表，不创建任何账号）"""
        return self.db.add_category_order(category_name)

    def delete_category(self, category: str) -> bool:
        """删除分类：
        - 删除二级分类：精确匹配的条目去掉二级部分（保留一级）
        - 删除一级分类：该一级及其所有子类下的条目移至'其他'
        同时从 category_order 排序表中真正移除该分类
        """
        all_accounts = self.get_all_accounts()
        updated = False
        with self.db.transaction():
            if '>' in category:
                # 删除二级分类：精确匹配，去掉二级部分
                parent = category.split('>')[0].strip()
                for account in all_accounts:
                    if account.category == category:
                        self.db.update_account(account.id, {'category': parent})
                        updated = True
            else:
                # 删除一级分类：匹配自身及所有子类，移到"其他"
                from core.category_utils import get_prefix_matcher
                matcher = get_prefix_matcher(category)
                for account in all_accounts:
                    if matcher(account.category):
                        self.db.update_account(account.id, {'category': '其他'})
                        updated = True
            # 同步从排序表中删除，确保该分类真正消失
            self.db.delete_category(category)
        if updated:
            self.get_all_accounts.cache_clear()
        return updated

    def _delete_category_no_commit(self, category: str) -> bool:
        """
        删除分类（不自行 commit，需在事务中调用）。
        逻辑与 delete_category 相同，但依赖外层事务进行提交/回滚。
        """
        all_accounts = self.get_all_accounts()
        updated = False
        with self.db.transaction():
            if '>' in category:
                # 删除二级分类：精确匹配，去掉二级部分
                parent = category.split('>')[0].strip()
                for account in all_accounts:
                    if account.category == category:
                        self.db.update_account(account.id, {'category': parent})
                        updated = True
            else:
                # 删除一级分类：匹配自身及所有子类，移到"其他"
                from core.category_utils import get_prefix_matcher
                matcher = get_prefix_matcher(category)
                for account in all_accounts:
                    if matcher(account.category):
                        self.db.update_account(account.id, {'category': '其他'})
                        updated = True
            # 同步从排序表中删除，确保该分类真正消失
            self.db.delete_category(category)
        if updated:
            self.get_all_accounts.cache_clear()
        return updated

    def promote_category(self, category_path: str) -> bool:
        """将二级分类升级为一级分类"""
        result = self.db.promote_category(category_path)
        self.get_all_accounts.cache_clear()
        return result
    
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
        
        result = self.db.reparent_category(old_path, new_path) > 0
        self.get_all_accounts.cache_clear()
        return result
    
    def toggle_favorite(self, account_id: int) -> bool:
        """Toggle favorite status for an account, returns new status"""
        current = self.get_account(account_id)
        if not current:
            return False
        new_status = not current.is_favorite
        self.db.update_account_field(account_id, 'is_favorite', int(new_status))
        self.get_all_accounts.cache_clear()
        return new_status

    def get_favorites(self) -> List[Account]:
        """Get all favorited accounts"""
        return [a for a in self.get_all_accounts() if a.is_favorite]
    
    def get_accounts_grouped(self) -> dict:
        """
        按首字母分组获取账号
        
        Returns:
            {字母: [Account, ...], ...}
        """
        accounts = self.get_all_accounts()
        grouped = {}
        
        for account in accounts:
            first_char = account.app_name[0].upper() if account.app_name else '#'
            if first_char not in grouped:
                grouped[first_char] = []
            grouped[first_char].append(account)
        
        # 按字母排序
        return dict(sorted(grouped.items()))
