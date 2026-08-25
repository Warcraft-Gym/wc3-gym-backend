class NotFoundError(Exception):
    """The row the request names does not exist. The API answers 404."""


class BadRequestError(Exception):
    """The request carries a value the rules reject. The API answers 400."""


class ExternalServiceError(Exception):
    """A service outside the app failed. The API answers 502."""


class W3CThrottledError(ExternalServiceError):
    """W3Champions refused the call for rate. The API answers 502."""
