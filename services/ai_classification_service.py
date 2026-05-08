"""
AI智能分类引擎
支持密码库和网址库的一键智能整理
工作流：预分析 -> 人工确认 -> 执行归类 -> 差异预览 -> 生效/回滚
"""
import logging
import json
import time
import hashlib
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from models.account import Account
from models.url_item import URLItem

logger = logging.getLogger(__name__)


@dataclass
class CategoryProposal:
    """类别提议"""
    name: str                          # 类别名称
    description: str                   # 类别定义/描述
    estimated_count: int               # 预计收纳条目数
    examples: List[str] = field(default_factory=list)  # 典型示例
    is_new: bool = True                # 是否新建类别
    conflicts: List[str] = field(default_factory=list)  # 冲突检测（与现有类别重叠）
    merge_target: Optional[str] = None # 合并目标类别
    force_new: bool = False            # 强制新建
    source_items: List[int] = field(default_factory=list)  # 关联的条目ID


@dataclass
class ClassificationChange:
    """分类变更记录"""
    item_id: int
    item_name: str                      # 应用名/标题
    item_type: str                      # 'account' 或 'url'
    old_category: str
    new_category: str
    confidence: float                   # 置信度
    suggested_tags: List[str] = field(default_factory=list)
    is_low_confidence: bool = False     # 是否低置信度
    is_pending: bool = False            # 是否在待整理区
    user_override: bool = False         # 用户是否手动覆盖


@dataclass
class ClassificationSnapshot:
    """分类快照（用于回滚）"""
    snapshot_id: str
    created_at: str
    item_type: str                      # 'account' 或 'url'
    changes: List[ClassificationChange]
    before_state: Dict[int, str]        # item_id -> category


