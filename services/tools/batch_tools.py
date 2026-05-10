"""
批量操作类工具 — 批量新增、更新、重组、添加备注/标签、删除账号和网址
"""
from .base import AITool, ToolRegistry, ToolResult, PermissionLevel

_BATCH_ADD_ACCOUNT_SCHEMA = {
    "items": {
        "type": "array",
        "description": "待添加的账号列表。你需要自行从用户输入中提取各字段，格式不固定时按语义推断。",
        "items": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "应用名称/网站名称。通常是用户输入的第一个词或最显眼的名称，如'专利'、'B站'、'学工系统'"},
                "username": {"type": "string", "description": "用户名/账号。看起来像手机号、邮箱、学号、QQ号等的字符串。如'13959106910'、'abc@qq.com'、'2023001'"},
                "password": {"type": "string", "description": "密码。紧跟在'密码'、'pwd'等词后面的内容，或看起来像密码的字符串"},
                "url": {"type": "string", "description": "网址。以http://或https://开头的链接。如果没有协议头但有域名，补全为https://。如'https://pss-system.cponline.cnipa.gov.cn'"},
                "category": {"type": "string", "description": "分类。根据应用名/网址推测最合适的分类，如学术网站→'学术与研究'，银行→'金融与支付'，学校系统→'青岛大学'"},
                "remark": {"type": "string", "description": "备注。用户额外说明的信息，没有则留空字符串"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表。没有则留空数组[]"}
            }
        }
    }
}

_BATCH_ADD_URL_SCHEMA = {
    "items": {
        "type": "array",
        "description": "待添加的网址列表",
        "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "网址标题/名称。如'GitHub'、'百度'"},
                "url": {"type": "string", "description": "网址链接。以http://或https://开头"},
                "category": {"type": "string", "description": "分类。根据网址内容推测最合适的分类"},
                "remark": {"type": "string", "description": "备注。没有则留空"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表。没有则留空数组[]"}
            }
        }
    }
}


@ToolRegistry.register(
    name="batch_add_accounts",
    description="批量添加账号到密码库",
    permission=PermissionLevel.PREVIEW,
    params_schema=_BATCH_ADD_ACCOUNT_SCHEMA
)
class BatchAddAccountsTool(AITool):
    def execute(self, params, context):
        items = params.get("items", [])
        preview_items = []
        for idx, item in enumerate(items):
            tags = item.get("tags", [])
            tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
            fields = [
                {"field_name": "应用名", "old_value": "-", "new_value": item.get("app_name", "")},
                {"field_name": "用户名", "old_value": "-", "new_value": item.get("username", "")},
                {"field_name": "密码", "old_value": "-", "new_value": item.get("password", "")},
                {"field_name": "分类", "old_value": "-", "new_value": item.get("category", "其他")},
                {"field_name": "备注", "old_value": "-", "new_value": item.get("remark", "")},
                {"field_name": "标签", "old_value": "-", "new_value": tags_str},
            ]
            preview_items.append(self._make_preview_item(
                row_id=f"new_{idx}",
                display_name=item.get("app_name", "未命名"),
                secondary_name=item.get("username", ""),
                fields=fields,
                raw_data=item
            ))
        preview = self._make_preview("add", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(items)},
            message=f"待添加 {len(items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="batch_add_urls",
    description="批量添加网址到网址库",
    permission=PermissionLevel.PREVIEW,
    params_schema=_BATCH_ADD_URL_SCHEMA
)
class BatchAddUrlsTool(AITool):
    def execute(self, params, context):
        items = params.get("items", [])
        preview_items = []
        for idx, item in enumerate(items):
            tags = item.get("tags", [])
            tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
            fields = [
                {"field_name": "标题", "old_value": "-", "new_value": item.get("title", "")},
                {"field_name": "URL", "old_value": "-", "new_value": item.get("url", "")},
                {"field_name": "分类", "old_value": "-", "new_value": item.get("category", "其他")},
                {"field_name": "备注", "old_value": "-", "new_value": item.get("remark", "")},
                {"field_name": "标签", "old_value": "-", "new_value": tags_str},
            ]
            preview_items.append(self._make_preview_item(
                row_id=f"new_{idx}",
                display_name=item.get("title", "未命名"),
                secondary_name=item.get("url", ""),
                fields=fields,
                raw_data=item
            ))
        preview = self._make_preview("add", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(items)},
            message=f"待添加 {len(items)} 个网址，请确认"
        )


