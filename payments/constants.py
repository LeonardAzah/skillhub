from decimal import Decimal

# SRS §9.8 — Platform commission rate (configurable by admin)
PLATFORM_COMMISSION_RATE = Decimal("0.015")   # 1.5%

# Minimum withdrawal amount (FCFA)
MIN_WITHDRAWAL_AMOUNT = Decimal("1000.00")

# Wallet PIN cache token TTLs (seconds)
WALLET_PIN_TTL_BOOKING    = 300   # 5 minutes — for booking confirmation
WALLET_PIN_TTL_WITHDRAWAL = 300   # 5 minutes — for withdrawal authorisation

# Cache key prefixes
WALLET_PIN_TOKEN_BOOKING    = "wallet_pin_verified"      # consumed by appointments module
WALLET_PIN_TOKEN_WITHDRAWAL = "wallet_pin_withdrawal"    # consumed by withdrawal endpoint

# SRS §9.5 — Fraud hold: new accounts must be at least 7 days old to withdraw
WITHDRAWAL_ACCOUNT_AGE_DAYS = 7

# SRS §9.7 — Gateway retry policy
GATEWAY_RETRY_DELAY_SECONDS = 300   # 5 minutes
GATEWAY_MAX_RETRIES         = 3


def _make_idempotency_key(*parts) -> str:
    return ":".join(str(p) for p in parts)
