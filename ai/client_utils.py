"""
Ollama 客户端工具函数
纯工具函数，无类依赖
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def _extract_json_object_robust(text: str) -> Optional[str]:
    """使用括号深度计数，从文本中提取第一个完整的 JSON 对象"""
    # 先尝试找 ```json ... ``` 代码块，提取块内全部内容（避免非贪婪截断嵌套 JSON）
    code_block = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if code_block:
        block_content = code_block.group(1).strip()
        start = block_content.find('{')
        if start != -1:
            text_to_scan = block_content
        else:
            text_to_scan = text
            start = text_to_scan.find('{')
    else:
        text_to_scan = text
        start = text_to_scan.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text_to_scan[start:], start):
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text_to_scan[start:i+1]
    return None


def _fix_json(text: str) -> str:
    """修复常见的模型输出 JSON 语法错误"""
    # 1. 去除首尾空白和常见非 JSON 前缀/后缀
    text = text.strip()
    # 去除可能的前缀，如 "输出："、"JSON:" 等
    text = re.sub(r'^(?:输出[:：]|JSON[:：]|Response[:：])\s*', '', text, flags=re.IGNORECASE)
    # 2. 中文引号 → 英文引号（注意保留 JSON 字符串内的中文内容）
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    # 3. 字符串内未转义的换行符/回车 → \\n
    # 使用状态机修复字符串内的原始换行
    result = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\':
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch in '\n\r\t':
            if ch == '\n':
                result.append('\\n')
            elif ch == '\r':
                result.append('\\r')
            else:
                result.append('\\t')
            continue
        result.append(ch)
    text = ''.join(result)
    # 4. 对象/数组末尾多余逗号（如 "a": 1,} → "a": 1}）
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    # 5. 缺少逗号：}{ 之间、}{ 前面有引号等情况（保守修复，只处理明显的）
    text = re.sub(r'"\s*\}\s*\{', r'"},{', text)
    # 6. 紧凑JSON常见：数组/对象结束后直接开始下一个键，缺少逗号
    text = re.sub(r'\](\s*)"', r'],\1"', text)
    text = re.sub(r'\}(\s*)"(?!\s*[\]\}])', r'},\1"', text)
    # 7. 去除 JSON 后可能粘着的解释文字（取最后一个 } 之前的内容）
    last_brace = text.rfind('}')
    if last_brace != -1 and last_brace < len(text) - 1:
        # 检查最后一个 } 后面是否是非空白字符
        tail = text[last_brace+1:].strip()
        if tail and not tail.startswith('}'):
            text = text[:last_brace+1]
    return text