@ToolRegistry.register(
    name="batch_update_accounts",
    description="批量更新账号指定字段",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标账号ID列表"},
        "updates": {"type": "object", "description": "字段更新映射，如 {'category': '工作>开发工具'}"}
    }
)
class BatchUpdateAccountsTool(AITool):
    def execute(self, params, context):
        target_ids = params.get("target_ids", [])
        updates = params.get("updates", {})
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            fields = []
            for field, new_value in updates.items():
                old_value = self._get_field_value_safe(item, field, repo)
                fields.append({"field_name": field, "old_value": old_value, "new_value": str(new_value)})
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=fields,
                raw_data={"target_id": tid, "updates": updates}
            ))
        preview = self._make_preview("update", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待更新 {len(preview_items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="batch_update_urls",
    description="批量更新网址指定字段",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标网址ID列表"},
        "updates": {"type": "object", "description": "字段更新映射，如 {'category': '工作>开发工具'}"}
    }
)
class BatchUpdateUrlsTool(AITool):
    def execute(self, params, context):
        target_ids = params.get("target_ids", [])
        updates = params.get("updates", {})
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            fields = []
            for field, new_value in updates.items():
                old_value = self._get_field_value_safe(item, field, repo)
                fields.append({"field_name": field, "old_value": old_value, "new_value": str(new_value)})
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=fields,
                raw_data={"target_id": tid, "updates": updates}
            ))
        preview = self._make_preview("update", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待更新 {len(preview_items)} 个网址，请确认"
        )


@ToolRegistry.register(
    name="batch_reorganize_accounts",
    description="批量重组整理账号（智能调整分类、标签等）",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "changes": {
            "type": "array",
            "description": "变更列表",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "integer"},
                    "field": {"type": "string"},
                    "new_value": {"type": "string"}
                }
            }
        }
    }
)
class BatchReorganizeAccountsTool(AITool):
    def execute(self, params, context):
        changes = params.get("changes", [])
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for ch in changes:
            tid = ch.get("target_id")
            field = ch.get("field", "category")
            new_value = ch.get("new_value", "")
            item = item_map.get(tid)
            if not item:
                continue
            old_value = self._get_field_value_safe(item, field, repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": field, "old_value": old_value, "new_value": str(new_value)}],
                raw_data=ch
            ))
        preview = self._make_preview("reorganize", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待重组 {len(preview_items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="batch_reorganize_urls",
    description="批量重组整理网址（智能调整分类、标签等）",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "changes": {
            "type": "array",
            "description": "变更列表",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "integer"},
                    "field": {"type": "string"},
                    "new_value": {"type": "string"}
                }
            }
        }
    }
)
class BatchReorganizeUrlsTool(AITool):
    def execute(self, params, context):
        changes = params.get("changes", [])
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for ch in changes:
            tid = ch.get("target_id")
            field = ch.get("field", "category")
            new_value = ch.get("new_value", "")
            item = item_map.get(tid)
            if not item:
                continue
            old_value = self._get_field_value_safe(item, field, repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": field, "old_value": old_value, "new_value": str(new_value)}],
                raw_data=ch
            ))
        preview = self._make_preview("reorganize", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待重组 {len(preview_items)} 个网址，请确认"
        )


@ToolRegistry.register(
    name="batch_add_remark_accounts",
    description="批量为账号添加备注。支持为每个账号指定不同的备注内容，changes 数组中每个元素包含 target_id 和 content",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "changes": {
            "type": "array",
            "description": "每个账号的备注内容列表，每个元素包含 target_id 和专属的 content",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "integer", "description": "目标账号ID"},
                    "content": {"type": "string", "description": "该账号的专属备注内容"}
                }
            }
        },
        "remark_type": {"type": "string", "enum": ["ai_remark", "remark"], "description": "备注类型，默认 ai_remark"}
    }
)
class BatchAddRemarkAccountsTool(AITool):
    def execute(self, params, context):
        changes = params.get("changes", [])
        remark_type = params.get("remark_type", "ai_remark")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for ch in changes:
            tid = ch.get("target_id")
            content = ch.get("content", "")
            item = item_map.get(tid)
            if not item:
                continue
            old_value = self._get_field_value_safe(item, remark_type, repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": remark_type, "old_value": old_value, "new_value": content}],
                raw_data={"target_id": tid, "remark_type": remark_type, "content": content}
            ))
        preview = self._make_preview("update", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待为 {len(preview_items)} 个账号添加备注，请确认"
        )


@ToolRegistry.register(
    name="batch_add_remark_urls",
    description="批量为网址添加备注。支持为每个网址指定不同的备注内容，changes 数组中每个元素包含 target_id 和 content",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "changes": {
            "type": "array",
            "description": "每个网址的备注内容列表，每个元素包含 target_id 和专属的 content",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "integer", "description": "目标网址ID"},
                    "content": {"type": "string", "description": "该网址的专属备注内容"}
                }
            }
        },
        "remark_type": {"type": "string", "enum": ["ai_remark", "remark"], "description": "备注类型，默认 ai_remark"}
    }
)
class BatchAddRemarkUrlsTool(AITool):
    def execute(self, params, context):
        changes = params.get("changes", [])
        remark_type = params.get("remark_type", "ai_remark")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for ch in changes:
            tid = ch.get("target_id")
            content = ch.get("content", "")
            item = item_map.get(tid)
            if not item:
                continue
            old_value = self._get_field_value_safe(item, remark_type, repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": remark_type, "old_value": old_value, "new_value": content}],
                raw_data={"target_id": tid, "remark_type": remark_type, "content": content}
            ))
        preview = self._make_preview("update", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待为 {len(preview_items)} 个网址添加备注，请确认"
        )


