"""Deprecated alias of :mod:`swu_checkin.login`.

The module was renamed because it implements the login flow, not data
retrieval. Importing this name yields the very same module object, so
existing imports and monkeypatch targets keep working.
"""

import sys

from . import login as _login

sys.modules[__name__] = _login
