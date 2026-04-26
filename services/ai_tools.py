"""
AI Tool Calling 基础设施
为 ReAct Agent 模式提供工具定义、注册和执行能力
"""
import json
import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable, Type


class PermissionLevel(Enum):
    """工具权限等级"""
    READONLY = "🟢"
    PREVIEW = "🟡"
    CONFIRM = "🔴"
    FORBIDDEN = "⛔"


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    preview_data: Optional[Dict] = None
    error: Optional[str] = None
    message: str = ""


class AITool:
    """AI 工具基类"""
    name: str = ""
    description: str = ""
    permission: PermissionLevel = PermissionLevel.READONLY
    params_schema: Dict[str, Any] = field(default_factory=dict)

    def execute(self, params: Dict, context: Dict) -> ToolResult:
        """执行工具
        Args:
            params: 工具参数
            context: 执行上下文，包含 accounts, urls, vault_type, inherited_ids, db, url_db, repo
        """
        raise NotImplementedError(f"工具 {self.name} 未实现 execute 方法")

    def validate_params(self, params: Dict) -> tuple[bool, Optional[str]]:
        """验证参数
        Returns:
            (是否有效, 错误信息)
        """
        return True, None

    def _make_preview(self, operation_type: str, target_vault: str,
                      items: List[Dict]) -> Dict:
        """构建标准预览数据结构"""
        return {
            "operation_type": operation_type,
            "target_vault": target_vault,
            "total_items": len(items),
            "items": items
        }

    def _make_preview_item(self, row_id: str, display_name: str,
                           secondary_name: str = "",
                           fields: List[Dict] = None,
                           raw_data: Dict = None) -> Dict:
        """构建标准预览条目"""
        return {
            "row_id": str(row_id),
            "display_name": display_name,
            "secondary_name": secondary_name,
            "fields": fields or [],
            "raw_data": raw_data or {}
        }

    def _get_item_map(self, context: Dict, key: str = "accounts") -> Dict[int, Any]:
        """从上下文中构建 ID -> 条目 映射"""
        items = context.get(key, [])
        return {getattr(it, 'id', it.get('id') if isinstance(it, dict) else None): it
                for it in items if getattr(it, 'id', it.get('id') if isinstance(it, dict) else None) is not None}

    def _get_field_value_safe(self, item: Any, field: str, repo=None) -> Any:
        """安全获取条目字段值"""
        if repo and hasattr(repo, 'get_field_value'):
            return repo.get_field_value(item, field) or ""
        if hasattr(item, field):
            val = getattr(item, field)
            return val if val is not None else ""
        if isinstance(item, dict):
            return item.get(field, "")
        return ""

    def _get_display_name_safe(self, item: Any, repo=None) -> str:
        """安全获取条目显示名"""
        if repo and hasattr(repo, 'get_display_name'):
            return repo.get_display_name(item)
        if hasattr(item, 'app_name'):
            return item.app_name or "未命名"
        if hasattr(item, 'title'):
            return item.title or "未命名"
        if isinstance(item, dict):
            return item.get('app_name', item.get('title', '未命名'))
        return "未命名"

    def _get_secondary_info_safe(self, item: Any, repo=None) -> str:
        """安全获取条目辅助信息"""
        if repo and hasattr(repo, 'get_secondary_info'):
            return repo.get_secondary_info(item) or ""
        if hasattr(item, 'username'):
            return item.username or ""
        if hasattr(item, 'url'):
            return item.url or ""
        if isinstance(item, dict):
            return item.get('username', item.get('url', ''))
        return ""


class ToolRegistry:
    """工具注册中心"""
    _tools: Dict[str, AITool] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, name: str = None, description: str = "",
                 permission: PermissionLevel = PermissionLevel.READONLY,
                 params_schema: Optional[Dict] = None) -> Callable[[Type], Type]:
        """装饰器注册工具类"""
        def decorator(tool_class: Type) -> Type:
            tool_name = name or tool_class.__name__
            instance = tool_class()
            instance.name = tool_name
            instance.description = description
            instance.permission = permission
            instance.params_schema = params_schema or {}
            with cls._lock:
                cls._tools[tool_name] = instance
            return tool_class
        return decorator

    @classmethod
    def list(cls) -> List[AITool]:
        """返回所有已注册工具实例"""
        with cls._lock:
            return list(cls._tools.values())

    @classmethod
    def list_for_prompt(cls) -> str:
        """生成 Prompt 可用的工具列表文本"""
        lines = []
        for tool in cls.list():
            lines.append(
                f"- {tool.name}: {tool.description} [权限: {tool.permission.value}]"
            )
            if tool.params_schema:
                schema_str = json.dumps(
                    tool.params_schema, ensure_ascii=False, indent=2
                )
                for line in schema_str.split('\n'):
                    lines.append(f"    {line}")
        return "\n".join(lines)

    @classmethod
    def get(cls, name: str) -> Optional[AITool]:
        """按名称获取工具实例"""
        with cls._lock:
            return cls._tools.get(name)


