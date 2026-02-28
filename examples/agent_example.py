#!/usr/bin/env python3
"""
SynAuth Agent Example — Realistic Approval Loop

A research agent that gathers information and requests human approval before
taking consequential actions (sending emails, making API calls, posting content).

This demonstrates the real pattern for integrating SynAuth into an agent:
  - Low-risk actions: request and poll, handle approval/denial gracefully
  - WYSIWYS actions: content-verified requests where the user sees exactly
    what they're approving
  - Error handling: timeouts, denials, API errors
  - Multiple action types in a single workflow

Prerequisites:
  pip install synauth

  You need a SynAuth API key (run quickstart_totp.py first, or get one from
  the SynAuth iOS app). Set it as an environment variable:

    export SYNAUTH_API_KEY="aa_your_key_here"

  Optionally set the backend URL:
    export SYNAUTH_URL="https://synauth.fly.dev"  # default

Usage:
  python agent_example.py                 # run the full demo workflow
  python agent_example.py --dry-run       # show what would happen, no API calls
"""

import argparse
import json
import os
import sys
import time

from synauth import (
    SynAuthClient,
    SynAuthError,
    SynAuthAPIError,
    ActionDeniedError,
    ActionExpiredError,
    ApprovalTimeoutError,
    RateLimitError,
    compute_content_hash,
)


# ─── Simulated agent actions ──────────────────────────────────────
# In a real agent, these would be actual API calls, database queries, etc.


def send_email(to: str, subject: str, body: str):
    """Simulate sending an email."""
    print(f"    [SEND] Email to {to}: '{subject}'")
    return {"sent": True, "message_id": "msg_sim_001"}


def execute_trade(ticker: str, side: str, quantity: int, price: float):
    """Simulate executing a trade."""
    total = quantity * price
    print(f"    [TRADE] {side.upper()} {quantity}x {ticker} @ ${price:.2f} = ${total:.2f}")
    return {"filled": True, "order_id": "ord_sim_001", "total": total}


def post_to_slack(channel: str, message: str):
    """Simulate posting a Slack message."""
    print(f"    [SLACK] #{channel}: {message[:80]}...")
    return {"posted": True, "ts": "1234567890.123456"}


# ─── The agent ─────────────────────────────────────────────────────


class ResearchAgent:
    """A research agent that gates sensitive operations through SynAuth.

    The pattern:
      1. Agent does research (no approval needed — read-only)
      2. Agent decides to take action (write operation)
      3. Agent requests approval via SynAuth
      4. Human approves or denies (TOTP or Face ID)
      5. Agent executes or gracefully handles denial
    """

    def __init__(self, api_key: str, base_url: str = "https://synauth.fly.dev"):
        self.client = SynAuthClient(api_key=api_key, base_url=base_url)
        self.name = "Research Agent"

    def run_workflow(self):
        """Run a demo workflow showing different approval patterns."""

        print(f"\n{'─'*60}")
        print(f"  {self.name} — Starting workflow")
        print(f"{'─'*60}\n")

        # Phase 1: Research (no approval needed)
        print("Phase 1: Research (no approval required)\n")
        findings = self._do_research()
        print(f"  Found {len(findings)} items to act on.\n")

        # Phase 2: Send a summary email (basic approval)
        print("Phase 2: Send email summary (basic approval)\n")
        self._send_summary_email(findings)

        # Phase 3: Execute a trade (WYSIWYS — user sees exact parameters)
        print("\nPhase 3: Execute trade (WYSIWYS verification)\n")
        self._execute_trade(findings)

        # Phase 4: Post results to Slack (convenience method)
        print("\nPhase 4: Post to Slack (convenience method)\n")
        self._post_results()

        print(f"\n{'─'*60}")
        print(f"  Workflow complete")
        print(f"{'─'*60}\n")

    def _do_research(self) -> list:
        """Simulate research phase. No approvals — read-only operations."""
        print("  Scanning market data...")
        time.sleep(0.5)
        print("  Analyzing earnings reports...")
        time.sleep(0.5)
        print("  Cross-referencing with macro indicators...")
        time.sleep(0.5)

        return [
            {"ticker": "NVDA", "signal": "strong buy", "price": 189.50, "target": 220.00},
            {"ticker": "MSFT", "signal": "hold", "price": 415.20, "target": 430.00},
            {"ticker": "AAPL", "signal": "buy", "price": 245.80, "target": 270.00},
        ]

    def _send_summary_email(self, findings: list):
        """Request approval to send a summary email.

        Uses the basic request_action flow — good for simple actions where
        the user doesn't need to verify exact content parameters.
        """
        summary = ", ".join(f"{f['ticker']} ({f['signal']})" for f in findings)

        try:
            # Request the action
            action = self.client.request_email(
                recipient="team@example.com",
                subject="Daily Research Summary",
                preview=f"Signals: {summary}",
            )
            print(f"  Action requested: {action['id']}")
            print(f"  Status: {action['status']}")
            print(f"  Waiting for approval (check your authenticator)...\n")

            # Wait for human approval
            result = self.client.wait_for_result(
                action["id"],
                timeout=120,  # 2 minutes to approve
                poll_interval=3.0,
            )

            if result["status"] == "approved":
                print("  Approved! Sending email...")
                send_email("team@example.com", "Daily Research Summary", summary)
            elif result["status"] == "denied":
                print(f"  Denied. Reason: {result.get('deny_reason', 'none given')}")
                print("  Skipping email send.")
            elif result["status"] == "expired":
                print("  Request expired — no response in time.")

        except ApprovalTimeoutError:
            print("  Polling timed out. The request is still pending on the server.")
            print("  You can still approve it later — the agent would pick it up.")
        except RateLimitError:
            print("  Rate limited. Backing off...")
            time.sleep(5)
        except SynAuthAPIError as e:
            print(f"  API error: {e.detail}")

    def _execute_trade(self, findings: list):
        """Request approval to execute a trade using WYSIWYS.

        WYSIWYS (What You See Is What You Sign) ensures the user sees the
        exact trade parameters. The content hash proves the displayed
        parameters match what will be executed. No bait-and-switch.
        """
        # Pick the strongest signal
        pick = max(findings, key=lambda f: f["target"] / f["price"])
        trade_params = {
            "ticker": pick["ticker"],
            "side": "buy",
            "quantity": 10,
            "price": pick["price"],
            "total": 10 * pick["price"],
        }

        try:
            # WYSIWYS action — user sees exact parameters
            action = self.client.wysiwys_action(
                action_type="purchase",
                params=trade_params,
                title=f"Buy {trade_params['quantity']}x {pick['ticker']}",
                risk_level="high",
            )
            print(f"  Action requested: {action['id']}")
            print(f"  Content hash: {action.get('content_hash', 'N/A')}")

            # Verify content hash locally (optional but recommended)
            expected_hash = compute_content_hash(trade_params)
            server_hash = action.get("content_hash")
            if server_hash and expected_hash == server_hash:
                print("  Content hash verified — parameters match.")
            elif server_hash:
                print("  WARNING: Content hash mismatch! Aborting.")
                return

            print(f"  Waiting for approval...\n")

            result = self.client.wait_for_result(action["id"], timeout=120)

            if result["status"] == "approved":
                print("  Approved! Executing trade...")
                execute_trade(**{k: v for k, v in trade_params.items() if k != "total"})
            elif result["status"] == "denied":
                reason = result.get("deny_reason", "none given")
                print(f"  Trade denied: {reason}")
            else:
                print(f"  Status: {result['status']}")

        except ActionDeniedError as e:
            print(f"  Trade denied by rules engine: {e.reason}")
        except ActionExpiredError:
            print("  Trade request expired.")
        except SynAuthAPIError as e:
            print(f"  API error: {e.detail}")

    def _post_results(self):
        """Request approval to post a Slack message.

        Uses WYSIWYS so the user sees the exact message content.
        """
        message = (
            "Daily research complete. "
            "3 tickers analyzed, 1 trade executed (NVDA 10x @ $189.50). "
            "Full report sent to team@example.com."
        )

        try:
            action = self.client.wysiwys_slack_message(
                channel="#trading-alerts",
                text=message,
            )
            print(f"  Action requested: {action['id']}")
            print(f"  Waiting for approval...\n")

            result = self.client.wait_for_result(action["id"], timeout=60)

            if result["status"] == "approved":
                print("  Approved! Posting to Slack...")
                post_to_slack("trading-alerts", message)
            else:
                print(f"  Status: {result['status']}")

        except (ActionDeniedError, ActionExpiredError, ApprovalTimeoutError) as e:
            print(f"  {type(e).__name__}: {e}")
        except SynAuthAPIError as e:
            print(f"  API error: {e.detail}")


