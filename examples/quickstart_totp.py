#!/usr/bin/env python3
"""
SynAuth Quickstart — TOTP Setup to First Approved Action

This script walks through the complete SynAuth flow using TOTP authentication.
No iOS app needed — just a TOTP authenticator (Google Authenticator, Authy,
Apple Passwords, 1Password).

What this does:
  1. Creates an account via magic link
  2. Registers your machine as a device
  3. Sets up TOTP (you scan a QR code / enter the secret)
  4. Creates an API key for an agent
  5. The agent requests an action
  6. You approve it with a TOTP code
  7. The agent sees the approval and proceeds

Prerequisites:
  pip install synauth pyotp qrcode  # qrcode is optional, for terminal QR display

Usage:
  python quickstart_totp.py                          # interactive, against production
  python quickstart_totp.py --base-url http://localhost:8000  # local dev server

Time to first approval: ~5 minutes.
"""

import argparse
import sys
import time
import threading

from synauth import SynAuthAdmin, SynAuthClient, SynAuthAPIError


DEFAULT_BASE_URL = "https://synauth.fly.dev"


def print_step(n: int, title: str):
    print(f"\n{'='*60}")
    print(f"  Step {n}: {title}")
    print(f"{'='*60}\n")


def print_qr(uri: str):
    """Try to print a QR code in the terminal. Falls back to the URI."""
    try:
        import qrcode
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(uri)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        print("  (Install 'qrcode' for a scannable QR: pip install qrcode)")


def main():
    parser = argparse.ArgumentParser(description="SynAuth TOTP Quickstart")
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help=f"SynAuth backend URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--email", default=None,
        help="Email address for account creation (prompted if not provided)",
    )
    args = parser.parse_args()

    base_url = args.base_url
    print(f"SynAuth backend: {base_url}")

    # ─── Step 1: Create account via magic link ─────────────────────
    print_step(1, "Create Account")

    email = args.email or input("Enter your email address: ").strip()
    if not email:
        print("Email is required.")
        sys.exit(1)

    print(f"  Requesting magic link for {email}...")
    result = SynAuthAdmin.request_magic_link(email, base_url=base_url)
    print(f"  Magic link sent: {result.get('sent')}")

    # In dev mode, the token is returned directly.
    # In production, you'd get the token from the email.
    token = result.get("token")
    if not token:
        token = input("\n  Check your email. Paste the token here: ").strip()
    else:
        print(f"  Token (dev mode): {token[:20]}...")

    # ─── Step 2: Register device ───────────────────────────────────
    print_step(2, "Register Device")

    device_name = "Quickstart Script"
    device = SynAuthAdmin.verify_magic_link(token, device_name, base_url=base_url)
    device_id = device["device_id"]
    print(f"  Device registered: {device_id}")
    print(f"  Account: {device.get('account_id')}")

    admin = SynAuthAdmin(device_id=device_id, base_url=base_url)

    # ─── Step 3: Set up TOTP ──────────────────────────────────────
    print_step(3, "Set Up TOTP")

    try:
        setup = admin.totp_setup()
    except SynAuthAPIError as e:
        if e.status_code == 409:
            print("  TOTP is already configured for this device.")
            print("  Skipping setup — using existing TOTP configuration.")
            setup = None
        else:
            raise

    if setup:
        uri = setup["provisioning_uri"]
        secret = setup.get("secret", "")

        print("  Scan this QR code with your authenticator app:\n")
        print_qr(uri)
        print(f"\n  Provisioning URI: {uri}")
        if secret:
            print(f"  Manual entry secret: {secret}")

        # Verify the setup
        print("\n  Open your authenticator app and enter the 6-digit code.")
        code = input("  TOTP code: ").strip()
        admin.totp_verify(code)
        print("  TOTP verified successfully!")

    # ─── Step 4: Create an API key ─────────────────────────────────
    print_step(4, "Create API Key")

    agent_id = "quickstart-agent"
    key_result = admin.create_key(agent_id, "Quickstart Agent")
    api_key = key_result["key"]
    print(f"  API key created: {key_result['key_prefix']}...")
    print(f"  Agent ID: {agent_id}")
    print()
    print(f"  *** Save this key — it won't be shown again ***")
    print(f"  API key: {api_key}")

    # ─── Step 5: Agent requests an action ──────────────────────────
    print_step(5, "Agent Requests an Action")

    client = SynAuthClient(api_key=api_key, base_url=base_url)

    action = client.request_action(
        action_type="communication",
        title="Send quarterly report",
        description="Email Q4 results to investors@example.com",
        risk_level="low",
    )
    action_id = action["id"]
    print(f"  Action requested: {action_id}")
    print(f"  Status: {action['status']}")  # "pending"

    # ─── Step 6: Approve with TOTP ─────────────────────────────────
    print_step(6, "Approve the Action")

    # Start polling in a background thread so approval is non-blocking
    result_holder = {"result": None, "done": False}

    def poll_for_result():
        result_holder["result"] = client.wait_for_result(action_id, timeout=120)
        result_holder["done"] = True

    poller = threading.Thread(target=poll_for_result, daemon=True)
    poller.start()

    print(f"  Action ID to approve: {action_id}")
    print(f"  The agent is polling for your approval...\n")

    totp_code = input("  Enter your current TOTP code to approve: ").strip()
    admin.approve(action_id, totp_code=totp_code)
    print("  Approved!")

    # Wait for the poller to pick up the result
    poller.join(timeout=10)

    # ─── Step 7: Agent sees the result ─────────────────────────────
    print_step(7, "Agent Receives Result")

    if result_holder["done"]:
        result = result_holder["result"]
        print(f"  Status: {result['status']}")
        print(f"  Verified by: {result.get('verified_by', 'N/A')}")
    else:
        # Fallback: poll once more
        result = client.get_status(action_id)
        print(f"  Status: {result['status']}")

    # ─── Done ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  Quickstart complete!")
    print(f"{'='*60}")
    print()
    print("  What you've set up:")
    print(f"    Account email:  {email}")
    print(f"    Device ID:      {device_id}")
    print(f"    Agent API key:  {key_result['key_prefix']}...")
    print()
    print("  Next steps:")
    print("    - Use agent_example.py to see a realistic agent approval loop")
    print("    - Explore WYSIWYS methods for content-verified actions")
    print("    - Set up the credential vault for zero-trust API calls")
    print("    - Install synauth-mcp for Claude/MCP integration")


if __name__ == "__main__":
    main()
