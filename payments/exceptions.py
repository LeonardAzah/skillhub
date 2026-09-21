class PaymentError(Exception):
    """Base exception for payment processing errors."""


class InsufficientFundsError(PaymentError):
    """Wallet does not have enough available balance for this operation."""

class CashOutServiceError(PaymentError):
    """Cashout request failed"""

class InvalidPaymentStateError(PaymentError):
    """Payment is not in the expected status for the requested transition."""


class PaymentProviderError(PaymentError):
    """The payment provider failed to process the request."""

class CashOutProviderError(PaymentProviderError):
    """The payment provider failed to process a cash-out (payout) request."""


class CashInProviderError(PaymentProviderError):
    """The payment provider failed to process a cash-in (top-up) request."""