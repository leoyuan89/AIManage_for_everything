"""
网址数据模型
"""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List


@dataclass
class URLItem:
    """网址数据模型"""
    id: Optional[int] = None
    title: str = ""           # 标题
    url: str = ""             # 网址
    category: str = "其他"     # 分类
    tags: str = "[]"          # 标签（JSON 数组）
    related_account_id: Optional[int] = None  # 关联的账号 ID
    password: str = ""        # 密码
    visit_count: int = 0      # 访问次数
    ai_remark: str = ""       # AI 生成的一句话备注（新增）
    remark: str = ""          # 用户备注（新增）
    is_favorite: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def get_tags_list(self) -> List[str]:
        """获取标签列表"""
        try:
            if isinstance(self.tags, str):
                return json.loads(self.tags) if self.tags else []
            return self.tags if isinstance(self.tags, list) else []
        except Exception:
            return []
    
    def set_tags_list(self, tags: List[str]):
        """设置标签列表"""
        self.tags = json.dumps(tags, ensure_ascii=False)
    
    def add_tag(self, tag: str):
        """添加标签"""
        tags = self.get_tags_list()
        if tag not in tags:
            tags.append(tag)
            self.set_tags_list(tags)
    
    def remove_tag(self, tag: str):
        """移除标签"""
        tags = self.get_tags_list()
        if tag in tags:
            tags.remove(tag)
            self.set_tags_list(tags)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'URLItem':
        """从字典创建 URLItem 对象"""
        return cls(
            id=data.get('id'),
            title=data.get('title', ''),
            url=data.get('url', ''),
            category=data.get('category', '其他'),
            tags=data.get('tags', '[]'),
            related_account_id=data.get('related_account_id'),
            password=data.get('password', ''),
            visit_count=data.get('visit_count', 0),
            ai_remark=data.get('ai_remark', ''),
            remark=data.get('remark', ''),
            is_favorite=bool(data.get('is_favorite', False)),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'title': self.title,
            'url': self.url,
            'category': self.category,
            'tags': self.tags,
            'related_account_id': self.related_account_id,
            'password': self.password,
            'visit_count': self.visit_count,
            'ai_remark': self.ai_remark,
            'remark': self.remark,
            'is_favorite': int(self.is_favorite),
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
