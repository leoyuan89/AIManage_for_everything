"""
密码强度评估模块
基于本地规则的密码强度计算，无需 LLM
"""


def evaluate_password_strength(password: str) -> dict:
    """
    评估密码强度
    
    返回 {"score": 0-4, "label": "弱/中/强/极强", "color": "#..."}
    
    评分规则：
    - 0-1分：弱（长度<8，或纯数字/纯字母）
    - 2分：中（长度>=8，含两种字符类型）
    - 3分：强（长度>=12，含三种字符类型）
    - 4分：极强（长度>=16，含四种字符类型：大写/小写/数字/特殊字符）
    """
    if not password:
        return {"score": 0, "label": "弱", "color": "#f44336"}
    
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
    
    # 标签和颜色映射
    labels = {
        0: "弱",
        1: "弱",
        2: "中",
        3: "强",
        4: "极强"
    }
    colors = {
        0: "#f44336",   # 红色
        1: "#f44336",   # 红色
        2: "#FF9800",   # 橙色
        3: "#4CAF50",   # 绿色
        4: "#2196F3"    # 蓝色
    }
    bg_colors = {
        0: "#ffebee",
        1: "#ffebee",
        2: "#fff3e0",
        3: "#e8f5e9",
        4: "#e3f2fd"
    }
    
    return {
        "score": score,
        "label": labels.get(score, "弱"),
        "color": colors.get(score, "#f44336"),
        "bg_color": bg_colors.get(score, "#ffebee")
    }
