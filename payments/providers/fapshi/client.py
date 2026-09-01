from typing import Any

import requests

from utils.helpers import _setting

from .exceptions import FapshiAPIError, FapshiError

from payments.models import Payment

class FapshiClient:

    def __init__(self):
        self.base_url = _setting("FAPSHI_BASE_URL", default="")

        self.headers = {
            "apiuser": _setting("FAPSHI_API_USER", default=""),
            "apikey": _setting("FAPSHI_API_KEY", default=""),
            "Content-Type": "application/json",
        }

    METHOD_MAP = {
            Payment.Method.MTN_MOBILE_MONEY: "mobile money",
            Payment.Method.ORANGE_MONEY: "orange money",
        }


    def _get_medium(self, method):
        try:
            return self.METHOD_MAP[method]
        except KeyError:
            raise ValueError(
                f"Unsupported Fapshi payment method: {method}"
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:

        url = f"{self.base_url}{path}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=json,
                params=params,
                timeout=30,
            )

        except requests.RequestException as exc:
            raise FapshiError(
                "Unable to communicate with Fapshi."
            ) from exc

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code >= 400:
            raise FapshiAPIError(
                data.get(
                    "message",
                    "Fapshi request failed.",
                )
            )

        data["statusCode"] = response.status_code

        return data

    def initiate_pay(
        self,
        *,
        amount: int,
        email: str | None = None,
        user_id: str | None = None,
        external_id: str,
        redirect_url: str,
        message: str | None = None,
    ) -> dict:

        data = {
            "amount": amount,
            "externalId": external_id,
            "redirectUrl": redirect_url,
        }

        if email:
            data["email"] = email

        if user_id:
            data["userId"] = user_id

        if message:
            data["message"] = message

        return self._request(
            "POST",
            "/initiate-pay",
            json=data,
        )


    def direct_pay(
        self,
        *,
        amount: int,
        phone: str,
        external_id: str,
        method: str | None = None,
        name: str | None = None,
        email: str | None = None,
        user_id: str | None = None,
        message: str | None = None,
    ) -> dict:
        """
        Directly initiate a Fapshi payment to a user's
        mobile device.

        Returns a transId which can later be used with
        payment_status().
        """
        medium = self._get_medium(method)

        data = {
            "amount": amount,
            "phone": phone,
            "externalId": external_id,
        }

        if medium:
            data["medium"] = medium

        if name:
            data["name"] = name

        if email:
            data["email"] = email

        if user_id:
            data["userId"] = user_id

        if message:
            data["message"] = message

        return self._request(
            "POST",
            "/direct-pay",
            json=data,
        )

    def payout(
        self,
        *,
        amount: int,
        phone: str,
        external_id: str,
        name: str | None = None,
        email: str | None = None,
        user_id: str | None = None,
        medium: str | None = None,
        message: str | None = None,
    ) -> dict:

        medium = self._get_medium(medium)

        data = {
            "amount": amount,
            "phone": phone,
            "externalId": external_id,
        }

        if name:
            data["name"] = name

        if email:
            data["email"] = email

        if user_id:
            data["userId"] = user_id

        if medium:
            data["medium"] = medium

        if message:
            data["message"] = message

        return self._request(
            "POST",
            "/payout",
            json=data,
        )

    def payment_status(
        self,
        trans_id: str,
    ) -> dict:

        return self._request(
            "GET",
            f"/payment-status/{trans_id}",
        )

    def expire_pay(
        self,
        trans_id: str,
    ) -> dict:

        return self._request(
            "POST",
            "/expire-pay",
            json={
                "transId": trans_id,
            },
        )

    def balance(self) -> dict:

        return self._request(
            "GET",
            "/balance",
        )
    
    def get_user_transactions(
        self,
        user_id: str,
    ) -> dict:
        """
        Get Fapshi transactions associated with a userId.
        """

        return self._request(
            "GET",
            f"/transaction/{user_id}",
        )
    

    def search(
        self,
        *,
        status: str | None = None,
        medium: str | None = None,
        start: str | None = None,
        end: str | None = None,
        amount: int | None = None,
        limit: int = 10,
        sort: str = "desc",
    ) -> dict:
        """
        Search Fapshi transactions.
        """

        params = {}

        if status:
            params["status"] = status

        if medium:
            params["medium"] = medium

        if start:
            params["start"] = start

        if end:
            params["end"] = end

        if amount is not None:
            params["amt"] = amount

        params["limit"] = limit
        params["sort"] = sort

        return self._request(
            "GET",
            "/search",
            params=params,
        )