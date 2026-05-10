"""
Ollama API 客户端基础类
包含核心 HTTP 调用和基础功能
"""
import logging
import json
import re
import requests
from typing import List, Optional, Tuple, Generator, Dict

from ai.client_utils import _extract_json_object_robust, _fix_json

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama HTTP API 客户端"""

    _extract_json_object_robust = staticmethod(_extract_json_object_robust)
    _fix_json = staticmethod(_fix_json)

    def __init__(self, model: str = "gemma4:4b", host: str = "http://localhost:11434", timeout: float = 300):
        """
        初始化 Ollama 客户端

        Args:
            model: 模型名称
            host: Ollama 服务地址
            timeout: 请求超时时间（秒），默认 300 秒（5 分钟）。设为 None 表示永不超时
        """
        self.model = model
        self.host = host.rstrip('/')
        self.api_url = f"{self.host}/api/generate"
        self.timeout = timeout
        self.session = requests.Session()

    def is_available(self) -> bool:
        """检查 Ollama 服务是否可用"""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            logger.debug("Ollama 可用性检查失败", exc_info=True)
            return False

    def generate(self, prompt: str, temperature: float = 0.1, num_predict: int = 16384) -> str:
        """
        调用 Ollama 生成文本

        Args:
            prompt: 提示词
            temperature: 温度参数（越低越确定）
            num_predict: 最大生成 token 数（默认 -1 表示不限，由模型自行决定何时停止）

        Returns:
            生成的文本
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
                "num_ctx": 32768  # 上下文窗口 32K
            }
        }

        try:
            response = self.session.post(
                self.api_url,
                json=payload,
                timeout=self.timeout
            )
            if response.status_code == 503:
                raise Exception("Ollama 模型加载中，请稍后重试")
            if response.status_code == 429:
                raise Exception("请求过于频繁，请稍后重试")
            if response.status_code != 200:
                raise Exception(f"Ollama 服务返回错误: {response.status_code}")
            response.raise_for_status()

            result = response.json()
            raw_response = result.get('response', '').strip()
            done_reason = result.get('done_reason', 'N/A')
            prompt_eval_count = result.get('prompt_eval_count', 'N/A')
            eval_count = result.get('eval_count', 'N/A')
            logger.debug("status=%s, prompt_len=%s, prompt_tokens=%s, gen_tokens=%s, response_len=%s, done_reason=%s, preview=%r",
                         response.status_code, len(prompt), prompt_eval_count, eval_count, len(raw_response), done_reason, raw_response[:200])
            if not raw_response:
                logger.debug("FULL result keys=%s", list(result.keys()))
            return raw_response

        except requests.exceptions.ConnectionError:
            raise Exception("无法连接到 Ollama 服务，请确保 Ollama 已启动")
        except requests.exceptions.Timeout:
            raise Exception("Ollama 响应超时，请检查模型是否已加载")
        except Exception as e:
            msg = str(e)
            if msg.startswith(("Ollama ", "请求过于频繁")):
                raise
            raise Exception(f"Ollama 调用失败: {msg}")

    def generate_stream(self, prompt: str, temperature: float = 0.1, num_predict: int = 16384) -> Generator[str, None, None]:
        """
        流式生成文本，逐 token 返回。
        如果流式调用失败，降级为非流式 generate() 并一次性 yield 全部结果。

        Args:
            prompt: 提示词
            temperature: 温度参数
            num_predict: 最大生成 token 数

        Yields:
            每个 token 字符串
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
                "num_ctx": 32768
            }
        }

        try:
            response = self.session.post(
                self.api_url,
                json=payload,
                stream=True,
                timeout=(10, self.timeout)
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line.decode('utf-8'))
                    token = data.get('response', '')
                    if token:
                        yield token
                    if data.get('done', False):
                        break
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

        except Exception as stream_e:
            logger.warning("流式生成失败，降级为非流式: %s", stream_e)
            # 降级为非流式生成
            try:
                result = self.generate(prompt, temperature=temperature, num_predict=num_predict)
                yield result
            except Exception as fallback_e:
                raise Exception(f"流式生成失败且降级失败: {fallback_e}") from stream_e

    def generate_with_think_result(self, prompt: str, temperature: float = 0.1, num_predict: int = 16384) -> dict:
        """
        生成文本，并要求模型按 <think> 和 <result> 标签输出结构化结果。

        Args:
            prompt: 提示词
            temperature: 温度参数
            num_predict: 最大生成 token 数

        Returns:
            {"think": "思考过程", "result": "最终结果"}
        """
        wrapped_prompt = f"""{prompt}

请按以下格式输出：

<think>
[你的思考过程]
</think>

