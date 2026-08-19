import re

from app.core.errors import AppError


ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


def normalize_account(value: str) -> str:
    return value.strip().lower()


def validate_account(value: str) -> str:
    account = normalize_account(value)
    if not ACCOUNT_PATTERN.fullmatch(account):
        raise AppError(
            "auth.invalid_account",
            "账号必须为 3 至 32 位，只能包含英文字母、数字、下划线和连字符",
            422,
        )
    return account
