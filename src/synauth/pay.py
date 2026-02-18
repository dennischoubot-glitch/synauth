"""
SynPay — Payment-specific convenience wrapper around SynAuth.

SynPay is a subset of SynAuth, focused on purchase authorization.
It provides a simpler interface for agents that only need to make payments.

Usage:
    from synauth import SynPayClient
    # or: from synauth.pay import SynPayClient

    client = SynPayClient(api_key="aa_...")

    # Request a payment (uses SynAuth's purchase action type under the hood)
    request = client.request_payment(
        amount=29.99,
        merchant="OpenAI",
        description="GPT-5 API credits - 1 month"
    )

    # Wait for Face ID authorization
    result = client.wait_for_result(request["id"], timeout=300)
    # result["status"]: "approved", "denied", "expired"
"""

from synauth.client import SynAuthClient


class SynPayClient:
    """Payment-focused client. Wraps SynAuth for purchase actions only."""

    def __init__(self, api_key: str, base_url: str = "https://synauth.fly.dev"):
        self._auth = SynAuthClient(api_key=api_key, base_url=base_url)

    def request_payment(
        self,
        amount: float,
        merchant: str,
        description: str,
        currency: str = "USD",
        metadata: dict = None,
    ) -> dict:
        """Request a payment. Returns immediately with request ID and status.

        The payment is pending until the user approves via Face ID on their phone.
        """
        return self._auth.request_purchase(
            amount=amount,
            merchant=merchant,
            description=description,
            currency=currency,
            metadata=metadata,
        )

    def get_status(self, request_id: str) -> dict:
        """Check the current status of a payment request."""
        return self._auth.get_status(request_id)

    def wait_for_result(
        self,
        request_id: str,
        timeout: int = 300,
        poll_interval: float = 2.0,
    ) -> dict:
        """Poll until the payment is resolved or timeout.

        Statuses:
            - "approved": Payment authorized
            - "denied": User denied the payment
            - "expired": No response within timeout
        """
        return self._auth.wait_for_result(request_id, timeout, poll_interval)


# Backward compatibility
AgentPayClient = SynPayClient
