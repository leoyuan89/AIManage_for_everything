"""
辅助工具类 — 生成备注、密码、检测密码强度等
"""
from .base import AITool, ToolRegistry, ToolResult, PermissionLevel


@ToolRegistry.register(
    name="generate_account_remark",
    description="生成账号AI备注",
    permission=PermissionLevel.READONLY,
    params_schema={
        "app_name": {"type": "string", "description": "应用名称"},
        "category": {"type": "string", "description": "分类"},
        "url": {"type": "string", "description": "网址"}
    }
)
class GenerateAccountRemarkTool(AITool):
    def execute(self, params, context):
        app_name = params.get("app_name", "")
        category = params.get("category", "")
        url = params.get("url", "")
        try:
            from ai.ollama_client import OllamaClient
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(timeout=300)
            prompt = f"请为密码管理软件的账号生成一句话备注。应用名：{app_name}，分类：{category}，网址：{url}。只返回一句话备注，不要其他解释。"
            remark = ollama.generate(prompt, temperature=0.3, num_predict=100)
            remark = remark.strip().strip('"').strip("'")
        except Exception as e:
            remark = f"{app_name}（{category}）账号"
        return ToolResult(
            success=True,
            data={"remark": remark},
            message=f"为 {app_name} 生成备注"
        )


@ToolRegistry.register(
    name="generate_url_remark",
    description="生成网址AI备注",
    permission=PermissionLevel.READONLY,
    params_schema={
        "title": {"type": "string", "description": "标题"},
        "url": {"type": "string", "description": "网址"},
        "category": {"type": "string", "description": "分类"}
    }
)
class GenerateUrlRemarkTool(AITool):
    def execute(self, params, context):
        title = params.get("title", "")
        category = params.get("category", "")
        url = params.get("url", "")
        try:
            from ai.ollama_client import OllamaClient
            # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
            ollama = OllamaClient(timeout=300)
            prompt = f"请为网址生成一句话备注。标题：{title}，分类：{category}，网址：{url}。只返回一句话备注，不要其他解释。"
            remark = ollama.generate(prompt, temperature=0.3, num_predict=100)
            remark = remark.strip().strip('"').strip("'")
        except Exception as e:
            remark = f"{title}（{category}）网址"
        return ToolResult(
            success=True,
            data={"remark": remark},
            message=f"为 {title} 生成备注"
        )


@ToolRegistry.register(
    name="generate_password",
    description="生成随机强密码",
    permission=PermissionLevel.CONFIRM,
    params_schema={
        "length": {"type": "integer", "description": "密码长度", "default": 16},
        "include_special": {"type": "boolean", "description": "是否包含特殊字符", "default": True}
    }
)
class GeneratePasswordTool(AITool):
    def execute(self, params, context):
        import secrets
        import string
        length = params.get("length", 16)
        include_special = params.get("include_special", True)
        chars = string.ascii_letters + string.digits
        if include_special:
            chars += string.punctuation
        password = ''.join(secrets.choice(chars) for _ in range(length))
        return ToolResult(
            success=True,
            data={"password": password, "length": length},
            message=f"已生成 {length} 位随机密码"
        )


@ToolRegistry.register(
    name="check_password_strength",
    description="检测密码强度",
    permission=PermissionLevel.READONLY,
    params_schema={"password": {"type": "string", "description": "待检测密码"}}
)
class CheckPasswordStrengthTool(AITool):
    def execute(self, params, context):
        password = params.get("password", "")
        score = 0
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if any(c.isupper() for c in password):
            score += 1
        if any(c.islower() for c in password):
            score += 1
        if any(c.isdigit() for c in password):
            score += 1
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            score += 1

        levels = ["弱", "弱", "中", "中", "强", "强", "极强"]
        strength = levels[min(score, 6)]
        return ToolResult(
            success=True,
            data={"password": password, "strength": strength, "score": score},
            message=f"密码强度：{strength}（得分 {score}/6）"
        )