# ============ 语义搜索 (4) ============

def _build_accounts_summary(accounts: List[Any]) -> str:
    """构建账号摘要文本，供语义搜索使用"""
    lines = []
    for acc in accounts:
        acc_id = getattr(acc, 'id', acc.get('id') if isinstance(acc, dict) else 0)
        app_name = getattr(acc, 'app_name', acc.get('app_name', '') if isinstance(acc, dict) else '')
        category = getattr(acc, 'category', acc.get('category', '') if isinstance(acc, dict) else '')
        remark = getattr(acc, 'remark', acc.get('remark', '') if isinstance(acc, dict) else '')
        tags_str = ""
        tags = getattr(acc, 'tags', acc.get('tags', '') if isinstance(acc, dict) else '')
        if tags:
            try:
                tag_list = json.loads(tags) if isinstance(tags, str) else tags
                tags_str = ",".join(tag_list) if isinstance(tag_list, list) else str(tag_list)
            except Exception:
                tags_str = str(tags)
        lines.append(f"{acc_id} | {app_name} | {category or '未分类'} | {tags_str} | {(remark or '')[:20]}")
    return "\n".join(lines)


def _build_urls_summary(urls: List[Any]) -> str:
    """构建网址摘要文本，供语义搜索使用"""
    lines = []
    for u in urls:
        u_id = getattr(u, 'id', u.get('id') if isinstance(u, dict) else 0)
        title = getattr(u, 'title', u.get('title', '') if isinstance(u, dict) else '')
        url = getattr(u, 'url', u.get('url', '') if isinstance(u, dict) else '')
        category = getattr(u, 'category', u.get('category', '') if isinstance(u, dict) else '')
        remark = getattr(u, 'remark', u.get('remark', '') if isinstance(u, dict) else '')
        tags_str = ""
        tags = getattr(u, 'tags', u.get('tags', '') if isinstance(u, dict) else '')
        if tags:
            try:
                tag_list = json.loads(tags) if isinstance(tags, str) else tags
                tags_str = ",".join(tag_list) if isinstance(tag_list, list) else str(tag_list)
            except Exception:
                tags_str = str(tags)
        lines.append(f"{u_id} | {title} | {url} | {category or '未分类'} | {tags_str} | {(remark or '')[:20]}")
    return "\n".join(lines)


@ToolRegistry.register(
    name="semantic_search_accounts",
    description="语义搜索账号，理解自然语言查询返回相关账号",
    permission=PermissionLevel.READONLY,
    params_schema={"query": {"type": "string", "description": "用户搜索词"}}
)
class SemanticSearchAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        query = params.get("query", "")
        accounts = context.get("accounts", [])
        if not accounts or not query:
            return ToolResult(success=True, data={"matched_count": 0, "matched_ids": [], "reasoning": ""}, message="无数据或空查询")

        items_summary = _build_accounts_summary(accounts)
        try:
            from ai.ollama_client import OllamaClient
            ollama = OllamaClient()
            result = ollama.semantic_match(query, items_summary)
            matched_ids = result.get("matched_ids", [])
            return ToolResult(
                success=True,
                data={"matched_count": len(matched_ids), "matched_ids": matched_ids, "reasoning": result.get("reasoning", "")},
                message=f"语义搜索账号 '{query}'，找到 {len(matched_ids)} 个结果"
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"语义搜索失败: {e}")


@ToolRegistry.register(
    name="semantic_search_urls",
    description="语义搜索网址，理解自然语言查询返回相关网址",
    permission=PermissionLevel.READONLY,
    params_schema={"query": {"type": "string", "description": "用户搜索词"}}
)
class SemanticSearchUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        query = params.get("query", "")
        urls = context.get("urls", [])
        if not urls or not query:
            return ToolResult(success=True, data={"matched_count": 0, "matched_ids": [], "reasoning": ""}, message="无数据或空查询")

        items_summary = _build_urls_summary(urls)
        try:
            from ai.ollama_client import OllamaClient
            ollama = OllamaClient()
            result = ollama.semantic_match(query, items_summary)
            matched_ids = result.get("matched_ids", [])
            return ToolResult(
                success=True,
                data={"matched_count": len(matched_ids), "matched_ids": matched_ids, "reasoning": result.get("reasoning", "")},
                message=f"语义搜索网址 '{query}'，找到 {len(matched_ids)} 个结果"
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"语义搜索失败: {e}")


