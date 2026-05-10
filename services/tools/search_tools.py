"""
搜索类工具 — 语义搜索账号和网址
"""
import json
from typing import Any, List

from .base import AITool, ToolRegistry, ToolResult, PermissionLevel


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
    def execute(self, params, context):
        query = params.get("query", "")
        accounts = context.get("accounts", [])
        if not accounts or not query:
            return ToolResult(success=True, data={"matched_count": 0, "matched_ids": [], "reasoning": ""}, message="无数据或空查询")

        items_summary = _build_accounts_summary(accounts)
        try:
            from ai.ollama_client import OllamaClient
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(timeout=300)
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
    def execute(self, params, context):
        query = params.get("query", "")
        urls = context.get("urls", [])
        if not urls or not query:
            return ToolResult(success=True, data={"matched_count": 0, "matched_ids": [], "reasoning": ""}, message="无数据或空查询")

        items_summary = _build_urls_summary(urls)
        try:
            from ai.ollama_client import OllamaClient
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(timeout=300)
            result = ollama.semantic_match(query, items_summary)
            matched_ids = result.get("matched_ids", [])
            return ToolResult(
                success=True,
                data={"matched_count": len(matched_ids), "matched_ids": matched_ids, "reasoning": result.get("reasoning", "")},
                message=f"语义搜索网址 '{query}'，找到 {len(matched_ids)} 个结果"
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e), message=f"语义搜索失败: {e}")
