"""Compatibility wrapper for credential verification."""

from .auth import AuthError
from .get_info import get_token


def verify(username: str, password: str, timeout: int = 10) -> bool:
    """Return whether the credentials can complete the existing login flow."""
    try:
        return bool(get_token(username, password, timeout))
    except AuthError:
        return False