@ToolRegistry.register(
    name="semantic_filter_accounts",
    description="按条件筛选账号（分类、标签等）",
    permission=PermissionLevel.READONLY,
    params_schema={
        "conditions": {
            "type": "object",
            "description": "筛选条件，如 {'category': '金融', 'tags': ['支付']}"
        }
    }
)
class SemanticFilterAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        conditions = params.get("conditions", {})
        repo = context.get("repo")
        matched_ids = []
        if repo and hasattr(repo, 'resolve_filter_conditions'):
            try:
                matched_ids = repo.resolve_filter_conditions(conditions)
            except Exception:
                pass
        if not matched_ids and conditions:
            accounts = context.get("accounts", [])
            for acc in accounts:
                match = True
                for field, value in conditions.items():
                    if field == 'tags':
                        try:
                            tag_list = acc.get_tags_list() if hasattr(acc, 'get_tags_list') else []
                            if isinstance(value, list):
                                if not any(v in tag_list for v in value):
                                    match = False
                                    break
                            elif value not in tag_list:
                                match = False
                                break
                        except Exception:
                            match = False
                            break
                    else:
                        item_val = getattr(acc, field, '') or (acc.get(field) if isinstance(acc, dict) else '')
                        if item_val != value:
                            match = False
                            break
                if match:
                    matched_ids.append(getattr(acc, 'id', acc.get('id') if isinstance(acc, dict) else None))
        matched_ids = [m for m in matched_ids if m is not None]
        return ToolResult(
            success=True,
            data={"matched_count": len(matched_ids), "matched_ids": matched_ids},
            message=f"筛选账号，条件 {conditions}，找到 {len(matched_ids)} 个结果"
        )


@ToolRegistry.register(
    name="semantic_filter_urls",
    description="按条件筛选网址（分类、标签等）",
    permission=PermissionLevel.READONLY,
    params_schema={
        "conditions": {
            "type": "object",
            "description": "筛选条件，如 {'category': '开发工具', 'tags': ['前端']}"
        }
    }
)
class SemanticFilterUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        conditions = params.get("conditions", {})
        repo = context.get("repo")
        matched_ids = []
        if repo and hasattr(repo, 'resolve_filter_conditions'):
            try:
                matched_ids = repo.resolve_filter_conditions(conditions)
            except Exception:
                pass
        if not matched_ids and conditions:
            urls = context.get("urls", [])
            for u in urls:
                match = True
                for field, value in conditions.items():
                    if field == 'tags':
                        try:
                            tag_list = u.get_tags_list() if hasattr(u, 'get_tags_list') else []
                            if isinstance(value, list):
                                if not any(v in tag_list for v in value):
                                    match = False
                                    break
                            elif value not in tag_list:
                                match = False
                                break
                        except Exception:
                            match = False
                            break
                    else:
                        item_val = getattr(u, field, '') or (u.get(field) if isinstance(u, dict) else '')
                        if item_val != value:
                            match = False
                            break
                if match:
                    matched_ids.append(getattr(u, 'id', u.get('id') if isinstance(u, dict) else None))
        matched_ids = [m for m in matched_ids if m is not None]
        return ToolResult(
            success=True,
            data={"matched_count": len(matched_ids), "matched_ids": matched_ids},
            message=f"筛选网址，条件 {conditions}，找到 {len(matched_ids)} 个结果"
        )


# ============ 批量新增 (2) ============

_BATCH_ADD_ACCOUNT_SCHEMA = {
    "items": {
        "type": "array",
        "description": "待添加的账号列表",
        "items": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "url": {"type": "string"},
                "category": {"type": "string"},
                "remark": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}}
            }
        }
    }
}

_BATCH_ADD_URL_SCHEMA = {
    "items": {
        "type": "array",
        "description": "待添加的网址列表",
        "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "url": {"type": "string"},
                "category": {"type": "string"},
                "remark": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}}
            }
        }
    }
}


@ToolRegistry.register(
    name="batch_add_accounts",
    description="批量添加账号到密码库",
    permission=PermissionLevel.PREVIEW,
    params_schema=_BATCH_ADD_ACCOUNT_SCHEMA
)
class BatchAddAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        items = params.get("items", [])
        preview_items = []
        for idx, item in enumerate(items):
            tags = item.get("tags", [])
            tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
            fields = [
                {"field_name": "应用名", "old_value": "-", "new_value": item.get("app_name", "")},
                {"field_name": "用户名", "old_value": "-", "new_value": item.get("username", "")},
                {"field_name": "密码", "old_value": "-", "new_value": item.get("password", "")},
                {"field_name": "分类", "old_value": "-", "new_value": item.get("category", "其他")},
                {"field_name": "备注", "old_value": "-", "new_value": item.get("remark", "")},
                {"field_name": "标签", "old_value": "-", "new_value": tags_str},
            ]
            preview_items.append(self._make_preview_item(
                row_id=f"new_{idx}",
                display_name=item.get("app_name", "未命名"),
                secondary_name=item.get("username", ""),
                fields=fields,
                raw_data=item
            ))
        preview = self._make_preview("add", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(items)},
            message=f"待添加 {len(items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="batch_add_urls",
    description="批量添加网址到网址库",
    permission=PermissionLevel.PREVIEW,
    params_schema=_BATCH_ADD_URL_SCHEMA
)
class BatchAddUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        items = params.get("items", [])
        preview_items = []
        for idx, item in enumerate(items):
            tags = item.get("tags", [])
            tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
            fields = [
                {"field_name": "标题", "old_value": "-", "new_value": item.get("title", "")},
                {"field_name": "URL", "old_value": "-", "new_value": item.get("url", "")},
                {"field_name": "分类", "old_value": "-", "new_value": item.get("category", "其他")},
                {"field_name": "备注", "old_value": "-", "new_value": item.get("remark", "")},
                {"field_name": "标签", "old_value": "-", "new_value": tags_str},
            ]
            preview_items.append(self._make_preview_item(
                row_id=f"new_{idx}",
                display_name=item.get("title", "未命名"),
                secondary_name=item.get("url", ""),
                fields=fields,
                raw_data=item
            ))
        preview = self._make_preview("add", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(items)},
            message=f"待添加 {len(items)} 个网址，请确认"
        )