# ─── Dry run mode ─────────────────────────────────────────────────


class DryRunAgent(ResearchAgent):
    """Same workflow, but prints what would happen without making API calls."""

    def __init__(self):
        self.name = "Research Agent (dry run)"
        self.client = None

    def run_workflow(self):
        print(f"\n{'─'*60}")
        print(f"  {self.name} — Showing workflow without API calls")
        print(f"{'─'*60}\n")

        print("Phase 1: Research (no approval required)")
        print("  Agent scans market data, analyzes earnings, cross-references.\n")

        print("Phase 2: Send email summary")
        print("  → client.request_email(to='team@example.com', subject='Daily Research Summary')")
        print("  → client.wait_for_result(action_id, timeout=120)")
        print("  → If approved: send_email(...)")
        print("  → If denied: skip\n")

        print("Phase 3: Execute trade (WYSIWYS)")
        trade_params = {"ticker": "NVDA", "side": "buy", "quantity": 10, "price": 189.50, "total": 1895.00}
        content_hash = compute_content_hash(trade_params)
        print(f"  → client.wysiwys_action(action_type='purchase', params={json.dumps(trade_params)})")
        print(f"  → Content hash: {content_hash}")
        print("  → If approved: execute_trade(...)")
        print("  → If denied: abort\n")

        print("Phase 4: Post to Slack (WYSIWYS)")
        print("  → client.wysiwys_slack_message(channel='#trading-alerts', text='...')")
        print("  → If approved: post_to_slack(...)\n")

        print("To run this for real:")
        print("  export SYNAUTH_API_KEY='aa_your_key_here'")
        print("  python agent_example.py\n")


# ─── Entry point ───────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="SynAuth Agent Example")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show workflow without making API calls",
    )
    parser.add_argument(
        "--base-url", default=None,
        help="SynAuth backend URL (default: SYNAUTH_URL env or https://synauth.fly.dev)",
    )
    args = parser.parse_args()

    if args.dry_run:
        agent = DryRunAgent()
        agent.run_workflow()
        return

    api_key = os.environ.get("SYNAUTH_API_KEY")
    if not api_key:
        print("Error: SYNAUTH_API_KEY environment variable not set.")
        print()
        print("Get an API key:")
        print("  1. Run quickstart_totp.py to set up an account and get a key")
        print("  2. Or copy your key from the SynAuth iOS app")
        print()
        print("Then: export SYNAUTH_API_KEY='aa_your_key_here'")
        print()
        print("Or try: python agent_example.py --dry-run")
        sys.exit(1)

    base_url = args.base_url or os.environ.get("SYNAUTH_URL", "https://synauth.fly.dev")

    agent = ResearchAgent(api_key=api_key, base_url=base_url)
    agent.run_workflow()


if __name__ == "__main__":
    main()
