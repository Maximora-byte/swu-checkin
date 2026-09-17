"""Compatibility wrapper for credential verification."""

from .get_info import get_token


def verify(username: str, password: str, timeout: int = 10) -> bool:
    """Return whether the credentials can complete the existing login flow."""
    return bool(get_token(username, password, timeout))
