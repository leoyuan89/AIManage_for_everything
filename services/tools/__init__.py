"""
AI 工具子模块聚合入口

导入本模块会自动触发所有工具的 ToolRegistry 注册。
"""

# 基础设施
from .base import (
    PermissionLevel,
    ToolResult,
    AITool,
    ToolRegistry,
)

# 搜索类
from .search_tools import (
    SemanticSearchAccountsTool,
    SemanticSearchUrlsTool,
)

# 过滤类
from .filter_tools import (
    SemanticFilterAccountsTool,
    SemanticFilterUrlsTool,
)

# 批量操作类
from .batch_tools import (
    BatchAddAccountsTool,
    BatchAddUrlsTool,
    BatchUpdateAccountsTool,
    BatchUpdateUrlsTool,
    BatchReorganizeAccountsTool,
    BatchReorganizeUrlsTool,
    BatchAddRemarkAccountsTool,
    BatchAddRemarkUrlsTool,
    BatchAddTagsAccountsTool,
    BatchAddTagsUrlsTool,
    BatchDeleteAccountsTool,
    BatchDeleteUrlsTool,
)

# 智能分类类
from .classify_tools import (
    sanitize_ai_category,
    SmartClassifyAccountsTool,
    SmartClassifyUrlsTool,
)

# 合并去重类
from .merge_tools import (
    SmartMergeDuplicateAccountsTool,
    SmartMergeDuplicateUrlsTool,
)

# 详情查询类
from .info_tools import (
    GetAccountDetailTool,
    GetUrlDetailTool,
    ListAllCategoriesTool,
    GetCategoryTreeTool,
    GetStatisticsTool,
    GetRecentChangesTool,
)

# 辅助工具类
from .utility_tools import (
    GenerateAccountRemarkTool,
    GenerateUrlRemarkTool,
    GeneratePasswordTool,
    CheckPasswordStrengthTool,
)

__all__ = [
    # base
    "PermissionLevel",
    "ToolResult",
    "AITool",
    "ToolRegistry",
    # search
    "SemanticSearchAccountsTool",
    "SemanticSearchUrlsTool",
    # filter
    "SemanticFilterAccountsTool",
    "SemanticFilterUrlsTool",
    # batch
    "BatchAddAccountsTool",
    "BatchAddUrlsTool",
    "BatchUpdateAccountsTool",
    "BatchUpdateUrlsTool",
    "BatchReorganizeAccountsTool",
    "BatchReorganizeUrlsTool",
    "BatchAddRemarkAccountsTool",
    "BatchAddRemarkUrlsTool",
    "BatchAddTagsAccountsTool",
    "BatchAddTagsUrlsTool",
    "BatchDeleteAccountsTool",
    "BatchDeleteUrlsTool",
    # classify
    "sanitize_ai_category",
    "SmartClassifyAccountsTool",
    "SmartClassifyUrlsTool",
    # merge
    "SmartMergeDuplicateAccountsTool",
    "SmartMergeDuplicateUrlsTool",
    # info
    "GetAccountDetailTool",
    "GetUrlDetailTool",
    "ListAllCategoriesTool",
    "GetCategoryTreeTool",
    "GetStatisticsTool",
    "GetRecentChangesTool",
    # utility
    "GenerateAccountRemarkTool",
    "GenerateUrlRemarkTool",
    "GeneratePasswordTool",
    "CheckPasswordStrengthTool",
]
