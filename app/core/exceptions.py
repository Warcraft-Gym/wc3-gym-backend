class NotFoundError(Exception):
    """The row the request names does not exist. The API answers 404."""


class BadRequestError(Exception):
    """The request carries a value the rules reject. The API answers 400."""
