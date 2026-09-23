"""Environment settings read fresh at call time, not cached at import time."""

import os


def frontend_url() -> str:
    """FRONTEND_URL with a trailing slash removed, or "" when it is unset."""
    return (os.getenv("FRONTEND_URL") or "").rstrip("/")
