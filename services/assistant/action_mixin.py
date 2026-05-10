import json
import logging
import uuid
from typing import List, Dict, Any

from models.account import Account
from models.url_item import URLItem
from core.repositories import RepositoryFactory
from services.ai_tools import ToolResult, AITool
from services.batch_add_processor import BatchAddProcessor

logger = logging.getLogger(__name__)


class ActionMixin:
    def _heuristic_reorganize(self, context_items: List[Any], repo) -> List[Dict]:
        """本地启发式分类（模型未返回结构化 changes 时的兜底）"""
        category_keywords = {
            '金融': ['银行', '支付', '理财', '保险', '证券', '信用卡', '支付宝', '财富', '股票', '东方财富', '银联', 'paypal', 'pay'],
            '社交': ['微信', 'QQ', '微博', '抖音', '小红书', '知乎', '推特', 'facebook', 'telegram', 'whatsapp', 'line'],
            '邮箱': ['邮箱', 'mail', 'gmail', 'outlook', '163', 'qq邮箱', 'email', '126'],
            '游戏': ['游戏', 'steam', 'epic', '暴雪', '腾讯游戏', '网易游戏', 'bilibili游戏', '原神', '王者'],
            '工作': ['办公', '企业', '钉钉', '飞书', 'slack', 'github', 'gitlab', 'notion', '语雀', '金山', 'wps', 'office', 'confluence'],
            '购物': ['淘宝', '京东', '拼多多', '亚马逊', '天猫', '购物', '商城', '电商', '便利店', '美团', '饿了么', '外卖'],
            '教育': ['学习', '课程', 'edu', '学堂', 'mooc', 'coursera', 'academy', 'acwing', 'leetcode', '知网', '学习通', 'cet', '四六级', '慕课', '校园', '大学', '图书馆'],
            '娱乐': ['视频', '影视', '音乐', 'bilibili', 'youtube', 'netflix', 'spotify', '直播', '斗鱼', '虎牙', '综艺', '电影', '追剧'],
            '开发': ['开发', '代码', 'git', 'api', 'docker', 'vscode', 'jetbrains', '编程', 'leetcode', 'acwing', 'github', 'gitlab', 'stackoverflow', 'hackerrank'],
            '云服务': ['云', '服务器', 'aws', '阿里云', '腾讯云', 'heroku', 'vercel', 'vps', '主机', 'cdn', '域名'],
            '健康': ['健康', '医院', '医保', '健身', 'medical', 'health', '体检', '疫苗'],
            '政府': ['政府', '社保', '公积金', '税务', 'gov', '政务', '国家', '图书馆', '医保', '公安部', '交管'],
            '翻译': ['翻译', 'deepl', 'translate', '词典', '字典', 'dictionary'],
            '竞赛': ['竞赛', '比赛', '大赛', '蓝桥', '大创', 'cvpr', 'acm', '挑战杯', 'kaggle'],
            '网盘': ['网盘', '云盘', '百度网盘', '阿里云盘', '坚果云', 'dropbox', 'onedrive', 'icloud'],
        }
        # 优化：扁平化关键词映射，减少嵌套循环
        keyword_to_cat = {}
        for cat, keywords in category_keywords.items():
            for kw in keywords:
                keyword_to_cat[kw] = cat
        
        preview_items = []
        for item in context_items:
            name = (repo.get_display_name(item) or '').lower()
            if not name:
                continue
            old_cat = repo.get_field_value(item, 'category') or '其他'
            new_cat = None
            # 使用扁平化的关键词映射，减少循环层数
            for kw, cat in keyword_to_cat.items():
                if kw in name:
                    new_cat = cat
                    break
            if new_cat and new_cat != old_cat:
                tid = item.id if hasattr(item, 'id') else item.get('id')
                preview_items.append({
                    "target_id": tid,
                    "app_name": repo.get_display_name(item),
                    "field": "category",
                    "old_value": old_cat,
                    "new_value": new_cat,
                    "reason": "本地关键词匹配"
                })
        return preview_items
    
    def build_action_preview(self, action: str, params: dict,
                             context_items: List[Any] = None,
                             vault_type: str = 'accounts') -> Dict:
        """
        Build 模式：生成结构化操作预览。
        
        Args:
            action: 动作类型
            params: 动作参数
            context_items: 当前上下文条目列表
            vault_type: 'accounts' 或 'urls'
            
        Returns:
            {
                "success": bool,
                "action": str,
                "preview_items": [...],
                "affected_count": int,
                "action_type": str,
                "message": str,
                "vault_type": str
            }
        """
        repo = RepositoryFactory.get_repository(vault_type)
        
        if context_items is None:
            context_items = repo.get_all()
        
        item_map = {item.id: item for item in context_items}
        preview_items = []
        affected_count = 0
        item_type_name = repo.get_item_type_name()
        
        if action == 'reorganize':
            changes = params.get('changes', [])
            if changes:
                for change in changes:
                    tid = change.get('target_id')
                    field = change.get('field', 'category')
                    new_val = change.get('new_value', '')
                    reason = change.get('reason', '')
                    item = item_map.get(tid)
                    if item is None:
                        continue
                    old_val = repo.get_field_value(item, field) or ''
                    preview_items.append({
                        "target_id": tid,
                        "app_name": repo.get_display_name(item),
                        "field": field,
                        "old_value": old_val,
                        "new_value": new_val,
                        "reason": reason
                    })
                affected_count = len(preview_items)
            else:
                # 模型未返回结构化 changes（数据量过大时常见），本地启发式兜底
                preview_items = self._heuristic_reorganize(context_items, repo)
                affected_count = len(preview_items)
        
        elif action == 'add_remark':
            changes = params.get('changes', [])
            if changes:
                for change in changes:
                    tid = change.get('target_id')
                    field = change.get('field', 'ai_remark')
                    new_val = change.get('new_value', '')
                    item = item_map.get(tid)
                    if item is None:
                        continue
                    old_val = repo.get_field_value(item, field) or ''
                    preview_items.append({
                        "target_id": tid,
                        "app_name": repo.get_display_name(item),
                        "field": field,
                        "old_value": old_val,
                        "new_value": new_val
                    })
                affected_count = len(preview_items)
            else:
                target_ids = params.get('target_ids', [])
                remark = params.get('remark', '')
                for tid in target_ids:
                    item = item_map.get(tid)
                    if item is None:
                        continue
                    old_val = repo.get_field_value(item, 'ai_remark') or ''
                    preview_items.append({
                        "target_id": tid,
                        "app_name": repo.get_display_name(item),
                        "field": "ai_remark",
                        "old_value": old_val,
                        "new_value": remark
                    })
                affected_count = len(preview_items)
        
        elif action == 'delete':
            target_ids = params.get('target_ids', [])
            item_type = params.get('item_type', 'account')
            
            # 如果模型返回的是条件而非具体 ID
            if not target_ids and 'filter_conditions' in params:
                conditions = params['filter_conditions']
                target_ids = repo.resolve_filter_conditions(conditions)
                params['target_ids'] = target_ids  # 回写
            
            for tid in target_ids:
                item = item_map.get(tid)
                if item:
                    preview_items.append({
                        "target_id": tid,
                        "item_type": item_type,
                        "app_name": repo.get_display_name(item),
                        "username": repo.get_secondary_info(item),
                        "category": repo.get_field_value(item, 'category'),
                        "impact": f"将从{item_type}库中删除，移入回收站保留30天"
                    })
            affected_count = len(preview_items)
        
        elif action == 'add':
            fields = params.get('fields', {})
            item_type = params.get('item_type', 'account')
            preview_items.append({
                "type": "add",
                "item_type": item_type,
                "fields": fields,
                "impact": f"新增到{item_type}库"
            })
            affected_count = 1
        
        elif action in ('batch_add_account', 'batch_add_url'):
            raw_items = params.get('items', [])
            from services.batch_add_processor import BatchAddProcessor
            batch_items = BatchAddProcessor.prepare_batch_items(raw_items, repo)
            for bi in batch_items:
                preview_items.append({
                    "type": "batch_add",
                    "batch_item": bi,
                    "display_name": bi.app if action == 'batch_add_account' else bi.title,
                    "impact": f"新增到{'账号' if action == 'batch_add_account' else '网址'}库"
                })
            affected_count = len(batch_items)
        
        return {
            "success": True,
            "action": action,
            "preview_items": preview_items,
            "affected_count": affected_count,
            "action_type": action,
            "vault_type": vault_type,
            "message": f"操作预览：将影响 {affected_count} 个{item_type_name}，请确认后执行。"
        }
    
    def build_action_preview_from_tool_result(self, tool_result: ToolResult, tool: AITool) -> Dict:
        """
        将 Tool 返回的 preview_data 封装为 UI 可用的预览结构。

        做格式校验和默认值填充。
        """
        preview_data = tool_result.preview_data or {}

        # 校验必填字段
        if "operation_type" not in preview_data:
            preview_data["operation_type"] = "unknown"
        if "target_vault" not in preview_data:
            preview_data["target_vault"] = "unknown"
        if "total_items" not in preview_data:
            preview_data["total_items"] = 0
        if "items" not in preview_data or not isinstance(preview_data["items"], list):
            preview_data["items"] = []

        validated_items = []
        for item in preview_data["items"]:
            if not isinstance(item, dict):
                continue
            validated_item = {
                "row_id": str(item.get("row_id", "")),
                "display_name": item.get("display_name", "未命名"),
                "secondary_name": item.get("secondary_name", ""),
                "fields": item.get("fields", []) if isinstance(item.get("fields"), list) else [],
                "raw_data": item.get("raw_data", {}) if isinstance(item.get("raw_data"), dict) else {}
            }
            validated_items.append(validated_item)

        preview_data["items"] = validated_items
        preview_data["total_items"] = len(validated_items)

        return {
            "preview_data": preview_data,
            "tool_name": tool.name,
            "tool_description": tool.description,
            "permission": tool.permission.value if hasattr(tool.permission, 'value') else str(tool.permission),
            "message": tool_result.message or f"{tool.name} 操作预览",
            "success": tool_result.success
        }
    
    def execute_action(self, action: str, params: dict,
                        context_items: List[Any] = None,
                        vault_type: str = 'accounts',
                        mode: str = 'plan') -> Dict:
        """
        在本地执行 AI 建议的动作（不涉及敏感操作，敏感操作需弹窗确认）
        
        Args:
            action: 动作类型
            params: 动作参数
            context_items: 当前上下文条目列表
            vault_type: 'accounts' 或 'urls'
            mode: 'plan' 或 'build'
            
        Returns:
            执行结果
        """
        repo = RepositoryFactory.get_repository(vault_type)
        
        if context_items is None:
            context_items = repo.get_all()
        
        # Plan 模式：batch_add 特殊处理（解析后降级为 explain）
        if mode == 'plan' and action in ('batch_add_account', 'batch_add_url'):
            text = params.get('text', '')
            vault_type_for_batch = 'accounts' if action == 'batch_add_account' else 'urls'
            parsed_items = []
            failed_chunks = []
            if text:
                try:
                    from services.batch_add_processor import BatchAddProcessor
                    from ai.ollama_client import OllamaClient
                    from services.ai_service_manager import AIServiceManager
                    ai_manager = AIServiceManager.instance()
                    if ai_manager.is_available():
                        # TODO(P0-3): 迁移到 AIServiceManager.submit_task() 异步执行，避免主线程阻塞
                        ollama = OllamaClient(model=ai_manager.get_state().model_name or "gemma4:4b", timeout=300)
                        parsed_items, failed_chunks = BatchAddProcessor.parse_batch_text(text, vault_type_for_batch, ollama)
                except Exception:
                    logger.warning("批量添加文本解析失败", exc_info=True)
            if not parsed_items:
                parsed_items = params.get('items', [])
            
            item_names = [item.get('app') or item.get('title', '未知') for item in parsed_items]
            msg = f"解析到 {len(parsed_items)} 条待导入数据"
            if item_names:
                msg += "：" + "、".join(item_names)
            msg += "\n\n💡 切换到 Build 模式可执行导入。"
            
            return {
                "success": True,
                "action": "explain",
                "matched_accounts": [],
                "message": msg,
                "is_preview": False,
                "parsed_items": parsed_items,
                "failed_chunks": failed_chunks
            }
        
        # Plan 模式：拒绝写操作
        if mode == 'plan' and action not in self.READONLY_ACTIONS:
            return {
                "success": False,
                "action": action,
                "matched_accounts": [],
                "message": f"Plan 模式下不能执行写操作「{action}」，请切换到 Build 模式。",
                "is_preview": False
            }
        
        # Build 模式：写操作返回结构化预览
        if mode == 'build' and action in self.WRITE_ACTIONS:
            preview = self.build_action_preview(action, params, context_items, vault_type)
            preview['is_preview'] = True
            return preview
        
        result = {
            "success": True,
            "action": action,
            "matched_accounts": [],
            "message": "",
            "is_preview": False
        }
        
        if action == 'search':
            keywords = params.get('keywords', [])
            if isinstance(keywords, str):
                keywords = [keywords]
            keywords = [kw for kw in keywords if kw and str(kw).strip()]
            
            search_result = repo.search(keywords)
            result["matched_accounts"] = search_result.items
            result["matched_ids"] = search_result.matched_ids
            result["message"] = f"找到 {len(search_result.items)} 个匹配的{repo.get_item_type_name()}"
        
        elif action == 'filter':
            if 'category' in params:
                search_result = repo.filter_by_category(params['category'])
            elif 'tag' in params:
                search_result = repo.filter_by_tags(params['tag'])
            else:
                from core.repositories import SearchResult
                search_result = SearchResult(context_items, [i.id for i in context_items], "全部")
            
            result["matched_accounts"] = search_result.items
            result["matched_ids"] = search_result.matched_ids
            result["message"] = f"筛选出 {len(search_result.items)} 个{repo.get_item_type_name()}"
        
        elif action == 'get_category_tree':
            item_type = params.get('item_type', 'account')
            tree = self.tool_get_category_tree(item_type)
            if tree:
                tree_lines = []
                for k, v in tree.items():
                    if v:
                        tree_lines.append(f"• {k} → {', '.join(v)}")
                    else:
                        tree_lines.append(f"• {k}")
                result["message"] = f"当前{item_type}库分类树：\n" + "\n".join(tree_lines)
            else:
                result["message"] = "暂无分类"
        
        elif action == 'list':
            if params.get('scope') == 'uncategorized':
                search_result = repo.get_uncategorized()
            else:
                from core.repositories import SearchResult
                search_result = SearchResult(context_items, [i.id for i in context_items], "全部")
            
            result["matched_accounts"] = search_result.items
            result["matched_ids"] = search_result.matched_ids
            result["message"] = search_result.query_description
        
        elif action == 'reorganize':
            changes = params.get('changes', [])
            if changes:
                result["message"] = f"整理建议：共 {len(changes)} 条分类调整"
            else:
                suggestions = params.get('suggestions', [])
                result["message"] = "整理建议：" + '\n'.join(f"• {s}" for s in suggestions) if suggestions else "暂无具体建议"
        
        elif action == 'add_remark':
            target_ids = params.get('target_ids', [])
            remark = params.get('remark', '')
            result["message"] = f"建议给 {len(target_ids)} 个{repo.get_item_type_name()}添加备注：{remark}"
        
        else:  # explain
            result["message"] = params.get('response', '') or '已收到您的指令。'
        
        return result
    
    def execute_build_action_with_transaction(self, confirmed_items=None, tool_name=None, user_query="", _force=False):
        """
        Build 模式：在 SQLite 事务中批量执行写操作，并写入审计日志。

        兼容两种调用方式：
        1. 新签名：execute_build_action_with_transaction(confirmed_items, tool_name, user_query, _force)
        2. 旧签名：execute_build_action_with_transaction(action_preview: dict, user_query: str = "")
        """
        # 兼容旧签名
        if isinstance(confirmed_items, dict) and tool_name is None:
            return self._execute_build_action_with_transaction_legacy(confirmed_items, user_query)

        # 新签名逻辑
        if not confirmed_items:
            return {
                "success": False,
                "affected_count": 0,
                "affected_ids": [],
                "transaction_id": "",
                "error": "没有可执行的操作项"
            }

        transaction_id = str(uuid.uuid4())[:8]
        affected_ids = []
        error_msg = None
        fail_ids = []
        success = True
        result_msg = ""

        logger.info("execute_build_action_with_transaction starting, items=%d, tool=%s", len(confirmed_items), tool_name)

        def _do_batch_add(repo, items, vault_type):
            for item in items:
                if vault_type == 'accounts':
                    account = Account(**item)
                    new_id = repo.insert(account.to_dict())
                else:
                    url_item = URLItem(**item)
                    new_id = repo.insert(url_item.to_dict())
                affected_ids.append(new_id)

        def _do_batch_update(repo, items):
            for item in items:
                if 'updates' in item:
                    target_id = item.get('target_id')
                    for field, value in item['updates'].items():
                        repo.update_field(target_id, field, value)
                    affected_ids.append(target_id)
                elif 'field' in item and 'new_value' in item:
                    target_id = item.get('target_id')
                    repo.update_field(target_id, item['field'], item['new_value'])
                    affected_ids.append(target_id)
                elif 'remark_type' in item and 'content' in item:
                    target_id = item.get('target_id')
                    repo.update_field(target_id, item['remark_type'], item['content'])
                    affected_ids.append(target_id)
                elif 'tags' in item and 'mode' in item:
                    target_id = item.get('target_id')
                    existing = repo.get_by_id(target_id)
                    if existing:
                        old_tags = repo.get_field_value(existing, 'tags') or []
                        if not isinstance(old_tags, list):
                            try:
                                old_tags = json.loads(old_tags) if old_tags else []
                            except Exception:
                                old_tags = []
                        if item['mode'] == 'append':
                            new_tags = list(set(old_tags + item['tags']))
                        else:
                            new_tags = item['tags']
                        repo.update_field(target_id, 'tags', new_tags)
                    affected_ids.append(target_id)
                else:
                    target_id = item.get('target_id')
                    if target_id:
                        for field in ['category', 'remark', 'ai_remark', 'tags']:
                            if field in item:
                                repo.update_field(target_id, field, item[field])
                        affected_ids.append(target_id)

        def _do_batch_delete(items, is_account):
            for item in items:
                target_id = item.get('target_id')
                if is_account:
                    original = self.db.get_account_by_id(target_id)
                    if original:
                        self.db.soft_delete_account(target_id, original)
                else:
                    original = self.db.get_url_by_id(target_id)
                    if original:
                        if self.url_db:
                            self.url_db.soft_delete_url(target_id, original)
                        else:
                            self.db.soft_delete_url(target_id, original)
                affected_ids.append(target_id)

        try:
            if tool_name in ('batch_add_accounts', 'batch_add_urls'):
                vault_type = 'accounts' if tool_name == 'batch_add_accounts' else 'urls'
                repo = RepositoryFactory.get_repository(vault_type)
                tx_db = self.db if vault_type == 'accounts' else (self.url_db or self.db)
                with tx_db.transaction():
                    _do_batch_add(repo, confirmed_items, vault_type)
                success = True
                result_msg = f"批量导入完成：成功 {len(affected_ids)} 条"
                logger.info("Batch add completed, success=%d", len(affected_ids))

            elif tool_name in ('batch_update_accounts', 'batch_update_urls',
                               'batch_reorganize_accounts', 'batch_reorganize_urls',
                               'batch_add_remark_accounts', 'batch_add_remark_urls',
                               'batch_add_tags_accounts', 'batch_add_tags_urls',
                               'smart_classify_accounts', 'smart_classify_urls'):
                vault_type = 'accounts' if tool_name.endswith('_accounts') else 'urls'
                repo = RepositoryFactory.get_repository(vault_type)
                tx_db = self.db if vault_type == 'accounts' else (self.url_db or self.db)
                with tx_db.transaction():
                    _do_batch_update(repo, confirmed_items)
                success = True
                result_msg = f"批量更新完成：成功 {len(affected_ids)} 条"
                logger.info("Batch update completed, success=%d", len(affected_ids))

            elif tool_name in ('batch_delete_accounts', 'batch_delete_urls'):
                if len(confirmed_items) > 50 and not _force:
                    return {
                        "success": False,
                        "needs_confirmation": True,
                        "affected_count": len(confirmed_items),
                        "message": f"即将删除 {len(confirmed_items)} 条记录，数量较多，请确认",
                        "preview": {"items": confirmed_items}
                    }
                is_account = tool_name == 'batch_delete_accounts'
                tx_db = self.db if is_account else (self.url_db or self.db)
                with tx_db.transaction():
                    _do_batch_delete(confirmed_items, is_account)
                success = True
                result_msg = f"删除完成：成功 {len(affected_ids)} 条"
                logger.info("Delete completed, success=%d", len(affected_ids))

            else:
                return {
                    "success": False,
                    "affected_count": 0,
                    "affected_ids": [],
                    "transaction_id": "",
                    "error": f"不支持的 tool_name: {tool_name}"
                }
        except Exception as e:
            logger.exception("Transaction failed, all changes rolled back")
            success = False
            error_msg = str(e)
            result_msg = f"操作失败，已回滚：{e}"

        # try 块正常完成（无异常且已执行了某个分支）
        return {
            "success": success,
            "affected_count": len(affected_ids),
            "affected_ids": affected_ids,
            "transaction_id": transaction_id,
            "result_msg": result_msg,
            "error": error_msg or "",
            "fail_ids": fail_ids
        }

        # 写入审计日志
        try:
            self.db.insert_audit_log(
                mode='build',
                user_query=user_query,
                parsed_action=tool_name,
                parsed_params={"tool_name": tool_name, "count": len(confirmed_items)},
                affected_count=len(affected_ids),
                affected_ids=affected_ids,
                result=result_msg,
                error_message=error_msg,
                transaction_id=transaction_id
            )
        except Exception as e:
            logger.error("写入审计日志失败: %s", e)

        return {
            "success": success,
            "affected_count": len(affected_ids),
            "affected_ids": affected_ids,
            "transaction_id": transaction_id,
            "result_msg": result_msg,
            "error": error_msg or "",
            "fail_ids": fail_ids
        }

    def _execute_build_action_with_transaction_legacy(self, action_preview: dict, user_query: str = "") -> Dict:
        """
        旧版 execute_build_action_with_transaction 实现（兼容保留）。
        """
        preview_items = action_preview.get('preview_items', [])
        action_type = action_preview.get('action_type', '')
        vault_type = action_preview.get('vault_type', 'accounts')

        if action_type in ('reorganize', 'add_remark'):
            executable_items = [item for item in preview_items if 'target_id' in item and 'field' in item]
        elif action_type == 'delete':
            executable_items = [item for item in preview_items if 'target_id' in item and 'item_type' in item]
        elif action_type == 'add':
            executable_items = [item for item in preview_items if item.get('type') == 'add']
        elif action_type in ('batch_add_account', 'batch_add_url'):
            executable_items = [item for item in preview_items if item.get('type') == 'batch_add']
        else:
            executable_items = []

        if not executable_items:
            return {
                "success": False,
                "affected_count": 0,
                "affected_ids": [],
                "transaction_id": "",
                "error": "没有可执行的操作项"
            }

        transaction_id = str(uuid.uuid4())[:8]
        affected_ids = []
        error_msg = None
        fail_ids = []
        success = True
        result_msg = ""

        if action_type == 'delete' and not action_preview.get('_force'):
            target_ids = [item['target_id'] for item in executable_items]
            if len(target_ids) > 50:
                return {
                    "success": False,
                    "needs_confirmation": True,
                    "affected_count": len(target_ids),
                    "message": f"即将删除 {len(target_ids)} 条记录，数量较多，请确认",
                    "preview": action_preview
                }

        tx_db = self.db if vault_type == 'accounts' else (self.url_db or self.db)

        logger.info("execute_build_action_with_transaction starting, items=%d, vault=%s", len(executable_items), vault_type)

        try:
            with tx_db.transaction():
                if action_type == 'delete':
                    for item in executable_items:
                        target_id = item['target_id']
                        item_vault_type = 'urls' if item.get('item_type') == 'url' else 'accounts'
                        try:
                            repo = RepositoryFactory.get_repository(item_vault_type)
                            repo.soft_delete(target_id)
                            affected_ids.append(target_id)
                        except Exception as e:
                            fail_ids.append((target_id, str(e)))

                    success = len(fail_ids) == 0
                    result_msg = f"删除完成：成功 {len(affected_ids)} 条" + (f"，失败 {len(fail_ids)} 条" if fail_ids else "")
                    logger.info("Delete completed, success=%d, fail=%d", len(affected_ids), len(fail_ids))
                elif action_type in ('batch_add_account', 'batch_add_url'):
                    repo = RepositoryFactory.get_repository(vault_type)
                    from services.batch_add_processor import BatchAddProcessor
                    batch_items = [item['batch_item'] for item in executable_items]
                    batch_result = BatchAddProcessor.execute_batch_add(batch_items, repo)
                    affected_ids = batch_result.get('inserted_ids', [])
                    success = batch_result.get('success', 0) > 0 or len(affected_ids) > 0
                    result_msg = f"批量导入完成：成功 {batch_result.get('success', 0)} 条，跳过 {batch_result.get('skip', 0)} 条，失败 {batch_result.get('fail', 0)} 条"
                    logger.info("Batch add completed, success=%s", batch_result.get('success', 0))
                else:
                    repo = RepositoryFactory.get_repository(vault_type)
                    item_type_name = repo.get_item_type_name()

                    for item in executable_items:
                        try:
                            if action_type in ('reorganize', 'add_remark'):
                                target_id = item['target_id']
                                field = item['field']
                                new_value = item['new_value']
                                logger.debug("UPDATE id=%s, field=%s, new_value=%s", target_id, field, new_value)
                                repo.update_field(target_id, field, new_value)
                                affected_ids.append(target_id)

                            elif action_type == 'add':
                                fields = item['fields']
                                new_id = repo.insert(fields)
                                affected_ids.append(new_id)

                        except Exception as e:
                            tid = item.get('target_id', item.get('fields', {}).get('app_name', 'unknown'))
                            logger.exception("Item execution failed: %s, error=%s", tid, e)
                            fail_ids.append((tid, str(e)))

                    success = len(fail_ids) == 0
                    result_msg = f"成功执行 {action_type}，共影响 {len(affected_ids)} 个{item_type_name}"
                    if fail_ids:
                        result_msg += f"，失败 {len(fail_ids)} 条"
                    logger.info("Execution completed, success=%d, fail=%d", len(affected_ids), len(fail_ids))
        except Exception as e:
            logger.exception("Transaction failed, all changes rolled back")
            success = False
            error_msg = str(e)
            result_msg = f"操作失败，已回滚：{e}"

        # 写入审计日志
        try:
            self.db.insert_audit_log(
                mode='build',
                user_query=user_query,
                parsed_action=action_type,
                parsed_params=action_preview,
                affected_count=len(affected_ids),
                affected_ids=affected_ids,
                result=result_msg,
                error_message=error_msg,
                transaction_id=transaction_id
            )
        except Exception as e:
            logger.error("写入审计日志失败: %s", e)

        return {
            "success": success,
            "affected_count": len(affected_ids),
            "affected_ids": affected_ids,
            "transaction_id": transaction_id,
            "result_msg": result_msg,
            "error": error_msg or "",
            "fail_ids": fail_ids
        }
