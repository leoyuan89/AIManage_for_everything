"""
语义搜索服务 [DEPRECATED / 已废弃]

⚠️ 警告：本模块基于 /api/embeddings API，但当前使用的 gemma4:4b 模型不支持该 API。
因此本服务已被废弃，不再推荐使用。

替代方案：
- 精确搜索请使用 services/search_service.py 的 SearchService
- AI 语义匹配请使用 ai/ollama_client.py 的 semantic_match()（基于 /api/generate 的文本推理）

保留本文件仅用于历史兼容，请勿在新代码中引用 SemanticSearchService。
"""
import logging
import json
import numpy as np
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from pathlib import Path

from models.account import Account
from models.url_item import URLItem
from ai.ollama_client import OllamaClient
from core.constants import DATA_DIR


@dataclass
class SemanticSearchResult:
    """语义搜索结果"""
    item_id: int
    item_type: str  # 'account' 或 'url'
    item_name: str
    similarity: float  # 余弦相似度
    is_ai_recommended: bool = False  # 是否AI推荐
    ai_reason: str = ""  # AI推荐理由


class SemanticSearchService:
    """语义搜索服务"""
    
    def __init__(self, ollama_client: Optional[OllamaClient] = None, 
                 data_dir: str = None):
        self.ollama = ollama_client
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.data_dir.mkdir(exist_ok=True)
        
        # 向量索引文件
        self.account_vectors_file = self.data_dir / 'account_vectors.json'
        self.url_vectors_file = self.data_dir / 'url_vectors.json'
        
        # 向量索引缓存
        self._account_vectors: Dict[int, np.ndarray] = {}
        self._url_vectors: Dict[int, np.ndarray] = {}
        self._account_texts: Dict[int, str] = {}
        self._url_texts: Dict[int, str] = {}
        
        # Embeddings API 可用性标志（检测失败后不再重试，避免刷屏）
        self._embeddings_available: Optional[bool] = None
        self._embeddings_error_count: int = 0
        self._max_embedding_errors: int = 3
        
        # 加载已有索引
        self._load_vectors()
    
    def build_account_index(self, accounts: List[Account]):
        """构建账号向量索引"""
        if not self.ollama or not self.ollama.is_available():
            return
        
        # 快速检测：如果 embeddings API 已被标记不可用，直接跳过
        if self._embeddings_available is False:
            return
        
        # 先做一次探测，确认 embeddings API 是否支持当前模型
        if self._embeddings_available is None:
            test_vector = self._get_embedding("test")
            if self._embeddings_available is False:
                logger.warning("Embeddings API probe failed, skipping index build.")
                return
        
        self._account_vectors.clear()
        self._account_texts.clear()
        
        for account in accounts:
            # 如果 embeddings 已被标记不可用，提前退出
            if self._embeddings_available is False:
                break
            
            text = self._build_account_text(account)
            vector = self._get_embedding(text)
            if vector is not None:
                self._account_vectors[account.id] = vector
                self._account_texts[account.id] = text
        
        self._save_vectors('account')
    
    def build_url_index(self, urls: List[URLItem]):
        """构建网址向量索引"""
        if not self.ollama or not self.ollama.is_available():
            return
        
        if self._embeddings_available is False:
            return
        
        if self._embeddings_available is None:
            test_vector = self._get_embedding("test")
            if self._embeddings_available is False:
                return
        
        self._url_vectors.clear()
        self._url_texts.clear()
        
        for url in urls:
            if self._embeddings_available is False:
                break
            
            text = self._build_url_text(url)
            vector = self._get_embedding(text)
            if vector is not None:
                self._url_vectors[url.id] = vector
                self._url_texts[url.id] = text
        
        self._save_vectors('url')
    
    def search_accounts(self, query: str, top_k: int = 10) -> List[SemanticSearchResult]:
        """
        搜索账号（语义相似度）
        
        Args:
            query: 查询文本
            top_k: 返回结果数
            
        Returns:
            语义搜索结果列表
        """
        if not self._account_vectors:
            return []
        
        query_vector = self._get_embedding(query)
        if query_vector is None:
            return []
        
        results = []
        for item_id, vector in self._account_vectors.items():
            similarity = self._cosine_similarity(query_vector, vector)
            if similarity > 0.5:  # 相似度阈值
                name = self._account_texts.get(item_id, '')
                # 提取应用名（第一个|前的内容）
                app_name = name.split('|')[0] if '|' in name else name
                results.append(SemanticSearchResult(
                    item_id=item_id,
                    item_type='account',
                    item_name=app_name,
                    similarity=similarity
                ))
        
        # 按相似度排序
        results.sort(key=lambda x: x.similarity, reverse=True)
        return results[:top_k]
    
    def search_urls(self, query: str, top_k: int = 10) -> List[SemanticSearchResult]:
        """搜索网址（语义相似度）"""
        if not self._url_vectors:
            return []
        
        query_vector = self._get_embedding(query)
        if query_vector is None:
            return []
        
        results = []
        for item_id, vector in self._url_vectors.items():
            similarity = self._cosine_similarity(query_vector, vector)
            if similarity > 0.5:
                name = self._url_texts.get(item_id, '')
                title = name.split('|')[0] if '|' in name else name
                results.append(SemanticSearchResult(
                    item_id=item_id,
                    item_type='url',
                    item_name=title,
                    similarity=similarity
                ))
        
        results.sort(key=lambda x: x.similarity, reverse=True)
        return results[:top_k]
    
    def ai_enhanced_search(self, query: str, accounts: List[Account] = None,
                          urls: List[URLItem] = None, top_k: int = 10) -> Tuple[List[SemanticSearchResult], List[SemanticSearchResult]]:
        """
        大模型增强搜索
        
        Args:
            query: 查询文本
            accounts: 账号列表（用于AI推理）
            urls: 网址列表
            top_k: 返回数量
            
        Returns:
            (account_results, url_results)
        """
        # 先进行向量语义搜索
        account_results = self.search_accounts(query, top_k * 2) if accounts else []
        url_results = self.search_urls(query, top_k * 2) if urls else []
        
        if not self.ollama or not self.ollama.is_available():
            return account_results[:top_k], url_results[:top_k]
        
        # 大模型意图解析与扩展
        try:
            # 构建条目列表文本
            items_text = []
            if accounts:
                for acc in accounts:  # 完整保留所有条目
                    items_text.append(f"账号:{acc.app_name} 分类:{acc.category}")
            if urls:
                for url in urls:
                    items_text.append(f"网址:{url.title} 分类:{url.category}")
            
            items_str = '\n'.join(items_text)
            prompt = f"""用户搜索："{query}"

软件中存储的条目：
{items_str}

请分析用户搜索意图，从列表中找出最相关的条目。
输出JSON格式：
{{
  "related_items": [
    {{
      "name": "条目名称",
      "type": "account|url",
      "reason": "推荐理由"
    }}
  ],
  "expanded_queries": ["扩展词1", "扩展词2"]
}}

要求：
1. 只返回JSON
2. reason简要说明匹配原因"""
            
            result = self.ollama.generate(prompt, temperature=0.2)
            json_str = self._extract_json(result)
            data = json.loads(json_str)
            
            # 将AI推荐结果融入向量搜索结果
            ai_items = {item['name']: item for item in data.get('related_items', [])}
            
            # 标记AI推荐
            for result in account_results:
                if result.item_name in ai_items:
                    result.is_ai_recommended = True
                    result.ai_reason = ai_items[result.item_name].get('reason', '')
                    result.similarity = max(result.similarity, 0.9)  # 提升AI推荐项的排序
            
            for result in url_results:
                if result.item_name in ai_items:
                    result.is_ai_recommended = True
                    result.ai_reason = ai_items[result.item_name].get('reason', '')
                    result.similarity = max(result.similarity, 0.9)
            
            # 按相似度重新排序
            account_results.sort(key=lambda x: x.similarity, reverse=True)
            url_results.sort(key=lambda x: x.similarity, reverse=True)
            
        except Exception as e:
            logger.error("AI enhancement failed: %s", e)
        
        return account_results[:top_k], url_results[:top_k]
    
    def is_account_index_built(self) -> bool:
        """检查账号向量索引是否已构建"""
        return len(self._account_vectors) > 0
    
    def is_ollama_available(self) -> bool:
        """检查 Ollama 服务是否可用"""
        return self.ollama is not None and self.ollama.is_available()
    
    def clear_account_index(self):
        """清空账号向量索引"""
        self._account_vectors.clear()
        self._account_texts.clear()
        if self.account_vectors_file.exists():
            try:
                self.account_vectors_file.unlink()
            except Exception:
                pass
    
    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        获取文本的embedding向量
        使用Ollama的embeddings API
        
        如果连续失败超过阈值，或检测到模型不支持embeddings，
        则标记 embeddings 不可用，后续不再尝试。
        """
        if not self.ollama:
            return None
        
        # 如果已确认 embeddings API 不可用，直接返回 None
        if self._embeddings_available is False:
            return None
        
        try:
            import requests
            response = requests.post(
                f"{self.ollama.host}/api/embeddings",
                json={
                    "model": self.ollama.model,
                    "prompt": text
                },
                timeout=5  # 缩短超时，快速失败
            )
            
            # 先检查状态码，再解析JSON
            if response.status_code >= 400:
                self._embeddings_error_count += 1
                # 400/500 错误通常表示模型不支持 embeddings
                if response.status_code in (400, 500):
                    self._embeddings_available = False
                    logger.warning("Embeddings API unavailable for model '%s' (HTTP %s). Fuzzy search will fall back to keyword matching.",
                                   self.ollama.model, response.status_code)
                elif self._embeddings_error_count >= self._max_embedding_errors:
                    self._embeddings_available = False
                    logger.warning("Embeddings API failed %d times. Disabling vector search to avoid flooding logs.",
                                   self._max_embedding_errors)
                return None
            
            result = response.json()
            embedding = result.get('embedding', [])
            if embedding:
                # 成功后重置错误计数，标记可用
                self._embeddings_available = True
                self._embeddings_error_count = 0
                return np.array(embedding, dtype=np.float32)
        except requests.exceptions.RequestException as e:
            self._embeddings_error_count += 1
            if self._embeddings_error_count >= self._max_embedding_errors:
                self._embeddings_available = False
                logger.warning("Embeddings API failed %d times. Disabling vector search to avoid flooding logs.",
                               self._max_embedding_errors)
            else:
                logger.warning("Embedding request failed: %s", e)
        except Exception as e:
            self._embeddings_error_count += 1
            if self._embeddings_error_count >= self._max_embedding_errors:
                self._embeddings_available = False
                logger.warning("Embeddings API failed %d times. Disabling vector search to avoid flooding logs.",
                               self._max_embedding_errors)
            else:
                logger.warning("Embedding failed: %s", e)
        
        return None
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """计算余弦相似度"""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def _build_account_text(self, account: Account) -> str:
        """构建账号的文本表示"""
        parts = [account.app_name]
        if account.url:
            parts.append(account.url)
        if account.remark:
            parts.append(account.remark)
        tags = account.get_tags_list()
        if tags:
            parts.extend(tags)
        return '|'.join(parts)
    
    def _build_url_text(self, url: URLItem) -> str:
        """构建网址的文本表示"""
        parts = [url.title or url.url]
        parts.append(url.url)
        tags = url.get_tags_list()
        if tags:
            parts.extend(tags)
        return '|'.join(parts)
    
    def _save_vectors(self, item_type: str):
        """保存向量索引到文件"""
        try:
            if item_type == 'account':
                data = {
                    'vectors': {str(k): v.tolist() for k, v in self._account_vectors.items()},
                    'texts': self._account_texts
                }
                with open(self.account_vectors_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
            else:
                data = {
                    'vectors': {str(k): v.tolist() for k, v in self._url_vectors.items()},
                    'texts': self._url_texts
                }
                with open(self.url_vectors_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.error("Save vectors failed: %s", e)
    
    def _load_vectors(self):
        """加载向量索引"""
        try:
            if self.account_vectors_file.exists():
                with open(self.account_vectors_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._account_vectors = {
                    int(k): np.array(v, dtype=np.float32) 
                    for k, v in data.get('vectors', {}).items()
                }
                self._account_texts = data.get('texts', {})
        except Exception as e:
            logger.error("Load account vectors failed: %s", e)
        
        try:
            if self.url_vectors_file.exists():
                with open(self.url_vectors_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._url_vectors = {
                    int(k): np.array(v, dtype=np.float32) 
                    for k, v in data.get('vectors', {}).items()
                }
                self._url_texts = data.get('texts', {})
        except Exception as e:
            logger.error("Load URL vectors failed: %s", e)
    
    def _extract_json(self, text: str) -> str:
        """从文本中提取JSON"""
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return text[start:end+1]
        return text
