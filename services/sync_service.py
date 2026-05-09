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

from core.pinyin import PinyinConverter
from models.account import Account


def _compute_sort_fields(text: str) -> dict:
    """
    计算排序字段（与 main_window.py 中 _get_alpha_key / _account_sort_key 逻辑一致）
    
    Returns:
        {'_alpha_key': 首字母或'#', '_sort_key': 排序文本}
    """
    if not text:
        return {'_alpha_key': '#', '_sort_key': ''}
    
    first_char = text[0]
    # 英文字母
    if 'a' <= first_char.lower() <= 'z':
        return {'_alpha_key': first_char.upper(), '_sort_key': text.lower()}
    # 中文 CJK 范围
    if '\u4e00' <= first_char <= '\u9fff':
        pinyin = PinyinConverter.get_pinyin_initials(text).lower()
        alpha = pinyin[0].upper() if pinyin else '#'
        return {'_alpha_key': alpha, '_sort_key': pinyin}
    # 数字、符号等其他字符归为 #
    return {'_alpha_key': '#', '_sort_key': text.lower()}


def _get_category_sort_key(category: str, category_orders: dict) -> tuple:
    """获取分类的排序key：(父类sort_index, 子类sort_index)"""
    if not category:
        return (float('inf'), float('inf'))
    parent = category.split('>')[0].strip() if '>' in category else category.strip()
    parent_order = category_orders.get(parent, float('inf'))
    child_order = category_orders.get(category, float('inf'))
    return (parent_order, child_order)


def _serialize_accounts(accounts: List[Account], category_orders: dict = None) -> list:
    """序列化账号列表并预计算排序字段"""
    if category_orders is None:
        category_orders = {}
    result = []
    for acc in accounts:
        item = {
            'id': acc.id,
            'app_name': acc.app_name,
            'url': acc.url,
            'username': acc.username,
            'password': acc.password,
            'category': acc.category,
            'tags': acc.tags if isinstance(acc.tags, str) else json.dumps(acc.tags, ensure_ascii=False),
            'remark': acc.remark,
            'ai_remark': getattr(acc, 'ai_remark', None),
            'security_level': acc.security_level,
        }
        sort_fields = _compute_sort_fields(acc.app_name or '')
        item['_alpha_key'] = sort_fields['_alpha_key']
        item['_sort_key'] = sort_fields['_sort_key']
        result.append(item)
    # 先按软件中设置的类别顺序排序，同一类别内按拼音首字母排序
    result.sort(key=lambda x: (
        _get_category_sort_key(x.get('category', ''), category_orders),
        0 if x['_alpha_key'] != '#' else 1,
        x['_sort_key']
    ))
    return result


def _serialize_urls(urls: List, category_orders: dict = None) -> list:
    """序列化网址列表并预计算排序字段"""
    if category_orders is None:
        category_orders = {}
    result = []
    for u in urls:
        item = {
            'id': u.id,
            'title': u.title,
            'url': u.url,
            'category': u.category,
            'tags': u.tags if isinstance(u.tags, str) else json.dumps(u.tags, ensure_ascii=False),
            'visit_count': u.visit_count,
            'password': getattr(u, 'password', None),
            'ai_remark': u.ai_remark,
            'remark': u.remark,
        }
        sort_fields = _compute_sort_fields(u.title or '')
        item['_alpha_key'] = sort_fields['_alpha_key']
        item['_sort_key'] = sort_fields['_sort_key']
        result.append(item)
    result.sort(key=lambda x: (
        _get_category_sort_key(x.get('category', ''), category_orders),
        0 if x['_alpha_key'] != '#' else 1,
        x['_sort_key']
    ))
    return result


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
    
    def generate_pwa_package(self, crypto_manager, accounts: List[Account], urls: List, output_path: str,
                             account_category_orders: dict = None, url_category_orders: dict = None) -> str:
        """
        生成 PWA 密包文件（同时包含密码库 + 网址库）
        
        Args:
            crypto_manager: 加密管理器实例
            accounts: 账号列表
            urls: 网址列表
            output_path: 输出 HTML 文件路径
            account_category_orders: 账号分类自定义排序（category -> sort_index）
            url_category_orders: 网址分类自定义排序（category -> sort_index）
            
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
        if urls is None:
            raise ValueError("urls 不能为 None")
        
        # 1. 序列化账号和网址数据（含排序字段，按软件中设置的类别顺序）
        accounts_data = _serialize_accounts(accounts, account_category_orders)
        urls_data = _serialize_urls(urls, url_category_orders)
        
        # 打包为统一结构（包含分类排序信息，供手机端按软件中的顺序显示）
        payload = {
            'accounts': accounts_data,
            'urls': urls_data,
            'account_category_orders': account_category_orders or {},
            'url_category_orders': url_category_orders or {},
        }
        json_data = json.dumps(payload, ensure_ascii=False, indent=2)
        
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
        html_content = html_content.replace('{{ITERATIONS}}', str(crypto_manager.iterations))
        html_content = html_content.replace('{{GENERATED_AT}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        html_content = html_content.replace('{{ACCOUNT_COUNT}}', str(len(accounts_data)))
        html_content = html_content.replace('{{URL_COUNT}}', str(len(urls_data)))
        
        # 6. 原子写入 HTML 文件（先写临时文件，成功后替换）
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        tmp_path = output_path.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        os.replace(str(tmp_path), str(output_path))
        
        return str(output_path)
