from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("not-a-real-user-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str | None) -> bool:
    verified = password_hash.verify(password, encoded_hash or dummy_password_hash)
    return encoded_hash is not None and verified