# ============ 批量更新 (8) ============

@ToolRegistry.register(
    name="batch_update_accounts",
    description="批量更新账号指定字段",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标账号ID列表"},
        "updates": {"type": "object", "description": "字段更新映射，如 {'category': '金融'}"}
    }
)
class BatchUpdateAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        updates = params.get("updates", {})
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            fields = []
            for field, new_value in updates.items():
                old_value = self._get_field_value_safe(item, field, repo)
                fields.append({"field_name": field, "old_value": old_value, "new_value": str(new_value)})
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=fields,
                raw_data={"target_id": tid, "updates": updates}
            ))
        preview = self._make_preview("update", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待更新 {len(preview_items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="batch_update_urls",
    description="批量更新网址指定字段",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标网址ID列表"},
        "updates": {"type": "object", "description": "字段更新映射，如 {'category': '开发工具'}"}
    }
)
class BatchUpdateUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        updates = params.get("updates", {})
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            fields = []
            for field, new_value in updates.items():
                old_value = self._get_field_value_safe(item, field, repo)
                fields.append({"field_name": field, "old_value": old_value, "new_value": str(new_value)})
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=fields,
                raw_data={"target_id": tid, "updates": updates}
            ))
        preview = self._make_preview("update", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待更新 {len(preview_items)} 个网址，请确认"
        )


@ToolRegistry.register(
    name="batch_reorganize_accounts",
    description="批量重组整理账号（智能调整分类、标签等）",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "changes": {
            "type": "array",
            "description": "变更列表",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "integer"},
                    "field": {"type": "string"},
                    "new_value": {"type": "string"}
                }
            }
        }
    }
)
class BatchReorganizeAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        changes = params.get("changes", [])
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for ch in changes:
            tid = ch.get("target_id")
            field = ch.get("field", "category")
            new_value = ch.get("new_value", "")
            item = item_map.get(tid)
            if not item:
                continue
            old_value = self._get_field_value_safe(item, field, repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": field, "old_value": old_value, "new_value": str(new_value)}],
                raw_data=ch
            ))
        preview = self._make_preview("reorganize", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待重组 {len(preview_items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="batch_reorganize_urls",
    description="批量重组整理网址（智能调整分类、标签等）",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "changes": {
            "type": "array",
            "description": "变更列表",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "integer"},
                    "field": {"type": "string"},
                    "new_value": {"type": "string"}
                }
            }
        }
    }
)
class BatchReorganizeUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        changes = params.get("changes", [])
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for ch in changes:
            tid = ch.get("target_id")
            field = ch.get("field", "category")
            new_value = ch.get("new_value", "")
            item = item_map.get(tid)
            if not item:
                continue
            old_value = self._get_field_value_safe(item, field, repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": field, "old_value": old_value, "new_value": str(new_value)}],
                raw_data=ch
            ))
        preview = self._make_preview("reorganize", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待重组 {len(preview_items)} 个网址，请确认"
        )


@ToolRegistry.register(
    name="batch_add_remark_accounts",
    description="批量为账号添加备注",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标账号ID列表"},
        "remark_type": {"type": "string", "enum": ["ai_remark", "remark"], "description": "备注类型"},
        "remark_content": {"type": "string", "description": "备注内容"}
    }
)
class BatchAddRemarkAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        remark_type = params.get("remark_type", "ai_remark")
        content = params.get("remark_content", "")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            old_value = self._get_field_value_safe(item, remark_type, repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": remark_type, "old_value": old_value, "new_value": content}],
                raw_data={"target_id": tid, "remark_type": remark_type, "content": content}
            ))
        preview = self._make_preview("update", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待为 {len(preview_items)} 个账号添加备注，请确认"
        )


