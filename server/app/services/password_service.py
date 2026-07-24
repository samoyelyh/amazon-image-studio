from __future__ import annotations

import re

from app.core.errors import AppError


COMMON_WEAK_PARTS = {
    "password", "passwd", "qwerty", "admin", "welcome", "letmein",
    "123456", "111111", "abc123", "iloveyou",
}


def validate_password(password: str, *, email: str = "", display_name: str = "") -> None:
    failures: list[str] = []
    if len(password) < 12:
        failures.append("至少12位")
    if not re.search(r"[A-Z]", password):
        failures.append("大写字母")
    if not re.search(r"[a-z]", password):
        failures.append("小写字母")
    if not re.search(r"\d", password):
        failures.append("数字")
    if not re.search(r"[^A-Za-z0-9]", password):
        failures.append("特殊字符")

    lowered = password.casefold()
    compact = re.sub(r"[^a-z0-9]", "", lowered)
    if any(part in compact for part in COMMON_WEAK_PARTS):
        failures.append("不能包含常见弱密码")

    identity_parts = [email.partition("@")[0], display_name]
    for part in identity_parts:
        normalized = re.sub(r"[^a-z0-9]", "", part.casefold())
        if len(normalized) >= 4 and normalized in compact:
            failures.append("不能包含邮箱或姓名的主要部分")
            break

    if failures:
        raise AppError(
            "auth.weak_password",
            "密码至少12位，并包含大小写字母、数字和特殊字符；" + "、".join(dict.fromkeys(failures)) + "。",
            422,
        )
