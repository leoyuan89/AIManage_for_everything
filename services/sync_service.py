"""
同步服务模块
生成单文件 HTML 密包，用于手机端离线查看
"""
import json
import base64
import os
from datetime import datetime
from pathlib import Path
from typing import List

from models.account import Account


class SyncService:
    """同步服务：生成加密的单文件 HTML 密包"""
    
    def __init__(self, template_path: str = None):
        """
        初始化同步服务
        
        Args:
            template_path: HTML 模板路径，默认使用项目 templates/pwa_template.html
        """
        if template_path is None:
            # 默认模板路径：项目根目录下的 templates/pwa_template.html
            project_root = Path(__file__).parent.parent
            template_path = project_root / 'templates' / 'pwa_template.html'
        self.template_path = Path(template_path)
    
    def generate_pwa_package(self, crypto_manager, accounts: List[Account], output_path: str) -> str:
        """
        生成 PWA 密包文件
        
        Args:
            crypto_manager: 加密管理器实例
            accounts: 账号列表
            output_path: 输出 HTML 文件路径
            
        Returns:
            生成的文件路径
            
        Raises:
            FileNotFoundError: 模板文件不存在
            ValueError: 参数无效
            Exception: 加密或写入失败
        """
        if not self.template_path.exists():
            raise FileNotFoundError(f"HTML模板不存在: {self.template_path}")
        
        if accounts is None:
            raise ValueError("accounts 不能为 None")
        
        # 1. 将账号列表转为 JSON（仅包含必要字段）
        accounts_data = []
        for acc in accounts:
            accounts_data.append({
                'id': acc.id,
                'app_name': acc.app_name,
                'url': acc.url,
                'username': acc.username,
                'password': acc.password,
                'category': acc.category,
                'tags': acc.tags if isinstance(acc.tags, str) else json.dumps(acc.tags, ensure_ascii=False),
                'remark': acc.remark,
                'security_level': acc.security_level,
            })
        
        json_data = json.dumps(accounts_data, ensure_ascii=False, indent=2)
        
        # 2. 用 crypto_manager 加密 JSON 数据
        encrypted_data = crypto_manager.encrypt_to_string(json_data)
        
        # 3. 获取 salt（Base64 编码，供 JS 使用）
        salt_b64 = base64.b64encode(crypto_manager.salt).decode('utf-8')
        
        # 4. 读取 HTML 模板
        with open(self.template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        # 5. 注入加密数据和 salt 到模板变量
        html_content = template.replace('{{ENCRYPTED_DATA}}', encrypted_data)
        html_content = html_content.replace('{{SALT_BASE64}}', salt_b64)
        html_content = html_content.replace('{{GENERATED_AT}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        html_content = html_content.replace('{{ACCOUNT_COUNT}}', str(len(accounts_data)))
        
        # 6. 写出 HTML 文件
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return str(output_path)