@ToolRegistry.register(
    name="batch_add_remark_urls",
    description="批量为网址添加备注",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标网址ID列表"},
        "remark_type": {"type": "string", "enum": ["ai_remark", "remark"], "description": "备注类型"},
        "remark_content": {"type": "string", "description": "备注内容"}
    }
)
class BatchAddRemarkUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        remark_type = params.get("remark_type", "ai_remark")
        content = params.get("remark_content", "")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            old_value = self._get_field_value_safe(item, remark_type, repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": remark_type, "old_value": old_value, "new_value": content}],
                raw_data={"target_id": tid, "remark_type": remark_type, "content": content}
            ))
        preview = self._make_preview("update", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待为 {len(preview_items)} 个网址添加备注，请确认"
        )


@ToolRegistry.register(
    name="batch_add_tags_accounts",
    description="批量为账号添加标签",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标账号ID列表"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
        "mode": {"type": "string", "enum": ["append", "replace"], "description": "添加模式：追加或替换"}
    }
)
class BatchAddTagsAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        tags = params.get("tags", [])
        mode = params.get("mode", "append")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            old_tags = self._get_field_value_safe(item, "tags", repo)
            if isinstance(old_tags, list):
                old_tags_str = ",".join(old_tags)
            else:
                old_tags_str = str(old_tags) if old_tags else ""
            if mode == "append" and old_tags_str:
                new_tags_str = old_tags_str + "," + ",".join(tags) if tags else old_tags_str
            else:
                new_tags_str = ",".join(tags)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": "tags", "old_value": old_tags_str, "new_value": new_tags_str}],
                raw_data={"target_id": tid, "tags": tags, "mode": mode}
            ))
        preview = self._make_preview("update", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待为 {len(preview_items)} 个账号{mode}标签，请确认"
        )


@ToolRegistry.register(
    name="batch_add_tags_urls",
    description="批量为网址添加标签",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标网址ID列表"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
        "mode": {"type": "string", "enum": ["append", "replace"], "description": "添加模式：追加或替换"}
    }
)
class BatchAddTagsUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        tags = params.get("tags", [])
        mode = params.get("mode", "append")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            old_tags = self._get_field_value_safe(item, "tags", repo)
            if isinstance(old_tags, list):
                old_tags_str = ",".join(old_tags)
            else:
                old_tags_str = str(old_tags) if old_tags else ""
            if mode == "append" and old_tags_str:
                new_tags_str = old_tags_str + "," + ",".join(tags) if tags else old_tags_str
            else:
                new_tags_str = ",".join(tags)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": "tags", "old_value": old_tags_str, "new_value": new_tags_str}],
                raw_data={"target_id": tid, "tags": tags, "mode": mode}
            ))
        preview = self._make_preview("update", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待为 {len(preview_items)} 个网址{mode}标签，请确认"
        )


# ============ 批量删除 (2) ============

@ToolRegistry.register(
    name="batch_delete_accounts",
    description="批量删除账号（移入回收站）",
    permission=PermissionLevel.CONFIRM,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "待删除账号ID列表"}
    }
)
class BatchDeleteAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            display = self._get_display_name_safe(item, repo)
            secondary = self._get_secondary_info_safe(item, repo)
            category = self._get_field_value_safe(item, "category", repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=display,
                secondary_name=secondary,
                fields=[
                    {"field_name": "应用名", "old_value": display, "new_value": "移入回收站"},
                    {"field_name": "分类", "old_value": category, "new_value": "移入回收站"},
                ],
                raw_data={"target_id": tid, "item_type": "account"}
            ))
        preview = self._make_preview("delete", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待删除 {len(preview_items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="batch_delete_urls",
    description="批量删除网址（移入回收站）",
    permission=PermissionLevel.CONFIRM,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "待删除网址ID列表"}
    }
)
class BatchDeleteUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            display = self._get_display_name_safe(item, repo)
            secondary = self._get_secondary_info_safe(item, repo)
            category = self._get_field_value_safe(item, "category", repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=display,
                secondary_name=secondary,
                fields=[
                    {"field_name": "标题", "old_value": display, "new_value": "移入回收站"},
                    {"field_name": "分类", "old_value": category, "new_value": "移入回收站"},
                ],
                raw_data={"target_id": tid, "item_type": "url"}
            ))
        preview = self._make_preview("delete", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待删除 {len(preview_items)} 个网址，请确认"
        )


# ============ 智能整理 (4) ============

