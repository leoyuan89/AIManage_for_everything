"""
账号服务模块
处理账号的增删改查、排序等业务逻辑
"""
from typing import List, Optional, Dict
from datetime import datetime
from core.database import DatabaseManager
from models.account import Account


class AccountService:
    """账号服务：CRUD 操作"""
    
    CATEGORIES = ['全部', '金融', '社交', '邮箱', '游戏', '工作', '其他']
    
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
        
        return self.db.insert_account(account_data)
    
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
        
        return self.db.update_account(account_id, account_data)
    
    def delete_account(self, account_id: int) -> bool:
        """
        删除账号
        
        Args:
            account_id: 账号 ID
            
        Returns:
            是否成功
        """
        return self.db.delete_account(account_id)
    
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
        
        Args:
            category: 分类名称（'全部' 返回所有）
            
        Returns:
            账号列表
        """
        if category == '全部':
            return self.get_all_accounts()
        
        accounts_data = self.db.get_accounts_by_category(category)
        accounts = [Account.from_dict(data) for data in accounts_data]
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
        
        keyword = keyword.lower()
        all_accounts = self.get_all_accounts()
        
        results = []
        for account in all_accounts:
            # 搜索应用名、网址、账号、备注
            if (keyword in account.app_name.lower() or
                keyword in account.url.lower() or
                keyword in account.username.lower() or
                keyword in account.remark.lower()):
                results.append(account)
        
        return results
    
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
            print(f"[AccountService] Failed to read categories from DB: {e}")
        
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
        """重命名分类"""
        return self.db.rename_category(old_name, new_name)
    
    def add_category(self, category_name: str) -> bool:
        """新建分类（插入排序表，不创建任何账号）"""
        return self.db.add_category_order(category_name)

    def delete_category(self, category_name: str) -> int:
        """删除分类：条目移至'其他'"""
        return self.db.delete_category(category_name)
    
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
