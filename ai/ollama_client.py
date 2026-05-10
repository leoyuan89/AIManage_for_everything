"""
Ollama API 客户端
用于调用本地 Gemma 4 E4B 模型

本模块为向后兼容的聚合导出入口。
所有实现已拆分到子模块：
- ai.client_base    : 基础 HTTP 客户端
- ai.client_semantic: 语义搜索
- ai.client_tools   : 工具调用与命令解析
- ai.client_utils   : 纯工具函数
"""
from ai.client_base import OllamaClient as _BaseClient
from ai.client_semantic import SemanticClient
from ai.client_tools import ToolClient
from ai.client_utils import _extract_json_object_robust, _fix_json


class OllamaClient(SemanticClient, ToolClient):
    """Ollama HTTP API 客户端（聚合版本）

    继承基础客户端、语义搜索和工具调用功能，
    保持与拆分前完全一致的公共 API。
    """
    pass


def categorize(app_name: str, url: str = "", existing_categories: list = None, parent_hint: str = None, remark: str = "", ai_remark: str = "") -> str:
    """向后兼容：智能分类（便捷函数）"""
    return OllamaClient().categorize(app_name, url, existing_categories, parent_hint, remark, ai_remark)


def semantic_search(query: str, app_list: list, accounts_info: list = None):
    """向后兼容：语义搜索（便捷函数）"""
    return OllamaClient().semantic_search(query, app_list, accounts_info)


__all__ = [
    'OllamaClient',
    'categorize',
    'semantic_search',
    '_extract_json_object_robust',
    '_fix_json',
]