@ToolRegistry.register(
    name="smart_classify_accounts",
    description="智能分类账号",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标账号ID列表"}
    }
)
class SmartClassifyAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        accounts = context.get("accounts", [])
        item_map = {a.id: a for a in accounts if hasattr(a, 'id')}
        target_items = [item_map.get(tid) for tid in target_ids if tid in item_map]
        if not target_items:
            target_items = accounts

        repo = context.get("repo")
        existing_categories = []
        if repo and hasattr(repo, 'get_categories'):
            try:
                existing_categories = repo.get_categories()
            except Exception:
                pass

        from services.ai_classification_service import AIClassificationService
        service = AIClassificationService()
        try:
            proposals = service.pre_analyze_accounts(target_items, existing_categories)
            categories = [p.name for p in proposals if p.name]
            if not categories:
                categories = existing_categories or ['其他']
            changes = service.execute_classification(target_items, categories, item_type='account')
        except Exception as e:
            # 降级：启发式分类
            categories = existing_categories or ['其他']
            changes = []
            for item in target_items:
                change = service._heuristic_classify_item(item, categories, 'account')
                changes.append(change)

        preview_items = []
        for ch in changes:
            preview_items.append(self._make_preview_item(
                row_id=str(ch.item_id),
                display_name=ch.item_name,
                secondary_name="",
                fields=[{"field_name": "category", "old_value": ch.old_category, "new_value": ch.new_category}],
                raw_data={"target_id": ch.item_id, "field": "category", "new_value": ch.new_category, "confidence": ch.confidence}
            ))
        preview = self._make_preview("classify", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(changes), "categories": categories},
            message=f"待智能分类 {len(changes)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="smart_classify_urls",
    description="智能分类网址",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标网址ID列表"}
    }
)
class SmartClassifyUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        urls = context.get("urls", [])
        item_map = {u.id: u for u in urls if hasattr(u, 'id')}
        target_items = [item_map.get(tid) for tid in target_ids if tid in item_map]
        if not target_items:
            target_items = urls

        repo = context.get("repo")
        existing_categories = []
        if repo and hasattr(repo, 'get_categories'):
            try:
                existing_categories = repo.get_categories()
            except Exception:
                pass

        from services.ai_classification_service import AIClassificationService
        service = AIClassificationService()
        try:
            proposals = service.pre_analyze_urls(target_items, existing_categories)
            categories = [p.name for p in proposals if p.name]
            if not categories:
                categories = existing_categories or ['其他']
            changes = service.execute_classification(target_items, categories, item_type='url')
        except Exception as e:
            categories = existing_categories or ['其他']
            changes = []
            for item in target_items:
                change = service._heuristic_classify_item(item, categories, 'url')
                changes.append(change)

        preview_items = []
        for ch in changes:
            preview_items.append(self._make_preview_item(
                row_id=str(ch.item_id),
                display_name=ch.item_name,
                secondary_name="",
                fields=[{"field_name": "category", "old_value": ch.old_category, "new_value": ch.new_category}],
                raw_data={"target_id": ch.item_id, "field": "category", "new_value": ch.new_category, "confidence": ch.confidence}
            ))
        preview = self._make_preview("classify", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(changes), "categories": categories},
            message=f"待智能分类 {len(changes)} 个网址，请确认"
        )


@ToolRegistry.register(
    name="smart_merge_duplicate_accounts",
    description="智能合并重复账号",
    permission=PermissionLevel.CONFIRM,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标账号ID列表，为空则自动检测"},
        "auto_detect": {"type": "boolean", "description": "是否自动检测重复项"}
    }
)
class SmartMergeDuplicateAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        auto_detect = params.get("auto_detect", False)
        accounts = context.get("accounts", [])
        item_map = {a.id: a for a in accounts if hasattr(a, 'id')}
        repo = context.get("repo")

        if auto_detect or not target_ids:
            seen = {}
            duplicates = []
            for acc in accounts:
                key = f"{getattr(acc, 'app_name', '')}|{getattr(acc, 'username', '')}"
                if key in seen:
                    duplicates.append(getattr(acc, 'id', None))
                else:
                    seen[key] = getattr(acc, 'id', None)
            target_ids = [tid for tid in duplicates if tid is not None]

        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": "合并", "old_value": "重复项", "new_value": "已合并"}],
                raw_data={"target_id": tid}
            ))
        preview = self._make_preview("merge", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items), "auto_detect": auto_detect},
            message=f"待合并 {len(preview_items)} 个重复账号，请确认"
        )


@ToolRegistry.register(
    name="smart_merge_duplicate_urls",
    description="智能合并重复网址",
    permission=PermissionLevel.CONFIRM,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标网址ID列表，为空则自动检测"},
        "auto_detect": {"type": "boolean", "description": "是否自动检测重复项"}
    }
)
class SmartMergeDuplicateUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        target_ids = params.get("target_ids", [])
        auto_detect = params.get("auto_detect", False)
        urls = context.get("urls", [])
        item_map = {u.id: u for u in urls if hasattr(u, 'id')}
        repo = context.get("repo")

        if auto_detect or not target_ids:
            seen = {}
            duplicates = []
            for u in urls:
                key = getattr(u, 'url', '')
                if key in seen:
                    duplicates.append(getattr(u, 'id', None))
                else:
                    seen[key] = getattr(u, 'id', None)
            target_ids = [tid for tid in duplicates if tid is not None]

        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": "合并", "old_value": "重复项", "new_value": "已合并"}],
                raw_data={"target_id": tid}
            ))
        preview = self._make_preview("merge", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items), "auto_detect": auto_detect},
            message=f"待合并 {len(preview_items)} 个重复网址，请确认"
        )


