"""
密码强度评估模块
基于本地规则的密码强度计算，无需 LLM
"""

# 内存级缓存，避免同一密码重复评估
_strength_cache = {}


def evaluate_password_strength(password: str) -> dict:
    """
    评估密码强度
    
    返回 {"score": 0-4, "label": "弱/中/强/极强"}
    
    评分规则：
    - 0-1分：弱（长度<8，或纯数字/纯字母）
    - 2分：中（长度>=8，含两种字符类型）
    - 3分：强（长度>=12，含三种字符类型）
    - 4分：极强（长度>=16，含四种字符类型：大写/小写/数字/特殊字符）
    
    Note:
        本函数仅返回语义标签（score/label），不返回颜色。
        UI 层应从 ThemeManager.instance().colors 根据 label 动态取色。
    """
    if not password:
        return {"score": 0, "label": "弱"}
    
    length = len(password)
    
    # 统计字符类型
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)
    
    types = sum([has_lower, has_upper, has_digit, has_special])
    
    # 评分逻辑
    if length >= 16 and types >= 4:
        score = 4
    elif length >= 12 and types >= 3:
        score = 3
    elif length >= 8 and types >= 2:
        score = 2
    else:
        # 弱密码：区分 0 分（极弱）和 1 分（较弱）
        if length < 6 or types == 1:
            score = 0
        else:
            score = 1
    
    # 标签映射
    labels = {
        0: "弱",
        1: "弱",
        2: "中",
        3: "强",
        4: "极强"
    }
    
    return {
        "score": score,
        "label": labels.get(score, "弱")
    }


def suggest_improvements(password: str) -> list:
    """Return a list of improvement suggestions for a password"""
    suggestions = []

    if len(password) < 8:
        suggestions.append("增加到 8 位以上")
    elif len(password) < 12:
        suggestions.append("建议增加到 12 位以上，更安全")

    if not any(c.isupper() for c in password):
        suggestions.append("添加大写字母 (A-Z)")

    if not any(c.islower() for c in password):
        suggestions.append("添加小写字母 (a-z)")

    if not any(c.isdigit() for c in password):
        suggestions.append("添加数字 (0-9)")

    if not any(c in '!@#$%^&*-_=+.,;:?<>[]{}|/~`' for c in password):
        suggestions.append("添加特殊符号 (!@#$%等)")

    # Check for sequential characters
    for i in range(len(password) - 2):
        if ord(password[i+1]) == ord(password[i]) + 1 and ord(password[i+2]) == ord(password[i]) + 2:
            suggestions.append("避免连续字符 (如abc、123)")
            break

    # Check for repeated characters
    if len(password) >= 3:
        for i in range(len(password) - 2):
            if password[i] == password[i+1] == password[i+2]:
                suggestions.append("避免重复字符 (如aaa、111)")
                break

    # Check for common patterns
    common_patterns = ['password', 'admin', '123456', 'qwerty', 'abc123', 'iloveyou']
    pw_lower = password.lower()
    for pattern in common_patterns:
        if pattern in pw_lower:
            suggestions.append("避免常见弱密码模式")
            break

    return suggestions
