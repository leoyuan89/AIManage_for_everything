"""
分类路径解析与层级工具。

为全项目提供统一的路径解析、校验、树构建工具，避免各模块重复实现。
该模块为纯工具函数，无状态，不依赖数据库。
"""

from typing import Callable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def parse_category_path(category: str) -> Tuple[str, Optional[str]]:
    """
    解析分类路径。

    输入 "工作>开发工具" → ("工作", "开发工具")
    输入 "学术与研究"   → ("学术与研究", None)
    输入 "A>B>C"       → 抛出 ValueError（禁止三级）

    Args:
        category: 分类路径字符串，可能包含层级分隔符 ">"

    Returns:
        (parent, child) 元组；child 为 None 表示一级分类

    Raises:
        ValueError: 当路径中出现两个及以上 ">" 时（禁止三级及以上）
    """
    if not category:
        return ("", None)

    parts = category.split(">")
    if len(parts) > 2:
        raise ValueError(f"禁止三级及以上分类路径: {category}")

    parent = parts[0].strip()
    child = parts[1].strip() if len(parts) == 2 else None
    return (parent, child)


def validate_category_name(name: str) -> bool:
    """
    校验单级分类名是否合法。

    禁止包含 '/', '>', '·' 以及空白字符首尾。

    Args:
        name: 单级分类名（不含 ">"）

    Returns:
        True 表示合法，False 表示非法
    """
    if not name:
        return False
    if name != name.strip():
        return False
    if any(ch in name for ch in ("/", ">", "·")):
        return False
    return True


def format_category_path(parent: str, child: Optional[str] = None) -> str:
    """
    格式化路径。

    ("工作", "开发工具") → "工作>开发工具"
    ("学术与研究", None) → "学术与研究"

    Args:
        parent: 主分类名
        child: 子分类名，为 None 时表示一级分类

    Returns:
        格式化后的分类路径字符串
    """
    if child:
        return f"{parent}>{child}"
    return parent


def build_category_tree(categories: List[str]) -> dict:
    """
    将扁平分类列表构建为树形字典。

    输入：["工作", "工作>开发工具", "娱乐>游戏", "学术与研究"]
    输出：{
        "工作": {"children": {"开发工具"}, "has_direct_items": True},
        "娱乐": {"children": {"游戏"}, "has_direct_items": False},
        "学术与研究": {"children": set(), "has_direct_items": True}
    }

    Args:
        categories: 分类路径字符串列表（可能包含重复或空字符串）

    Returns:
        树形字典，键为主分类名，值为 {"children": set(), "has_direct_items": bool}
    """
    tree: dict = {}

    for cat in categories:
        if not cat:
            continue
        parent, child = parse_category_path(cat)
        if not parent:
            continue

        if parent not in tree:
            tree[parent] = {"children": set(), "has_direct_items": False}

        if child:
            tree[parent]["children"].add(child)
        else:
            tree[parent]["has_direct_items"] = True

    return tree


def get_prefix_matcher(category: str) -> Callable[[str], bool]:
    """
    返回一个匹配函数，用于判断某条目的分类是否属于当前选中节点。

    选中 "工作" → 匹配 "工作" 和 "工作>开发工具"
    选中 "工作>开发工具" → 仅精确匹配

    Args:
        category: 当前选中的分类路径

    Returns:
        接收 item_category 字符串并返回 bool 的匹配函数
    """
    if ">" in category:
        # 子节点：精确匹配
        def _exact_matcher(item_category: str) -> bool:
            return item_category == category
        return _exact_matcher

    # 父节点：匹配自身及所有子类
    prefix = f"{category}>"

    def _prefix_matcher(item_category: str) -> bool:
        return item_category == category or item_category.startswith(prefix)

    return _prefix_matcher
