"""
详情查询类工具 — 查询账号/网址详情、分类、统计、最近变更等
"""
import json
import logging
from datetime import datetime, timedelta

from .base import AITool, ToolRegistry, ToolResult, PermissionLevel

logger = logging.getLogger(__name__)


def _parse_timestamp(ts):
    """把 SQLite 字符串或 datetime 统一解析为 datetime 对象"""
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
    name="get_account_detail",
    description="获取账号详细信息",
    permission=PermissionLevel.READONLY,
    params_schema={"account_id": {"type": "integer", "description": "账号ID"}}
)
class GetAccountDetailTool(AITool):
    def execute(self, params, context):
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
    def execute(self, params, context):
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
    def execute(self, params, context):
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
    def execute(self, params, context):
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
    def execute(self, params, context):
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
    description="获取最近一轮变更记录（按时间聚类，同一批次5分钟内的修改视为一轮）",
    permission=PermissionLevel.READONLY,
    params_schema={
        "vault_type": {"type": "string", "enum": ["account", "url"], "description": "库类型"}
    }
)
class GetRecentChangesTool(AITool):
    def execute(self, params, context):
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
