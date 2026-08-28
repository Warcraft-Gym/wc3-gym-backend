from typing import Any


class ApiError(Exception):
    """A status and a body the route names, sent as they are.

    Clients read bodies that carry more than the error string: the 401
    and 422 token answers, and the 403 answers that add a message."""

    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        super().__init__(body.get("error", ""))
        self.status_code = status_code
        self.body = body


class NotFoundError(Exception):
    """The row the request names does not exist. The API answers 404."""


class BadRequestError(Exception):
    """The request carries a value the rules reject. The API answers 400."""


class ExternalServiceError(Exception):
    """A service outside the app failed. The API answers 502."""


class W3CThrottledError(ExternalServiceError):
    """W3Champions refused the call for rate. The API answers 502."""

    # The matches and the finished seasons the refused call had already read
    fetched: tuple[list[Any], dict[int, bool]] | None = None
