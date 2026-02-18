# SynAuth SDK

Python SDK for AI agents to request biometric-approved actions. Every sensitive action your AI agent takes — sending emails, making purchases, accessing data, signing contracts — goes through Face ID verification on your iPhone.

## Install

```bash
pip install synauth
```

## Setup

1. **Get the SynAuth iOS app** from the App Store. Create an account.
2. **Copy your API key** from the app — it starts with `aa_`.
3. **(Optional) Store credentials in the vault** — add your API keys (OpenAI, GitHub, Stripe, etc.) in the Vault tab. This lets agents use these services without ever seeing the keys.

## Quick Start

```python
from synauth import SynAuthClient

client = SynAuthClient(api_key="aa_your_key_here")

# Request approval for an action
result = client.request_action(
    action_type="communication",
    title="Send quarterly report",
    description="Email to investor@example.com with Q4 results",
    risk_level="low",
)

# Wait for Face ID approval
status = client.wait_for_result(result["id"])
if status["status"] == "approved":
    send_email(...)
```

## How It Works

1. Your AI agent calls `request_action()` (or a convenience method like `request_email()`)
2. SynAuth sends a push notification to the user's iPhone
3. The user verifies with Face ID
4. The agent polls for the result — or receives a webhook callback
5. If using the credential vault, SynAuth executes the action with stored credentials

## Credential Vault

**The agent can't bypass what it can't access.** Store your API credentials in SynAuth's vault. The agent requests actions through the SDK — SynAuth injects the real credentials after biometric approval. The agent never sees your API keys.

```python
# Discover available services
services = client.list_vault_services()

# Execute an API call through the vault (biometric-gated)
result = client.execute_api_call(
    service_name="openai",
    method="POST",
    url="https://api.openai.com/v1/chat/completions",
    body='{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}',
)
```

## Convenience Methods

```python
# Email
client.request_email(recipient="team@co.com", subject="Update", preview="Q4 numbers")

# Purchase
client.request_purchase(amount=49.99, merchant="DigitalOcean", description="3x droplets")

# Booking
client.request_booking(title="Team lunch", description="12pm at Nobu", amount=850.00)

# Social media
client.request_post(platform="Twitter", content_preview="Announcing our Series A...")

# Data access
client.request_data_access(resource="production-db", reason="Monthly analytics export")

# Legal
client.request_contract(title="NDA with Acme Corp", description="Standard mutual NDA")
```

## Payment-Only Wrapper

For agents that only need payment authorization:

```python
from synauth.pay import SynPayClient

client = SynPayClient(api_key="aa_your_key_here")

request = client.request_payment(
    amount=29.99,
    merchant="OpenAI",
    description="GPT-5 API credits",
)
status = client.wait_for_result(request["id"])
```

## Error Handling

```python
from synauth import (
    SynAuthClient,
    SynAuthError,
    SynAuthAPIError,
    RateLimitError,
    ActionDeniedError,
    ActionExpiredError,
    VaultExecutionError,
)

client = SynAuthClient(api_key="aa_...")

try:
    result = client.execute_api_call(
        service_name="github",
        method="POST",
        url="https://api.github.com/repos",
        body='{"name": "new-repo"}',
    )
except ActionDeniedError as e:
    print(f"User denied: {e.reason}")
except ActionExpiredError as e:
    print(f"Request expired: {e.request_id}")
except RateLimitError:
    print("Rate limited — back off and retry")
except VaultExecutionError as e:
    print(f"Vault execution failed: {e.detail}")
except SynAuthAPIError as e:
    print(f"API error {e.status_code}: {e.detail}")
```

## Spending Limits

Check your agent's spending against configured limits before making purchases:

```python
summary = client.get_spending_summary()
for s in summary["summaries"]:
    print(f"{s['action_type']} ({s['period']}): ${s['spent']:.2f} / ${s['limit']:.2f}")
```

## History

Review past action requests:

```python
history = client.get_history(limit=10, status="approved")
for action in history["actions"]:
    print(f"{action['title']} — {action['status']}")
```

## Webhook Callbacks

Receive status updates without polling:

```python
result = client.request_action(
    action_type="purchase",
    title="Buy API credits",
    amount=100.00,
    callback_url="https://your-server.com/webhook/synauth",
)
# SynAuth will POST to callback_url when the user approves or denies
```

## Action Types

| Type | Examples | Default Risk |
|------|----------|-------------|
| `communication` | Emails, messages, notifications | low |
| `purchase` | Buying, subscriptions, payments | medium |
| `scheduling` | Bookings, reservations, calendar | low |
| `legal` | Contracts, terms, agreements | critical |
| `data_access` | Database queries, file downloads | high |
| `social` | Social media posts, profile updates | medium |
| `system` | Config changes, restarts, deployments | high |

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `api_key` | *(required)* | Your SynAuth API key (`aa_...`) |
| `base_url` | `https://synauth.fly.dev` | SynAuth backend URL (override for self-hosted) |

## Also Available

- **[synauth-mcp](https://pypi.org/project/synauth-mcp/)** — MCP server for Claude and other MCP-compatible agents
- **SynAuth iOS App** — Face ID approval on your iPhone

## License

MIT
