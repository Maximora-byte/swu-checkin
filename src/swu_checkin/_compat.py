"""Helpers for keeping historical entry points while steering callers to the typed core."""

from __future__ import annotations

import functools
import warnings
from collections.abc import Callable
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")


def deprecated(replacement: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Mark a compatibility wrapper; it keeps working but emits DeprecationWarning."""

    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        message = f"{function.__module__}.{function.__qualname__} is deprecated; use {replacement} instead"

        @functools.wraps(function)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return function(*args, **kwargs)

        return wrapper

    return decorate
