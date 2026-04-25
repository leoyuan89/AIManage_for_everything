"""
Repository Pattern - 统一密码库/网址库数据层抽象
所有 AI 助手相关操作面向此接口，消除 vault_type 分支判断
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import json

from models.account import Account
from models.url_item import URLItem


# ============ 标准化数据结构 ============

@dataclass
class SearchResult:
    """搜索结果统一封装"""
    items: List[Any]
    matched_ids: List[int]
    query_description: str


@dataclass
class PreviewRow:
    """预览表格单行数据（UI 无关）"""
    item_id: int
    display_name: str
    secondary_info: str
    field_changes: List[Dict]
    warnings: Optional[List[str]] = None


@dataclass
class BatchItem:
    """批量导入单条记录（与 UI 无关的标准中间格式）"""
    confirmed: bool = True
    status: str = "就绪"
    
    # 通用字段
    category: str = "其他"
    tags: List[str] = None
    remark: str = ""
    ai_remark: str = ""
    
    # 密码库字段
    app: str = ""
    account: str = ""
    password: str = ""
    url: str = ""
    
    # 网址库字段
    title: str = ""
    
    # 原始数据
    raw_data: Dict = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.raw_data is None:
            self.raw_data = {}


@dataclass
class PreviewData:
    """操作预览标准化数据"""
    action: str
    description: str
    rows: List[PreviewRow]
    affected_count: int
    vault_type: str
    batch_items: Optional[List[BatchItem]] = None
    failed_chunks: Optional[List[Tuple]] = None


# ============ 仓库抽象基类 ============

class VaultRepository(ABC):
    """仓库抽象基类"""
    
    ALLOWED_FIELDS: set = set()
    
    # ----- 查询 -----
    
    @abstractmethod
    def get_all(self) -> List[Any]:
        pass
    
    @abstractmethod
    def get_by_id(self, item_id: int) -> Optional[Any]:
        pass
    
    @abstractmethod
    def search(self, keywords: List[str]) -> SearchResult:
        pass
    
    @abstractmethod
    def filter_by_category(self, category: str) -> SearchResult:
        pass
    
    @abstractmethod
    def filter_by_tags(self, tag: str) -> SearchResult:
        pass
    
    @abstractmethod
    def get_uncategorized(self) -> SearchResult:
        pass
    
    # ----- 预览与元数据 -----
    
    @abstractmethod
    def get_display_name(self, item: Any) -> str:
        pass
    
    @abstractmethod
    def get_secondary_info(self, item: Any) -> str:
        pass
    
    @abstractmethod
    def get_field_value(self, item: Any, field: str) -> Any:
        pass
    
    @abstractmethod
    def get_preview_columns(self) -> List[str]:
        pass
    
    @abstractmethod
    def get_categories(self) -> List[str]:
        pass
    
    @abstractmethod
    def get_item_type_name(self) -> str:
        pass
    
    # ----- 写操作 -----
    
    @abstractmethod
    def update_field(self, item_id: int, field: str, value: Any) -> bool:
        pass
    
    @abstractmethod
    def soft_delete(self, item_id: int) -> bool:
        pass
    
    @abstractmethod
    def insert(self, item_data: Dict) -> int:
        pass
    
    @abstractmethod
    def check_duplicate(self, item_data: Dict) -> Optional[Any]:
        pass
    
    @abstractmethod
    def auto_classify(self, key_text: str) -> str:
        pass
    
    # ----- 批量操作 -----
    
    @abstractmethod
    def resolve_filter_conditions(self, conditions: Dict) -> List[int]:
        pass


# ============ AccountRepository ============

class AccountRepository(VaultRepository):
    """密码库仓库实现"""
    
    ALLOWED_FIELDS = {'category', 'remark', 'ai_remark', 'tags'}
    
    def __init__(self, db, category_service=None, classification_service=None):
        """
        Args:
            db: DatabaseManager 实例
            category_service: CategoryService 实例
            classification_service: AIClassificationService 实例
        """
        self.db = db
        self.category_service = category_service
        self.classification_service = classification_service
    
    # ----- 查询 -----
    
    def get_all(self) -> List[Account]:
        data = self.db.get_all_accounts()
        return [Account.from_dict(d) for d in data]
    
    def get_by_id(self, item_id: int) -> Optional[Account]:
        data = self.db.get_account_by_id(item_id)
        return Account.from_dict(data) if data else None
    
    def search(self, keywords: List[str]) -> SearchResult:
        accounts = self.get_all()
        matched = []
        matched_ids = []
        
        for acc in accounts:
            text = f"{acc.app_name} {acc.username} {acc.category} {acc.remark or ''} {acc.ai_remark or ''}"
            if any(kw.lower() in text.lower() for kw in keywords if kw and str(kw).strip()):
                matched.append(acc)
                matched_ids.append(acc.id)
        
        return SearchResult(
            items=matched, matched_ids=matched_ids,
            query_description=f"关键词搜索: {', '.join(keywords)}"
        )
    
    def filter_by_category(self, category: str) -> SearchResult:
        accounts = self.get_all()
        matched = [a for a in accounts if a.category == category]
        return SearchResult(
            items=matched, matched_ids=[a.id for a in matched],
            query_description=f"分类筛选: {category}"
        )
    
    def filter_by_tags(self, tag: str) -> SearchResult:
        accounts = self.get_all()
        matched = []
        for acc in accounts:
            try:
                tags = acc.get_tags_list()
                if tag in tags:
                    matched.append(acc)
            except Exception:
                continue
        return SearchResult(
            items=matched, matched_ids=[a.id for a in matched],
            query_description=f"标签筛选: {tag}"
        )
    
    def get_uncategorized(self) -> SearchResult:
        accounts = self.get_all()
        matched = [a for a in accounts if not a.category or a.category in ('其他', '未分类', '')]
        return SearchResult(
            items=matched, matched_ids=[a.id for a in matched],
            query_description="未分类账号"
        )
    
    # ----- 预览与元数据 -----
    
    def get_display_name(self, item: Account) -> str:
        return item.app_name or "未命名"
    
    def get_secondary_info(self, item: Account) -> str:
        return item.mask_username() if hasattr(item, 'mask_username') else (item.username or "")
    
    def get_field_value(self, item: Account, field: str) -> Any:
        if field == 'tags':
            return item.get_tags_list()
        return getattr(item, field, None)
    
    def get_preview_columns(self) -> List[str]:
        return ['应用名', '账号', '字段', '原值', '新值']
    
    def get_categories(self) -> List[str]:
        if self.category_service:
            return self.category_service.get_all_categories()
        return ['全部', '金融', '社交', '工作', '娱乐', '购物', '其他']
    
    def get_item_type_name(self) -> str:
        return "账号"
    
    # ----- 写操作 -----
    
    def update_field(self, item_id: int, field: str, value: Any) -> bool:
        if field not in self.ALLOWED_FIELDS:
            raise ValueError(f"字段 {field} 不在白名单中")
        
        # 先获取完整数据，修改指定字段后更新
        original = self.db.get_account_by_id(item_id)
        if not original:
            return False
        
        update_data = dict(original)
        if field == 'tags' and isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)
        update_data[field] = value
        
        return self.db.update_account(item_id, update_data)
    
    def soft_delete(self, item_id: int) -> bool:
        original = self.db.get_account_by_id(item_id)
        if not original:
            return False
        return self.db.soft_delete_account(item_id, original)
    
    def insert(self, item_data: Dict) -> int:
        account = Account(
            app_name=item_data.get('app_name', item_data.get('app', '')),
            username=item_data.get('username', item_data.get('account', '')),
            password=item_data.get('password', ''),
            url=item_data.get('url', ''),
            category=item_data.get('category', '其他'),
            remark=item_data.get('remark', ''),
            ai_remark=item_data.get('ai_remark', ''),
            tags=json.dumps(item_data.get('tags', []), ensure_ascii=False)
        )
        if not account.category or account.category == '其他':
            account.category = self.auto_classify(account.app_name)
        return self.db.insert_account(account.to_dict())
    
    def check_duplicate(self, item_data: Dict) -> Optional[Account]:
        app = item_data.get('app_name', item_data.get('app', ''))
        username = item_data.get('username', item_data.get('account', ''))
        accounts = self.get_all()
        for acc in accounts:
            if acc.app_name == app and acc.username == username:
                return acc
        return None
    
    def auto_classify(self, key_text: str) -> str:
        if self.classification_service:
            try:
                return self.classification_service.classify(key_text)
            except Exception:
                pass
        return '其他'
    
    # ----- 批量操作 -----
    
    def resolve_filter_conditions(self, conditions: Dict) -> List[int]:
        accounts = self.get_all()
        matched_ids = []
        for acc in accounts:
            match = True
            for field, value in conditions.items():
                if field == 'tags':
                    try:
                        tags = acc.get_tags_list()
                        if value not in tags:
                            match = False
                            break
                    except Exception:
                        match = False
                        break
                else:
                    item_val = getattr(acc, field, '')
                    if item_val != value:
                        match = False
                        break
            if match:
                matched_ids.append(acc.id)
        return matched_ids


# ============ URLRepository ============

class URLRepository(VaultRepository):
    """网址库仓库实现"""
    
    ALLOWED_FIELDS = {'category', 'remark', 'ai_remark', 'tags', 'title', 'url'}
    
    def __init__(self, db, url_service=None, main_db=None):
        """
        Args:
            db: URLDatabaseManager 实例
            url_service: URLService 实例
            main_db: DatabaseManager 主库实例（用于回收站备份）
        """
        self.db = db
        self.url_service = url_service
        self.main_db = main_db
    
    # ----- 查询 -----
    
    def get_all(self) -> List[URLItem]:
        data = self.db.get_all_urls()
        return [URLItem.from_dict(d) for d in data]
    
    def get_by_id(self, item_id: int) -> Optional[URLItem]:
        data = self.db.get_url_by_id(item_id)
        return URLItem.from_dict(data) if data else None
    
    def search(self, keywords: List[str]) -> SearchResult:
        urls = self.get_all()
        matched = []
        matched_ids = []
        
        for u in urls:
            text = f"{u.title} {u.url} {u.category} {u.remark or ''} {u.ai_remark or ''}"
            try:
                tags = u.get_tags_list()
                text += ' ' + ' '.join(tags)
            except Exception:
                pass
            if any(kw.lower() in text.lower() for kw in keywords if kw and str(kw).strip()):
                matched.append(u)
                matched_ids.append(u.id)
        
        return SearchResult(
            items=matched, matched_ids=matched_ids,
            query_description=f"关键词搜索: {', '.join(keywords)}"
        )
    
    def filter_by_category(self, category: str) -> SearchResult:
        urls = self.get_all()
        matched = [u for u in urls if u.category == category]
        return SearchResult(
            items=matched, matched_ids=[u.id for u in matched],
            query_description=f"分类筛选: {category}"
        )
    
    def filter_by_tags(self, tag: str) -> SearchResult:
        urls = self.get_all()
        matched = []
        for u in urls:
            try:
                tags = u.get_tags_list()
                if tag in tags:
                    matched.append(u)
            except Exception:
                continue
        return SearchResult(
            items=matched, matched_ids=[u.id for u in matched],
            query_description=f"标签筛选: {tag}"
        )
    
    def get_uncategorized(self) -> SearchResult:
        urls = self.get_all()
        matched = [u for u in urls if not u.category or u.category in ('其他', '未分类', '')]
        return SearchResult(
            items=matched, matched_ids=[u.id for u in matched],
            query_description="未分类网址"
        )
    
    # ----- 预览与元数据 -----
    
    def get_display_name(self, item: URLItem) -> str:
        return item.title or item.url or "未命名"
    
    def get_secondary_info(self, item: URLItem) -> str:
        return item.url or ""
    
    def get_field_value(self, item: URLItem, field: str) -> Any:
        if field == 'tags':
            return item.get_tags_list()
        return getattr(item, field, None)
    
    def get_preview_columns(self) -> List[str]:
        return ['标题', '网址', '字段', '原值', '新值']
    
    def get_categories(self) -> List[str]:
        if self.url_service:
            return self.url_service.get_categories()
        return ['全部', '开发工具', '云服务', '社交平台', '学习资源', '娱乐', '购物', '其他']
    
    def get_item_type_name(self) -> str:
        return "网址"
    
    # ----- 写操作 -----
    
    def update_field(self, item_id: int, field: str, value: Any) -> bool:
        if field not in self.ALLOWED_FIELDS:
            raise ValueError(f"字段 {field} 不在白名单中")
        
        original = self.db.get_url_by_id(item_id)
        if not original:
            return False
        
        update_data = dict(original)
        if field == 'tags' and isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)
        update_data[field] = value
        
        return self.db.update_url(item_id, update_data)
    
    def soft_delete(self, item_id: int) -> bool:
        original = self.db.get_url_by_id(item_id)
        if not original:
            return False
        # 先通过主库备份到回收站
        if self.main_db:
            self.main_db.soft_delete_url(item_id, original)
        # 再物理删除网址表记录
        return self.db.delete_url(item_id)
    
    def insert(self, item_data: Dict) -> int:
        url_item = URLItem(
            title=item_data.get('title', ''),
            url=item_data.get('url', ''),
            category=item_data.get('category', '其他'),
            tags=json.dumps(item_data.get('tags', []), ensure_ascii=False),
            remark=item_data.get('remark', ''),
            ai_remark=item_data.get('ai_remark', '')
        )
        if not url_item.category or url_item.category == '其他':
            url_item.category = self.auto_classify(url_item.url)
        return self.db.insert_url(url_item.to_dict())
    
    def check_duplicate(self, item_data: Dict) -> Optional[URLItem]:
        url = item_data.get('url', '')
        urls = self.get_all()
        for u in urls:
            if u.url == url:
                return u
        return None
    
    def auto_classify(self, key_text: str) -> str:
        if self.url_service:
            try:
                return self.url_service.auto_categorize(key_text)
            except Exception:
                pass
        return '其他'
    
    # ----- 批量操作 -----
    
    def resolve_filter_conditions(self, conditions: Dict) -> List[int]:
        urls = self.get_all()
        matched_ids = []
        for u in urls:
            match = True
            for field, value in conditions.items():
                if field == 'tags':
                    try:
                        tags = u.get_tags_list()
                        if value not in tags:
                            match = False
                            break
                    except Exception:
                        match = False
                        break
                else:
                    item_val = getattr(u, field, '')
                    if item_val != value:
                        match = False
                        break
            if match:
                matched_ids.append(u.id)
        return matched_ids


# ============ RepositoryFactory ============

class RepositoryFactory:
    """仓库工厂，管理 Repository 实例的生命周期"""
    
    _instances: Dict[str, VaultRepository] = {}
    
    @classmethod
    def register(cls, vault_type: str, repo: VaultRepository):
        cls._instances[vault_type] = repo
    
    @classmethod
    def get_repository(cls, vault_type: str) -> VaultRepository:
        if vault_type not in cls._instances:
            raise KeyError(f"Repository 未注册: {vault_type}。请先调用 register() 初始化。")
        return cls._instances[vault_type]
    
    @classmethod
    def clear(cls):
        cls._instances.clear()
