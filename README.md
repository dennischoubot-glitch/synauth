# SynAuth SDK

Python SDK for AI agents to request human-approved actions. Two approval methods: **TOTP** (any authenticator app) or **Face ID** (SynAuth iOS app).

## Install

```bash
pip install synauth
```

## Two Ways to Get Started

### Option A: TOTP (No iOS App Required)

Use any TOTP authenticator (Google Authenticator, Authy, Apple Passwords, 1Password). **Time to first approval: ~5 minutes.**

```python
from synauth import SynAuthAdmin, SynAuthClient

# 1. Create account via magic link
result = SynAuthAdmin.request_magic_link("you@example.com")

# 2. Verify and register your device
device = SynAuthAdmin.verify_magic_link(result["token"], "My Laptop")
admin = SynAuthAdmin(device_id=device["device_id"])

# 3. Set up TOTP — scan the QR code with your authenticator app
setup = admin.totp_setup()
print(f"Add to authenticator: {setup['provisioning_uri']}")

# 4. Verify TOTP with a code from your authenticator
admin.totp_verify("123456")  # replace with actual code

# 5. Create an API key for your agent
key = admin.create_key("my-agent", "Research Agent")
print(f"API key (save this!): {key['key']}")
```

### Option B: Face ID (iOS App)

1. **Get the SynAuth iOS app** from the App Store. Create an account.
2. **Copy your API key** from the app — it starts with `aa_`.

## Quick Start — Agent Side

```python
from synauth import SynAuthClient

client = SynAuthClient(api_key="aa_your_key_here")

# Agent requests approval for an action
result = client.request_action(
    action_type="communication",
    title="Send quarterly report",
    description="Email to investor@example.com with Q4 results",
    risk_level="low",
)

# Agent waits for human approval (TOTP or Face ID)
status = client.wait_for_result(result["id"])
if status["status"] == "approved":
    send_email(...)
```

## Approving Actions with TOTP

```python
from synauth import SynAuthAdmin

admin = SynAuthAdmin(device_id="dev_your_device_id")

# See what's pending
pending = admin.get_pending()
for action in pending["actions"]:
    print(f"{action['id']}: {action['title']}")

# Approve with your TOTP code
admin.approve("action_id_here", totp_code="123456")

# Or deny
admin.deny("action_id_here", reason="Not authorized")
```

## How It Works

1. Your AI agent calls `request_action()` (or a convenience method like `request_email()`)
2. The action goes pending on SynAuth
3. You approve via TOTP code or Face ID on your iPhone
4. The agent polls for the result — or receives a webhook callback
5. If using the credential vault, SynAuth executes the action with stored credentials

## API Key Management

```python
admin = SynAuthAdmin(device_id="dev_your_device_id")

# Create keys for your agents
key = admin.create_key("trading-agent", "Trading Bot")

# List active keys (values hidden — only prefixes)
keys = admin.list_keys()
for k in keys["keys"]:
    print(f"{k['key_prefix']} — {k['name']} ({k['agent_id']})")

# Revoke a compromised key
admin.revoke_key("aa_abc12")
```

## TOTP Management

```python
admin = SynAuthAdmin(device_id="dev_your_device_id")

# Check TOTP status
status = admin.totp_status()
print(f"TOTP enabled: {status['enabled']}")

# Reset TOTP (delete and re-setup)
admin.totp_delete()
setup = admin.totp_setup()
admin.totp_verify("654321")
```

## Credential Vault

**The agent can't bypass what it can't access.** Store your API credentials in SynAuth's vault. The agent requests actions through the SDK — SynAuth injects the real credentials after approval. The agent never sees your API keys.

```python
# Discover available services
services = client.list_vault_services()

# Execute an API call through the vault (approval-gated)
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

| Class | Auth | Purpose |
|-------|------|---------|
| `SynAuthClient(api_key)` | API key (`aa_...`) | Agent-facing: request actions, poll status, vault |
| `SynAuthAdmin(device_id)` | Device ID (`dev_...`) | Developer-facing: TOTP, keys, approve/deny |

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_url` | `https://synauth.fly.dev` | SynAuth backend URL (override for self-hosted) |

## Examples

Runnable examples in the [`examples/`](examples/) directory:

- **[`quickstart_totp.py`](examples/quickstart_totp.py)** — End-to-end TOTP setup: account creation → device registration → TOTP setup → API key → first approved action. Interactive, ~5 minutes.
- **[`agent_example.py`](examples/agent_example.py)** — A research agent that gates sensitive operations (email, trades, Slack posts) through SynAuth approval. Shows the approval loop pattern, WYSIWYS verification, and error handling. Try `--dry-run` first.

### Framework Integrations

- **[`langchain_tool.py`](examples/langchain_tool.py)** — SynAuth as a LangChain tool. Wrap biometric approval into any LangChain agent — the agent reasons freely but can't act without human verification. Supports both basic approval and WYSIWYS (content-verified) actions.
- **[`crewai_tool.py`](examples/crewai_tool.py)** — SynAuth tools for CrewAI crews. Three tools: `RequestApprovalTool` (basic), `WYSIWYSApprovalTool` (content-verified), `CheckSpendingTool` (budget check). Gate any crew member's actions through biometric approval.

All examples support `--dry-run` to show the flow without making API calls.

## Also Available

- **[synauth-mcp](https://pypi.org/project/synauth-mcp/)** — MCP server for Claude and other MCP-compatible agents
- **SynAuth iOS App** — Face ID approval on your iPhone

## License

MIT
