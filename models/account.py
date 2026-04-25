"""
数据模型模块
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class Account:
    """账号数据模型"""
    id: Optional[int] = None
    app_name: str = ""
    url: str = ""
    username: str = ""
    password: str = ""
    category: str = "其他"  # 默认分类
    tags: str = "[]"  # JSON 字符串，如 '["支付", "理财"]'
    remark: str = ""
    ai_remark: str = ""  # AI 生成的一句话备注
    security_level: str = ""  # 安全等级：强/中/弱
    last_password_change: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def get_tags_list(self) -> List[str]:
        """获取标签列表"""
        try:
            if isinstance(self.tags, str):
                return json.loads(self.tags) if self.tags else []
            return self.tags if isinstance(self.tags, list) else []
        except:
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
    def from_dict(cls, data: dict) -> 'Account':
        """从字典创建 Account 对象"""
        return cls(
            id=data.get('id'),
            app_name=data.get('app_name', ''),
            url=data.get('url', ''),
            username=data.get('username', ''),
            password=data.get('password', ''),
            category=data.get('category', '其他'),
            tags=data.get('tags', '[]'),
            remark=data.get('remark', ''),
            ai_remark=data.get('ai_remark', ''),
            security_level=data.get('security_level', ''),
            last_password_change=data.get('last_password_change'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': self.id,
            'app_name': self.app_name,
            'url': self.url,
            'username': self.username,
            'password': self.password,
            'category': self.category,
            'tags': self.tags,
            'remark': self.remark,
            'ai_remark': self.ai_remark,
            'security_level': self.security_level,
            'last_password_change': self.last_password_change,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    def mask_username(self) -> str:
        """
        返回脱敏的账号显示
        例如: 138****1234 或 my***@163.com
        """
        if not self.username:
            return ""
        
        username = self.username
        length = len(username)
        
        if length <= 4:
            return username
        elif '@' in username:
            # 邮箱格式：保留首尾，中间用 *** 替代
            local, domain = username.split('@', 1)
            if len(local) <= 2:
                return username
            masked = local[0] + '***' + local[-1] + '@' + domain
            return masked
        else:
            # 普通账号：显示前3位和后3位，中间用 **** 替代
            return username[:3] + '****' + username[-3:]
    
    def get_display_title(self) -> str:
        """获取显示标题"""
        return self.app_name or self.url or '未命名账号'
