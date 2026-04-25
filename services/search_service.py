"""
搜索服务模块
分层搜索：精确匹配 + 拼音搜索（语义搜索由调用方异步处理）
"""
import json
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

from core.database import DatabaseManager
from core.pinyin import PinyinConverter
from models.account import Account


@dataclass
class SearchResult:
    """搜索结果"""
    account: Account
    match_type: str  # 'exact' 精确匹配, 'pinyin' 拼音匹配, 'semantic' 语义匹配
    confidence: float  # 置信度
    matched_field: str  # 匹配字段（如 'app_name', 'username'）


class SearchService:
    """搜索服务：精确搜索 + 拼音搜索 + 语义搜索"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化搜索服务
        
        Args:
            db_manager: 数据库管理器
        """
        self.db = db_manager
        self._search_history: List[str] = []  # 搜索历史
        self._max_history = 10  # 最大历史记录数
    
    def search(self, query: str, accounts: List[Account] = None) -> List[SearchResult]:
        """
        同步搜索：精确匹配 + 拼音匹配（不含语义搜索）
        
        搜索优先级：
        1. 精确匹配（应用名、账号、网址、备注）
        2. 拼音匹配（如"wx"匹配"微信"）
        
        Args:
            query: 搜索关键词
            accounts: 账号列表（可选，不传则从数据库读取）
            
        Returns:
            搜索结果列表（按优先级排序，只含 exact/pinyin）
        """
        if not query or not query.strip():
            # 返回所有账号（按最近添加排序）
            if accounts is None:
                accounts_data = self.db.get_all_accounts()
                accounts = [Account.from_dict(data) for data in accounts_data]
            return [SearchResult(acc, 'all', 1.0, '') for acc in accounts]
        
        query = query.strip().lower()
        
        # 记录搜索历史
        self._add_to_history(query)
        
        # 获取账号列表
        if accounts is None:
            accounts_data = self.db.get_all_accounts()
            accounts = [Account.from_dict(data) for data in accounts_data]
        
        results = []
        exact_matches = []
        pinyin_matches = []
        
        # ==================== 第一层：精确匹配 ====================
        for account in accounts:
            match_info = self._exact_match(query, account)
            if match_info:
                field, score = match_info
                exact_matches.append(SearchResult(account, 'exact', score, field))
        
        # 按匹配分数排序
        exact_matches.sort(key=lambda x: x.confidence, reverse=True)
        results.extend(exact_matches)
        
        # ==================== 第二层：拼音匹配 ====================
        # 如果没有精确匹配，或查询是纯英文字母，尝试拼音匹配
        if not exact_matches or query.isalpha():
            for account in accounts:
                # 跳过已精确匹配的账号
                if any(r.account.id == account.id for r in results):
                    continue
                
                match_info = self._pinyin_match(query, account)
                if match_info:
                    field, score = match_info
                    pinyin_matches.append(SearchResult(account, 'pinyin', score, field))
            
            pinyin_matches.sort(key=lambda x: x.confidence, reverse=True)
            results.extend(pinyin_matches)
        
        return results
    
    def get_remaining_for_semantic(self, accounts: List[Account],
                                    existing_results: List[SearchResult]) -> List[Account]:
        """返回语义搜索候选账号（排除已精确/拼音匹配的）
        
        Args:
            accounts: 全部账号列表
            existing_results: 已匹配结果（精确+拼音）
            
        Returns:
            剩余未匹配的账号列表
        """
        matched_ids = {r.account.id for r in existing_results}
        return [acc for acc in accounts if acc.id not in matched_ids]
    
    def _exact_match(self, query: str, account: Account) -> Optional[tuple]:
        """
        精确匹配
        
        Returns:
            (匹配字段, 分数) 或 None
        """
        query = query.lower()
        
        # 应用名匹配（权重最高）
        if query in account.app_name.lower():
            return ('app_name', 1.0)
        
        # 账号匹配
        if query in account.username.lower():
            return ('username', 0.9)
        
        # 网址匹配
        if account.url and query in account.url.lower():
            return ('url', 0.8)
        
        # 备注匹配
        if account.remark and query in account.remark.lower():
            return ('remark', 0.7)
        
        # 分类匹配
        if query in account.category.lower():
            return ('category', 0.6)
        
        # 标签匹配
        if account.tags:
            tags = json.loads(account.tags) if isinstance(account.tags, str) else account.tags
            if isinstance(tags, list):
                for tag in tags:
                    if query in tag.lower():
                        return ('tags', 0.75)
        
        return None
    
    def _pinyin_match(self, query: str, account: Account) -> Optional[tuple]:
        """
        拼音匹配
        
        Returns:
            (匹配字段, 分数) 或 None
        """
        # 应用名拼音匹配
        if PinyinConverter.match_pinyin(query, account.app_name):
            return ('app_name', 0.85)
        
        # 分类拼音匹配
        if PinyinConverter.match_pinyin(query, account.category):
            return ('category', 0.7)
        
        return None
    
    def _add_to_history(self, query: str):
        """添加到搜索历史"""
        # 去重
        if query in self._search_history:
            self._search_history.remove(query)
        
        self._search_history.insert(0, query)
        
        # 限制历史记录数
        if len(self._search_history) > self._max_history:
            self._search_history = self._search_history[:self._max_history]
    
    def get_search_history(self) -> List[str]:
        """获取搜索历史"""
        return self._search_history.copy()
    
    def clear_history(self):
        """清空搜索历史"""
        self._search_history.clear()
    
    def search_by_category(self, category: str, accounts: List[Account] = None) -> List[Account]:
        """
        按分类搜索
        
        Args:
            category: 分类名称
            accounts: 账号列表（可选）
            
        Returns:
            该分类下的所有账号
        """
        if accounts is None:
            accounts_data = self.db.get_accounts_by_category(category)
            return [Account.from_dict(data) for data in accounts_data]
        else:
            return [acc for acc in accounts if acc.category == category]
    
    def get_recent_accounts(self, limit: int = 10) -> List[Account]:
        """
        获取最近添加的账号
        
        Args:
            limit: 返回数量限制
            
        Returns:
            最近添加的账号列表
        """
        # 从数据库按时间倒序读取
        self.db.cursor.execute(
            "SELECT * FROM accounts ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = self.db.cursor.fetchall()
        accounts_data = [self.db._decrypt_row(dict(row)) for row in rows]
        return [Account.from_dict(data) for data in accounts_data]
