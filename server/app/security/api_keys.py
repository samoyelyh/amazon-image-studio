from cryptography.fernet import Fernet, InvalidToken
from hashlib import sha256

from app.core.config import Settings
from app.core.errors import AppError


def api_key_fingerprint(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()


def encrypt_api_key(settings: Settings, secret: str) -> str:
    value = secret.strip()
    if len(value) < 8:
        raise AppError("resource_pool.invalid_api_key", "API key must contain at least 8 characters", 422)
    cipher = Fernet(settings.api_key_encryption_key.get_secret_value().encode("ascii"))
    return cipher.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(settings: Settings, ciphertext: str) -> str:
    cipher = Fernet(settings.api_key_encryption_key.get_secret_value().encode("ascii"))
    try:
        return cipher.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise AppError("resource_pool.key_decryption_failed", "API key cannot be decrypted with the configured key", 500) from error
