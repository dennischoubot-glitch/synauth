"""
SynAuth client — Python SDK for AI agents to request human authorization.

SynAuth is the unified authorization layer. Any agent action — sending emails,
making purchases, booking meetings, signing contracts — goes through here.
Human approves via Face ID on iPhone.

Usage:
    from synauth import SynAuthClient

    client = SynAuthClient(api_key="aa_...")

    # Request permission to send an email
    result = client.request_action(
        action_type="communication",
        title="Send quarterly report",
        description="Email to john@company.com with Q4 results",
        recipient="john@company.com",
        risk_level="low",
    )

    # Wait for human approval via Face ID
    status = client.wait_for_result(result["id"])
    if status["status"] == "approved":
        send_email(...)

    # List vault services (structural enforcement — agent never sees credentials)
    services = client.list_vault_services()

    # Execute an API call through the vault (biometric approval + credential injection)
    result = client.execute_api_call(
        service_name="openai",
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        body='{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}',
    )
"""

import time
import requests


# --- Error classes ---


class SynAuthError(Exception):
    """Base exception for all SynAuth SDK errors."""
    pass


class SynAuthAPIError(SynAuthError):
    """HTTP error from the SynAuth backend."""

    def __init__(self, status_code: int, detail: str, response: requests.Response = None):
        self.status_code = status_code
        self.detail = detail
        self.response = response
        super().__init__(f"SynAuth API error {status_code}: {detail}")


class RateLimitError(SynAuthAPIError):
    """Rate limit exceeded (HTTP 429)."""

    def __init__(self, detail: str = "Rate limit exceeded", response: requests.Response = None):
        super().__init__(429, detail, response)


class ActionExpiredError(SynAuthError):
    """Action request expired before approval."""

    def __init__(self, request_id: str):
        self.request_id = request_id
        super().__init__(f"Action {request_id} expired")


