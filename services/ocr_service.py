"""
OCR 服务模块
集成 PaddleOCR 实现截图文字识别
"""
import os
import re
from pathlib import Path
from typing import Dict, Optional, List
from PIL import Image

# 禁用 oneDNN 加速（解决 Windows 兼容性错误）
os.environ['FLAGS_use_mkldnn'] = 'false'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['FLAGS_enable_pir_api'] = 'false'  # 禁用 PIR 模式

from paddleocr import PaddleOCR


class OCRService:
    """OCR 服务：截图文字识别与字段提取"""
    
    def __init__(self):
        """初始化 OCR 引擎"""
        # 初始化 PaddleOCR（简化配置）
        try:
            self.ocr = PaddleOCR(
                lang='ch'
            )
        except Exception as e:
            print(f"[ERROR] PaddleOCR init failed: {e}")
            raise
    
    def recognize_image(self, image_path: str) -> List[Dict]:
        """
        识别图片中的文字
        
        Args:
            image_path: 图片路径
            
        Returns:
            识别结果列表：[{'text': '文字', 'confidence': 0.95, 'box': [...]}, ...]
        """
        try:
            # 尝试使用新版本的 API
            try:
                result = self.ocr.ocr(image_path)
            except TypeError:
                # 旧版本可能需要 cls 参数
                result = self.ocr.ocr(image_path, cls=True)
            
            extracted_texts = []
            if result and result[0]:
                for line in result[0]:
                    if line:
                        box = line[0]  # 文本框坐标
                        text = line[1][0]  # 识别文本
                        confidence = line[1][1]  # 置信度
                        
                        extracted_texts.append({
                            'text': text,
                            'confidence': confidence,
                            'box': box
                        })
            
            return extracted_texts
            
        except Exception as e:
            print(f"OCR 识别失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def extract_account_fields(self, image_path: str) -> Dict[str, str]:
        """
        从截图中提取账号相关字段
        
        Args:
            image_path: 图片路径
            
        Returns:
            {'app_name': '...', 'username': '...', 'password': '...', 'all_texts': [...]}
        """
        texts = self.recognize_image(image_path)
        
        if not texts:
            return {}
        
        # 合并所有文本，但先过滤掉密码相关的UI文字行
        password_ui_keywords = ['找回密码', '忘记密码', '记住密码', '修改密码', 
                               '重置密码', '密码找回', '密码重置']
        filtered_texts = []
        for t in texts:
            text = t['text'].strip()
            if not any(kw in text for kw in password_ui_keywords):
                filtered_texts.append(text)
        
        all_text = '\n'.join(filtered_texts)
        
        # 调试：打印所有识别的文字
        print(f"[OCR] Recognized {len(texts)} texts:")
        for i, t in enumerate(texts):
            print(f"  [{i}] {t['text']}")
        
        extracted = {
            'app_name': '',
            'url': '',
            'username': '',
            'password': '',
            'all_texts': [t['text'] for t in texts]  # 返回所有文本供参考
        }
        
        # 提取网址
        url_match = re.search(r'(https?://[^\n\r\s]+)', all_text)
        if url_match:
            extracted['url'] = url_match.group(1).strip()
        
        # 提取应用名：优先从非URL、非UI元素的文本中提取
        # 策略1：查找包含特定关键词的文本（如"大学"、"学院"、"平台"、"系统"）
        app_keywords = ['大学', '学院', '平台', '系统', '网站', '门户', '中心', '管理', 
                        'University', 'College', 'Platform', 'System', 'Portal']
        
        for t in texts:
            text = t['text'].strip()
            # 跳过URL
            if text.startswith('http') or text.startswith('www'):
                continue
            # 跳过UI元素
            if text in ['登录', 'Login', '注册', 'Register', '忘记密码', '记住密码', '提交']:
                continue
            # 查找包含应用关键词的文本
            if any(kw in text for kw in app_keywords):
                # 如果文本不太长，直接使用
                if len(text) <= 30:
                    extracted['app_name'] = text
                    break
        
        # 策略2：如果没有找到关键词，使用第一个非URL、非UI的短文本
        if not extracted['app_name']:
            for t in texts:
                text = t['text'].strip()
                # 跳过URL和UI元素
                if (text.startswith('http') or text.startswith('www') or 
                    text in ['登录', 'Login', '注册', 'Register'] or
                    len(text) > 25):
                    continue
                # 使用第一个合适的文本
                if len(text) >= 2:
                    extracted['app_name'] = text
                    break
        
        # 策略3：如果还是没有，从URL推断
        if not extracted['app_name'] and extracted['url']:
            extracted['app_name'] = self._infer_app_name_from_url(extracted['url'])
        
        # 提取账号（多种格式）
        username_patterns = [
            r'(?:账号|用户名|帐号|账户|登录名)[：:\s]*([\w\-\.@]+)',
            r'(?:Account|Username|Login|Email)[：:\s]*([\w\-\.@]+)',
            r'(?:手机|电话|邮箱)[：:\s]*([\d\w\-\.@]+)',
        ]
        
        for pattern in username_patterns:
            match = re.search(pattern, all_text, re.IGNORECASE)
            if match:
                extracted['username'] = match.group(1).strip()
                break
        
        # 提取密码（多种格式）
        # 添加\b单词边界防止子字符串匹配（如mypassword123中的pass）
        # 使用[^\n\r\s]排除换行符，防止跨行匹配（如"记住密码\n找回密码"）
        password_patterns = [
            r'(?:密码|口令|密文|\bPassword\b|\bPwd\b|\bPass\b)[：:]*\s*([^\n\r\s]+)',
            r'(?:初始密码|默认密码)[：:]*\s*([^\n\r\s]+)',
        ]
        
        for pattern in password_patterns:
            match = re.search(pattern, all_text, re.IGNORECASE)
            if match:
                extracted['password'] = match.group(1).strip()
                break
        
        # 智能推测：如果没有提取到账号密码，分析所有文本
        if not extracted['username'] or not extracted['password']:
            # 收集所有候选文本（排除UI元素和短文本）
            candidates = []
            ui_keywords = ['登录', 'login', '提交', '确定', '取消', '忘记密码', '记住密码', 
                          'register', 'sign up', '验证码', 'code', '注册']
            
            for t in texts:
                text = t['text'].strip()
                # 排除空文本、UI元素
                if (text and len(text) >= 3 and len(text) <= 50 and 
                    text.lower() not in [k.lower() for k in ui_keywords] and
                    not any(kw in text.lower() for kw in ui_keywords)):
                    candidates.append(text)
            
            print(f"[OCR] Candidates: {candidates}")
            
            # 尝试从冒号分割的文本中提取（如 "账号: xxx"）
            for text in candidates:
                if ':' in text or '：' in text:
                    parts = re.split(r'[:：]', text, 1)
                    if len(parts) == 2:
                        key, value = parts[0].strip(), parts[1].strip()
                        # 判断key类型
                        if any(kw in key for kw in ['账号', '用户', 'User', '登录', 'Account', '手机', '邮箱']):
                            if not extracted['username']:
                                extracted['username'] = value
                        elif any(kw in key for kw in ['密码', '口令', 'Pass', 'Pwd', 'Password']):
                            if not extracted['password']:
                                extracted['password'] = value
                        elif any(kw in key for kw in ['应用', 'App', '软件', '网站']):
                            if not extracted['app_name']:
                                extracted['app_name'] = value
            
            # 如果仍没有提取到，尝试使用纯候选值（去掉冒号部分）
            clean_candidates = []
            for text in candidates:
                # 如果有冒号，取冒号后的部分
                if ':' in text or '：' in text:
                    parts = re.split(r'[:：]', text, 1)
                    if len(parts) == 2:
                        value = parts[1].strip()
                        if value and len(value) >= 2:
                            clean_candidates.append(value)
                else:
                    clean_candidates.append(text)
            
            # 过滤掉包含"密码"但不是密码本身的项（如"记住密码"、"找回密码"、"修改密码"）
            final_candidates = []
            for text in clean_candidates:
                # 排除密码相关的UI文字
                password_ui_keywords = ['找回密码', '忘记密码', '记住密码', '修改密码', 
                                       '重置密码', '密码找回', '密码重置']
                if any(kw in text for kw in password_ui_keywords):
                    continue
                final_candidates.append(text)
            
            # 应用名通常是第一个，账号密码在后面
            # 从非应用名的候选中选择账号密码
            non_app_candidates = [c for c in final_candidates if c != extracted.get('app_name', '')]
            
            if len(non_app_candidates) >= 2:
                if not extracted['username']:
                    extracted['username'] = non_app_candidates[0]
                if not extracted['password']:
                    extracted['password'] = non_app_candidates[1]
            elif len(non_app_candidates) == 1 and not extracted['username']:
                extracted['username'] = non_app_candidates[0]
        
        print(f"[OCR] Extracted: {extracted}")
        return extracted
    
    def _infer_app_name_from_url(self, url: str) -> str:
        """从 URL 推断应用名称"""
        url_lower = url.lower()
        
        # 常见应用映射
        app_mapping = {
            'alipay': '支付宝',
            'taobao': '淘宝',
            'tmall': '天猫',
            'jd': '京东',
            'wechat': '微信',
            'wx': '微信',
            'qq': 'QQ',
            'weibo': '微博',
            'douyin': '抖音',
            'bilibili': '哔哩哔哩',
            'bili': '哔哩哔哩',
            'zhihu': '知乎',
            'baidu': '百度',
            'netease': '网易',
            '163': '网易邮箱',
            '126': '网易邮箱',
            'sina': '新浪',
            'ximalaya': '喜马拉雅',
            'xiaomi': '小米',
            'huawei': '华为',
            'apple': '苹果',
            'icloud': 'iCloud',
            'github': 'GitHub',
            'gitlab': 'GitLab',
            'gitee': 'Gitee',
        }
        
        for key, name in app_mapping.items():
            if key in url_lower:
                return name
        
        # 如果没有匹配，返回域名
        domain = url.split('.')[0]
        return domain.capitalize()
    
    def preprocess_image(self, image_path: str, output_path: str = None) -> str:
        """
        图片预处理（可选）：调整大小、增强对比度
        
        Args:
            image_path: 原图路径
            output_path: 输出路径（默认覆盖原图）
            
        Returns:
            处理后图片路径
        """
        try:
            img = Image.open(image_path)
            
            # 如果图片太大，缩小以提高 OCR 速度
            max_size = 1920
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # 转换为 RGB（处理 PNG 透明通道）
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # 保存
            save_path = output_path or image_path
            img.save(save_path, quality=95)
            
            return save_path
            
        except Exception as e:
            print(f"图片预处理失败: {e}")
            return image_path