<result>
[最终结果]
</result>
"""
        raw = self.generate(wrapped_prompt, temperature=temperature, num_predict=num_predict)

        # 使用索引提取 think 内容（避免正则过度匹配）
        think = ""
        think_start = raw.find('<think>')
        if think_start != -1:
            think_end = raw.find('</think>', think_start)
            if think_end != -1:
                think = raw[think_start + len('<think>'):think_end].strip()

        result_text = raw.strip()
        result_start = raw.find('<result>')
        if result_start != -1:
            result_end = raw.find('</result>', result_start)
            if result_end != -1:
                result_text = raw[result_start + len('<result>'):result_end].strip()

        return {"think": think, "result": result_text}

    def categorize(self, app_name: str, url: str = "", existing_categories: list = None, parent_hint: str = None, remark: str = "", ai_remark: str = "") -> str:
        """
        AI 智能分类

        Args:
            app_name: 应用名称/标题
            url: 网址（可选）
            existing_categories: 当前已有的分类列表（可选），AI 优先从中匹配
            parent_hint: 当前已选中的一级分类（可选）。传入时只要求返回二级子类
            remark: 用户手动备注（可选）
            ai_remark: AI 生成备注（可选）

        Returns:
            分类名称（parent_hint 为空时返回完整分类，否则只返回子类名）
        """
        cat_hint = ""
        if existing_categories:
            cat_list = "\n".join(f"- {c}" for c in existing_categories if c and c != '全部')
            cat_hint = f"""当前已有的分类：
{cat_list}

"""

        extra_info = ""
        if remark:
            extra_info += f"用户备注：{remark}\n"
        if ai_remark:
            extra_info += f"AI备注：{ai_remark}\n"

        if parent_hint:
            # 二级分类模式：只返回子类名
            prompt = f"""你是一款密码管理软件的智能分类助手。当前已选中的一级分类是「{parent_hint}」，请为该条目推荐一个最合适的二级子类。

{cat_hint}规则：
1. 该条目属于「{parent_hint}」分类体系，请只给出二级子类名称（不要带一级分类前缀）
2. 如果现有子类中有高度匹配的，优先使用已有子类名
3. 如果现有子类都不合适，可以自创一个更精准的子类名称
4. 子类名应简洁明确（2-5个字），如"前端框架"、"后端开发"、"机器学习"等
5. 只返回子类名称，不要解释、不要加引号、不要返回多余内容
6. 禁止包含 "/"、">"、"·" 等符号

应用名称/标题：{app_name}
网址：{url}
{extra_info}二级子类："""
        else:
            # 一级分类模式：返回完整分类名
            prompt = f"""你是一款密码管理软件的智能分类助手。请根据以下信息，分析该条目最合理的一级分类。

{cat_hint}规则：
1. 优先从「当前已有的分类」中找出最接近的一个直接使用
2. 如果现有分类都不合适，再自创一个更精准的新分类名称
3. 分类名称应简洁明确（2-6个字），如"开发工具"、"学术资源"、"生活服务"等
4. 只返回一级分类名称，不要解释、不要加引号、不要返回多余内容
5. 禁止包含 "/"、">"、"·" 等符号

应用名称/标题：{app_name}
网址：{url}
{extra_info}一级分类："""

        try:
            result = self.generate(prompt, temperature=0.2, num_predict=50)
        except Exception as e:
            logger.error("AI 分类网络调用失败: %s", e)
            raise

        try:
            # 清洗结果
            result = result.strip().strip('"').strip("'")

            # 如果AI返回了分析内容+分类，尝试提取最后一行或第一个有意义的词
            lines = [l.strip() for l in result.split('\n') if l.strip()]
            if lines:
                result = lines[-1]

            # 过滤掉常见的前缀噪音
            for prefix in ['分类：', '分类:', '分类是', '属于', '结果为', '答案是', '一级分类：', '二级子类：', '子类：']:
                if result.startswith(prefix):
                    result = result[len(prefix):].strip()

            # 清理非法字符
            result = result.replace('/', '-').replace('·', '-')

            return result if result else '其他'

        except Exception as e:
            logger.warning("AI 分类结果解析失败: %s，返回默认值", e)
            return '其他'

    def close(self):
        """关闭 HTTP Session，释放连接池"""
        try:
            if hasattr(self, 'session') and self.session:
                self.session.close()
        except Exception:
            pass

    def chat(self, messages: List[dict], temperature: float = 0.3, num_predict: int = 16384) -> str:
        """
        对话模式：支持多轮上下文（通过 messages 拼接为 prompt）

        Args:
            messages: 消息列表，每项为 {"role": "user"|"assistant", "content": "..."}
            temperature: 温度参数
            num_predict: 最大生成 token 数

        Returns:
            模型回复文本
        """
        # 将 messages 拼接为单个 prompt（gemma4:4b 不支持原生 chat API，用 prompt 模拟）
        prompt_parts = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if role == 'user':
                prompt_parts.append(f"用户：{content}")
            else:
                prompt_parts.append(f"助手：{content}")

        prompt = '\n\n'.join(prompt_parts) + "\n\n助手："

        return self.generate(prompt, temperature=temperature, num_predict=num_predict)
