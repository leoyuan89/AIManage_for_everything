"""
AI Tool Calling 基础设施
为 ReAct Agent 模式提供工具定义、注册和执行能力
"""
import logging
import json
import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable, Type

logger = logging.getLogger(__name__)


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
            context: 执行上下文，包含 accounts, urls, vault_type, db, url_db, repo
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
        lines.append(f"{acc_id} | {app_name} | {category or '未分类'} | {tags_str} | {remark or ''}")
    return "\n".join(lines)


def _build_urls_summary(urls: List[Any]) -> str:
    """构建网址摘要文本，供语义搜索使用（不含URL，保留标题/分类/标签/备注/AI备注）"""
    lines = []
    for u in urls:
        u_id = getattr(u, 'id', u.get('id') if isinstance(u, dict) else 0)
        title = getattr(u, 'title', u.get('title', '') if isinstance(u, dict) else '')
        category = getattr(u, 'category', u.get('category', '') if isinstance(u, dict) else '')
        remark = getattr(u, 'remark', u.get('remark', '') if isinstance(u, dict) else '')
        ai_remark = getattr(u, 'ai_remark', u.get('ai_remark', '') if isinstance(u, dict) else '')
        tags_str = ""
        tags = getattr(u, 'tags', u.get('tags', '') if isinstance(u, dict) else '')
        if tags:
            try:
                tag_list = json.loads(tags) if isinstance(tags, str) else tags
                tags_str = ",".join(tag_list) if isinstance(tag_list, list) else str(tag_list)
            except Exception:
                tags_str = str(tags)
        parts = [f"{u_id}", title, category or '未分类']
        if tags_str:
            parts.append(f"标签:{tags_str}")
        if remark:
            parts.append(f"备注:{remark}")
        if ai_remark:
            parts.append(f"AI备注:{ai_remark}")
        lines.append(" | ".join(parts))
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
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(timeout=30)
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
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(timeout=30)
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
            "description": "筛选条件，如 {'category': '金融与支付', 'tags': ['支付']}"
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
            "description": "筛选条件，如 {'category': '工作>开发工具', 'tags': ['前端']}"
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
        "description": "待添加的账号列表。你需要自行从用户输入中提取各字段，格式不固定时按语义推断。",
        "items": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "应用名称/网站名称。通常是用户输入的第一个词或最显眼的名称，如'专利'、'B站'、'学工系统'"},
                "username": {"type": "string", "description": "用户名/账号。看起来像手机号、邮箱、学号、QQ号等的字符串。如'13959106910'、'abc@qq.com'、'2023001'"},
                "password": {"type": "string", "description": "密码。紧跟在'密码'、'pwd'等词后面的内容，或看起来像密码的字符串"},
                "url": {"type": "string", "description": "网址。以http://或https://开头的链接。如果没有协议头但有域名，补全为https://。如'https://pss-system.cponline.cnipa.gov.cn'"},
                "category": {"type": "string", "description": "分类。根据应用名/网址推测最合适的分类，如学术网站→'学术与研究'，银行→'金融与支付'，学校系统→'青岛大学'"},
                "remark": {"type": "string", "description": "备注。用户额外说明的信息，没有则留空字符串"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表。没有则留空数组[]"}
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
                "title": {"type": "string", "description": "网址标题/名称。如'GitHub'、'百度'"},
                "url": {"type": "string", "description": "网址链接。以http://或https://开头"},
                "category": {"type": "string", "description": "分类。根据网址内容推测最合适的分类"},
                "remark": {"type": "string", "description": "备注。没有则留空"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表。没有则留空数组[]"}
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
        "updates": {"type": "object", "description": "字段更新映射，如 {'category': '工作>开发工具'}"}
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
        "updates": {"type": "object", "description": "字段更新映射，如 {'category': '工作>开发工具'}"}
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
    description="批量为账号添加备注。支持为每个账号指定不同的备注内容，changes 数组中每个元素包含 target_id 和 content",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "changes": {
            "type": "array",
            "description": "每个账号的备注内容列表，每个元素包含 target_id 和专属的 content",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "integer", "description": "目标账号ID"},
                    "content": {"type": "string", "description": "该账号的专属备注内容"}
                }
            }
        },
        "remark_type": {"type": "string", "enum": ["ai_remark", "remark"], "description": "备注类型，默认 ai_remark"}
    }
)
class BatchAddRemarkAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        changes = params.get("changes", [])
        remark_type = params.get("remark_type", "ai_remark")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for ch in changes:
            tid = ch.get("target_id")
            content = ch.get("content", "")
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
    description="批量为网址添加备注。支持为每个网址指定不同的备注内容，changes 数组中每个元素包含 target_id 和 content",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "changes": {
            "type": "array",
            "description": "每个网址的备注内容列表，每个元素包含 target_id 和专属的 content",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "integer", "description": "目标网址ID"},
                    "content": {"type": "string", "description": "该网址的专属备注内容"}
                }
            }
        },
        "remark_type": {"type": "string", "enum": ["ai_remark", "remark"], "description": "备注类型，默认 ai_remark"}
    }
)
class BatchAddRemarkUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        changes = params.get("changes", [])
        remark_type = params.get("remark_type", "ai_remark")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for ch in changes:
            tid = ch.get("target_id")
            content = ch.get("content", "")
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