@ToolRegistry.register(
    name="batch_add_tags_accounts",
    description="批量为账号添加标签",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标账号ID列表"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
        "mode": {"type": "string", "enum": ["append", "replace"], "description": "添加模式：追加或替换"}
    }
)
class BatchAddTagsAccountsTool(AITool):
    def execute(self, params, context):
        target_ids = params.get("target_ids", [])
        tags = params.get("tags", [])
        mode = params.get("mode", "append")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            old_tags = self._get_field_value_safe(item, "tags", repo)
            if isinstance(old_tags, list):
                old_tags_str = ",".join(old_tags)
            else:
                old_tags_str = str(old_tags) if old_tags else ""
            if mode == "append" and old_tags_str:
                new_tags_str = old_tags_str + "," + ",".join(tags) if tags else old_tags_str
            else:
                new_tags_str = ",".join(tags)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": "tags", "old_value": old_tags_str, "new_value": new_tags_str}],
                raw_data={"target_id": tid, "tags": tags, "mode": mode}
            ))
        preview = self._make_preview("update", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待为 {len(preview_items)} 个账号{mode}标签，请确认"
        )


@ToolRegistry.register(
    name="batch_add_tags_urls",
    description="批量为网址添加标签",
    permission=PermissionLevel.PREVIEW,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "目标网址ID列表"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
        "mode": {"type": "string", "enum": ["append", "replace"], "description": "添加模式：追加或替换"}
    }
)
class BatchAddTagsUrlsTool(AITool):
    def execute(self, params, context):
        target_ids = params.get("target_ids", [])
        tags = params.get("tags", [])
        mode = params.get("mode", "append")
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            old_tags = self._get_field_value_safe(item, "tags", repo)
            if isinstance(old_tags, list):
                old_tags_str = ",".join(old_tags)
            else:
                old_tags_str = str(old_tags) if old_tags else ""
            if mode == "append" and old_tags_str:
                new_tags_str = old_tags_str + "," + ",".join(tags) if tags else old_tags_str
            else:
                new_tags_str = ",".join(tags)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=self._get_display_name_safe(item, repo),
                secondary_name=self._get_secondary_info_safe(item, repo),
                fields=[{"field_name": "tags", "old_value": old_tags_str, "new_value": new_tags_str}],
                raw_data={"target_id": tid, "tags": tags, "mode": mode}
            ))
        preview = self._make_preview("update", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待为 {len(preview_items)} 个网址{mode}标签，请确认"
        )


@ToolRegistry.register(
    name="batch_delete_accounts",
    description="批量删除账号（移入回收站）",
    permission=PermissionLevel.CONFIRM,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "待删除账号ID列表"}
    }
)
class BatchDeleteAccountsTool(AITool):
    def execute(self, params, context):
        target_ids = params.get("target_ids", [])
        repo = context.get("repo")
        item_map = self._get_item_map(context, "accounts")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            display = self._get_display_name_safe(item, repo)
            secondary = self._get_secondary_info_safe(item, repo)
            category = self._get_field_value_safe(item, "category", repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=display,
                secondary_name=secondary,
                fields=[
                    {"field_name": "应用名", "old_value": display, "new_value": "移入回收站"},
                    {"field_name": "分类", "old_value": category, "new_value": "移入回收站"},
                ],
                raw_data={"target_id": tid, "item_type": "account"}
            ))
        preview = self._make_preview("delete", "account", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待删除 {len(preview_items)} 个账号，请确认"
        )


@ToolRegistry.register(
    name="batch_delete_urls",
    description="批量删除网址（移入回收站）",
    permission=PermissionLevel.CONFIRM,
    params_schema={
        "target_ids": {"type": "array", "items": {"type": "integer"}, "description": "待删除网址ID列表"}
    }
)
class BatchDeleteUrlsTool(AITool):
    def execute(self, params, context):
        target_ids = params.get("target_ids", [])
        repo = context.get("repo")
        item_map = self._get_item_map(context, "urls")
        preview_items = []
        for tid in target_ids:
            item = item_map.get(tid)
            if not item:
                continue
            display = self._get_display_name_safe(item, repo)
            secondary = self._get_secondary_info_safe(item, repo)
            category = self._get_field_value_safe(item, "category", repo)
            preview_items.append(self._make_preview_item(
                row_id=str(tid),
                display_name=display,
                secondary_name=secondary,
                fields=[
                    {"field_name": "标题", "old_value": display, "new_value": "移入回收站"},
                    {"field_name": "分类", "old_value": category, "new_value": "移入回收站"},
                ],
                raw_data={"target_id": tid, "item_type": "url"}
            ))
        preview = self._make_preview("delete", "url", preview_items)
        return ToolResult(
            success=True,
            preview_data=preview,
            data={"count": len(preview_items)},
            message=f"待删除 {len(preview_items)} 个网址，请确认"
        )
