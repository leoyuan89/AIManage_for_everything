"""
导出服务模块
支持：Excel 导出、加密备份导出、HTML 书签导出
"""
import logging
import html
import json
import base64
from pathlib import Path
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

from core.crypto import CryptoManager
from core.database import DatabaseManager
from models.account import Account


class ExportService:
    """导出服务"""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        初始化导出服务
        
        Args:
            db_manager: 数据库管理器
        """
        self.db = db_manager
    
    def export_to_excel(self, accounts: List[Account], file_path: str, include_password: bool = True) -> bool:
        """
        导出到 Excel
        
        Args:
            accounts: 要导出的账号列表
            file_path: 导出文件路径
            include_password: 是否包含密码
            
        Returns:
            是否成功
        """
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "账号列表"
            
            # 设置标题样式
            header_font = Font(bold=True, size=12, color="FFFFFF")
            header_fill = PatternFill(start_color="2196F3", end_color="2196F3", fill_type="solid")
            header_alignment = Alignment(horizontal="center", vertical="center")
            
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            # 表头
            headers = ['序号', '应用名', '网址', '账号']
            if include_password:
                headers.append('密码')
            headers.extend(['分类', '备注', '创建时间'])
            
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border
            
            # 数据行
            for idx, account in enumerate(accounts, 1):
                row = idx + 1
                ws.cell(row=row, column=1, value=idx).border = thin_border
                ws.cell(row=row, column=2, value=account.app_name).border = thin_border
                ws.cell(row=row, column=3, value=account.url).border = thin_border
                ws.cell(row=row, column=4, value=account.username).border = thin_border
                
                col = 5
                if include_password:
                    ws.cell(row=row, column=col, value=account.password).border = thin_border
                    col += 1
                
                ws.cell(row=row, column=col, value=account.category).border = thin_border
                ws.cell(row=row, column=col+1, value=account.remark).border = thin_border
                ws.cell(row=row, column=col+2, value=str(account.created_at)).border = thin_border
                
                # 设置行高
                ws.row_dimensions[row].height = 25
            
            # 调整列宽
            ws.column_dimensions['A'].width = 8
            ws.column_dimensions['B'].width = 20
            ws.column_dimensions['C'].width = 30
            ws.column_dimensions['D'].width = 25
            if include_password:
                ws.column_dimensions['E'].width = 20
            ws.column_dimensions['F'].width = 12
            ws.column_dimensions['G'].width = 30
            ws.column_dimensions['H'].width = 20
            
            # 冻结首行
            ws.freeze_panes = 'A2'
            
            # 保存
            wb.save(file_path)
            return True
            
        except Exception as e:
            logger.error("Excel export failed: %s", e)
            return False
    
    def export_encrypted_backup(self, accounts: List[Account], file_path: str, 
                                   backup_password: str = None) -> bool:
        """
        导出加密备份文件（.vault）
        
        Args:
            accounts: 要导出的账号列表
            file_path: 导出文件路径（.vault）
            backup_password: 独立备份密码（None则使用主密码加密）
            
        Returns:
            是否成功
        """
        try:
            # 构建数据
            data = {
                'version': '1.0',
                'export_time': datetime.now().isoformat(),
                'count': len(accounts),
                'accounts': []
            }
            
            for account in accounts:
                data['accounts'].append({
                    'app_name': account.app_name,
                    'url': account.url,
                    'username': account.username,
                    'password': account.password,
                    'category': account.category,
                    'remark': account.remark,
                    'tags': account.tags,
                    'created_at': str(account.created_at) if account.created_at else None,
                    'updated_at': str(account.updated_at) if account.updated_at else None
                })
            
            # 转为 JSON
            json_data = json.dumps(data, ensure_ascii=False, indent=2)
            
            # 创建加密管理器
            if backup_password:
                # 使用独立密码
                crypto = CryptoManager(backup_password)
            else:
                # 使用主密码（从数据库获取）
                crypto = self.db.crypto
            
            # 加密
            encrypted = crypto.encrypt_to_string(json_data)
            
            # 保存：第一行是盐值(Base64)，第二行是加密数据
            # 这样可以跨设备恢复（新设备需要盐值来派生密钥）
            import base64
            salt_b64 = base64.b64encode(crypto.salt).decode('utf-8')
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(salt_b64 + '\n')
                f.write(encrypted)
            
            return True
            
        except Exception as e:
            logger.error("Encrypted backup failed: %s", e)
            return False
    
    def export_urls_to_html(self, urls: List, file_path: str) -> bool:
        """
        导出网址到 HTML 书签文件（Netscape Bookmark Format）
        可被 Chrome / Edge / Firefox 导入
        
        按二级分类嵌套结构生成：<H3> 主类 → <DL> → <H3> 子类 → <DL> → <A> 链接
        
        Args:
            urls: 要导出的网址列表（URLItem）
            file_path: 导出文件路径
            
        Returns:
            是否成功
        """
        try:
            from core.category_utils import parse_category_path
            
            def _build_nested_groups(urls):
                """构建二级嵌套结构：{parent: {'direct': [], 'children': {child: []}}}"""
                groups = {}
                for item in urls:
                    parent, child = parse_category_path(item.category or '其他')
                    if parent not in groups:
                        groups[parent] = {'direct': [], 'children': {}}
                    if child:
                        if child not in groups[parent]['children']:
                            groups[parent]['children'][child] = []
                        groups[parent]['children'][child].append(item)
                    else:
                        groups[parent]['direct'].append(item)
                return groups
            
            def to_timestamp(dt) -> int:
                if isinstance(dt, datetime):
                    return int(dt.timestamp())
                return int(datetime.now().timestamp())
            
            lines = [
                '<!DOCTYPE NETSCAPE-Bookmark-file-1>',
                '<!-- This is an automatically generated file.',
                '     It will be read and overwritten.',
                '     DO NOT EDIT! -->',
                '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
                '<TITLE>Bookmarks</TITLE>',
                '<H1>Bookmarks</H1>',
                '<DL><p>',
            ]
            
            now_ts = to_timestamp(datetime.now())
            groups = _build_nested_groups(urls)
            
            for parent_name in sorted(groups.keys()):
                data = groups[parent_name]
                # 取父文件夹时间戳（优先用直接条目，否则用子类条目）
                parent_items = data['direct'] or (
                    next(iter(data['children'].values())) if data['children'] else []
                )
                parent_ts = to_timestamp(parent_items[0].created_at) if parent_items else now_ts
                
                # 一级文件夹
                lines.append(f'    <DT><H3 ADD_DATE="{parent_ts}" LAST_MODIFIED="{now_ts}">{html.escape(parent_name)}</H3>')
                lines.append('    <DL><p>')
                
                # 属于一级分类本身的条目（无子类）
                for item in data['direct']:
                    item_ts = to_timestamp(item.created_at)
                    title = html.escape(item.title or item.url or '未命名')
                    url = html.escape(item.url or '')
                    tip = html.escape(item.remark or item.ai_remark or '')
                    attr_title = f' TITLE="{tip}"' if tip else ''
                    lines.append(f'        <DT><A HREF="{url}" ADD_DATE="{item_ts}"{attr_title}>{title}</A>')
                
                # 二级文件夹
                for child_name in sorted(data['children'].keys()):
                    child_items = data['children'][child_name]
                    child_ts = to_timestamp(child_items[0].created_at) if child_items else now_ts
                    
                    lines.append(f'        <DT><H3 ADD_DATE="{child_ts}" LAST_MODIFIED="{now_ts}">{html.escape(child_name)}</H3>')
                    lines.append('        <DL><p>')
                    
                    for item in child_items:
                        item_ts = to_timestamp(item.created_at)
                        title = html.escape(item.title or item.url or '未命名')
                        url = html.escape(item.url or '')
                        tip = html.escape(item.remark or item.ai_remark or '')
                        attr_title = f' TITLE="{tip}"' if tip else ''
                        lines.append(f'            <DT><A HREF="{url}" ADD_DATE="{item_ts}"{attr_title}>{title}</A>')
                    
                    lines.append('        </DL><p>')
                
                lines.append('    </DL><p>')
            
            lines.append('</DL><p>')
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            return True
            
        except Exception as e:
            logger.error("URL HTML export failed: %s", e)
            return False
    
    def export_urls_to_excel(self, urls: List, file_path: str) -> bool:
        """
        导出网址到 Excel
        
        Args:
            urls: 要导出的网址列表（URLItem）
            file_path: 导出文件路径
            
        Returns:
            是否成功
        """
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "网址列表"
            
            # 设置标题样式
            header_font = Font(bold=True, size=12, color="FFFFFF")
            header_fill = PatternFill(start_color="2196F3", end_color="2196F3", fill_type="solid")
            header_alignment = Alignment(horizontal="center", vertical="center")
            
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            # 表头
            headers = ['序号', '标题', '网址', '分类', '标签', '访问次数', '创建时间']
            
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border
            
            # 数据行
            for idx, url_item in enumerate(urls, 1):
                row = idx + 1
                ws.cell(row=row, column=1, value=idx).border = thin_border
                ws.cell(row=row, column=2, value=url_item.title).border = thin_border
                ws.cell(row=row, column=3, value=url_item.url).border = thin_border
                ws.cell(row=row, column=4, value=url_item.category).border = thin_border
                
                tags = url_item.get_tags_list()
                tags_str = ', '.join(tags) if tags else ''
                ws.cell(row=row, column=5, value=tags_str).border = thin_border
                
                ws.cell(row=row, column=6, value=url_item.visit_count).border = thin_border
                ws.cell(row=row, column=7, value=str(url_item.created_at)).border = thin_border
                
                # 设置行高
                ws.row_dimensions[row].height = 25
            
            # 调整列宽
            ws.column_dimensions['A'].width = 8
            ws.column_dimensions['B'].width = 25
            ws.column_dimensions['C'].width = 40
            ws.column_dimensions['D'].width = 12
            ws.column_dimensions['E'].width = 20
            ws.column_dimensions['F'].width = 10
            ws.column_dimensions['G'].width = 20
            
            # 冻结首行
            ws.freeze_panes = 'A2'
            
            # 保存
            wb.save(file_path)
            return True
            
        except Exception as e:
            logger.error("URL Excel export failed: %s", e)
            return False
    
    def import_from_vault(self, file_path: str, master_password: str) -> Optional[List[Account]]:
        """
        从加密备份文件导入（支持跨设备恢复）
        
        Args:
            file_path: 备份文件路径
            master_password: 用户输入的主密码
            
        Returns:
            账号列表，失败返回 None，密码错误返回空列表
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.read().strip().split('\n')
            
            # 判断格式：新格式（2行：salt + encrypted）或旧格式（1行：仅 encrypted）
            if len(lines) >= 2:
                # 新格式：第一行是 salt，第二行是加密数据
                import base64
                salt = base64.b64decode(lines[0].encode('utf-8'))
                encrypted = lines[1]
            else:
                # 旧格式：只有加密数据，尝试用当前 crypto 解密（仅同设备）
                # 如果外部没提供 crypto，这里会失败
                raise ValueError("旧格式备份文件需要使用相同的设备配置才能恢复")
            
            # 使用用户提供的密码和盐值创建 CryptoManager
            from core.crypto import CryptoManager
            crypto = CryptoManager(master_password, salt)
            
            # 解密
            json_data = crypto.decrypt_from_string(encrypted)
            
            # 解析 JSON
            data = json.loads(json_data)
            
            accounts = []
            for acc_data in data.get('accounts', []):
                account = Account(
                    app_name=acc_data.get('app_name', ''),
                    url=acc_data.get('url', ''),
                    username=acc_data.get('username', ''),
                    password=acc_data.get('password', ''),
                    category=acc_data.get('category', '其他'),
                    remark=acc_data.get('remark', ''),
                    tags=acc_data.get('tags', '[]')
                )
                accounts.append(account)
            
            return accounts
            
        except Exception as e:
            logger.error("Vault import failed: %s", e)
            return None
