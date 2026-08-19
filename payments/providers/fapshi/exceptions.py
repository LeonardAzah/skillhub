class FapshiError(Exception):
    """Base Fapshi integration error."""


class FapshiAPIError(FapshiError):
    """Fapshi returned an unsuccessful response."""