class AIClassificationService:
    """AI智能分类引擎"""
    
    # 最小条目数阈值
    MIN_ITEMS_THRESHOLD = 5
    # 冷却时间已移除：用户可随时执行一键整理
    # 低置信度阈值
    LOW_CONFIDENCE_THRESHOLD = 0.6

    def _format_category_tree(self, categories: list) -> str:
        """将分类列表格式化为树形文本，用于注入 Prompt"""
        from core.category_utils import build_category_tree
        tree = build_category_tree([c for c in categories if c and c != '全部'])
        lines = []
        for parent, info in sorted(tree.items()):
            children = sorted(info.get('children', set()))
            if children:
                lines.append(f"- {parent}")
                for child in children:
                    lines.append(f"  - {parent}>{child}")
            else:
                lines.append(f"- {parent}")
        return "\n".join(lines) if lines else "（暂无分类）"
    
    def _sanitize_classified_category(self, raw_category: str, approved_categories: list) -> str:
        """校验并修正 AI 输出的分类路径"""
        from core.category_utils import format_category_path, parse_category_path, validate_category_name
        cleaned = raw_category.strip()
        if not cleaned:
            return '其他'

        parent = None
        child = None
        try:
            parent, child = parse_category_path(cleaned)
            if not validate_category_name(parent) or (child and not validate_category_name(child)):
                raise ValueError("Invalid category name")
            cleaned = format_category_path(parent, child)
        except ValueError:
            # 回退：尝试提取一级分类
            if parent is not None:
                parent_fallback = parent
            else:
                sep_idx = cleaned.find('>')
                parent_fallback = cleaned[:sep_idx].strip() if sep_idx != -1 else cleaned.strip()

            if validate_category_name(parent_fallback) and parent_fallback in approved_categories:
                return parent_fallback
            # 完全回退到"其他"
            return '其他'

        # 如果不在批准列表中，回退
        if cleaned not in approved_categories:
            # 尝试一级分类回退
            if parent in approved_categories:
                return parent
            return '其他'
        return cleaned
    
    def __init__(self, db_manager=None, url_db_manager=None):
        self.db = db_manager
        self.url_db = url_db_manager
        self._current_proposals: List[CategoryProposal] = []
        self._pending_changes: List[ClassificationChange] = []
        self._snapshots: List[ClassificationSnapshot] = []
        
        # 冷却时间已移除
    
    def can_classify(self, items_count: int) -> Tuple[bool, str]:
        """
        检查是否可以执行分类
        
        Returns:
            (是否可以, 原因)
        """
        if items_count < self.MIN_ITEMS_THRESHOLD:
            return False, f"条目数量不足（当前{items_count}条，至少需要{self.MIN_ITEMS_THRESHOLD}条）"
        
        return True, ""
    
    def pre_analyze_accounts(self, accounts: List[Account], 
                            existing_categories: List[str]) -> List[CategoryProposal]:
        """
        预分析密码库：生成类别提议清单（非阻塞只读）
        
        Args:
            accounts: 账号列表
            existing_categories: 现有类别列表
            
        Returns:
            类别提议列表
        """
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            # 降级：使用启发式分类
            return self._heuristic_pre_analyze(accounts, existing_categories, 'account')
        
        # 构建元数据文本
        items_text = []
        for i, acc in enumerate(accounts):
            tags = acc.get_tags_list()
            tags_str = ','.join(tags) if tags else '无标签'
            items_text.append(
                f"[{i}] 应用名:{acc.app_name} 网址:{acc.url} 分类:{acc.category} "
                f"标签:{tags_str} 备注:{acc.remark}"
            )
        
        # 传入全部数据，超过200条时截断到150条
        items_str = '\n'.join(items_text)
        prompt = f"""你是一款密码管理软件的AI分类专家。请对以下所有账号进行深度分析，提出一套精细、合理的分类体系。

## 分析要求
1. 仔细阅读每个账号的【应用名、网址、当前分类、标签、备注】，找出数据中的真实聚类特征
2. 不要局限于现有类别，根据数据特征提出 8-15 个新分类
3. 每个分类必须有清晰的定义（说明包含什么、不包含什么）
4. 分类名称要简洁（2-4个字），但要能准确反映类别特征
5. **重要**：不要把"其他"作为默认选项。只有当某个账号确实与所有分类都不相关时，才放入"其他"
6. **目标**："其他"类别的账号数量不得超过总数的 10%
7. 对于当前已在合理分类中的账号，保留其现有分类

## 当前分类体系（请优先在此体系内归类，必要时可新建）
{self._format_category_tree(existing_categories)}

## 输出规则
1. 分类名称使用路径格式 `主类>子类`（最多二级），如 `工作>开发工具`、`娱乐>游戏`
2. 如果某个条目只属于一个大类、不需要细分，可只输出主类，如 `学术与研究`
3. 如需新建子类，确保主类已存在于体系中；如需新建主类，直接输出主类名
4. 分类名禁止包含 `/`、`>`、`·` 三个符号（`>` 仅作为层级分隔符出现一次）
5. 并列概念用"与"连接，如 `金融与支付`

## 账号列表（共{len(accounts)}条，请务必分析全部）：
{items_str}

## 输出格式（严格JSON）
你必须只输出纯JSON，不要任何解释、markdown代码块标记或其他文字：
{{"proposals":[{{"name":"类别名称","estimated_count":预计条目数}}]}}

要求：
- proposals 中的类别必须能覆盖绝大多数账号（>90%）
- 只输出纯JSON，不要```json标记
- 任何字段的值都不要包含英文双引号"，如果必须引用请使用中文引号「」"""
        
        result = None
        json_str = None
        try:
            from ai.ollama_client import OllamaClient
            state = ai_manager.get_state()
            ollama = OllamaClient(model=state.model_name or "gemma4:4b")
            result = ollama.generate(prompt, temperature=0.3)
            
            # 提取JSON
            json_str = self._extract_json(result)
            data = json.loads(json_str)
            
            proposals = []
            for prop in data.get('proposals', []):
                raw_name = prop.get('name', '未命名')
                from services.ai_tools import sanitize_ai_category
                sanitized_name = sanitize_ai_category(raw_name)
                proposal = CategoryProposal(
                    name=sanitized_name,
                    description=prop.get('description', ''),
                    estimated_count=prop.get('estimated_count', 0),
                    examples=prop.get('examples', []),
                    conflicts=prop.get('conflicts', [])
                )
                proposals.append(proposal)
            
            self._current_proposals = proposals
            return proposals
            
        except Exception as e:
            logger.exception("Pre-analysis failed")
            if result is not None:
                logger.debug("Raw result full (%d chars): %r", len(result), result)
            if json_str is not None:
                logger.debug("Extracted JSON full (%d chars): %r", len(json_str), json_str)
            return self._heuristic_pre_analyze(accounts, existing_categories, 'account')
    
    def pre_analyze_urls(self, urls: List[URLItem], 
                        existing_categories: List[str]) -> List[CategoryProposal]:
        """
        预分析网址库：生成类别提议清单
        """
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            return self._heuristic_pre_analyze(urls, existing_categories, 'url')
        
        items_text = []
        for i, item in enumerate(urls):
            tags = item.get_tags_list()
            tags_str = ','.join(tags) if tags else '无标签'
            items_text.append(
                f"[{i}] 标题:{item.title} 网址:{item.url} 分类:{item.category} 标签:{tags_str}"
            )
        
        # 传入全部数据，超过200条时截断到150条
        items_str = '\n'.join(items_text)
        prompt = f"""你是一款网址管理软件的AI分类专家。请对以下所有网址进行深度分析，提出一套精细、合理的分类体系。

## 分析要求
1. 仔细阅读每个网址的【标题、网址、当前分类、标签】，找出数据中的真实聚类特征
2. 不要局限于现有类别，根据数据特征提出 8-15 个新分类
3. 每个分类必须有清晰的定义（说明包含什么、不包含什么）
4. 分类名称要简洁（2-4个字），但要能准确反映类别特征
5. **重要**：不要把"其他"作为默认选项。只有当某个网址确实与所有分类都不相关时，才放入"其他"
6. **目标**："其他"类别的网址数量不得超过总数的 10%
7. 对于当前已在合理分类中的网址，保留其现有分类

## 当前分类体系（请优先在此体系内归类，必要时可新建）
{self._format_category_tree(existing_categories)}

## 输出规则
1. 分类名称使用路径格式 `主类>子类`（最多二级），如 `工作>开发工具`、`娱乐>游戏`
2. 如果某个条目只属于一个大类、不需要细分，可只输出主类，如 `学术与研究`
3. 如需新建子类，确保主类已存在于体系中；如需新建主类，直接输出主类名
4. 分类名禁止包含 `/`、`>`、`·` 三个符号（`>` 仅作为层级分隔符出现一次）
5. 并列概念用"与"连接，如 `金融与支付`

## 网址列表（共{len(urls)}条，请务必分析全部）：
{items_str}

## 输出格式（严格JSON）
你必须只输出纯JSON，不要任何解释、markdown代码块标记或其他文字：
{{"proposals":[{{"name":"类别名称","estimated_count":预计条目数}}]}}

要求：
- proposals 中的类别必须能覆盖绝大多数网址（>90%）
- 只输出纯JSON，不要```json标记
- 任何字段的值都不要包含英文双引号"，如果必须引用请使用中文引号「」"""
        
        try:
            from ai.ollama_client import OllamaClient
            state = ai_manager.get_state()
            ollama = OllamaClient(model=state.model_name or "gemma4:4b")
            result = ollama.generate(prompt, temperature=0.3)
            json_str = self._extract_json(result)
            data = json.loads(json_str)
            
            proposals = []
            for prop in data.get('proposals', []):
                raw_name = prop.get('name', '未命名')
                from services.ai_tools import sanitize_ai_category
                sanitized_name = sanitize_ai_category(raw_name)
                proposal = CategoryProposal(
                    name=sanitized_name,
                    description=prop.get('description', ''),
                    estimated_count=prop.get('estimated_count', 0),
                    examples=prop.get('examples', []),
                    conflicts=prop.get('conflicts', [])
                )
                proposals.append(proposal)
            
            self._current_proposals = proposals
            return proposals
            
        except Exception as e:
            logger.exception("URL pre-analysis failed")
            return self._heuristic_pre_analyze(urls, existing_categories, 'url')
    
    def execute_classification(self, items: List, 
                              approved_categories: List[str],
                              item_type: str = 'account',
                              progress_callback=None) -> List[ClassificationChange]:
        """
        执行批量归类（需要用户确认后的类别列表）
        
        Args:
            items: 账号列表或网址列表
            approved_categories: 用户确认的类别名称列表
            item_type: 'account' 或 'url'
            progress_callback: 进度回调函数(progress, total)
            
        Returns:
            变更列表
        """
        if not items:
            return []
        
        changes = []
        total = len(items)
        
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        if not ai_manager.is_available():
            # 降级：启发式分类
            for i, item in enumerate(items):
                change = self._heuristic_classify_item(item, approved_categories, item_type)
                changes.append(change)
                if progress_callback:
                    progress_callback(i + 1, total)
            self._pending_changes = changes
            return changes
        
        # 分批处理（每批10条，避免上下文过长）
        batch_size = 10
        for batch_start in range(0, len(items), batch_size):
            batch = items[batch_start:batch_start + batch_size]
            batch_changes = self._classify_batch(batch, approved_categories, item_type)
            changes.extend(batch_changes)
            
            if progress_callback:
                progress_callback(min(batch_start + batch_size, total), total)
        
        self._pending_changes = changes
        return changes
    
    def create_snapshot(self, item_type: str, items: List) -> ClassificationSnapshot:
        """创建分类前快照"""
        snapshot_id = hashlib.sha256(
            f"{item_type}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]
        
        before_state = {}
        for item in items:
            item_id = item.id if hasattr(item, 'id') else 0
            category = item.category if hasattr(item, 'category') else '其他'
            before_state[item_id] = category
        
        snapshot = ClassificationSnapshot(
            snapshot_id=snapshot_id,
            created_at=datetime.now().isoformat(),
            item_type=item_type,
            changes=self._pending_changes.copy(),
            before_state=before_state
        )
        
        # 持久化到数据库
        if self.db:
            try:
                before_state_json = json.dumps(before_state, ensure_ascii=False)
                changes_json = json.dumps(
                    [self._change_to_dict(c) for c in self._pending_changes],
                    ensure_ascii=False
                )
                self.db.insert_snapshot(snapshot_id, item_type, before_state_json, changes_json)
            except Exception as e:
                logger.error("Failed to persist snapshot: %s", e)
                # 回退到内存存储
                self._snapshots.append(snapshot)
        else:
            self._snapshots.append(snapshot)
        
        # 只保留最近30天的快照
        self._cleanup_old_snapshots()
        
        return snapshot
    
    def rollback(self, snapshot_id: str, items: List) -> bool:
        """
        回滚到快照状态
        
        Args:
            snapshot_id: 快照ID
            items: 当前条目列表
            
        Returns:
            是否成功
        """
        snapshot = None
        
        # 优先从数据库读取
        if self.db:
            try:
                db_snapshots = self.db.get_snapshots()
                for s in db_snapshots:
                    if s['snapshot_id'] == snapshot_id:
                        changes_data = json.loads(s['changes'])
                        if not isinstance(changes_data, list):
                            changes_data = []
                        snapshot = ClassificationSnapshot(
                            snapshot_id=s['snapshot_id'],
                            created_at=s['created_at'],
                            item_type=s['item_type'],
                            before_state=json.loads(s['before_state']),
                            changes=[self._dict_to_change(c) for c in changes_data]
                        )
                        break
            except Exception as e:
                logger.error("Failed to load snapshot from DB: %s", e)
        
        # 回退到内存
        if not snapshot:
            for s in self._snapshots:
                if s.snapshot_id == snapshot_id:
                    snapshot = s
                    break
        
        if not snapshot:
            return False
        
        # 回滚分类并写入数据库
        for item in items:
            item_id = item.id if hasattr(item, 'id') else 0
            if item_id in snapshot.before_state:
                item.category = snapshot.before_state[item_id]
                
                # 写入数据库
                if snapshot.item_type == 'account' and self.db:
                    try:
                        self.db.update_account(item_id, {'category': item.category})
                    except Exception as e:
                        logger.error("Failed to update account %s: %s", item_id, e)
                elif snapshot.item_type == 'url' and self.url_db:
                    try:
                        self.url_db.update_url(item_id, {'category': item.category})
                    except Exception as e:
                        logger.error("Failed to update url %s: %s", item_id, e)
        
        return True
    
    def get_snapshots(self, item_type: str = None) -> List[ClassificationSnapshot]:
        """获取快照列表"""
        snapshots = []
        
        # 优先从数据库读取
        if self.db:
            try:
                db_snapshots = self.db.get_snapshots(item_type)
                for s in db_snapshots:
                    try:
                        changes_data = json.loads(s['changes'])
                        if not isinstance(changes_data, list):
                            changes_data = []
                        snapshots.append(ClassificationSnapshot(
                            snapshot_id=s['snapshot_id'],
                            created_at=s['created_at'],
                            item_type=s['item_type'],
                            before_state=json.loads(s['before_state']),
                            changes=[self._dict_to_change(c) for c in changes_data]
                        ))
                    except Exception as e:
                        logger.error("Failed to parse snapshot %s: %s", s['snapshot_id'], e)
            except Exception as e:
                logger.error("Failed to get snapshots from DB: %s", e)
        
        # 如果数据库为空，回退到内存中的快照
        if not snapshots and self._snapshots:
            if item_type:
                return [s for s in self._snapshots if s.item_type == item_type]
            return self._snapshots.copy()
        
        return snapshots
    
    def _classify_batch(self, batch: List, categories: List[str], 
                       item_type: str) -> List[ClassificationChange]:
        """分类一批条目"""
        items_text = []
        for i, item in enumerate(batch):
            if item_type == 'account':
                tags = item.get_tags_list()
                tags_str = ','.join(tags) if tags else ''
                items_text.append(
                    f"[{i}] {item.app_name}|{item.url}|{item.category}|{tags_str}|{item.remark}"
                )
            else:
                items_text.append(
                    f"[{i}] {item.title}|{item.url}|{item.category}"
                )
        
        items_str = '\n'.join(items_text)
        prompt = f"""请将以下{item_type}分配到最合适的类别中。

## 可用类别（用户已确认的分类体系）
{self._format_category_tree(categories)}

## 分类原则
1. 仔细阅读每个条目的名称、网址、备注，找到与类别的最佳匹配
2. 只要条目与某个类别有一定相关性，就优先归入该类别，**不要偷懒归入"其他"**
3. 只有当条目与所有类别的关联度都极低（几乎完全不相关）时，才归入"其他"
4. "其他"的使用比例应控制在 10% 以内
5. 对于跨域条目，选择最相关的一个类别（强制单选）
6. 类别名使用分类路径格式 `主类>子类`（最多二级），如 `工作>开发工具`
7. 如果某个条目只属于一个大类、不需要细分，可只输出主类，如 `学术与研究`
8. 分类名禁止包含 `/`、`>`、`·` 三个符号（`>` 仅作为层级分隔符出现一次）

## 条目列表（格式：序号|名称|网址|当前分类|备注）：
{items_str}

## 输出格式（严格JSON）
你必须只输出纯JSON，不要任何解释或markdown代码块：
{{"results":[{{"index":0,"category":"类别名称"}}]}}
注意：
- category 只能从给定的类别列表中选择
- 不要输出 reason、confidence、tags 等额外字段
- 只输出纯JSON，不要```json标记"""
        
        result = None
        json_str = None
        try:
            from services.ai_service_manager import AIServiceManager
            ai_manager = AIServiceManager.instance()
            from ai.ollama_client import OllamaClient
            state = ai_manager.get_state()
            ollama = OllamaClient(model=state.model_name or "gemma4:4b")
            result = ollama.generate(prompt, temperature=0.2)
            json_str = self._extract_json(result)
            data = json.loads(json_str)
            
            changes = []
            for res in data.get('results', []):
                idx = res.get('index', 0)
                if 0 <= idx < len(batch):
                    item = batch[idx]
                    old_cat = item.category
                    raw_cat = res.get('category', old_cat)
                    confidence = res.get('confidence', 0.5)
                    
                    # 校验并修正 AI 输出的分类路径
                    new_cat = self._sanitize_classified_category(raw_cat, categories)
                    
                    change = ClassificationChange(
                        item_id=item.id if hasattr(item, 'id') else 0,
                        item_name=item.app_name if hasattr(item, 'app_name') else item.title,
                        item_type=item_type,
                        old_category=old_cat,
                        new_category=new_cat,
                        confidence=confidence,
                        suggested_tags=res.get('tags', []),
                        is_low_confidence=confidence < self.LOW_CONFIDENCE_THRESHOLD
                    )
                    changes.append(change)
            
            # 补充未分类的
            if len(changes) < len(batch):
                classified_indices = {c.item_id for c in changes}
                for item in batch:
                    item_id = item.id if hasattr(item, 'id') else 0
                    if item_id not in classified_indices:
                        changes.append(ClassificationChange(
                            item_id=item_id,
                            item_name=item.app_name if hasattr(item, 'app_name') else item.title,
                            item_type=item_type,
                            old_category=item.category,
                            new_category='其他',
                            confidence=0.0,
                            is_low_confidence=True
                        ))
            
            return changes
            
        except Exception as e:
            logger.exception("Batch classification failed")
            if result is not None:
                logger.debug("Batch raw result preview (first 500 chars): %r", result[:500])
            if json_str is not None:
                logger.debug("Batch extracted JSON preview (first 500 chars): %r", json_str[:500])
            # 降级：全部归入当前分类
            changes = []
            for item in batch:
                changes.append(ClassificationChange(
                    item_id=item.id if hasattr(item, 'id') else 0,
                    item_name=item.app_name if hasattr(item, 'app_name') else item.title,
                    item_type=item_type,
                    old_category=item.category,
                    new_category=item.category,
                    confidence=0.0
                ))
            return changes
    
    def _heuristic_pre_analyze(self, items: List, existing_categories: List[str], 
                               item_type: str) -> List[CategoryProposal]:
        """启发式预分析（降级方案）"""
        # 基于关键词统计
        category_keywords = {
            '金融': ['银行', '支付', '理财', '保险', '证券', '信用卡', '支付宝', '微信'],
            '社交': ['微信', 'QQ', '微博', '抖音', '小红书', '知乎', '推特', 'Facebook'],
            '邮箱': ['邮箱', 'mail', 'gmail', 'outlook', '163', 'qq邮箱'],
            '游戏': ['游戏', 'steam', 'epic', '暴雪', '腾讯', '网易游戏'],
            '工作': ['办公', '企业', '钉钉', '飞书', 'slack', 'github', 'gitlab'],
            '购物': ['淘宝', '京东', '拼多多', '亚马逊', '天猫', '购物', '商城', '电商'],
            '教育': ['学习', '课程', 'edu', '学堂', 'mooc', 'coursera', 'academy'],
            '娱乐': ['视频', '影视', '音乐', 'bilibili', 'youtube', 'netflix', 'spotify'],
            '开发': ['开发', '代码', 'git', 'api', 'docker', 'vscode', 'jetbrains'],
            '云服务': ['云', '服务器', 'aws', '阿里云', '腾讯云', 'heroku', 'vercel'],
            '健康': ['健康', '医院', '医保', '健身', 'medical', 'health'],
            '政府': ['政府', '社保', '公积金', '税务', 'gov'],
        }
        
        # 统计各类别数量
        category_counts = {cat: 0 for cat in existing_categories}
        category_examples = {cat: [] for cat in existing_categories}
        
        for item in items:
            name = item.app_name if hasattr(item, 'app_name') else item.title
            matched = False
            for cat, keywords in category_keywords.items():
                if any(kw in name.lower() for kw in keywords):
                    if cat in category_counts:
                        category_counts[cat] += 1
                        if len(category_examples[cat]) < 3:
                            category_examples[cat].append(name)
                    matched = True
                    break
            if not matched:
                category_counts['其他'] = category_counts.get('其他', 0) + 1
                if len(category_examples.get('其他', [])) < 3:
                    category_examples.setdefault('其他', []).append(name)
        
        proposals = []
        for cat, count in category_counts.items():
            if count > 0:
                proposals.append(CategoryProposal(
                    name=cat,
                    description=f"基于关键词规则自动识别的{cat}类条目",
                    estimated_count=count,
                    examples=category_examples.get(cat, [])[:3],
                    is_new=cat not in existing_categories
                ))
        
        return proposals
    
    def _heuristic_classify_item(self, item, categories: List[str], 
                                 item_type: str) -> ClassificationChange:
        """启发式单条分类"""
        name = item.app_name if hasattr(item, 'app_name') else item.title
        old_cat = item.category
        
        # 基于关键词匹配
        category_keywords = {
            '金融': ['银行', '支付', '理财', '保险', '证券', '信用卡', '支付宝'],
            '社交': ['微信', 'QQ', '微博', '抖音', '小红书', '知乎', '推特', 'Facebook'],
            '邮箱': ['邮箱', 'mail', 'gmail', 'outlook', '163', 'qq邮箱'],
            '游戏': ['游戏', 'steam', 'epic', '暴雪', '腾讯', '网易游戏'],
            '工作': ['办公', '企业', '钉钉', '飞书', 'slack', 'github', 'gitlab'],
            '购物': ['淘宝', '京东', '拼多多', '亚马逊', '天猫', '购物', '商城', '电商'],
            '教育': ['学习', '课程', 'edu', '学堂', 'mooc', 'coursera', 'academy'],
            '娱乐': ['视频', '影视', '音乐', 'bilibili', 'youtube', 'netflix', 'spotify'],
            '开发': ['开发', '代码', 'git', 'api', 'docker', 'vscode', 'jetbrains'],
            '云服务': ['云', '服务器', 'aws', '阿里云', '腾讯云', 'heroku', 'vercel'],
            '健康': ['健康', '医院', '医保', '健身', 'medical', 'health'],
            '政府': ['政府', '社保', '公积金', '税务', 'gov'],
        }
        
        for cat, keywords in category_keywords.items():
            if cat in categories and any(kw in name.lower() for kw in keywords):
                return ClassificationChange(
                    item_id=item.id if hasattr(item, 'id') else 0,
                    item_name=name,
                    item_type=item_type,
                    old_category=old_cat,
                    new_category=cat,
                    confidence=0.5,
                    is_low_confidence=False
                )
        
        # 无匹配，保持原分类
        return ClassificationChange(
            item_id=item.id if hasattr(item, 'id') else 0,
            item_name=name,
            item_type=item_type,
            old_category=old_cat,
            new_category=old_cat,
            confidence=0.0
        )
    
    def _extract_json(self, text: str) -> str:
        """从文本中提取JSON，支持代码块和普通文本，并修复常见语法错误"""
        import re
        from ai.ollama_client import OllamaClient

        # 1. 先尝试提取 ```json ... ``` 代码块
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            extracted = match.group(1).strip()
        else:
            # 2. 再尝试提取 ``` ... ``` 代码块
            match = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
            if match:
                extracted = match.group(1).strip()
            else:
                # 3. 使用 OllamaClient 的鲁棒提取
                extracted = OllamaClient._extract_json_object_robust(text) or text

        # 4. 修复常见 JSON 语法错误
        fixed = OllamaClient._fix_json(extracted)
        return fixed
    
    def _cleanup_old_snapshots(self):
        """清理30天前的快照"""
        # 清理数据库中的旧快照
        if self.db:
            try:
                self.db.cleanup_old_snapshots(30)
            except Exception as e:
                logger.error("Failed to cleanup DB snapshots: %s", e)
        
        # 同时清理内存中的旧快照
        cutoff = datetime.now().timestamp() - 30 * 86400
        self._snapshots = [
            s for s in self._snapshots 
            if datetime.fromisoformat(s.created_at).timestamp() > cutoff
        ]
    
    @staticmethod
    def _change_to_dict(change: ClassificationChange) -> dict:
        """将ClassificationChange转为字典"""
        return {
            'item_id': change.item_id,
            'item_name': change.item_name,
            'item_type': change.item_type,
            'old_category': change.old_category,
            'new_category': change.new_category,
            'confidence': change.confidence,
            'suggested_tags': change.suggested_tags,
            'is_low_confidence': change.is_low_confidence,
            'is_pending': change.is_pending,
            'user_override': change.user_override,
        }
    
    @staticmethod
    def _dict_to_change(data: dict) -> ClassificationChange:
        """将字典转为ClassificationChange"""
        return ClassificationChange(
            item_id=data.get('item_id', 0),
            item_name=data.get('item_name', ''),
            item_type=data.get('item_type', 'account'),
            old_category=data.get('old_category', ''),
            new_category=data.get('new_category', ''),
            confidence=data.get('confidence', 0.0),
            suggested_tags=data.get('suggested_tags', []),
            is_low_confidence=data.get('is_low_confidence', False),
            is_pending=data.get('is_pending', False),
            user_override=data.get('user_override', False),
        )