class ActionDeniedError(SynAuthError):
    """Action request was denied."""

    def __init__(self, request_id: str, reason: str = None):
        self.request_id = request_id
        self.reason = reason
        msg = f"Action {request_id} denied"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class VaultExecutionError(SynAuthError):
    """Vault credential execution failed."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"Vault execution failed: {detail}")


class SynAuthClient:
    """Client for agents to request Face ID-authorized actions."""

    API_VERSION = "v1"

    def __init__(self, api_key: str, base_url: str = "https://synauth.fly.dev"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = api_key

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an authenticated request to the SynAuth backend.

        Centralizes error handling — converts HTTP errors to typed exceptions.
        """
        url = f"{self.base_url}/api/{self.API_VERSION}{path}"
        resp = self.session.request(method, url, timeout=30, **kwargs)

        if resp.status_code == 429:
            raise RateLimitError(response=resp)

        if not resp.ok:
            try:
                detail = resp.json().get("detail", resp.text)
            except (ValueError, KeyError):
                detail = resp.text
            raise SynAuthAPIError(resp.status_code, detail, resp)

        return resp.json()

    # --- Core action methods ---

    def request_action(
        self,
        action_type: str,
        title: str,
        description: str = None,
        risk_level: str = "medium",
        reversible: bool = True,
        amount: float = None,
        currency: str = "USD",
        recipient: str = None,
        metadata: dict = None,
        expires_in_seconds: int = 300,
        callback_url: str = None,
    ) -> dict:
        """Submit an action for human authorization. Returns immediately.

        If callback_url is set, the backend will POST the action status to that
        URL when the human approves or denies. The agent can still poll as a
        fallback.
        """
        payload = {
            "action_type": action_type,
            "title": title,
            "risk_level": risk_level,
            "reversible": reversible,
            "expires_in_seconds": expires_in_seconds,
        }
        if description:
            payload["description"] = description
        if amount is not None:
            payload["amount"] = amount
            payload["currency"] = currency
        if recipient:
            payload["recipient"] = recipient
        if metadata:
            payload["metadata"] = metadata
        if callback_url:
            payload["callback_url"] = callback_url

        return self._request("POST", "/actions", json=payload)

    def get_status(self, request_id: str) -> dict:
        """Check the current status of an action request."""
        return self._request("GET", f"/actions/{request_id}")

    def wait_for_result(
        self,
        request_id: str,
        timeout: int = 300,
        poll_interval: float = 2.0,
    ) -> dict:
        """Block until the action is approved, denied, or expired."""
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_status(request_id)
            if status["status"] != "pending":
                return status
            time.sleep(poll_interval)
        return self.get_status(request_id)

    # --- History ---

    def get_history(
        self,
        limit: int = 50,
        status: str = None,
        action_type: str = None,
    ) -> dict:
        """Get this agent's action request history.

        Returns past action requests (approved, denied, expired, pending).
        Useful for reviewing what actions have been taken and their outcomes.

        Args:
            limit: Max number of results (default 50).
            status: Filter by status ('approved', 'denied', 'expired', 'pending').
            action_type: Filter by action type ('communication', 'purchase', etc.).

        Returns:
            Dict with 'actions' key containing list of action records.
        """
        params = {"limit": limit}
        if status:
            params["status"] = status
        if action_type:
            params["action_type"] = action_type
        return self._request("GET", "/actions", params=params)

    # --- Spending summary ---

    def get_spending_summary(self) -> dict:
        """Get this agent's current spending vs. limits.

        Returns spending summaries for all limits that apply to this agent —
        both agent-specific limits and global limits. Spend amounts are scoped
        to this agent only.

        Use this before making a purchase or other monetary action to check
        whether you have budget remaining. Each summary includes the limit,
        amount spent, amount remaining, and utilization percentage.

        Returns:
            Dict with 'agent_id' and 'summaries' keys. Each summary contains:
            limit_id, agent_id, action_type, period, limit, spent, remaining,
            utilization_pct.
        """
        return self._request("GET", "/agent/spending-summary")

    # --- Vault (structural enforcement) ---

    def list_vault_services(self) -> dict:
        """List available vault services (stored API credentials).

        Shows which services have credentials stored in SynAuth's vault.
        Each service has allowed hosts that restrict where credentials can be sent.
        The agent never sees the actual credential values — only service names
        and metadata.

        Use this to discover what API services are available before calling
        execute_api_call().

        Returns:
            Dict with 'services' key containing list of service records,
            each with: service_name, auth_type, allowed_hosts, description.
        """
        return self._request("GET", "/vault/services")

    def execute_api_call(
        self,
        service_name: str,
        method: str,
        url: str,
        headers: dict = None,
        body: str = None,
        description: str = None,
        timeout: int = 120,
        poll_interval: float = 3.0,
    ) -> dict:
        """Make an API call using a credential stored in SynAuth's vault.

        This is the core structural enforcement method: the agent provides the
        request details, SynAuth requests biometric approval, then executes the
        call with the stored credential. The agent never sees the raw API key.

        Flow:
        1. Creates an action request with vault execution metadata.
        2. Waits for biometric approval via Face ID.
        3. Executes the HTTP request with the stored credential injected.
        4. Returns the API response.

        The URL must match one of the service's allowed hosts (security:
        prevents credential exfiltration). Each approval is single-use.

        Args:
            service_name: Name of the vault service (see list_vault_services()).
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            url: Full URL to call (host must be in service's allowed_hosts).
            headers: Additional headers (auth header is injected automatically).
            body: Request body (typically JSON string for POST/PUT/PATCH).
            description: Human-readable description shown in the approval prompt.
            timeout: Max seconds to wait for approval (default 120).
            poll_interval: Seconds between status checks (default 3.0).

        Returns:
            Dict with vault execution result including the API response.

        Raises:
            ActionDeniedError: If the user denied the request.
            ActionExpiredError: If the request expired before approval.
            VaultExecutionError: If the credential execution failed.
            SynAuthAPIError: For other API errors.
        """
        # Step 1: Create approval request with vault metadata
        payload = {
            "action_type": "data_access",
            "title": description or f"API call: {method} {url}",
            "description": f"Service: {service_name} | {method} {url}",
            "risk_level": "medium",
            "metadata": {
                "vault_execute": True,
                "service_name": service_name,
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": body,
            },
        }
        result = self._request("POST", "/actions", json=payload)

        # May be auto-denied by rules
        if result.get("status") == "denied":
            raise ActionDeniedError(result["id"], result.get("deny_reason"))

        request_id = result["id"]

        # Step 2: Wait for approval if pending
        if result.get("status") == "pending":
            start = time.time()
            while time.time() - start < timeout:
                result = self.get_status(request_id)
                if result["status"] != "pending":
                    break
                time.sleep(poll_interval)

        if result.get("status") == "expired":
            raise ActionExpiredError(request_id)
        if result.get("status") == "denied":
            raise ActionDeniedError(request_id, result.get("deny_reason"))
        if result.get("status") != "approved":
            raise VaultExecutionError(
                f"Unexpected status '{result.get('status')}' for request {request_id}"
            )

        # Step 3: Execute with stored credential
        return self._request("POST", f"/vault/execute/{request_id}")

    # --- Convenience methods for common action types ---

    def request_email(self, recipient: str, subject: str, preview: str = None, **kwargs) -> dict:
        return self.request_action(
            action_type="communication",
            title=f"Send email: {subject}",
            description=preview,
            recipient=recipient,
            risk_level=kwargs.pop("risk_level", "low"),
            **kwargs,
        )

    def request_purchase(self, amount: float, merchant: str, description: str = None, **kwargs) -> dict:
        return self.request_action(
            action_type="purchase",
            title=f"Purchase from {merchant}",
            description=description,
            amount=amount,
            recipient=merchant,
            risk_level=kwargs.pop("risk_level", "medium"),
            **kwargs,
        )

    def request_booking(self, title: str, description: str = None, amount: float = None, **kwargs) -> dict:
        return self.request_action(
            action_type="scheduling",
            title=title,
            description=description,
            amount=amount,
            risk_level=kwargs.pop("risk_level", "low"),
            **kwargs,
        )

    def request_post(self, platform: str, content_preview: str, **kwargs) -> dict:
        return self.request_action(
            action_type="social",
            title=f"Post to {platform}",
            description=content_preview,
            risk_level=kwargs.pop("risk_level", "medium"),
            **kwargs,
        )

    def request_data_access(self, resource: str, reason: str, **kwargs) -> dict:
        return self.request_action(
            action_type="data_access",
            title=f"Access: {resource}",
            description=reason,
            risk_level=kwargs.pop("risk_level", "high"),
            **kwargs,
        )

    def request_contract(self, title: str, description: str, **kwargs) -> dict:
        return self.request_action(
            action_type="legal",
            title=title,
            description=description,
            reversible=False,
            risk_level=kwargs.pop("risk_level", "critical"),
            **kwargs,
        )
