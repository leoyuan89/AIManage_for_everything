"""
AI Tool Calling 基础设施
为 ReAct Agent 模式提供工具定义、注册和执行能力
"""
import logging
import json
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
