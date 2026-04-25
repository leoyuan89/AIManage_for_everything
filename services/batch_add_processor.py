"""
批量导入处理器
负责：文本分块、AI 解析、去重预检、执行导入
"""
import json
import re
from typing import List, Dict, Tuple, Optional

from core.repositories import BatchItem, VaultRepository


class BatchAddProcessor:
    """批量导入处理器"""

    MAX_BATCH_CHARS = 4000
    MAX_BATCH_ITEMS = 20

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """估算文本所需的 token 数量"""
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        en_words = len(re.findall(r'[a-zA-Z]+', text))
        return int(cn_chars * 1.5 + en_words * 1.2)

    @classmethod
    def chunk_text(cls, text: str) -> List[str]:
        """将长文本按字符数和条目数上限切割为多个块"""
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        chunks = []
        current_chunk = []
        current_chars = 0
        current_items = 0

        for line in lines:
            line_chars = len(line)
            if (current_chars + line_chars > cls.MAX_BATCH_CHARS or
                    current_items >= cls.MAX_BATCH_ITEMS):
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_chars = line_chars
                current_items = 1
            else:
                current_chunk.append(line)
                current_chars += line_chars
                current_items += 1

        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        return chunks

    @classmethod
    def parse_batch_text(cls, text: str, vault_type: str, ollama_client) -> Tuple[List[Dict], List[Tuple]]:
        """
        解析批量导入文本，返回 (解析出的原始条目列表, 失败的块信息列表)

        Args:
            text: 用户输入的批量文本
            vault_type: 'accounts' 或 'urls'
            ollama_client: OllamaClient 实例

        Returns:
            (items_list, failed_chunks)
            failed_chunks 每项为 (chunk_index, chunk_preview, error_message)
        """
        chunks = cls.chunk_text(text)
        all_items = []
        failed_chunks = []

        for idx, chunk in enumerate(chunks):
            prompt = cls._build_batch_prompt(chunk, vault_type)
            try:
                raw = ollama_client.generate(prompt, temperature=0.1, num_predict=2000)
                items = cls._parse_json_response(raw)
                all_items.extend(items)
            except Exception as e:
                failed_chunks.append((idx, chunk[:200], str(e)))

        return all_items, failed_chunks

    @classmethod
    def _build_batch_prompt(cls, text_chunk: str, vault_type: str) -> str:
        """构建批量解析 Prompt"""
        if vault_type == 'accounts':
            return cls._build_account_prompt(text_chunk)
        else:
            return cls._build_url_prompt(text_chunk)

    @classmethod
    def _build_account_prompt(cls, text_chunk: str) -> str:
        return f"""你是一款密码管理软件的AI助手。用户想要批量导入账号信息。
请从以下文本中提取账号信息，并输出为JSON数组格式。

文本内容：
{text_chunk}

请输出严格符合以下格式的JSON数组（不要包含任何其他说明文字）：
[
  {{
    "app": "应用名称",
    "account": "账号",
    "password": "密码",
    "url": "相关网址（可选）",
    "category": "分类（可选，如金融/社交/工作等）",
    "remark": "备注（可选）",
    "tags": ["标签1", "标签2"]
  }}
]

规则：
1. 必须返回合法的JSON数组
2. 如果文本中没有账号信息，返回空数组 []
3. 不要添加任何解释、markdown代码块标记或其他文字
4. 分类字段如果用户未提供，留空字符串或省略
5. 标签字段如果用户未提供，返回空数组 []
"""

    @classmethod
    def _build_url_prompt(cls, text_chunk: str) -> str:
        return f"""你是一款密码管理软件的AI助手。用户想要批量导入网址信息。
请从以下文本中提取网址信息，并输出为JSON数组格式。

文本内容：
{text_chunk}

请输出严格符合以下格式的JSON数组（不要包含任何其他说明文字）：
[
  {{
    "title": "网址标题",
    "url": "网址链接",
    "category": "分类（可选，如开发工具/学习资源等）",
    "tags": ["标签1", "标签2"],
    "remark": "备注（可选）",
    "ai_remark": "AI备注（可选）"
  }}
]

规则：
1. 必须返回合法的JSON数组
2. 如果文本中没有网址信息，返回空数组 []
3. 不要添加任何解释、markdown代码块标记或其他文字
4. 分类字段如果用户未提供，留空字符串或省略
5. 标签字段如果用户未提供，返回空数组 []
"""

    @classmethod
    def _parse_json_response(cls, raw: str) -> List[Dict]:
        """从模型响应中解析 JSON 数组"""
        text = raw.strip()
        # 去除 markdown 代码块
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()

        data = json.loads(text)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # 尝试从常见键中提取
            for key in ('items', 'data', 'results', 'urls', 'accounts'):
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data] if data else []
        return []

    @classmethod
    def prepare_batch_items(cls, parsed_items: List[Dict], repo: VaultRepository) -> List[BatchItem]:
        """
        将解析后的原始字典转换为 BatchItem，并进行预检（去重、分类校验等）。
        """
        result = []
        for item in parsed_items:
            batch_item = cls._dict_to_batch_item(item, repo)
            status, confirmed = cls._check_item_status(batch_item, repo)
            batch_item.status = status
            batch_item.confirmed = confirmed
            result.append(batch_item)
        return result

    @classmethod
    def _dict_to_batch_item(cls, item: Dict, repo: VaultRepository) -> BatchItem:
        """将原始字典转换为 BatchItem"""
        if repo.get_item_type_name() == "网址":
            return BatchItem(
                app="",
                account="",
                password="",
                url=item.get('url', ''),
                title=item.get('title', ''),
                category=item.get('category', '其他') or '其他',
                tags=item.get('tags', []) or [],
                remark=item.get('remark', ''),
                ai_remark=item.get('ai_remark', ''),
                raw_data=dict(item)
            )
        else:
            return BatchItem(
                app=item.get('app', ''),
                account=item.get('account', ''),
                password=item.get('password', ''),
                url=item.get('url', ''),
                title="",
                category=item.get('category', '其他') or '其他',
                tags=item.get('tags', []) or [],
                remark=item.get('remark', ''),
                ai_remark=item.get('ai_remark', ''),
                raw_data=dict(item)
            )

    @classmethod
    def _check_item_status(cls, item: BatchItem, repo: VaultRepository) -> Tuple[str, bool]:
        """
        检查单个条目的状态，返回 (状态描述, 是否默认勾选)
        """
        # 1. 必填字段检查
        if repo.get_item_type_name() == "网址":
            if not item.url:
                return "格式错误：URL 缺失", False
            if not item.title:
                return "格式错误：标题缺失", False
        else:
            if not item.app:
                return "格式错误：应用名缺失", False

        # 2. 重复检查
        item_data = dict(item.raw_data) if item.raw_data else {}
        if repo.get_item_type_name() == "网址":
            item_data['url'] = item.url
            item_data['title'] = item.title
        else:
            item_data['app'] = item.app
            item_data['account'] = item.account

        existing = repo.check_duplicate(item_data)
        if existing:
            return f"重复：已存在 ID={existing.id}", False

        # 3. 分类检查
        category = item.category or '其他'
        valid_categories = repo.get_categories()
        if category not in valid_categories:
            item.category = '其他'
            return f"分类'{category}'不存在，已归入'其他'", True

        return "就绪", True

    @classmethod
    def _batch_item_to_dict(cls, item: BatchItem, repo: VaultRepository) -> Dict:
        """将 BatchItem 转换为可插入的字典"""
        if repo.get_item_type_name() == "网址":
            return {
                'title': item.title,
                'url': item.url,
                'category': item.category,
                'tags': item.tags,
                'remark': item.remark,
                'ai_remark': item.ai_remark
            }
        else:
            return {
                'app': item.app,
                'account': item.account,
                'password': item.password,
                'url': item.url,
                'category': item.category,
                'remark': item.remark,
                'tags': item.tags,
                'ai_remark': item.ai_remark
            }

    @classmethod
    def _execute_batch_add(cls, items: List[BatchItem], repo: VaultRepository) -> Dict:
        """逐条独立导入"""
        success_count = 0
        skip_count = 0
        fail_count = 0
        fail_details = []
        inserted_ids = []

        for item in items:
            if not item.confirmed:
                skip_count += 1
                continue

            try:
                item_data = cls._batch_item_to_dict(item, repo)
                new_id = repo.insert(item_data)
                success_count += 1
                inserted_ids.append(new_id)
            except Exception as e:
                fail_count += 1
                fail_details.append({'item': item.raw_data, 'error': str(e)})

        return {
            'success': success_count,
            'skip': skip_count,
            'fail': fail_count,
            'fail_details': fail_details,
            'inserted_ids': inserted_ids
        }

    @classmethod
    def execute_batch_add(cls, batch_items: List[BatchItem], repo: VaultRepository) -> Dict:
        """公开接口：执行批量导入"""
        return cls._execute_batch_add(batch_items, repo)
