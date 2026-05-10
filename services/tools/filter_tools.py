"""
过滤类工具 — 按条件筛选账号和网址
"""
from .base import AITool, ToolRegistry, ToolResult, PermissionLevel


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
    def execute(self, params, context):
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
    def execute(self, params, context):
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
