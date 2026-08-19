class CashOutError(Exception):
    """Base exception for cash-out failures."""


class InsufficientFundsError(CashOutError):
    pass


class CashOutServiceError(CashOutError):
    pass


class CashOutProviderError(CashOutError):
    """The payment provider rejected or failed a cash-out."""