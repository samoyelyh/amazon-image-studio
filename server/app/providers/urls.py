from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_base_url(base_url: str) -> str:
    """Return a stable provider base URL without logging or altering credentials."""
    value = base_url.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Provider base URL must be an absolute HTTP(S) URL")
    path = "/" + "/".join(segment for segment in parts.path.split("/") if segment)
    if path == "/":
        path = ""
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


def provider_url(base_url: str, endpoint: str) -> str:
    base = normalize_base_url(base_url)
    path = "/" + endpoint.strip().lstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    if base.endswith(path):
        return base
    return f"{base}{path}"
