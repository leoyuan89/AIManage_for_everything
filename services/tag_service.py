"""
标签服务模块
支持：AI 自动生成 + 用户自定义
"""
import logging
import json
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


class TagService:
    """标签服务"""
    
    # 预定义标签库（用于快速匹配）
    PREDEFINED_TAGS = {
        '金融': ['支付', '理财', '银行', '信用卡', '投资', '保险'],
        '社交': ['聊天', '社交', '通讯', '社区', '论坛'],
        '开发工具': ['代码', '开发', '编程', 'IDE', 'Git', 'API', '云服务器'],
        '购物': ['电商', '购物', '外卖', '团购', '二手交易'],
        '云服务': ['云盘', '云存储', '云计算', 'CDN', '服务器'],
        '娱乐': ['游戏', '视频', '音乐', '直播', '动漫'],
        '教育': ['学习', '课程', '考试', '学术', '图书馆'],
        '工作': ['办公', '协作', '项目管理', '文档', '邮箱'],
        '生活': ['出行', '酒店', '票务', '健康', '健身']
    }
    
    def __init__(self):
        """初始化标签服务"""
        pass
    
    def generate_tags(self, app_name: str, url: str = "", category: str = "") -> List[str]:
        """
        生成标签（仅规则标签，同步接口，向后兼容）
        
        Args:
            app_name: 应用名
            url: 网址
            category: 分类
            
        Returns:
            标签列表
        """
        tags = []
        
        # 1. 基于分类的预定义标签
        if category and category in self.PREDEFINED_TAGS:
            tags.extend(self.PREDEFINED_TAGS[category])
        
        # 2. 基于应用名的关键词提取
        name_tags = self._extract_tags_from_name(app_name)
        tags.extend(name_tags)
        
        # 3. 基于 URL 的域名提取
        if url:
            domain_tags = self._extract_tags_from_url(url)
            tags.extend(domain_tags)
        
        # 去重并限制数量
        tags = list(dict.fromkeys(tags))  # 保持顺序去重
        return tags[:5]  # 最多 5 个标签
    
    def generate_tags_async(self, app_name: str, url: str = "", category: str = "") -> str:
        """
        异步生成 AI 标签，返回 task_id。
        结果通过 AIServiceManager.task_finished / task_failed 信号接收。
        
        Args:
            app_name: 应用名
            url: 网址
            category: 分类
            
        Returns:
            task_id
        """
        prompt = f"""请为以下应用生成 2-3 个关键词标签，用于分类管理。

应用名称：{app_name}
网址：{url}
分类：{category}

要求：
- 标签简短（2-4 个字）
- 标签应体现应用的核心功能或用途
- 直接返回标签，用逗号分隔，不要解释

标签："""
        
        from services.ai_service_manager import AIServiceManager
        from services.ai_worker_thread import AITaskType
        ai_manager = AIServiceManager.instance()
        return ai_manager.submit_task(AITaskType.GENERATE_REMARK, {
            "app_name": app_name,
            "url": url,
            "category": category,
            "prompt": prompt,
            "temperature": 0.3
        })
    
    def parse_tags_from_remark(self, remark_text: str) -> List[str]:
        """
        将 AI 生成的文本解析为标签列表。
        
        Args:
            remark_text: AI 返回的原始文本
            
        Returns:
            标签列表（最多 5 个）
        """
        tags = [tag.strip() for tag in remark_text.split(',') if tag.strip()]
        tags = [tag for tag in tags if len(tag) <= 10]  # 过滤过长的标签
        return tags[:5]
    
    def _extract_tags_from_name(self, app_name: str) -> List[str]:
        """从应用名提取标签关键词"""
        tags = []
        
        # 常见应用关键词映射
        keyword_map = {
            '支付': ['支付宝', '微信支付', 'PayPal'],
            '银行': ['银行', 'Bank'],
            '社交': ['微信', 'QQ', '微博', '抖音', '小红书'],
            '购物': ['淘宝', '京东', '拼多多', '亚马逊', '美团'],
            '云盘': ['百度网盘', '阿里云盘', 'OneDrive', 'Google Drive'],
            '邮箱': ['邮箱', 'Mail', 'Gmail', 'Outlook'],
            '代码': ['GitHub', 'GitLab', 'Gitee', 'Coding'],
            '视频': ['B站', '哔哩哔哩', 'YouTube', '优酷', '爱奇艺'],
            '音乐': ['网易云音乐', 'QQ音乐', 'Spotify'],
            '学习': ['学堂', '课程', '慕课', 'Coursera']
        }
        
        for tag, keywords in keyword_map.items():
            if any(kw in app_name for kw in keywords):
                tags.append(tag)
        
        return tags
    
    def _extract_tags_from_url(self, url: str) -> List[str]:
        """从 URL 提取标签"""
        tags = []
        url_lower = url.lower()
        
        # 根据域名判断
        domain_tags = {
            'github': '代码托管',
            'gitlab': '代码托管',
            'aliyun': '阿里云',
            'tencent': '腾讯',
            'baidu': '百度',
            'google': '谷歌',
        }
        
        for domain, tag in domain_tags.items():
            if domain in url_lower:
                tags.append(tag)
        
        return tags
    
    def _generate_tags_with_ai(self, app_name: str, url: str, category: str) -> List[str]:
        """使用 AI 生成标签"""
        prompt = f"""请为以下应用生成 2-3 个关键词标签，用于分类管理。

应用名称：{app_name}
网址：{url}
分类：{category}

要求：
- 标签简短（2-4 个字）
- 标签应体现应用的核心功能或用途
- 直接返回标签，用逗号分隔，不要解释

标签："""
        
        from services.ai_service_manager import AIServiceManager
        ai_manager = AIServiceManager.instance()
        from ai.ollama_client import OllamaClient
        state = ai_manager.get_state()
        ollama = OllamaClient(model=state.model_name or "gemma4:4b", timeout=300)
        result = ollama.generate(prompt, temperature=0.3)
        
        # 解析结果
        tags = [tag.strip() for tag in result.split('，') if tag.strip()]
        tags = [tag for tag in tags if len(tag) <= 10]  # 过滤过长的标签
        
        return tags
    
    def validate_tag(self, tag: str) -> bool:
        """
        验证标签是否有效
        
        Args:
            tag: 标签文本
            
        Returns:
            是否有效
        """
        if not tag or not tag.strip():
            return False
        
        tag = tag.strip()
        
        # 长度检查
        if len(tag) > 10:
            return False
        
        # 不允许特殊字符
        if any(c in tag for c in ['\n', '\r', '\t', ',', ';']):
            return False
        
        return True
    
    def merge_tags(self, existing_tags: List[str], new_tags: List[str]) -> List[str]:
        """
        合并标签列表（去重）
        
        Args:
            existing_tags: 已有标签
            new_tags: 新标签
            
        Returns:
            合并后的标签列表
        """
        merged = list(existing_tags)
        for tag in new_tags:
            if tag not in merged:
                merged.append(tag)
        return merged[:5]  # 最多 5 个
