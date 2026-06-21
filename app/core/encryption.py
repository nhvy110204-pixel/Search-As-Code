import base64
import json
import logging
import hashlib
from cryptography.fernet import Fernet
from app.config.settings import settings

logger = logging.getLogger(__name__)

def _get_encryption_key() -> bytes:
    if hasattr(settings, "ENCRYPTION_KEY") and settings.ENCRYPTION_KEY:
        try:
            key_bytes = settings.ENCRYPTION_KEY.encode("utf-8")
            Fernet(key_bytes)
            return key_bytes
        except Exception:
            logger.warning("Configured ENCRYPTION_KEY is invalid for Fernet. Falling back to JWT_SECRET_KEY derivation.")
            
    secret_bytes = settings.JWT_SECRET_KEY.encode("utf-8")
    hash_bytes = hashlib.sha256(secret_bytes).digest()
    return base64.urlsafe_b64encode(hash_bytes)

def encrypt_api_keys(keys_dict: dict) -> str:
    """
    Encrypt a dictionary of API keys to an encrypted string.
    """
    try:
        json_str = json.dumps(keys_dict)
        key = _get_encryption_key()
        f = Fernet(key)
        encrypted_bytes = f.encrypt(json_str.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to encrypt API keys: {e}")
        raise RuntimeError("API key encryption failed.") from e

def decrypt_api_keys(encrypted_str: str | None) -> dict:
    """
    Decrypt an encrypted string back to a dictionary of API keys.
    """
    if not encrypted_str:
        return {}
    try:
        key = _get_encryption_key()
        f = Fernet(key)
        decrypted_bytes = f.decrypt(encrypted_str.encode("utf-8"))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to decrypt API keys: {e}")
        return {}