def sanitize_ai_category(ai_output: str) -> str:
    """
    校验并修正 AI 输出的分类路径。

    规则：
    1. 去除首尾空白
    2. 替换非法字符 `/`、`·` 为 `-`
    3. 截断三级及以上为二级
    4. 规范 `> ` 和 ` >` 等空格问题（通过 parse + format 自然实现）
    """
    from core.category_utils import format_category_path, parse_category_path

    # 1. 去除首尾空白
    cleaned = ai_output.strip()

    # 2. 替换非法字符
    if any(c in cleaned for c in ['/', '·']):
        cleaned = cleaned.replace('/', '-').replace('·', '-')

    # 3. 使用 parse_category_path 解析，三级及以上截断为二级
    try:
        parent, child = parse_category_path(cleaned)
    except ValueError:
        first_sep = cleaned.find('>')
        if first_sep != -1:
            second_sep = cleaned.find('>', first_sep + 1)
            if second_sep != -1:
                cleaned = cleaned[:second_sep]
        parent, child = parse_category_path(cleaned)

    # 4. 通过 format_category_path 规范化空格
    return format_category_path(parent, child)


# ============ 智能整理 (4) ============

@ToolRegistry.register(
    name="smart_classify_accounts",
    description="智能分类账号（自动获取全部账号，无需传入ID列表）",
    permission=PermissionLevel.PREVIEW,
    params_schema={}
)
class SmartClassifyAccountsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        accounts = context.get("accounts", [])
        if not accounts:
            return ToolResult(success=False, message="没有可分类的账号")

        # 获取用户原始查询作为分类指令
        user_query = context.get('query', '请对以下账号进行分类')

        # 获取现有分类列表
        existing_categories = []
        repo = context.get("repo")
        if repo and hasattr(repo, 'get_categories'):
            try:
                existing_categories = repo.get_categories()
            except Exception:
                pass

        # 检测用户是否在查询中指定了某个具体分类
        # 从现有分类中查找在 user_query 中出现过的分类名（支持完整路径或父节点匹配）
        target_category = None
        matched_cats = []
        for cat in existing_categories:
            if not cat or cat == '全部':
                continue
            if cat in user_query:
                matched_cats.append(cat)
            elif '>' in cat:
                parent = cat.split('>')[0].strip()
                if parent in user_query:
                    matched_cats.append(parent)
        if matched_cats:
            # 优先匹配最长的（更精确）
            target_category = max(matched_cats, key=len)

        # 如果用户指定了具体分类，只筛选该分类下的账号
        if target_category:
            from core.category_utils import get_prefix_matcher
            matcher = get_prefix_matcher(target_category)
            filtered_accounts = [acc for acc in accounts if matcher(acc.category or '')]
            if filtered_accounts:
                accounts = filtered_accounts
                scope_hint = f"（仅处理「{target_category}」分类下的 {len(accounts)} 个账号）"
            else:
                scope_hint = ""
        else:
            scope_hint = ""

        # 构建账号信息（key=value 形式，不暴露内部格式）
        lines = []
        for acc in accounts:
            remark = (acc.remark or '')[:20]
            ai_remark = (getattr(acc, 'ai_remark', '') or '')[:20]
            parts = [f"ID={acc.id}", f"应用名={(acc.app_name or '')[:30]}", f"分类={(acc.category or '未分类')[:30]}"]
            if remark:
                parts.append(f"备注={remark}")
            if ai_remark:
                parts.append(f"AI备注={ai_remark}")
            lines.append(", ".join(parts))
        items_str = '\n'.join(lines)

        # 格式化现有分类列表，同时提取一级分类名
        top_level_cats = set()
        if existing_categories:
            tree_lines = []
            for cat in sorted(existing_categories):
                if cat and cat != '全部':
                    tree_lines.append(f"  - {cat}")
                    if '>' in cat:
                        top_level_cats.add(cat.split('>')[0].strip())
                    else:
                        top_level_cats.add(cat.strip())
            category_tree_text = "\n".join(tree_lines) if tree_lines else "  （暂无分类）"
            top_level_text = "\n".join(f"  - {c}" for c in sorted(top_level_cats)) if top_level_cats else "  （暂无）"
        else:
            category_tree_text = "  （暂无分类）"
            top_level_text = "  （暂无）"

        # 检测用户是否明确要求细分二级子类
        force_subclass_keywords = ['细分', '二级', '子类', '子分类']
        force_subclass = any(kw in user_query for kw in force_subclass_keywords)

        if force_subclass:
            # 推断主分类名（从 target_category 或 top_level_cats）
            main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
            rules_text = f"""【输出规则】（必须严格遵守）：
1. 输出格式必须是严格JSON：{{"类别名": [ID列表], ...}}
2. 每个类别名必须是二级分类路径，格式为 `主类>子类`，如 `{main_category}>考试`、`{main_category}>课程平台`
3. 这些账号都属于 `{main_category}` 分类体系（有些可能已有二级子类如 `{main_category}>xxx`，有些可能仍是一级 `{main_category}`）。你的任务是重新细分/调整二级子类，但主类必须是 `{main_category}`，绝对不允许更改
4. 子类名绝对不能和以下一级分类名重复：
{top_level_text}
5. 你必须根据每个账号的应用名、备注等信息，尽可能细分到合理的二级子类。不允许因为"看起来比较杂"就把所有条目归到同一个分类下偷懒
6. 优先匹配【当前分类体系】中已有的路径
7. 如需新建子类，子类名应简洁明确（2-4个字），如 `考试`、`课程平台`、`学术工具`、`语言学习`
8. 分类名中禁止包含 `/`、`·` 两个符号
9. 层级分隔符 `>` 最多出现一次，禁止输出三级及以上路径（如 `A>B>C` 是非法的）
10. 不要在任何值中包含英文双引号"，如需引用请用中文引号「」
11. 【绝对禁止】更改一级分类。所有输出分类的主类必须是 `{main_category}`，不允许改成其他主类如 `一般与其他>xxx`
12. 【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。ID之间只用逗号分隔，如 `[101,102,103,104]`
13. 【覆盖检查】输出JSON中所有类别的ID总数必须等于输入条目总数，不允许遗漏任何一个ID。如果某个ID确实难以归类，也必须分配到一个最接近的类别中，绝不能跳过。

【输出示例】
{{"{main_category}>考试":[101,102],"{main_category}>课程平台":[103,104,105],"{main_category}>学术工具":[106]}}"""
        else:
            rules_text = """【输出规则】（必须严格遵守）：
1. 输出格式必须是严格JSON：{"类别名": [ID列表], ...}
2. 类别名使用分类路径格式：`主类>子类`（最多二级），如 `工作>开发工具`、`娱乐>游戏`
3. 默认情况下只输出一级分类。如果某个条目确实无法归入更细的子类，只输出主类，如 `教育与学习`。
4. 只有在用户明确要求细分或条目明显需要细分时，才输出二级分类路径，如 `教育与学习>考试`。
5. 优先匹配【当前分类体系】中已有的路径
6. 如需新建子类，确保主类已存在于体系中；如需新建主类，直接输出主类名
7. 分类名中禁止包含 `/`、`·` 两个符号
8. 并列概念用"与"连接，如 `金融与支付`、`工具与系统`
9. 层级分隔符 `>` 最多出现一次，禁止输出三级及以上路径（如 `A>B>C` 是非法的）
10. 不要在任何值中包含英文双引号"，如需引用请用中文引号「」
11. 【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。ID之间只用逗号分隔，如 `[101,102,103,104]`
12. 【覆盖检查】输出JSON中所有类别的ID总数必须等于输入条目总数，不允许遗漏任何一个ID。如果某个ID确实难以归类，也必须分配到一个最接近的类别中，绝不能跳过。

【输出示例】
{"工作>开发工具":[101,102],"娱乐>游戏":[103,104,105]}"""

        prompt = f"""你正在执行用户的分类指令。请仔细阅读所有账号信息，严格按照用户指令进行分类。

【重要】输入共 {len(accounts)} 个账号，你必须为每一个账号分配分类。输出JSON必须包含全部 {len(accounts)} 个ID，不允许遗漏任何一个。遗漏会导致数据丢失！

用户指令：{user_query} {scope_hint}

【当前分类体系】
{category_tree_text}

账号信息（共 {len(accounts)} 条）：
{items_str}

{rules_text}

输出："""

        # 调用大模型一次完成全部分类
        import json
        from ai.ollama_client import OllamaClient
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        state = ai_manager.get_state()
        ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=30)
        raw = ollama.generate(prompt, temperature=0.3)

        # 解析JSON
        extracted = OllamaClient._extract_json_object_robust(raw) or raw
        fixed = OllamaClient._fix_json(extracted)
        try:
            data = json.loads(fixed)
        except Exception as e:
            logger.warning("JSON parse failed: %s, raw preview: %r", e, raw[:300])
            return ToolResult(success=False, message=f"分类结果解析失败: {e}")

        # 统一ID类型为int，并去重
        def _normalize_data(raw_data):
            """将分类结果中的ID统一转为int并去重，同时处理模型返回的字符串数组"""
            result = {}
            for cat_name, id_list in raw_data.items():
                # 处理模型返回字符串形式如 "[1,2,3]" 的情况
                if isinstance(id_list, str):
                    s = id_list.strip()
                    if s.startswith('[') and s.endswith(']'):
                        try:
                            id_list = json.loads(s)
                        except Exception:
                            continue
                    else:
                        continue
                if not isinstance(id_list, list):
                    continue
                cleaned_name = sanitize_ai_category(cat_name)
                int_ids = []
                seen = set()
                for tid in id_list:
                    try:
                        int_tid = int(tid)
                        if int_tid not in seen:
                            seen.add(int_tid)
                            int_ids.append(int_tid)
                    except (ValueError, TypeError):
                        continue
                if int_ids:
                    result.setdefault(cleaned_name, []).extend(int_ids)
            return result

        data = _normalize_data(data)

        # 兜底：force_subclass 模式下，强制修正一级分类和错误的主类
        if force_subclass:
            main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
            corrected_data = {}
            for cat_name, id_list in data.items():
                cleaned = sanitize_ai_category(cat_name)
                if '>' not in cleaned:
                    logger.debug("AUTO-CORRECT: '%s' -> '%s>其他' (force_subclass)", cleaned, main_category)
                    cleaned = f"{main_category}>其他"
                else:
                    actual_main = cleaned.split('>')[0].strip()
                    if actual_main != main_category:
                        sub = cleaned.split('>', 1)[1].strip()
                        logger.debug("AUTO-CORRECT: main '%s' -> '%s', sub '%s' (force_subclass)", actual_main, main_category, sub)
                        cleaned = f"{main_category}>{sub}"
                corrected_data.setdefault(cleaned, []).extend(id_list)
            data = corrected_data

        # 自纠正循环：处理遗漏的ID
        input_ids = {getattr(a, 'id', None) for a in accounts}
        input_ids.discard(None)
        for retry in range(2):
            classified_ids = set()
            for id_list in data.values():
                if isinstance(id_list, list):
                    classified_ids.update(id_list)
            missing_ids = input_ids - classified_ids
            if not missing_ids:
                break

            missing_accounts = [a for a in accounts if getattr(a, 'id', None) in missing_ids]
            missing_lines = []
            for acc in missing_accounts:
                remark = (getattr(acc, 'remark', '') or '')[:20]
                ai_remark = (getattr(acc, 'ai_remark', '') or '')[:20]
                parts = [f"ID={getattr(acc, 'id', 0)}", f"应用名={(getattr(acc, 'app_name', '') or '')[:30]}", f"分类={(getattr(acc, 'category', '') or '未分类')[:30]}"]
                if remark:
                    parts.append(f"备注={remark}")
                if ai_remark:
                    parts.append(f"AI备注={ai_remark}")
                missing_lines.append(", ".join(parts))
            missing_items_str = '\n'.join(missing_lines)

            established_cats = list(dict.fromkeys(sanitize_ai_category(c) for c in data.keys()))
            retry_prompt = f"""你正在执行分类补充任务。以下是第一轮分类时遗漏的账号，请为它们分配最合适的分类。

【重要】这些是第一轮遗漏的 {len(missing_accounts)} 个账号，必须全部分类，不允许再遗漏！

已建立的分类体系（请优先从中选择）：
{', '.join(established_cats)}

账号信息（共 {len(missing_accounts)} 条）：
{missing_items_str}

输出格式必须是严格JSON：{{"类别名": [ID列表], ...}}
【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。
【覆盖检查】输出必须包含全部 {len(missing_accounts)} 个ID。

输出："""

            raw_retry = ollama.generate(retry_prompt, temperature=0.3)
            extracted_retry = OllamaClient._extract_json_object_robust(raw_retry) or raw_retry
            fixed_retry = OllamaClient._fix_json(extracted_retry)
            try:
                retry_data = json.loads(fixed_retry)
                retry_data = _normalize_data(retry_data)
                # force_subclass 模式下对retry结果同样强制修正主类
                if force_subclass:
                    main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
                    corrected_retry = {}
                    for cat_name, id_list in retry_data.items():
                        cleaned = sanitize_ai_category(cat_name)
                        if '>' not in cleaned:
                            logger.debug("AUTO-CORRECT retry: '%s' -> '%s>其他' (force_subclass)", cleaned, main_category)
                            cleaned = f"{main_category}>其他"
                        else:
                            actual_main = cleaned.split('>')[0].strip()
                            if actual_main != main_category:
                                sub = cleaned.split('>', 1)[1].strip()
                                logger.debug("AUTO-CORRECT retry: main '%s' -> '%s', sub '%s' (force_subclass)", actual_main, main_category, sub)
                                cleaned = f"{main_category}>{sub}"
                        corrected_retry.setdefault(cleaned, []).extend(id_list)
                    retry_data = corrected_retry
                for cat_name, id_list in retry_data.items():
                    data.setdefault(sanitize_ai_category(cat_name), []).extend(id_list)
                # 重新计算仍然遗漏的数量
                classified_ids = set()
                for id_list in data.values():
                    if isinstance(id_list, list):
                        classified_ids.update(id_list)
                still_missing = input_ids - classified_ids
                logger.info("Retry %d: %d missing -> %d still missing", retry+1, len(missing_ids), len(still_missing))
            except Exception as e:
                logger.warning("Retry %d failed: %s", retry+1, e)
                break

        # 生成分类变更预览
        item_map = {a.id: a for a in accounts if hasattr(a, 'id')}
        preview_items = []
        
        # 第一轮：收集每个ID被分配到的所有分类
        id_to_cats = {}
        cat_order = []
        for cat_name, id_list in data.items():
            if not isinstance(id_list, list):
                continue
            cat_name = sanitize_ai_category(cat_name)
            if cat_name not in cat_order:
                cat_order.append(cat_name)
            for tid in id_list:
                id_to_cats.setdefault(tid, []).append(cat_name)
        
        # 第二轮：处理重复，保留路径最长的分类（长度相同保留首次出现的）
        resolved = {}
        cat_rank = {c: i for i, c in enumerate(cat_order)}
        for tid, cats in id_to_cats.items():
            if len(cats) > 1:
                best_cat = max(cats, key=lambda c: (len(c), cat_rank.get(c, float('inf'))))
                logger.debug("RESOLVE duplicate id=%s: keep '%s', drop %s", tid, best_cat, cats)
            else:
                best_cat = cats[0]
            resolved[tid] = best_cat
        
        # 收集实际使用的分类（保持顺序）
        categories = list(dict.fromkeys(resolved.values()))
        
        # 第三轮：生成预览
        seen_ids = set()
        for tid, best_cat in resolved.items():
            item = item_map.get(tid)
            if item:
                seen_ids.add(tid)
                preview_items.append(self._make_preview_item(
                    row_id=str(tid),
                    display_name=item.app_name,
                    secondary_name="",
                    fields=[{"field_name": "category", "old_value": item.category or '未分类', "new_value": best_cat}],
                    raw_data={"target_id": tid, "field": "category", "new_value": best_cat}
                ))

        # 遗漏检测：找出模型未返回的ID
        input_ids = {a.id for a in accounts if hasattr(a, 'id')}
        missing_ids = input_ids - seen_ids
        if missing_ids:
            fallback_cat = f"{main_category}>未分类" if force_subclass else '其他'
            logger.warning("MISSING %d IDs: %s%s", len(missing_ids), sorted(missing_ids)[:20], '...' if len(missing_ids) > 20 else '')
            for tid in missing_ids:
                item = item_map.get(tid)
                if item:
                    old_cat = item.category or '未分类'
                    preview_items.append(self._make_preview_item(
                        row_id=str(tid),
                        display_name=item.app_name,
                        secondary_name="",
                        fields=[{"field_name": "category", "old_value": old_cat, "new_value": fallback_cat}],
                        raw_data={"target_id": tid, "field": "category", "new_value": fallback_cat}
                    ))
                    seen_ids.add(tid)

        preview = self._make_preview("classify", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items), "categories": categories},
            message=f"待智能分类 {len(preview_items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="smart_classify_urls",
    description="智能分类网址（自动获取全部网址，无需传入ID列表）",
    permission=PermissionLevel.PREVIEW,
    params_schema={}
)
class SmartClassifyUrlsTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        urls = context.get("urls", [])
        if not urls:
            return ToolResult(success=False, message="没有可分类的网址")

        # 获取用户原始查询作为分类指令
        user_query = context.get('query', '请对以下网址进行分类')

        # 获取现有分类列表
        existing_categories = []
        repo = context.get("repo")
        if repo and hasattr(repo, 'get_categories'):
            try:
                existing_categories = repo.get_categories()
            except Exception:
                pass

        # 检测用户是否在查询中指定了某个具体分类
        # 从现有分类中查找在 user_query 中出现过的分类名（支持完整路径或父节点匹配）
        target_category = None
        matched_cats = []
        for cat in existing_categories:
            if not cat or cat == '全部':
                continue
            if cat in user_query:
                matched_cats.append(cat)
            elif '>' in cat:
                parent = cat.split('>')[0].strip()
                if parent in user_query:
                    matched_cats.append(parent)
        if matched_cats:
            target_category = max(matched_cats, key=len)

        # 如果用户指定了具体分类，只筛选该分类下的网址
        if target_category:
            from core.category_utils import get_prefix_matcher
            matcher = get_prefix_matcher(target_category)
            filtered_urls = [u for u in urls if matcher(getattr(u, 'category', '') or '')]
            if filtered_urls:
                urls = filtered_urls
                scope_hint = f"（仅处理「{target_category}」分类下的 {len(urls)} 个网址）"
            else:
                scope_hint = ""
        else:
            scope_hint = ""

        # 构建网址信息（key=value 形式，精简：去掉网址URL，保留标题/分类/备注/AI备注）
        lines = []
        for u in urls:
            title = getattr(u, 'title', '')[:30]
            cat = getattr(u, 'category', '') or '未分类'
            remark = (getattr(u, 'remark', '') or '')[:20]
            ai_remark = (getattr(u, 'ai_remark', '') or '')[:20]
            parts = [f"ID={getattr(u, 'id', 0)}", f"标题={title}", f"分类={cat}"]
            if remark:
                parts.append(f"备注={remark}")
            if ai_remark:
                parts.append(f"AI备注={ai_remark}")
            lines.append(", ".join(parts))
        items_str = '\n'.join(lines)

        # 格式化现有分类列表，同时提取一级分类名
        top_level_cats = set()
        if existing_categories:
            tree_lines = []
            for cat in sorted(existing_categories):
                if cat and cat != '全部':
                    tree_lines.append(f"  - {cat}")
                    if '>' in cat:
                        top_level_cats.add(cat.split('>')[0].strip())
                    else:
                        top_level_cats.add(cat.strip())
            category_tree_text = "\n".join(tree_lines) if tree_lines else "  （暂无分类）"
            top_level_text = "\n".join(f"  - {c}" for c in sorted(top_level_cats)) if top_level_cats else "  （暂无）"
        else:
            category_tree_text = "  （暂无分类）"
            top_level_text = "  （暂无）"

        # 检测用户是否明确要求细分二级子类
        force_subclass_keywords = ['细分', '二级', '子类', '子分类']
        force_subclass = any(kw in user_query for kw in force_subclass_keywords)

        if force_subclass:
            main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
            rules_text = f"""【输出规则】（必须严格遵守）：
1. 输出格式必须是严格JSON：{{"类别名": [ID列表], ...}}
2. 每个类别名必须是二级分类路径，格式为 `主类>子类`，如 `{main_category}>考试`、`{main_category}>课程平台`
3. 这些网址都属于 `{main_category}` 分类体系（有些可能已有二级子类如 `{main_category}>xxx`，有些可能仍是一级 `{main_category}`）。你的任务是重新细分/调整二级子类，但主类必须是 `{main_category}`，绝对不允许更改
4. 子类名绝对不能和以下一级分类名重复：
{top_level_text}
5. 你必须根据每个网址的标题、备注等信息，尽可能细分到合理的二级子类。不允许因为"看起来比较杂"就把所有条目归到同一个分类下偷懒
6. 优先匹配【当前分类体系】中已有的路径
7. 如需新建子类，子类名应简洁明确（2-4个字），如 `考试`、`课程平台`、`学术工具`、`语言学习`
8. 分类名中禁止包含 `/`、`·` 两个符号
9. 层级分隔符 `>` 最多出现一次，禁止输出三级及以上路径（如 `A>B>C` 是非法的）
10. 不要在任何值中包含英文双引号"，如需引用请用中文引号「」
11. 【绝对禁止】更改一级分类。所有输出分类的主类必须是 `{main_category}`，不允许改成其他主类如 `一般与其他>xxx`
12. 【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。ID之间只用逗号分隔，如 `[101,102,103,104]`
13. 【覆盖检查】输出JSON中所有类别的ID总数必须等于输入条目总数，不允许遗漏任何一个ID。如果某个ID确实难以归类，也必须分配到一个最接近的类别中，绝不能跳过。

【输出示例】
{{"{main_category}>考试":[101,102],"{main_category}>课程平台":[103,104,105],"{main_category}>学术工具":[106]}}"""
        else:
            rules_text = """【输出规则】（必须严格遵守）：
1. 输出格式必须是严格JSON：{"类别名": [ID列表], ...}
2. 类别名使用分类路径格式：`主类>子类`（最多二级），如 `工作>开发工具`、`娱乐>游戏`
3. 默认情况下只输出一级分类。如果某个条目确实无法归入更细的子类，只输出主类，如 `教育与学习`。
4. 只有在用户明确要求细分或条目明显需要细分时，才输出二级分类路径，如 `教育与学习>考试`。
5. 优先匹配【当前分类体系】中已有的路径
6. 如需新建子类，确保主类已存在于体系中；如需新建主类，直接输出主类名
7. 分类名中禁止包含 `/`、`·` 两个符号
8. 并列概念用"与"连接，如 `金融与支付`、`工具与系统`
9. 层级分隔符 `>` 最多出现一次，禁止输出三级及以上路径（如 `A>B>C` 是非法的）
10. 不要在任何值中包含英文双引号"，如需引用请用中文引号「」
11. 【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。ID之间只用逗号分隔，如 `[101,102,103,104]`
12. 【覆盖检查】输出JSON中所有类别的ID总数必须等于输入条目总数，不允许遗漏任何一个ID。如果某个ID确实难以归类，也必须分配到一个最接近的类别中，绝不能跳过。

【输出示例】
{"工作>开发工具":[101,102],"娱乐>游戏":[103,104,105]}"""

        prompt = f"""你正在执行用户的分类指令。请仔细阅读所有网址信息，严格按照用户指令进行分类。

【重要】输入共 {len(urls)} 个网址，你必须为每一个网址分配分类。输出JSON必须包含全部 {len(urls)} 个ID，不允许遗漏任何一个。遗漏会导致数据丢失！

用户指令：{user_query} {scope_hint}

【当前分类体系】
{category_tree_text}

网址信息（共 {len(urls)} 条）：
{items_str}

{rules_text}

输出："""

        import json
        from ai.ollama_client import OllamaClient
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        state = ai_manager.get_state()
        ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=30)
        raw = ollama.generate(prompt, temperature=0.3)

        extracted = OllamaClient._extract_json_object_robust(raw) or raw
        fixed = OllamaClient._fix_json(extracted)
        try:
            data = json.loads(fixed)
        except Exception as e:
            logger.warning("JSON parse failed: %s, raw preview: %r", e, raw[:300])
            return ToolResult(success=False, message=f"分类结果解析失败: {e}")

        # 统一ID类型为int，并去重
        def _normalize_data(raw_data):
            """将分类结果中的ID统一转为int并去重，同时处理模型返回的字符串数组"""
            result = {}
            for cat_name, id_list in raw_data.items():
                # 处理模型返回字符串形式如 "[1,2,3]" 的情况
                if isinstance(id_list, str):
                    s = id_list.strip()
                    if s.startswith('[') and s.endswith(']'):
                        try:
                            id_list = json.loads(s)
                        except Exception:
                            continue
                    else:
                        continue
                if not isinstance(id_list, list):
                    continue
                cleaned_name = sanitize_ai_category(cat_name)
                int_ids = []
                seen = set()
                for tid in id_list:
                    try:
                        int_tid = int(tid)
                        if int_tid not in seen:
                            seen.add(int_tid)
                            int_ids.append(int_tid)
                    except (ValueError, TypeError):
                        continue
                if int_ids:
                    result.setdefault(cleaned_name, []).extend(int_ids)
            return result

        data = _normalize_data(data)

        # 兜底：force_subclass 模式下，强制修正一级分类和错误的主类
        if force_subclass:
            main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
            corrected_data = {}
            for cat_name, id_list in data.items():
                cleaned = sanitize_ai_category(cat_name)
                if '>' not in cleaned:
                    logger.debug("AUTO-CORRECT: '%s' -> '%s>其他' (force_subclass)", cleaned, main_category)
                    cleaned = f"{main_category}>其他"
                else:
                    actual_main = cleaned.split('>')[0].strip()
                    if actual_main != main_category:
                        sub = cleaned.split('>', 1)[1].strip()
                        logger.debug("AUTO-CORRECT: main '%s' -> '%s', sub '%s' (force_subclass)", actual_main, main_category, sub)
                        cleaned = f"{main_category}>{sub}"
                corrected_data.setdefault(cleaned, []).extend(id_list)
            data = corrected_data

        # 自纠正循环：处理遗漏的ID
        input_ids = {getattr(u, 'id', None) for u in urls}
        input_ids.discard(None)
        for retry in range(2):
            classified_ids = set()
            for id_list in data.values():
                if isinstance(id_list, list):
                    classified_ids.update(id_list)
            missing_ids = input_ids - classified_ids
            if not missing_ids:
                break

            missing_urls = [u for u in urls if getattr(u, 'id', None) in missing_ids]
            missing_lines = []
            for u in missing_urls:
                title = getattr(u, 'title', '')[:30]
                cat = getattr(u, 'category', '') or '未分类'
                remark = (getattr(u, 'remark', '') or '')[:20]
                ai_remark = (getattr(u, 'ai_remark', '') or '')[:20]
                parts = [f"ID={getattr(u, 'id', 0)}", f"标题={title}", f"分类={cat}"]
                if remark:
                    parts.append(f"备注={remark}")
                if ai_remark:
                    parts.append(f"AI备注={ai_remark}")
                missing_lines.append(", ".join(parts))
            missing_items_str = '\n'.join(missing_lines)

            established_cats = list(dict.fromkeys(sanitize_ai_category(c) for c in data.keys()))
            retry_prompt = f"""你正在执行分类补充任务。以下是第一轮分类时遗漏的网址，请为它们分配最合适的分类。

【重要】这些是第一轮遗漏的 {len(missing_urls)} 个网址，必须全部分类，不允许再遗漏！

已建立的分类体系（请优先从中选择）：
{', '.join(established_cats)}

网址信息（共 {len(missing_urls)} 条）：
{missing_items_str}

输出格式必须是严格JSON：{{"类别名": [ID列表], ...}}
【紧凑格式】JSON必须在一行内输出，不要换行、不要缩进、不要空格。
【覆盖检查】输出必须包含全部 {len(missing_urls)} 个ID。

输出："""

            raw_retry = ollama.generate(retry_prompt, temperature=0.3)
            extracted_retry = OllamaClient._extract_json_object_robust(raw_retry) or raw_retry
            fixed_retry = OllamaClient._fix_json(extracted_retry)
            try:
                retry_data = json.loads(fixed_retry)
                retry_data = _normalize_data(retry_data)
                # force_subclass 模式下对retry结果同样强制修正主类
                if force_subclass:
                    main_category = target_category or (sorted(top_level_cats)[0] if top_level_cats else "其他")
                    corrected_retry = {}
                    for cat_name, id_list in retry_data.items():
                        cleaned = sanitize_ai_category(cat_name)
                        if '>' not in cleaned:
                            logger.debug("AUTO-CORRECT retry: '%s' -> '%s>其他' (force_subclass)", cleaned, main_category)
                            cleaned = f"{main_category}>其他"
                        else:
                            actual_main = cleaned.split('>')[0].strip()
                            if actual_main != main_category:
                                sub = cleaned.split('>', 1)[1].strip()
                                logger.debug("AUTO-CORRECT retry: main '%s' -> '%s', sub '%s' (force_subclass)", actual_main, main_category, sub)
                                cleaned = f"{main_category}>{sub}"
                        corrected_retry.setdefault(cleaned, []).extend(id_list)
                    retry_data = corrected_retry
                for cat_name, id_list in retry_data.items():
                    data.setdefault(sanitize_ai_category(cat_name), []).extend(id_list)
                # 重新计算仍然遗漏的数量
                classified_ids = set()
                for id_list in data.values():
                    if isinstance(id_list, list):
                        classified_ids.update(id_list)
                still_missing = input_ids - classified_ids
                logger.info("SmartClassifyUrls Retry %d: %d missing -> %d still missing", retry+1, len(missing_ids), len(still_missing))
            except Exception as e:
                logger.warning("SmartClassifyUrls Retry %d failed: %s", retry+1, e)
                break

        item_map = {getattr(u, 'id', 0): u for u in urls if hasattr(u, 'id')}
        preview_items = []
        
        # 第一轮：收集每个ID被分配到的所有分类
        id_to_cats = {}
        cat_order = []
        for cat_name, id_list in data.items():
            if not isinstance(id_list, list):
                continue
            cat_name = sanitize_ai_category(cat_name)
            if cat_name not in cat_order:
                cat_order.append(cat_name)
            for tid in id_list:
                id_to_cats.setdefault(tid, []).append(cat_name)
        
        # 第二轮：处理重复，保留路径最长的分类（长度相同保留首次出现的）
        resolved = {}
        cat_rank = {c: i for i, c in enumerate(cat_order)}
        for tid, cats in id_to_cats.items():
            if len(cats) > 1:
                best_cat = max(cats, key=lambda c: (len(c), cat_rank.get(c, float('inf'))))
                logger.debug("RESOLVE duplicate id=%s: keep '%s', drop %s", tid, best_cat, cats)
            else:
                best_cat = cats[0]
            resolved[tid] = best_cat
        
        # 收集实际使用的分类（保持顺序）
        categories = list(dict.fromkeys(resolved.values()))
        
        # 第三轮：生成预览
        seen_ids = set()
        for tid, best_cat in resolved.items():
            item = item_map.get(tid)
            if item:
                seen_ids.add(tid)
                preview_items.append(self._make_preview_item(
                    row_id=str(tid),
                    display_name=getattr(item, 'title', ''),
                    secondary_name="",
                    fields=[{"field_name": "category", "old_value": getattr(item, 'category', '') or '未分类', "new_value": best_cat}],
                    raw_data={"target_id": tid, "field": "category", "new_value": best_cat}
                ))

        # 遗漏检测：找出模型未返回的ID
        input_ids = {getattr(u, 'id', 0) for u in urls if hasattr(u, 'id')}
        missing_ids = input_ids - seen_ids
        if missing_ids:
            fallback_cat = f"{main_category}>未分类" if force_subclass else '其他'
            logger.warning("SmartClassifyUrls MISSING %d IDs: %s%s", len(missing_ids), sorted(missing_ids)[:20], '...' if len(missing_ids) > 20 else '')
            for tid in missing_ids:
                item = item_map.get(tid)
                if item:
                    old_cat = getattr(item, 'category', '') or '未分类'
                    preview_items.append(self._make_preview_item(
                        row_id=str(tid),
                        display_name=getattr(item, 'title', ''),
                        secondary_name="",
                        fields=[{"field_name": "category", "old_value": old_cat, "new_value": fallback_cat}],
                        raw_data={"target_id": tid, "field": "category", "new_value": fallback_cat}
                    ))
                    seen_ids.add(tid)

        preview = self._make_preview("classify", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items), "categories": categories},
            message=f"待智能分类 {len(preview_items)} 个网址，请确认"
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
    name="get_category_tree",
    description="获取当前分类树结构，params={'item_type': 'account|url'}",
    permission=PermissionLevel.READONLY,
    params_schema={"item_type": {"type": "string", "enum": ["account", "url"], "description": "库类型"}}
)
class GetCategoryTreeTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        vault_type = params.get("item_type", context.get("vault_type", "account"))
        repo = context.get("repo")
        tree = {}
        if repo and hasattr(repo, 'get_category_tree'):
            try:
                raw_tree = repo.get_category_tree()
                tree = {k: sorted(v.get('children', set())) for k, v in raw_tree.items()}
            except Exception:
                pass
        if not tree and repo and hasattr(repo, 'get_categories'):
            try:
                from core.category_utils import build_category_tree
                cats = repo.get_categories()
                raw_tree = build_category_tree([c for c in cats if c != '全部'])
                tree = {k: sorted(v.get('children', set())) for k, v in raw_tree.items()}
            except Exception:
                pass
        return ToolResult(
            success=True,
            data={"vault_type": vault_type, "tree": tree},
            message=f"{vault_type} 库分类树"
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


def _parse_timestamp(ts):
    """把 SQLite 字符串或 datetime 统一解析为 datetime 对象"""
    from datetime import datetime
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        # 尝试多种格式
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S.%fZ'):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except ValueError:
            pass
    return None


@ToolRegistry.register(
    name="get_recent_changes",
    description="获取最近一轮变更记录（按时间聚类，同一批次5分钟内的修改视为一轮）",
    permission=PermissionLevel.READONLY,
    params_schema={
        "vault_type": {"type": "string", "enum": ["account", "url"], "description": "库类型"}
    }
)
class GetRecentChangesTool(AITool):
    def execute(self, params: Dict, context: Dict) -> ToolResult:
        vault_type = params.get("vault_type", context.get("vault_type", "account"))
        items = context.get("accounts" if vault_type == "account" else "urls", [])
        changes = []
        for item in items:
            ts = _parse_timestamp(getattr(item, 'updated_at', None)) \
                 or _parse_timestamp(getattr(item, 'created_at', None))
            if ts:
                changes.append({
                    "id": getattr(item, 'id', None),
                    "name": getattr(item, 'app_name', '') or getattr(item, 'title', ''),
                    "timestamp": ts,
                    "type": vault_type
                })
        
        if not changes:
            return ToolResult(
                success=True,
                data={"vault_type": vault_type, "changes": []},
                message="暂无变更记录"
            )
        
        # 按时间倒序排序
        changes.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # 时间聚类：相邻修改时间差 < 5分钟视为同一轮
        from datetime import timedelta
        cluster = [changes[0]]
        for i in range(1, len(changes)):
            prev_ts = changes[i - 1]["timestamp"]
            curr_ts = changes[i]["timestamp"]
            if prev_ts - curr_ts < timedelta(minutes=5):
                cluster.append(changes[i])
            else:
                break
        
        # 序列化时间戳用于返回
        for c in cluster:
            ts = c["timestamp"]
            c["timestamp"] = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
        
        return ToolResult(
            success=True,
            data={"vault_type": vault_type, "changes": cluster},
            message=f"获取 {vault_type} 库最近一轮修改，共 {len(cluster)} 条"
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
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(timeout=30)
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
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(timeout=30)
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
