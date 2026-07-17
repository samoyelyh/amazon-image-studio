"""Replaceable authentication and authorization boundary for Phase 3."""
from app.security.principal import Principal, get_current_principal, require_permissions

__all__ = ["Principal", "get_current_principal", "require_permissions"]
