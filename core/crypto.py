"""
加密引擎模块
实现 PBKDF2 密钥派生 + AES-256-GCM 加密
"""
import os
import hashlib
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


class CryptoManager:
    """加密管理器：负责密钥派生、加解密操作"""
    
    # 常量定义
    SALT_LENGTH = 32  # 盐值长度（字节）
    KEY_LENGTH = 32   # AES-256 密钥长度（字节）
    NONCE_LENGTH = 12 # GCM nonce 长度（字节）
    ITERATIONS = 100000  # PBKDF2 迭代次数
    
    def __init__(self, master_password: str, salt: bytes = None):
        """
        初始化加密管理器
        
        Args:
            master_password: 用户主密码
            salt: 盐值（首次使用不传，自动生成新盐值）
        """
        if salt is None:
            self._salt = os.urandom(self.SALT_LENGTH)
        else:
            self._salt = salt
        
        # 派生加密密钥
        self._key = self._derive_key(master_password, self._salt)
    
    @property
    def salt(self) -> bytes:
        """获取当前盐值（用于保存到配置文件）"""
        return self._salt
    
    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """
        使用 PBKDF2 派生密钥
        
        Args:
            password: 密码明文
            salt: 盐值
            
        Returns:
            32字节派生密钥
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_LENGTH,
            salt=salt,
            iterations=self.ITERATIONS
        )
        return kdf.derive(password.encode('utf-8'))
    
    def encrypt(self, plaintext: str) -> bytes:
        """
        AES-256-GCM 加密
        
        Args:
            plaintext: 明文文本
            
        Returns:
            密文字节（nonce + tag + ciphertext 拼接）
        """
        if not plaintext:
            return b''
        
        nonce = os.urandom(self.NONCE_LENGTH)
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        
        # 返回: nonce (12字节) + tag (16字节) + ciphertext
        return nonce + ciphertext
    
    def decrypt(self, ciphertext: bytes) -> str:
        """
        AES-256-GCM 解密
        
        Args:
            ciphertext: 密文字节（nonce + tag + ciphertext 拼接）
            
        Returns:
            明文文本
        """
        if not ciphertext:
            return ''
        
        if len(ciphertext) < self.NONCE_LENGTH + 16:
            raise ValueError("Invalid ciphertext format")
        
        nonce = ciphertext[:self.NONCE_LENGTH]
        encrypted_data = ciphertext[self.NONCE_LENGTH:]
        
        aesgcm = AESGCM(self._key)
        plaintext = aesgcm.decrypt(nonce, encrypted_data, None)
        
        return plaintext.decode('utf-8')
    
    def encrypt_to_string(self, plaintext: str) -> str:
        """
        加密并转为 Base64 字符串（用于数据库存储）
        
        Args:
            plaintext: 明文文本
            
        Returns:
            Base64 编码的密文字符串
        """
        ciphertext = self.encrypt(plaintext)
        return base64.b64encode(ciphertext).decode('utf-8')
    
    def decrypt_from_string(self, ciphertext_str: str) -> str:
        """
        从 Base64 字符串解密
        
        Args:
            ciphertext_str: Base64 编码的密文字符串
            
        Returns:
            明文文本
        """
        ciphertext = base64.b64decode(ciphertext_str.encode('utf-8'))
        return self.decrypt(ciphertext)
    
    def verify_password(self, password: str) -> bool:
        """
        验证密码是否与当前密钥匹配
        
        Args:
            password: 待验证的密码明文
            
        Returns:
            True 表示密码正确
        """
        test_key = self._derive_key(password, self._salt)
        return test_key == self._key
    
    def change_password(self, new_password: str) -> None:
        """
        更换主密码：重新生成盐值和密钥
        
        Args:
            new_password: 新密码明文
        """
        self._salt = os.urandom(self.SALT_LENGTH)
        self._key = self._derive_key(new_password, self._salt)
    
    def hash_for_cache(self, text: str) -> str:
        """
        计算文本的 SHA256 哈希（用于分类缓存表，不存储原文）
        
        Args:
            text: 原文
            
        Returns:
            SHA256 哈希字符串
        """
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
