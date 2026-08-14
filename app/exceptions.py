class DBException(Exception):
    """The database itself failed. The API answers 500."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return self.message


class NotFoundException(Exception):
    """The row the request names does not exist. The API answers 404."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return self.message
