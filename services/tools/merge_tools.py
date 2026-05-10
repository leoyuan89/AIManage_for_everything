"""
合并去重类工具 — 智能合并重复的账号和网址
"""
from .base import AITool, ToolRegistry, ToolResult, PermissionLevel


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
    def execute(self, params, context):
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
    def execute(self, params, context):
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
