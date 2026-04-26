# 0425 炽阳 AI 助手 V2 实施规划

> **文档状态**：方案已确认，进入详细设计与编码阶段  
> **目标**：(1) 引入 Repository 抽象统一密码库/网址库数据层；(2) 多轮上下文对话与意图继承；(3) `batch_add_account` / `batch_add_url` 批量导入；(4) 批量删除（按标号/类别/标签）；(5) 网址库弹窗增强（备注/标签/AI生成/点击编辑）；(6) 列表滚动位置保持。  
> **核心约束**：Gemma 4B（16K 上下文），仅支持 `/api/generate`。

---

## 目录

1. [前置确认摘要](#一前置确认摘要)
2. [Phase 0：Repository 抽象 + 架构底座](#二phase-0repository-抽象--架构底座)
   - 2.1 [Repository Pattern 核心设计](#21-repository-pattern-核心设计)
   - 2.2 [AccountRepository 实现](#22-accountrepository-实现)
   - 2.3 [URLRepository 实现](#23-urlrepository-实现)
   - 2.4 [PreviewData 标准化格式](#24-previewdata-标准化格式)
   - 2.5 [RepositoryFactory 工厂](#25-repositoryfactory-工厂)
   - 2.6 [AIAssistantService 重构](#26-aiassistantservice-重构)
   - 2.7 [数据模型增强](#27-数据模型增强)
   - 2.8 [清理旧代码](#28-清理旧代码)
3. [Phase 1：UI 修复与增强](#三phase-1ui-修复与增强)
   - 3.1 [列表滚动位置保持](#31-列表滚动位置保持)
   - 3.2 [网址库弹窗增强](#32-网址库弹窗增强)
   - 3.3 [分类下拉栏同步修复](#33-分类下拉栏同步修复)
4. [Phase 2：多轮上下文对话](#四phase-2多轮上下文对话与意图继承)
   - 4.1 [ConversationContext](#41-conversationcontext)
   - 4.2 [生命周期管理](#42-生命周期管理)
   - 4.3 [指代消解](#43-指代消解预处理器)
   - 4.4 [Prompt 改造](#44-prompt-模板改造)
   - 4.5 [高亮绑定](#45-高亮状态与上下文绑定)
5. [Phase 3：批量导入](#五phase-3批量导入)
   - 5.1 [Action 定义](#51-action-定义)
   - 5.2 [分批解析](#52-分批切割与解析)
   - 5.3 [BatchAddPreviewWidget](#53-batchaddpreviewwidget)
   - 5.4 [去重预检](#54-去重预检与分类处理)
   - 5.5 [执行层](#55-执行层逐条独立导入)
   - 5.6 [Plan 降级](#56-plan-模式降级)
6. [Phase 4：批量删除](#六phase-4批量删除)
   - 6.1 [filter_conditions](#61-delete-action-扩展)
   - 6.2 [预览与警告](#62-预览与执行)
7. [实施顺序](#七实施顺序与估时)

---

## 一、前置确认摘要

| 编号 | 决策项 | 确认结论 |
|------|--------|----------|
| C1 | Repository 抽象 | **本次直接做好**，作为架构底座统一密码库/网址库数据层 |
| C2 | 网址库与 AI 助手 | 网址库**已集成**主窗口 Tab；旧版 `URLManagerDialog` **彻底删除** |
| C3 | 网址库 AI 功能 | `search`/`filter`/`list`/`explain`/`add`/`delete`/`reorganize`/`add_remark` **全部支持** |
| C4 | 上下文生命周期 | 切换 vault Tab / Plan-Build Tab **清空**；`idle_timeout` 后自动清空 |
| C5 | 批量导入 Action | **`batch_add_account`** / **`batch_add_url`** 两个独立 Action |
| C6 | 批量导入事务 | **逐条独立导入**，跳过重复/失败，互不影响 |
| C7 | 网址库弹窗增强 | 备注、标签（手动+AI生成）、AI备注、主列表**可点击编辑** |
| C8 | 列表刷新位置 | 保存/删除/导入后**保持滚动位置**，不跳回开头 |
| C9 | 分类下拉栏 | 修复网址库弹窗分类未同步数据库的 Bug |
| C10 | 批量删除上限 | 超过 **50 条**弹窗警告 |
| C11 | 密码预览 | 批量导入预览中密码**默认明文**，方便审核 |
| C12 | 分类不存在 | 归入"其他"，状态列提示 |

---

## 二、Phase 0：Repository 抽象 + 架构底座

### 2.1 Repository Pattern 核心设计

**设计目标**：消除 `AIAssistantService` 中所有 `if vault_type == 'accounts'` 分支，让核心逻辑完全面向抽象接口编程。

**文件位置**：`core/repositories.py`（新建）

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass


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
    display_name: str           # 主显示名称（密码库=app_name，网址库=title）
    secondary_info: str         # 辅助信息（密码库=username，网址库=url）
    field_changes: List[Dict]   # [{field, old_value, new_value}]
    warnings: List[str] = None  # 警告信息


@dataclass
class BatchItem:
    """批量导入单条记录（与 UI 无关的标准中间格式）"""
    confirmed: bool = True
    status: str = "就绪"        # 就绪 / 重复 / 格式错误 / 分类已修正
    
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
    
    # 原始数据（用于调试和回显）
    raw_data: Dict = None


class VaultRepository(ABC):
    """
    仓库抽象基类。
    所有方法面向"业务对象"（Account / URLItem），不暴露底层 SQL。
    """

    # ========== 查询 ==========
    
    @abstractmethod
    def get_all(self) -> List[Any]:
        """获取全部条目"""
        pass
    
    @abstractmethod
    def get_by_id(self, item_id: int) -> Optional[Any]:
        """按 ID 获取单条"""
        pass
    
    @abstractmethod
    def search(self, keywords: List[str]) -> SearchResult:
        """
        关键词搜索。
        密码库搜索字段：app_name, username, category, remark, ai_remark
        网址库搜索字段：title, url, category, tags
        """
        pass
    
    @abstractmethod
    def filter_by_category(self, category: str) -> SearchResult:
        """按分类精确筛选"""
        pass
    
    @abstractmethod
    def filter_by_tags(self, tag: str) -> SearchResult:
        """按标签筛选（标签为 JSON 数组）"""
        pass
    
    @abstractmethod
    def get_uncategorized(self) -> SearchResult:
        """获取未分类条目（category='其他' 或空）"""
        pass
    
    # ========== 预览与元数据 ==========
    
    @abstractmethod
    def get_display_name(self, item: Any) -> str:
        """获取条目的主显示名称"""
        pass
    
    @abstractmethod
    def get_secondary_info(self, item: Any) -> str:
        """获取条目的辅助显示信息"""
        pass
    
    @abstractmethod
    def get_field_value(self, item: Any, field: str) -> Any:
        """获取指定字段值（用于 preview 的原值展示）"""
        pass
    
    @abstractmethod
    def get_preview_columns(self) -> List[str]:
        """
        返回预览表格的列名列表。
        密码库：['应用名', '账号', '字段', '原值', '新值']
        网址库：['标题', '网址', '字段', '原值', '新值']
        """
        pass
    
    @abstractmethod
    def get_categories(self) -> List[str]:
        """获取当前数据库中的所有分类列表"""
        pass
    
    @abstractmethod
    def get_item_type_name(self) -> str:
        """返回条目类型名称（用于日志和提示）"""
        pass
    
    # ========== 写操作 ==========
    
    @abstractmethod
    def update_field(self, item_id: int, field: str, value: Any) -> bool:
        """
        更新单字段。
        支持字段白名单：category, remark, ai_remark, tags
        """
        pass
    
    @abstractmethod
    def soft_delete(self, item_id: int) -> bool:
        """软删除（移入回收站）"""
        pass
    
    @abstractmethod
    def insert(self, item_data: Dict) -> int:
        """
        插入新条目，返回新 ID。
        item_data 为 BatchItem.to_dict() 或类似结构。
        """
        pass
    
    @abstractmethod
    def check_duplicate(self, item_data: Dict) -> Optional[Any]:
        """
        检查是否已存在重复条目。
        密码库：按 app + account 判重
        网址库：按 url 判重
        返回已存在的条目或 None
        """
        pass
    
    @abstractmethod
    def auto_classify(self, key_text: str) -> str:
        """
        自动推断分类。
        密码库：调用 AIClassificationService
        网址库：调用 URLService.auto_categorize
        """
        pass
    
    # ========== 批量操作 ==========
    
    @abstractmethod
    def resolve_filter_conditions(self, conditions: Dict) -> List[int]:
        """
        将过滤条件解析为 ID 列表（用于批量删除）。
        conditions 示例：{"category": "测试"}, {"tags": "临时"}
        """
        pass
```

### 2.2 AccountRepository 实现

**文件位置**：`core/repositories.py`

```python
import json
from typing import List, Optional, Any
from core.database import DatabaseManager
from services.category_service import CategoryService
from services.ai_classification_service import AIClassificationService
from models.account import Account


class AccountRepository(VaultRepository):
    """密码库仓库实现"""
    
    # 字段白名单（安全控制）
    ALLOWED_FIELDS = {'category', 'remark', 'ai_remark', 'tags'}
    
    # 搜索字段优先级
    SEARCH_FIELDS = ['app_name', 'username', 'category', 'remark', 'ai_remark']
    
    def __init__(self, db: DatabaseManager, 
                 category_service: CategoryService = None,
                 classification_service: AIClassificationService = None):
        self.db = db
        self.category_service = category_service
        self.classification_service = classification_service
    
    def get_all(self) -> List[Account]:
        return self.db.get_all_accounts()
    
    def get_by_id(self, item_id: int) -> Optional[Account]:
        return self.db.get_account_by_id(item_id)
    
    def search(self, keywords: List[str]) -> SearchResult:
        all_accounts = self.get_all()
        matched = []
        matched_ids = []
        
        for account in all_accounts:
            text = f"{account.app_name} {account.username} {account.category} {account.remark or ''} {account.ai_remark or ''}"
            if any(kw.lower() in text.lower() for kw in keywords):
                matched.append(account)
                matched_ids.append(account.id)
        
        return SearchResult(
            items=matched,
            matched_ids=matched_ids,
            query_description=f"关键词搜索: {', '.join(keywords)}"
        )
    
    def filter_by_category(self, category: str) -> SearchResult:
        all_accounts = self.get_all()
        matched = [a for a in all_accounts if a.category == category]
        return SearchResult(
            items=matched,
            matched_ids=[a.id for a in matched],
            query_description=f"分类筛选: {category}"
        )
    
    def filter_by_tags(self, tag: str) -> SearchResult:
        all_accounts = self.get_all()
        matched = []
        for account in all_accounts:
            try:
                tags = json.loads(account.tags) if account.tags else []
                if tag in tags:
                    matched.append(account)
            except json.JSONDecodeError:
                continue
        return SearchResult(
            items=matched,
            matched_ids=[a.id for a in matched],
            query_description=f"标签筛选: {tag}"
        )
    
    def get_uncategorized(self) -> SearchResult:
        all_accounts = self.get_all()
        matched = [a for a in all_accounts if not a.category or a.category == '其他']
        return SearchResult(
            items=matched,
            matched_ids=[a.id for a in matched],
            query_description="未分类账号"
        )
    
    def get_display_name(self, item: Account) -> str:
        return item.app_name or "未命名"
    
    def get_secondary_info(self, item: Account) -> str:
        return item.username or ""
    
    def get_field_value(self, item: Account, field: str) -> Any:
        if field == 'tags':
            return json.loads(item.tags) if item.tags else []
        return getattr(item, field, None)
    
    def get_preview_columns(self) -> List[str]:
        return ['应用名', '账号', '字段', '原值', '新值']
    
    def get_categories(self) -> List[str]:
        if self.category_service:
            return self.category_service.get_categories()
        return ['全部', '金融', '社交', '工作', '娱乐', '购物', '其他']
    
    def get_item_type_name(self) -> str:
        return "账号"
    
    def update_field(self, item_id: int, field: str, value: Any) -> bool:
        if field not in self.ALLOWED_FIELDS:
            raise ValueError(f"字段 {field} 不在白名单中")
        if field == 'tags' and isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)
        return self.db.update_account_field(item_id, field, value)
    
    def soft_delete(self, item_id: int) -> bool:
        return self.db.soft_delete_account(item_id)
    
    def insert(self, item_data: Dict) -> int:
        account = Account(
            app_name=item_data.get('app', ''),
            username=item_data.get('account', ''),
            password=item_data.get('password', ''),
            url=item_data.get('url', ''),
            category=item_data.get('category', '其他'),
            remark=item_data.get('remark', ''),
            ai_remark=item_data.get('ai_remark', ''),
            tags=json.dumps(item_data.get('tags', []), ensure_ascii=False)
        )
        if not account.category or account.category == '其他':
            account.category = self.auto_classify(account.app_name)
        return self.db.insert_account(account)
    
    def check_duplicate(self, item_data: Dict) -> Optional[Account]:
        app = item_data.get('app', '')
        account = item_data.get('account', '')
        # 假设 db 提供按 app+account 查询方法
        return self.db.find_account_by_app_and_account(app, account)
    
    def auto_classify(self, key_text: str) -> str:
        if self.classification_service:
            return self.classification_service.classify(key_text)
        return '其他'
    
    def resolve_filter_conditions(self, conditions: Dict) -> List[int]:
        all_accounts = self.get_all()
        matched_ids = []
        for account in all_accounts:
            match = True
            for field, value in conditions.items():
                if field == 'tags':
                    try:
                        tags = json.loads(account.tags) if account.tags else []
                        if value not in tags:
                            match = False
                            break
                    except json.JSONDecodeError:
                        match = False
                        break
                else:
                    item_val = getattr(account, field, '')
                    if item_val != value:
                        match = False
                        break
            if match:
                matched_ids.append(account.id)
        return matched_ids
```

### 2.3 URLRepository 实现

```python
import json
from typing import List, Optional, Any
from core.url_database import URLDatabaseManager
from services.url_service import URLService
from models.url_item import URLItem


class URLRepository(VaultRepository):
    """网址库仓库实现"""
    
    ALLOWED_FIELDS = {'category', 'remark', 'ai_remark', 'tags', 'title', 'url'}
    SEARCH_FIELDS = ['title', 'url', 'category', 'tags']
    
    def __init__(self, db: URLDatabaseManager, url_service: URLService = None):
        self.db = db
        self.url_service = url_service
    
    def get_all(self) -> List[URLItem]:
        return self.db.get_all_urls()
    
    def get_by_id(self, item_id: int) -> Optional[URLItem]:
        return self.db.get_url_by_id(item_id)
    
    def search(self, keywords: List[str]) -> SearchResult:
        all_urls = self.get_all()
        matched = []
        matched_ids = []
        
        for url_item in all_urls:
            text = f"{url_item.title} {url_item.url} {url_item.category} {url_item.tags or ''}"
            if any(kw.lower() in text.lower() for kw in keywords):
                matched.append(url_item)
                matched_ids.append(url_item.id)
        
        return SearchResult(
            items=matched,
            matched_ids=matched_ids,
            query_description=f"关键词搜索: {', '.join(keywords)}"
        )
    
    def filter_by_category(self, category: str) -> SearchResult:
        all_urls = self.get_all()
        matched = [u for u in all_urls if u.category == category]
        return SearchResult(
            items=matched,
            matched_ids=[u.id for u in matched],
            query_description=f"分类筛选: {category}"
        )
    
    def filter_by_tags(self, tag: str) -> SearchResult:
        all_urls = self.get_all()
        matched = []
        for url_item in all_urls:
            try:
                tags = json.loads(url_item.tags) if url_item.tags else []
                if tag in tags:
                    matched.append(url_item)
            except json.JSONDecodeError:
                continue
        return SearchResult(
            items=matched,
            matched_ids=[u.id for u in matched],
            query_description=f"标签筛选: {tag}"
        )
    
    def get_uncategorized(self) -> SearchResult:
        all_urls = self.get_all()
        matched = [u for u in all_urls if not u.category or u.category == '其他']
        return SearchResult(
            items=matched,
            matched_ids=[u.id for u in matched],
            query_description="未分类网址"
        )
    
    def get_display_name(self, item: URLItem) -> str:
        return item.title or item.url or "未命名"
    
    def get_secondary_info(self, item: URLItem) -> str:
        return item.url or ""
    
    def get_field_value(self, item: URLItem, field: str) -> Any:
        if field == 'tags':
            return json.loads(item.tags) if item.tags else []
        return getattr(item, field, None)
    
    def get_preview_columns(self) -> List[str]:
        return ['标题', '网址', '字段', '原值', '新值']
    
    def get_categories(self) -> List[str]:
        if self.url_service:
            return self.url_service.get_all_categories()
        return ['全部', '开发工具', '云服务', '社交平台', '学习资源', '娱乐', '购物', '其他']
    
    def get_item_type_name(self) -> str:
        return "网址"
    
    def update_field(self, item_id: int, field: str, value: Any) -> bool:
        if field not in self.ALLOWED_FIELDS:
            raise ValueError(f"字段 {field} 不在白名单中")
        if field == 'tags' and isinstance(value, list):
            value = json.dumps(value, ensure_ascii=False)
        # 假设 url_db 提供通用 update_url_field
        return self.db.update_url_field(item_id, field, value)
    
    def soft_delete(self, item_id: int) -> bool:
        return self.db.soft_delete_url(item_id)
    
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
        return self.db.insert_url(url_item)
    
    def check_duplicate(self, item_data: Dict) -> Optional[URLItem]:
        url = item_data.get('url', '')
        return self.db.find_by_url(url)
    
    def auto_classify(self, key_text: str) -> str:
        if self.url_service:
            return self.url_service.auto_categorize(key_text)
        return '其他'
    
    def resolve_filter_conditions(self, conditions: Dict) -> List[int]:
        all_urls = self.get_all()
        matched_ids = []
        for url_item in all_urls:
            match = True
            for field, value in conditions.items():
                if field == 'tags':
                    try:
                        tags = json.loads(url_item.tags) if url_item.tags else []
                        if value not in tags:
                            match = False
                            break
                    except json.JSONDecodeError:
                        match = False
                        break
                else:
                    item_val = getattr(url_item, field, '')
                    if item_val != value:
                        match = False
                        break
            if match:
                matched_ids.append(url_item.id)
        return matched_ids
```

### 2.4 PreviewData 标准化格式

`build_action_preview` 不再返回 UI 相关的字典，而是返回标准化的 `PreviewData`，由 UI 层统一渲染。

```python
@dataclass
class PreviewData:
    action: str                          # 'reorganize' | 'add_remark' | 'delete' | 'add' | 'batch_add'
    description: str                     # 操作描述（如"将分类修改为'金融'"）
    rows: List[PreviewRow]               # 预览表格行数据
    affected_count: int                  # 影响条目数
    vault_type: str                      # 'accounts' | 'urls'
    
    # 批量导入专用
    batch_items: List[BatchItem] = None  # batch_add 时的完整数据
    failed_chunks: List[tuple] = None    # 解析失败的批次
```

**AIAssistantService.build_action_preview 重构后：**

```python
def build_action_preview(self, action: str, params: Dict, 
                         context_items: List[Any], vault_type: str = 'accounts') -> PreviewData:
    """
    通过 Repository 构建标准化预览数据，完全不关心底层是 Account 还是 URLItem。
    """
    repo = RepositoryFactory.get_repository(vault_type, self)
    
    if action == 'reorganize':
        return self._build_reorganize_preview(params, context_items, repo)
    elif action == 'add_remark':
        return self._build_add_remark_preview(params, context_items, repo)
    elif action == 'delete':
        return self._build_delete_preview(params, context_items, repo)
    elif action == 'add':
        return self._build_add_preview(params, repo)
    elif action in ('batch_add_account', 'batch_add_url'):
        return self._build_batch_add_preview(params, repo)
    else:
        raise ValueError(f"不支持预览的动作: {action}")

def _build_delete_preview(self, params, context_items, repo: VaultRepository) -> PreviewData:
    target_ids = params.get('target_ids', [])
    
    # 若模型返回的是条件而非具体 ID，通过 Repository 解析
    if not target_ids and 'filter_conditions' in params:
        target_ids = repo.resolve_filter_conditions(params['filter_conditions'])
        params['target_ids'] = target_ids
    
    rows = []
    item_map = {item.id: item for item in context_items}
    
    for tid in target_ids:
        item = item_map.get(tid) or repo.get_by_id(tid)
        if item:
            rows.append(PreviewRow(
                item_id=tid,
                display_name=repo.get_display_name(item),
                secondary_info=repo.get_secondary_info(item),
                field_changes=[{
                    'field': '状态',
                    'old_value': '正常',
                    'new_value': '移入回收站'
                }]
            ))
    
    return PreviewData(
        action='delete',
        description=f"将 {len(rows)} 条{repo.get_item_type_name()}移入回收站",
        rows=rows,
        affected_count=len(rows),
        vault_type='accounts' if isinstance(repo, AccountRepository) else 'urls'
    )
```

### 2.5 RepositoryFactory 工厂

```python
class RepositoryFactory:
    """仓库工厂，管理 Repository 实例的生命周期"""
    
    _instances: Dict[str, VaultRepository] = {}
    
    @classmethod
    def register(cls, vault_type: str, repo: VaultRepository):
        cls._instances[vault_type] = repo
    
    @classmethod
    def get_repository(cls, vault_type: str, service=None) -> VaultRepository:
        if vault_type in cls._instances:
            return cls._instances[vault_type]
        
        # 延迟初始化
        if vault_type == 'accounts':
            from core.database import DatabaseManager
            from services.category_service import CategoryService
            from services.ai_classification_service import AIClassificationService
            db = DatabaseManager()
            repo = AccountRepository(
                db=db,
                category_service=CategoryService(db),
                classification_service=AIClassificationService()
            )
        elif vault_type == 'urls':
            from core.url_database import URLDatabaseManager
            from services.url_service import URLService
            db = URLDatabaseManager()
            repo = URLRepository(
                db=db,
                url_service=URLService(db)
            )
        else:
            raise ValueError(f"不支持的 vault_type: {vault_type}")
        
        cls._instances[vault_type] = repo
        return repo
    
    @classmethod
    def clear(cls):
        cls._instances.clear()
```

### 2.6 AIAssistantService 重构

**改造后的核心方法签名：**

```python
class AIAssistantService:
    def __init__(self, db_manager, url_db_manager, ollama_client):
        self.db = db_manager
        self.url_db = url_db_manager
        self.ollama = ollama_client
        self.conversation_context = ConversationContext()
        
        # 注册 Repository
        RepositoryFactory.register('accounts', AccountRepository(db_manager))
        RepositoryFactory.register('urls', URLRepository(url_db_manager))
    
    def execute_action(self, action: str, params: Dict, 
                       context_items: List[Any], vault_type: str = 'accounts', 
                       mode: str = 'plan') -> Dict:
        """
        通过 Repository 执行动作，完全无分支判断。
        """
        repo = RepositoryFactory.get_repository(vault_type)
        
        if action in READONLY_ACTIONS:
            # 只读操作直接执行
            if action == 'search':
                keywords = params.get('keywords', [])
                result = repo.search(keywords)
                return {
                    'action': 'search',
                    'items': result.items,
                    'matched_ids': result.matched_ids,
                    'reply': f"找到 {len(result.items)} 条{repo.get_item_type_name()}"
                }
            elif action == 'filter':
                if 'category' in params:
                    result = repo.filter_by_category(params['category'])
                elif 'tag' in params:
                    result = repo.filter_by_tags(params['tag'])
                else:
                    result = repo.get_all()
                return {
                    'action': 'filter',
                    'items': result.items,
                    'matched_ids': result.matched_ids,
                    'reply': f"筛选出 {len(result.items)} 条{repo.get_item_type_name()}"
                }
            elif action == 'list':
                if params.get('scope') == 'uncategorized':
                    result = repo.get_uncategorized()
                else:
                    all_items = repo.get_all()
                    result = SearchResult(all_items, [i.id for i in all_items], "全部列表")
                return {
                    'action': 'list',
                    'items': result.items,
                    'matched_ids': result.matched_ids,
                    'reply': f"共 {len(result.items)} 条{repo.get_item_type_name()}"
                }
            elif action == 'explain':
                return {'action': 'explain', 'reply': params.get('reply', '')}
        
        else:
            # 写操作仅在 Build 模式下执行
            if mode == 'plan':
                return {
                    'action': 'explain',
                    'reply': f"当前为 Plan 模式，无法执行 {action}。请切换到 Build 模式。"
                }
            
            # Build 模式下生成预览
            preview = self.build_action_preview(action, params, context_items, vault_type)
            return {
                'action': action,
                'is_preview': True,
                'preview': preview,
                'reply': f"请确认以下 {preview.affected_count} 条操作的预览"
            }
    
    def execute_build_action(self, action: str, params: Dict, vault_type: str = 'accounts') -> Dict:
        """
        用户确认预览后，执行实际写操作。
        """
        repo = RepositoryFactory.get_repository(vault_type)
        
        if action == 'reorganize':
            changes = params.get('changes', [])
            success = 0
            for change in changes:
                repo.update_field(change['target_id'], change['field'], change['new_value'])
                success += 1
            return {'success': success, 'action': 'reorganize'}
        
        elif action == 'add_remark':
            changes = params.get('changes', [])
            for change in changes:
                repo.update_field(change['target_id'], 'ai_remark', change['new_value'])
            return {'success': len(changes), 'action': 'add_remark'}
        
        elif action == 'delete':
            target_ids = params.get('target_ids', [])
            success_ids = []
            fail_ids = []
            for tid in target_ids:
                try:
                    repo.soft_delete(tid)
                    success_ids.append(tid)
                except Exception as e:
                    fail_ids.append((tid, str(e)))
            return {'success_ids': success_ids, 'fail_ids': fail_ids, 'action': 'delete'}
        
        elif action == 'add':
            item_data = params.get('fields', {})
            new_id = repo.insert(item_data)
            return {'new_id': new_id, 'action': 'add'}
        
        elif action in ('batch_add_account', 'batch_add_url'):
            return self._execute_batch_add(params, repo)
```

### 2.7 数据模型增强

**`models/url_item.py` 新增字段：**

```python
@dataclass
class URLItem:
    id: Optional[int] = None
    title: str = ""
    url: str = ""
    category: str = "其他"
    tags: str = "[]"
    related_account_id: Optional[int] = None
    visit_count: int = 0
    ai_remark: str = ""        # 新增
    remark: str = ""           # 新增
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

**数据库迁移（`core/url_database.py`）：**

在 `URLDatabaseManager.__init__` 或 `_init_database` 中，增加列存在性检查和自动迁移：

```python
def _ensure_columns(self):
    """确保 urls 表包含所有必要列"""
    cursor = self.conn.cursor()
    cursor.execute("PRAGMA table_info(urls)")
    columns = {row[1] for row in cursor.fetchall()}
    
    if 'ai_remark' not in columns:
        cursor.execute("ALTER TABLE urls ADD COLUMN ai_remark TEXT DEFAULT ''")
    if 'remark' not in columns:
        cursor.execute("ALTER TABLE urls ADD COLUMN remark TEXT DEFAULT ''")
    
    self.conn.commit()
```

### 2.8 清理旧代码

- 删除 `ui/url_manager_dialog.py`
- 全局搜索 `URLManagerDialog` / `URLListItem` 字符串引用，全部清理
- 清理 `ui/__init__.py` 中的导出

---

## 三、Phase 1：UI 修复与增强

### 3.1 列表滚动位置保持

```python
class MainWindow(QMainWindow):
    def _save_scroll_state(self):
        """保存当前列表的滚动位置和选中项ID"""
        if self.current_vault == 'accounts':
            list_widget = self.account_list
            cached = self._cached_accounts
        else:
            list_widget = self.url_list
            cached = self._cached_urls
            
        self._scroll_state = {
            'vault_type': self.current_vault,
            'selected_id': None,
            'scroll_value': list_widget.verticalScrollBar().value()
        }
        
        current_row = list_widget.currentRow()
        if 0 <= current_row < len(cached):
            self._scroll_state['selected_id'] = cached[current_row].id
    
    def _restore_scroll_state(self):
        """恢复滚动位置和选中项"""
        if not hasattr(self, '_scroll_state'):
            return
        if self._scroll_state.get('vault_type') != self.current_vault:
            return
            
        if self.current_vault == 'accounts':
            list_widget = self.account_list
            cached = self._cached_accounts
        else:
            list_widget = self.url_list
            cached = self._cached_urls
        
        selected_id = self._scroll_state.get('selected_id')
        if selected_id is not None:
            for idx, item in enumerate(cached):
                if item.id == selected_id:
                    list_widget.setCurrentRow(idx)
                    list_widget.scrollToItem(list_widget.item(idx))
                    return
        
        scroll_value = self._scroll_state.get('scroll_value', 0)
        list_widget.verticalScrollBar().setValue(scroll_value)
```

**植入点：**
- `_on_account_saved` / `_on_url_saved`
- `_on_action_preview_confirmed`（删除后）
- `_after_batch_import`

### 3.2 网址库弹窗增强

**文件**：复用或新建 `ui/url_dialog.py`（若当前无独立网址弹窗，则在现有对话框基础上增强）

**新增控件：**

```python
class URLEditDialog(QDialog):
    def setup_ui(self):
        # ... 现有字段：title, url, category ...
        
        # 新增：备注输入框
        self.remark_edit = QTextEdit()
        self.remark_edit.setPlaceholderText("输入备注...")
        layout.addRow("备注:", self.remark_edit)
        
        # 新增：标签输入（带 AI 生成按钮）
        tags_layout = QHBoxLayout()
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("逗号分隔，如: 工作, 常用")
        tags_layout.addWidget(self.tags_edit, 1)
        
        self.btn_ai_tags = QPushButton("AI生成标签")
        self.btn_ai_tags.clicked.connect(self._on_ai_generate_tags)
        tags_layout.addWidget(self.btn_ai_tags)
        layout.addRow("标签:", tags_layout)
        
        # 新增：AI 备注（只读 + 重新生成按钮）
        ai_remark_layout = QHBoxLayout()
        self.ai_remark_edit = QTextEdit()
        self.ai_remark_edit.setReadOnly(True)
        self.ai_remark_edit.setPlaceholderText("点击右侧按钮生成 AI 备注...")
        self.ai_remark_edit.setMaximumHeight(60)
        ai_remark_layout.addWidget(self.ai_remark_edit, 1)
        
        self.btn_ai_remark = QPushButton("生成 AI 备注")
        self.btn_ai_remark.clicked.connect(self._on_ai_generate_remark)
        ai_remark_layout.addWidget(self.btn_ai_remark)
        layout.addRow("AI 备注:", ai_remark_layout)
    
    def _on_ai_generate_tags(self):
        """调用 AI 服务根据 title + url 生成标签"""
        title = self.title_edit.text().strip()
        url = self.url_edit.text().strip()
        if not title and not url:
            return
        # 异步调用 AIClassificationService 或 AIRemarkService
        # 结果写入 self.tags_edit
    
    def _on_ai_generate_remark(self):
        """调用 AI 服务生成备注"""
        title = self.title_edit.text().strip()
        url = self.url_edit.text().strip()
        if not title and not url:
            return
        # 异步调用 AIRemarkService
        # 结果写入 self.ai_remark_edit
```

**主列表条目可点击：**

在 `MainWindow.load_urls()` 或列表初始化中绑定点击事件：

```python
self.url_list.itemClicked.connect(self._on_url_item_clicked)
self.url_list.itemDoubleClicked.connect(self._on_url_item_double_clicked)

def _on_url_item_double_clicked(self, item):
    """双击打开编辑弹窗"""
    row = self.url_list.row(item)
    if 0 <= row < len(self._cached_urls):
        url_item = self._cached_urls[row]
        dialog = URLEditDialog(url_item, self.url_db, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_scroll_state()
            self.load_urls()
            self._restore_scroll_state()
```

### 3.3 分类下拉栏同步修复

**问题**：弹窗中的 `QComboBox` 未从数据库实时拉取分类列表。

**修复**：弹窗初始化时调用 Repository 获取当前分类：

```python
def _load_categories(self):
    repo = RepositoryFactory.get_repository(self.vault_type)
    categories = repo.get_categories()
    
    self.category_combo.clear()
    self.category_combo.addItems(categories)
    
    if self.current_item and self.current_item.category in categories:
        self.category_combo.setCurrentText(self.current_item.category)
```

**检查密码库弹窗**：同步检查密码库的添加/编辑对话框是否也有相同问题，确保同样从 `AccountRepository.get_categories()` 或 `CategoryService` 拉取。

---

## 四、Phase 2：多轮上下文对话与意图继承

### 4.1 ConversationContext

```python
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Set, List, Dict
import time

@dataclass
class TurnSnapshot:
    user_input: str
    parsed_action: str
    params_summary: str
    ai_reply_summary: str
    plan_entity_ids: Optional[Set[int]] = None
    build_entity_refs: Optional[List[Dict]] = None
    vault_type: str = 'accounts'
    timestamp: float = field(default_factory=time.time)

class ConversationContext:
    def __init__(self, max_turns=6, idle_timeout=300):
        self.history: deque[TurnSnapshot] = deque(maxlen=max_turns)
        self.last_active_timestamp = time.time()
        self.idle_timeout = idle_timeout
        self.current_vault_type: Optional[str] = None
        
    def reset(self):
        self.history.clear()
        self.last_active_timestamp = time.time()
        self.current_vault_type = None
        
    def is_expired(self) -> bool:
        return time.time() - self.last_active_timestamp > self.idle_timeout
        
    def append_turn(self, snapshot: TurnSnapshot):
        self.history.append(snapshot)
        self.last_active_timestamp = time.time()
        self.current_vault_type = snapshot.vault_type
        
    def get_recent_entities(self, turn_offset: int = 1) -> Set[int]:
        if len(self.history) < turn_offset:
            return set()
        turn = list(self.history)[-turn_offset]
        ids = set()
        if turn.plan_entity_ids:
            ids.update(turn.plan_entity_ids)
        if turn.build_entity_refs:
            ids.update(ref.get('id') for ref in turn.build_entity_refs if ref.get('id'))
        return ids
        
    def serialize_for_prompt(self, max_chars=2000) -> str:
        lines = []
        total = len(self.history)
        for idx, turn in enumerate(self.history, 1):
            if total - idx < 2:
                detail = f"用户: {turn.user_input[:80]} | AI: {turn.ai_reply_summary[:80]}"
            else:
                detail = f"动作: {turn.parsed_action}"
            entity_info = f"实体: {list(turn.plan_entity_ids or [])[:5]}" if turn.plan_entity_ids else ""
            lines.append(f"第{idx}轮({turn.vault_type}): {detail} {entity_info}")
        
        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[-max_chars:]
            first_idx = result.find("第")
            if first_idx > 0:
                result = result[first_idx:]
        return result
```

### 4.2 生命周期管理

**触发 `reset()` 的事件：**
1. 密码库/网址库 Tab 切换
2. Plan/Build 模式切换
3. 用户点击 AI 面板"清空"按钮
4. `idle_timeout` 超时（后台 `QTimer` 每30秒检测）

```python
# MainWindow
class MainWindow(QMainWindow):
    def __init__(self):
        # ...
        self._context_timer = QTimer(self)
        self._context_timer.timeout.connect(self._check_context_expiry)
        self._context_timer.start(30000)
    
    def _on_vault_tab_changed(self, index):
        # ... 原有逻辑 ...
        if hasattr(self, 'ai_assistant_service') and self.ai_assistant_service:
            self.ai_assistant_service.conversation_context.reset()
            
    def _on_ai_mode_changed(self, mode):
        if hasattr(self, 'ai_assistant_service') and self.ai_assistant_service:
            self.ai_assistant_service.conversation_context.reset()
    
    def _check_context_expiry(self):
        ctx = getattr(self.ai_assistant_service, 'conversation_context', None)
        if ctx and ctx.is_expired():
            ctx.reset()
```

**`idle_timeout` 设置项（`ui/settings_dialog.py`）：**

```python
# 新增分组：AI 助手设置
ai_group = QGroupBox("AI 助手设置")
spin_idle_timeout = QSpinBox()
spin_idle_timeout.setRange(60, 3600)
spin_idle_timeout.setValue(self.config.get('ai_idle_timeout', 300))
spin_idle_timeout.setSuffix(" 秒")
layout.addRow("对话上下文超时:", spin_idle_timeout)
```

### 4.3 指代消解预处理器

```python
import re

class ReferenceResolver:
    PRONOUNS = {'这些', '那些', '它们', '他们', '她们', '这个', '那个', 
                '刚才', '之前', '上面', '下边', '前面'}
    OMISSION_PATTERNS = [
        r'^删除[吧呢]?$', r'^删掉[吧呢]?$', r'^修改分类[吧呢]?$',
        r'^确认[吧呢]?$', r'^好的[吧呢]?$', r'^执行[吧呢]?$', r'^同意[吧呢]?$',
    ]
    
    @classmethod
    def resolve(cls, query: str, context: 'ConversationContext') -> tuple[str, Optional[Set[int]]]:
        query = query.strip()
        has_pronoun = any(p in query for p in cls.PRONOUNS)
        is_omission = any(re.match(pat, query) for pat in cls.OMISSION_PATTERNS)
        
        if not (has_pronoun or is_omission):
            return query, None
            
        inherited_ids = context.get_recent_entities(turn_offset=1)
        if not inherited_ids:
            return query, None
            
        scope_hint = f"[系统提示：用户使用了指代/省略表达，当前作用域包含 ID: {sorted(inherited_ids)}]"
        enhanced_query = f"{scope_hint}\n用户输入：{query}"
        return enhanced_query, inherited_ids
```

### 4.4 Prompt 模板改造

```
[系统指令]
你是炽阳，本地密码保险箱的AI助手。当前模式：{mode}。当前仓库：{vault_type}。
...

[对话历史]
{conversation_history}

[当前数据库摘要]
{db_summary}

[用户输入]
{enhanced_query}
```

**自适应压缩：**
- 历史总字符 > 2000：仅保留最近 3 轮
- 历史总字符 > 3000：仅保留最近 2 轮极简格式 `(action, entity_ids)`
- 数据库摘要：第一轮注入完整摘要；后续仅当检测到"新增"/"变化"词汇时重新注入

### 4.5 高亮状态与上下文绑定

```python
def _on_ai_query_finished(self, result):
    matched_ids = result.get('matched_ids', [])
    self._highlight_items(matched_ids)
    
    if self.ai_mode == 'plan':
        snapshot = TurnSnapshot(
            user_input=result['original_query'],
            parsed_action=result['action'],
            params_summary=str(result.get('params', {}))[:100],
            ai_reply_summary=result['reply'][:80],
            plan_entity_ids=set(matched_ids),
            vault_type=self.current_vault
        )
        self.ai_assistant_service.conversation_context.append_turn(snapshot)
```

**高亮持久化规则：**
- 上下文未重置时，跨轮继承高亮**持续保持**
- 新全局查询返回新 `matched_ids` 时，**替换高亮**
- 点击"清空"或切换 Tab 时，**清除高亮**

---

## 五、Phase 3：批量导入

### 5.1 Action 定义

```python
VALID_ACTIONS = [
    'search', 'filter', 'list', 'reorganize', 'add_remark', 
    'delete', 'add', 'explain',
    'batch_add_account', 'batch_add_url'
]
READONLY_ACTIONS = {'search', 'filter', 'list', 'explain'}
WRITE_ACTIONS = {'reorganize', 'add_remark', 'delete', 'add', 
                 'batch_add_account', 'batch_add_url'}
```

### 5.2 分批切割与解析

```python
class BatchAddProcessor:
    MAX_BATCH_CHARS = 4000
    MAX_BATCH_ITEMS = 20
    
    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        import re
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        en_words = len(re.findall(r'[a-zA-Z]+', text))
        return int(cn_chars * 1.5 + en_words * 1.2)
    
    @classmethod
    def chunk_text(cls, text: str) -> List[str]:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        chunks = []
        current_chunk = []
        current_chars = 0
        current_items = 0
        
        for line in lines:
            line_chars = len(line)
            if (current_chars + line_chars > cls.MAX_BATCH_CHARS or 
                current_items >= cls.MAX_BATCH_ITEMS):
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_chars = line_chars
                current_items = 1
            else:
                current_chunk.append(line)
                current_chars += line_chars
                current_items += 1
                
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        return chunks
```

### 5.3 BatchAddPreviewWidget

采用 `QTableView` + `QAbstractTableModel`。

**密码库列：**
| 列 | 内容 | 可编辑 | 默认显示 |
|----|------|--------|----------|
| ☑ | 复选框 | 是 | 勾选 |
| 应用 | app | 是 | - |
| 账号 | account | 是 | - |
| 密码 | password | 是 | **明文** |
| 网址 | url | 是 | - |
| 分类 | category（下拉框） | 是 | - |
| 备注 | remark | 是 | - |
| 标签 | tags | 是 | - |
| 状态 | 预检结果 | 否 | 动态 |

**网址库列：**
| 列 | 内容 | 可编辑 |
|----|------|--------|
| ☑ | 复选框 | 是 |
| 标题 | title | 是 |
| 网址 | url | 是 |
| 分类 | category | 是 |
| 标签 | tags | 是 |
| 备注 | remark | 是 |
| 状态 | 预检结果 | 否 |

**底部快捷操作栏：**
- `[全选]` `[全不选]` `[反选]`
- `[批量修改分类 ▼]`
- `[智能推断分类]`

### 5.4 去重预检与分类处理

```python
def _check_item_status(self, item: Dict, repo: VaultRepository) -> tuple[str, bool]:
    # 1. 必填字段
    if repo.get_item_type_name() == "网址" and not item.get('url'):
        return "格式错误：URL 缺失", False
    if repo.get_item_type_name() == "账号" and not item.get('app'):
        return "格式错误：应用名缺失", False
    
    # 2. 重复检查
    existing = repo.check_duplicate(item)
    if existing:
        return f"重复：已存在 ID={existing.id}", False
    
    # 3. 分类检查
    category = item.get('category', '其他')
    valid_categories = repo.get_categories()
    if category not in valid_categories:
        item['category'] = '其他'
        return f"分类'{category}'不存在，已归入'其他'", True
    
    return "就绪", True
```

**状态图标：**
- 🟢 `就绪`
- 🟡 `重复：已存在 ID=xx`（不勾选）
- 🔴 `格式错误：...`（不勾选）
- 🔵 `分类'xxx'不存在，已归入'其他'`（勾选，提示用户）

### 5.5 执行层：逐条独立导入

```python
def _execute_batch_add(self, params: Dict, repo: VaultRepository) -> Dict:
    items = params.get('items', [])
    
    success_count = 0
    skip_count = 0
    fail_count = 0
    fail_details = []
    inserted_ids = []
    
    for item in items:
        if not item.get('confirmed', True):
            skip_count += 1
            continue
            
        try:
            new_id = repo.insert(item)
            success_count += 1
            inserted_ids.append(new_id)
        except Exception as e:
            fail_count += 1
            fail_details.append({'item': item, 'error': str(e)})
    
    self.db.insert_audit_log(
        action=f'batch_add_{repo.get_item_type_name()}',
        details=f'成功{success_count}, 跳过{skip_count}, 失败{fail_count}'
    )
    
    return {
        'success': success_count, 'skip': skip_count, 'fail': fail_count,
        'fail_details': fail_details, 'inserted_ids': inserted_ids
    }
```

### 5.6 Plan 模式降级

```python
if mode == 'plan' and action in ('batch_add_account', 'batch_add_url'):
    items, failed = self.parse_batch_text(text, vault_type)
    return {
        'action': 'explain',
        'reply': self._format_batch_preview_reply(items, failed, vault_type),
        'parsed_items': items,
        'show_switch_to_build_button': True
    }
```

UI 展示：文本总结 + 可折叠 JSON 预览 + **`[切换到 BUILD 模式并导入]`** 按钮。

---

## 六、Phase 4：批量删除

### 6.1 `delete` Action 扩展

模型解析支持两种形式：

```json
// 形式A：条件式
{"action": "delete", "params": {"item_type": "account", "filter_conditions": {"category": "测试"}}}

// 形式B：ID列表式
{"action": "delete", "params": {"item_type": "url", "target_ids": [5, 8, 12]}}
```

### 6.2 预览与执行

通过 `repo.resolve_filter_conditions(conditions)` 将条件解析为 ID 列表，复用 `PreviewData` 展示。

**超过 50 条警告：**

```python
if len(target_ids) > 50:
    reply = QMessageBox.warning(
        self, "批量删除警告",
        f"即将删除 {len(target_ids)} 条记录，数量较多。\n请确认是否继续？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if reply != QMessageBox.StandardButton.Yes:
        return
```

**执行：逐条独立软删除。**

---

## 七、实施顺序与估时

```
Phase 0: Repository 抽象 + 架构底座（约 2-3 天）
  ├─ 新建 core/repositories.py（VaultRepository / AccountRepository / URLRepository / RepositoryFactory）
  ├─ AIAssistantService 重构（execute_action / build_action_preview / execute_build_action）
  ├─ PreviewData 标准化格式替换旧字典
  ├─ URLItem 新增 ai_remark / remark 字段 + 数据库 migration
  ├─ 删除 ui/url_manager_dialog.py 及所有引用
  └─ 修复 semantic_match 网址库高亮逻辑

Phase 1: UI 修复与增强（约 1-2 天）
  ├─ 列表滚动位置保持机制（保存/恢复）
  ├─ 网址库添加/编辑弹窗增强（备注、标签、AI生成、点击编辑）
  └─ 分类下拉栏同步修复（网址库 + 检查密码库）

Phase 2: 多轮上下文（约 1-2 天）
  ├─ ConversationContext + TurnSnapshot
  ├─ ReferenceResolver 指代消解
  ├─ Prompt 模板改造 + 自适应压缩
  ├─ 生命周期植入（Tab切换、idle_timeout、定时器）
  ├─ idle_timeout 设置项加入设置对话框
  └─ 高亮状态与上下文绑定

Phase 3: 批量导入（约 2-3 天）
  ├─ batch_add_account / batch_add_url Action
  ├─ BatchAddProcessor 分批切割
  ├─ 批量解析 Prompt 与聚合逻辑
  ├─ BatchAddPreviewWidget（QTableView + Model + 编辑 + 去重预检）
  ├─ 逐条独立导入执行层
  └─ Plan 降级与"一键转 Build"

Phase 4: 批量删除（约 1 天）
  ├─ delete Action 扩展 filter_conditions
  ├─ resolve_filter_to_ids（通过 Repository）
  ├─ 超过 50 条警告弹窗
  └─ 预览 UI 增强

Phase 5: 联调测试（约 1-2 天）
  ├─ 密码库/网址库全流程测试
  ├─ Repository 单元测试
  ├─ 多轮对话边界测试
  ├─ 批量导入边界测试（超长文本、格式错误、重复、分批失败）
  ├─ 批量删除条件解析测试
  └─ 性能测试（上下文内存、分批并发、大列表滚动保持）
```

---

**文档结束。Repository 抽象已作为核心架构底座纳入 Phase 0。请回复"开始 Phase 0"即可进入编码。**
