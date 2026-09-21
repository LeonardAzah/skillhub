from payments.models import WalletPin


def verify_wallet_pin(user, pin: str) -> None:
    """
    Verify a user's wallet PIN.

    Raises:
        ValueError: PIN is not configured or is locked.
        serializers.ValidationError: PIN is invalid.
    """

    try:
        wallet_pin = user.wallet_pin
    except WalletPin.DoesNotExist:
        raise ValueError("You have not set a wallet PIN yet.")

    if not wallet_pin.is_set:
        raise ValueError("You have not set a wallet PIN yet.")

    try:
        ok = wallet_pin.verify(pin)
    except ValueError:
        # Preserve the lockout error from WalletPin.verify()
        raise

    if not ok:
        remaining = max(
            0,
            WalletPin.MAX_ATTEMPTS - wallet_pin.failed_attempts,
        )

        raise ValueError(
            f"Incorrect PIN. "
            f"{remaining} attempt(s) remaining before lockout."
        )