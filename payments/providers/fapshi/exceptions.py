class FapshiError(Exception):
    """Base Fapshi integration error."""


class FapshiAPIError(FapshiError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code
