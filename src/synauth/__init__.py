"""SynAuth SDK — Biometric approval for AI agent actions."""

__version__ = "0.1.0"

from synauth.client import (
    SynAuthClient,
    SynAuthError,
    SynAuthAPIError,
    RateLimitError,
    ActionExpiredError,
    ActionDeniedError,
    VaultExecutionError,
)
from synauth.pay import SynPayClient

# Backward compatibility
AgentAuthClient = SynAuthClient