# ============ 查询统计 (5) ============

@ToolRegistry.register(
    name="get_account_detail",
    description="获取账号详细信息",
    permission=PermissionLevel.READONLY,
    params_schema={"account_id": {"type": "integer", "description": "账号ID"}}
)
class GetAccountDetailTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        account_id = params.get("account_id")
        identifier = params.get("identifier")
        match_field = params.get("match_field", "app_name")
        repo = context.get("repo")
        accounts = context.get("accounts", [])

        if account_id is not None:
            if repo and hasattr(repo, 'get_by_id'):
                try:
                    account = repo.get_by_id(account_id)
                    if account:
                        return ToolResult(
                            success=True,
                            data=account.to_dict() if hasattr(account, 'to_dict') else account,
                            message=f"获取账号 #{account_id} 详情"
                        )
                except Exception:
                    pass
            for acc in accounts:
                if getattr(acc, 'id', None) == account_id:
                    return ToolResult(
                        success=True,
                        data=acc.to_dict() if hasattr(acc, 'to_dict') else acc,
                        message=f"获取账号 #{account_id} 详情"
                    )

        if identifier:
            for acc in accounts:
                val = getattr(acc, match_field, '') or (acc.get(match_field) if isinstance(acc, dict) else '')
                if val == identifier:
                    return ToolResult(
                        success=True,
                        data=acc.to_dict() if hasattr(acc, 'to_dict') else acc,
                        message=f"获取账号详情: {identifier}"
                    )

        return ToolResult(success=True, data=None, message="未找到账号")


@ToolRegistry.register(
    name="get_url_detail",
    description="获取网址详细信息",
    permission=PermissionLevel.READONLY,
    params_schema={"url_id": {"type": "integer", "description": "网址ID"}}
)
class GetUrlDetailTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        url_id = params.get("url_id")
        identifier = params.get("identifier")
        match_field = params.get("match_field", "title")
        repo = context.get("repo")
        urls = context.get("urls", [])

        if url_id is not None:
            if repo and hasattr(repo, 'get_by_id'):
                try:
                    item = repo.get_by_id(url_id)
                    if item:
                        return ToolResult(
                            success=True,
                            data=item.to_dict() if hasattr(item, 'to_dict') else item,
                            message=f"获取网址 #{url_id} 详情"
                        )
                except Exception:
                    pass
            for u in urls:
                if getattr(u, 'id', None) == url_id:
                    return ToolResult(
                        success=True,
                        data=u.to_dict() if hasattr(u, 'to_dict') else u,
                        message=f"获取网址 #{url_id} 详情"
                    )

        if identifier:
            for u in urls:
                val = getattr(u, match_field, '') or (u.get(match_field) if isinstance(u, dict) else '')
                if val == identifier:
                    return ToolResult(
                        success=True,
                        data=u.to_dict() if hasattr(u, 'to_dict') else u,
                        message=f"获取网址详情: {identifier}"
                    )

        return ToolResult(success=True, data=None, message="未找到网址")


@ToolRegistry.register(
    name="list_all_categories",
    description="列出所有分类",
    permission=PermissionLevel.READONLY,
    params_schema={"vault_type": {"type": "string", "enum": ["account", "url"], "description": "库类型"}}
)
class ListAllCategoriesTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        vault_type = params.get("vault_type", context.get("vault_type", "account"))
        repo = context.get("repo")
        categories = []
        if repo and hasattr(repo, 'get_categories'):
            try:
                categories = repo.get_categories()
            except Exception:
                pass
        return ToolResult(
            success=True,
            data={"vault_type": vault_type, "categories": categories},
            message=f"{vault_type} 库分类列表"
        )


@ToolRegistry.register(
    name="get_statistics",
    description="获取统计信息",
    permission=PermissionLevel.READONLY,
    params_schema={"vault_type": {"type": "string", "enum": ["account", "url"], "description": "库类型"}}
)
class GetStatisticsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        vault_type = params.get("vault_type", context.get("vault_type", "account"))
        items = context.get("accounts" if vault_type == "account" else "urls", [])
        total = len(items)
        categories = {}
        tags_count = 0
        for item in items:
            cat = getattr(item, 'category', '未分类') or (item.get('category') if isinstance(item, dict) else '未分类')
            categories[cat] = categories.get(cat, 0) + 1
            # 统计有标签的条目
            item_tags = self._get_field_value_safe(item, 'tags')
            if item_tags:
                try:
                    tag_list = json.loads(item_tags) if isinstance(item_tags, str) else item_tags
                    if isinstance(tag_list, list) and len(tag_list) > 0:
                        tags_count += 1
                except Exception:
                    pass
        return ToolResult(
            success=True,
            data={
                "total": total,
                "vault_type": vault_type,
                "category_distribution": categories,
                "tagged_items": tags_count
            },
            message=f"{vault_type} 库统计：共 {total} 条"
        )


