"""
拼音转换工具
支持中文转拼音首字母，用于拼音搜索
基于 pypinyin 库实现，覆盖全量汉字
"""
from pypinyin import pinyin, Style


class PinyinConverter:
    """拼音转换器"""
    
    @classmethod
    def get_pinyin_initials(cls, text: str) -> str:
        """
        获取中文文本的拼音首字母
        
        Args:
            text: 中文文本
            
        Returns:
            拼音首字母字符串
        """
        if not text:
            return ''
        
        initials = []
        for char in text:
            # 如果是英文字母，直接使用
            if char.isalpha() and char.isascii():
                initials.append(char.lower())
            else:
                # 使用 pypinyin 获取首字母
                try:
                    py = pinyin(char, style=Style.FIRST_LETTER, errors='default')
                    if py and py[0] and py[0][0]:
                        initials.append(py[0][0].lower())
                except Exception:
                    pass
        
        return ''.join(initials)
    
    @classmethod
    def match_pinyin(cls, query: str, text: str) -> bool:
        """
        检查拼音是否匹配
        
        Args:
            query: 查询拼音（如"wx"）
            text: 目标文本（如"微信"）
            
        Returns:
            是否匹配
        """
        if not query or not text:
            return False
        
        query = query.lower()
        text_initials = cls.get_pinyin_initials(text)
        
        # 完全匹配拼音首字母
        if query == text_initials:
            return True
        
        # 包含匹配
        if query in text_initials:
            return True
        
        return False
