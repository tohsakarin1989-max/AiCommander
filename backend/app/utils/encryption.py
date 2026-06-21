from cryptography.fernet import Fernet
from app.config import settings
import base64
import hashlib

def get_encryption_key() -> bytes:
    """从SECRET_KEY生成加密密钥"""
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key)

def encrypt_api_key(api_key: str) -> str:
    """加密API密钥"""
    f = Fernet(get_encryption_key())
    encrypted = f.encrypt(api_key.encode())
    return encrypted.decode()

def decrypt_api_key(encrypted_key: str) -> str:
    """解密API密钥"""
    try:
        f = Fernet(get_encryption_key())
        decrypted = f.decrypt(encrypted_key.encode())
        return decrypted.decode()
    except Exception as e:
        # 如果解密失败，可能是旧格式，直接返回
        if encrypted_key.startswith("encrypted_"):
            return encrypted_key.replace("encrypted_", "")
        raise e