@ToolRegistry.register(
    name="get_recent_changes",
    description="获取最近变更记录",
    permission=PermissionLevel.READONLY,
    params_schema={
        "vault_type": {"type": "string", "enum": ["account", "url"], "description": "库类型"},
        "limit": {"type": "integer", "description": "返回条数", "default": 10}
    }
)
class GetRecentChangesTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        vault_type = params.get("vault_type", context.get("vault_type", "account"))
        limit = params.get("limit", 10)
        items = context.get("accounts" if vault_type == "account" else "urls", [])
        changes = []
        for item in items:
            ts = getattr(item, 'updated_at', None) or getattr(item, 'created_at', None)
            changes.append({
                "id": getattr(item, 'id', None),
                "name": getattr(item, 'app_name', '') or getattr(item, 'title', ''),
                "timestamp": ts.isoformat() if hasattr(ts, 'isoformat') else str(ts) if ts else None,
                "type": vault_type
            })
        changes.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        changes = changes[:limit]
        return ToolResult(
            success=True,
            data={"vault_type": vault_type, "limit": limit, "changes": changes},
            message=f"获取 {vault_type} 库最近 {len(changes)} 条变更"
        )


# ============ 辅助生成 (4) ============

@ToolRegistry.register(
    name="generate_account_remark",
    description="生成账号AI备注",
    permission=PermissionLevel.READONLY,
    params_schema={
        "app_name": {"type": "string", "description": "应用名称"},
        "category": {"type": "string", "description": "分类"},
        "url": {"type": "string", "description": "网址"}
    }
)
class GenerateAccountRemarkTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        app_name = params.get("app_name", "")
        category = params.get("category", "")
        url = params.get("url", "")
        try:
            from ai.ollama_client import OllamaClient
            ollama = OllamaClient()
            prompt = f"请为密码管理软件的账号生成一句话备注。应用名：{app_name}，分类：{category}，网址：{url}。只返回一句话备注，不要其他解释。"
            remark = ollama.generate(prompt, temperature=0.3, num_predict=100)
            remark = remark.strip().strip('"').strip("'")
        except Exception as e:
            remark = f"{app_name}（{category}）账号"
        return ToolResult(
            success=True,
            data={"remark": remark},
            message=f"为 {app_name} 生成备注"
        )


@ToolRegistry.register(
    name="generate_url_remark",
    description="生成网址AI备注",
    permission=PermissionLevel.READONLY,
    params_schema={
        "title": {"type": "string", "description": "标题"},
        "url": {"type": "string", "description": "网址"},
        "category": {"type": "string", "description": "分类"}
    }
)
class GenerateUrlRemarkTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        title = params.get("title", "")
        category = params.get("category", "")
        url = params.get("url", "")
        try:
            from ai.ollama_client import OllamaClient
            ollama = OllamaClient()
            prompt = f"请为网址生成一句话备注。标题：{title}，分类：{category}，网址：{url}。只返回一句话备注，不要其他解释。"
            remark = ollama.generate(prompt, temperature=0.3, num_predict=100)
            remark = remark.strip().strip('"').strip("'")
        except Exception as e:
            remark = f"{title}（{category}）网址"
        return ToolResult(
            success=True,
            data={"remark": remark},
            message=f"为 {title} 生成备注"
        )


@ToolRegistry.register(
    name="generate_password",
    description="生成随机强密码",
    permission=PermissionLevel.CONFIRM,
    params_schema={
        "length": {"type": "integer", "description": "密码长度", "default": 16},
        "include_special": {"type": "boolean", "description": "是否包含特殊字符", "default": True}
    }
)
class GeneratePasswordTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        import secrets
        import string
        length = params.get("length", 16)
        include_special = params.get("include_special", True)
        chars = string.ascii_letters + string.digits
        if include_special:
            chars += string.punctuation
        password = ''.join(secrets.choice(chars) for _ in range(length))
        return ToolResult(
            success=True,
            data={"password": password, "length": length},
            message=f"已生成 {length} 位随机密码"
        )


@ToolRegistry.register(
    name="check_password_strength",
    description="检测密码强度",
    permission=PermissionLevel.READONLY,
    params_schema={"password": {"type": "string", "description": "待检测密码"}}
)
class CheckPasswordStrengthTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        password = params.get("password", "")
        score = 0
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if any(c.isupper() for c in password):
            score += 1
        if any(c.islower() for c in password):
            score += 1
        if any(c.isdigit() for c in password):
            score += 1
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            score += 1

        levels = ["弱", "弱", "中", "中", "强", "强", "极强"]
        strength = levels[min(score, 6)]
        return ToolResult(
            success=True,
            data={"password": password, "strength": strength, "score": score},
            message=f"密码强度：{strength}（得分 {score}/6）"
        )
