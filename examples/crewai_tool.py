#!/usr/bin/env python3
"""
SynAuth + CrewAI — Biometric approval for AI crew actions.

This wraps SynAuth as a CrewAI tool so any agent in a crew can gate
sensitive actions through human approval (Face ID or TOTP).

Pattern:
  1. CrewAI agent receives a task
  2. Agent decides to take a sensitive action (email, purchase, API call)
  3. Agent uses the SynAuth tool → human gets a notification
  4. Human approves (Face ID / TOTP) or denies
  5. Agent receives the result and reports back to the crew

Prerequisites:
  pip install synauth crewai crewai-tools

  export SYNAUTH_API_KEY="aa_your_key_here"
  export OPENAI_API_KEY="sk-..."  # CrewAI uses OpenAI by default

Usage:
  python crewai_tool.py                # run with a real crew
  python crewai_tool.py --dry-run      # show the tools without making calls

Why this matters:
  CrewAI crews can have multiple agents working autonomously. Without SynAuth,
  any agent can act without verification. With SynAuth, agents can plan freely
  but require biometric proof before executing consequential actions. The human
  stays in the loop without being in the way.
"""

import argparse
import json
import os
import sys
from typing import Optional

from synauth import (
    SynAuthClient,
    ApprovalTimeoutError,
    ActionDeniedError,
    ActionExpiredError,
    SynAuthAPIError,
    compute_content_hash,
)

# ─── SynAuth CrewAI Tools ────────────────────────────────────────

try:
    from crewai.tools import BaseTool as CrewAIBaseTool
    from pydantic import BaseModel, Field

    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    CrewAIBaseTool = object

    class BaseModel:
        pass

    class Field:
        @staticmethod
        def __call__(*args, **kwargs):
            return None


def _get_client(api_key: str = None, base_url: str = "https://synauth.fly.dev") -> SynAuthClient:
    """Create a SynAuth client from explicit key or environment."""
    key = api_key or os.environ.get("SYNAUTH_API_KEY")
    if not key:
        raise ValueError(
            "SynAuth API key required. Pass api_key= or set SYNAUTH_API_KEY env var."
        )
    return SynAuthClient(api_key=key, base_url=base_url)


if CREWAI_AVAILABLE:

    class RequestApprovalInput(BaseModel):
        """Input for requesting human approval."""

        action_type: str = Field(
            description=(
                "Category: 'communication', 'purchase', 'data_access', "
                "'contract', or 'system'."
            )
        )
        title: str = Field(description="What the action is (shown to the approver).")
        description: str = Field(description="Why this action is needed.")
        risk_level: str = Field(
            default="medium", description="Risk: 'low', 'medium', 'high', 'critical'."
        )

    class RequestApprovalTool(CrewAIBaseTool):
        """Request human approval for a sensitive action.

        Use this before executing any action that sends data, spends money,
        modifies systems, or has real-world consequences. The human receives
        a notification and approves or denies via Face ID or TOTP.
        """

        name: str = "request_human_approval"
        description: str = (
            "Request biometric human approval before taking a sensitive action. "
            "Returns 'approved', 'denied', or 'expired'. Always use this before "
            "sending emails, making payments, modifying data, or calling external APIs."
        )
        args_schema: type = RequestApprovalInput

        client: SynAuthClient = None
        timeout: int = 120

        class Config:
            arbitrary_types_allowed = True

        def __init__(self, api_key: str = None, base_url: str = "https://synauth.fly.dev", **kwargs):
            super().__init__(**kwargs)
            self.client = _get_client(api_key, base_url)

        def _run(
            self,
            action_type: str,
            title: str,
            description: str,
            risk_level: str = "medium",
        ) -> str:
            try:
                action = self.client.request_action(
                    action_type=action_type,
                    title=title,
                    description=description,
                    risk_level=risk_level,
                )

                if action["status"] != "pending":
                    return json.dumps({"status": action["status"], "id": action["id"]})

                result = self.client.wait_for_result(
                    action["id"], timeout=self.timeout, poll_interval=2.0
                )
                return json.dumps(
                    {
                        "status": result["status"],
                        "id": action["id"],
                        "verified_by": result.get("verified_by"),
                    }
                )

            except ActionDeniedError as e:
                return json.dumps({"status": "denied", "reason": str(e.reason)})
            except (ActionExpiredError, ApprovalTimeoutError):
                return json.dumps({"status": "expired"})
            except SynAuthAPIError as e:
                return json.dumps({"status": "error", "detail": f"{e.status_code}: {e.detail}"})

    class WYSIWYSApprovalInput(BaseModel):
        """Input for WYSIWYS (What You See Is What You Sign) approval."""

        action_type: str = Field(
            description="Category: 'purchase', 'communication', 'system', etc."
        )
        title: str = Field(description="What the action is.")
        parameters: str = Field(
            description=(
                "JSON string of exact parameters for the action. The human will see "
                "these exact values — a content hash proves no bait-and-switch. "
                "Example: '{\"ticker\": \"NVDA\", \"quantity\": 10, \"price\": 189.50}'"
            )
        )
        risk_level: str = Field(default="high", description="Risk level.")

    class WYSIWYSApprovalTool(CrewAIBaseTool):
        """Request WYSIWYS-verified human approval for high-stakes actions.

        WYSIWYS = What You See Is What You Sign. The human sees the exact
        parameters that will be executed, and a cryptographic hash proves
        the displayed content matches the execution content. Use this for
        financial transactions, API calls with specific parameters, or any
        action where the exact details matter.
        """

        name: str = "request_verified_approval"
        description: str = (
            "Request WYSIWYS (What You See Is What You Sign) approval for a "
            "high-stakes action. The human sees the exact parameters and a content "
            "hash proves no bait-and-switch. Use for financial transactions, specific "
            "API calls, or any action where exact parameters must be verified."
        )
        args_schema: type = WYSIWYSApprovalInput

        client: SynAuthClient = None
        timeout: int = 120

        class Config:
            arbitrary_types_allowed = True

        def __init__(self, api_key: str = None, base_url: str = "https://synauth.fly.dev", **kwargs):
            super().__init__(**kwargs)
            self.client = _get_client(api_key, base_url)

        def _run(
            self,
            action_type: str,
            title: str,
            parameters: str,
            risk_level: str = "high",
        ) -> str:
            try:
                params = json.loads(parameters)
            except json.JSONDecodeError:
                return json.dumps({"status": "error", "detail": "Invalid JSON in parameters"})

            try:
                action = self.client.wysiwys_action(
                    action_type=action_type,
                    params=params,
                    title=title,
                    risk_level=risk_level,
                )

                if action["status"] != "pending":
                    return json.dumps({"status": action["status"], "id": action["id"]})

                result = self.client.wait_for_result(
                    action["id"], timeout=self.timeout, poll_interval=2.0
                )
                return json.dumps(
                    {
                        "status": result["status"],
                        "id": action["id"],
                        "content_hash": action.get("content_hash"),
                        "verified_by": result.get("verified_by"),
                    }
                )

            except ActionDeniedError as e:
                return json.dumps({"status": "denied", "reason": str(e.reason)})
            except (ActionExpiredError, ApprovalTimeoutError):
                return json.dumps({"status": "expired"})
            except SynAuthAPIError as e:
                return json.dumps({"status": "error", "detail": f"{e.status_code}: {e.detail}"})

    class CheckSpendingInput(BaseModel):
        """Input for checking spending limits."""
        pass  # No inputs needed

    class CheckSpendingTool(CrewAIBaseTool):
        """Check remaining budget before making purchases.

        Returns spending summaries grouped by action type and period.
        Use this before requesting purchase approval to verify budget.
        """

        name: str = "check_spending_budget"
        description: str = (
            "Check remaining spending budget. Returns how much budget remains "
            "for each action type (daily, weekly, monthly limits). Use before "
            "making purchase requests to verify the budget is available."
        )
        args_schema: type = CheckSpendingInput

        client: SynAuthClient = None

        class Config:
            arbitrary_types_allowed = True

        def __init__(self, api_key: str = None, base_url: str = "https://synauth.fly.dev", **kwargs):
            super().__init__(**kwargs)
            self.client = _get_client(api_key, base_url)

        def _run(self) -> str:
            try:
                summary = self.client.get_spending_summary()
                return json.dumps(summary)
            except SynAuthAPIError as e:
                return json.dumps({"error": f"{e.status_code}: {e.detail}"})


# ─── Example: Research crew with SynAuth ──────────────────────────


def run_crew_example():
    """Run a CrewAI crew that uses SynAuth for approval."""
    if not CREWAI_AVAILABLE:
        print("Error: crewai not installed. Run: pip install crewai crewai-tools")
        sys.exit(1)

    api_key = os.environ.get("SYNAUTH_API_KEY")
    if not api_key:
        print("Error: SYNAUTH_API_KEY not set.")
        print("  export SYNAUTH_API_KEY='aa_your_key_here'")
        sys.exit(1)

    from crewai import Agent, Task, Crew

    # Create the tools
    approval_tool = RequestApprovalTool(api_key=api_key)
    wysiwys_tool = WYSIWYSApprovalTool(api_key=api_key)
    spending_tool = CheckSpendingTool(api_key=api_key)

    # Create agents
    researcher = Agent(
        role="Market Researcher",
        goal="Find actionable investment opportunities",
        backstory=(
            "You are an experienced market researcher who analyzes financial data "
            "and identifies investment opportunities. You are thorough and evidence-based."
        ),
        tools=[],  # Research doesn't need approval
        verbose=True,
    )

    executor = Agent(
        role="Trade Executor",
        goal="Execute approved trades and communicate results",
        backstory=(
            "You execute financial actions ONLY after receiving explicit human approval. "
            "You ALWAYS use the request_human_approval or request_verified_approval tool "
            "before taking any action. You check spending budgets before purchases. "
            "You never skip the approval step."
        ),
        tools=[approval_tool, wysiwys_tool, spending_tool],
        verbose=True,
    )

    # Create tasks
    research_task = Task(
        description=(
            "Research the current market conditions for NVDA, MSFT, and AAPL. "
            "Provide a brief analysis of each with a buy/hold/sell recommendation."
        ),
        expected_output="Analysis of each stock with recommendation and reasoning.",
        agent=researcher,
    )

    execution_task = Task(
        description=(
            "Based on the research, execute the strongest buy recommendation. "
            "First check the spending budget, then request WYSIWYS-verified approval "
            "for the trade with exact parameters (ticker, quantity, price). "
            "After approval, send a summary email to team@company.com."
        ),
        expected_output="Confirmation of executed trade and sent email.",
        agent=executor,
        context=[research_task],
    )

    # Run the crew
    crew = Crew(
        agents=[researcher, executor],
        tasks=[research_task, execution_task],
        verbose=True,
    )

    result = crew.kickoff()
    print(f"\nCrew result:\n{result}")


def run_dry_run():
    """Show what the tools do without making API calls."""
    print("SynAuth + CrewAI Integration")
    print("=" * 50)
    print()
    print("Three tools for CrewAI agents:\n")

    print("1. RequestApprovalTool — Basic approval")
    print("   name: request_human_approval")
    print("   inputs: action_type, title, description, risk_level")
    print("   Use for: emails, data access, system changes\n")

    print("2. WYSIWYSApprovalTool — Content-verified approval")
    print("   name: request_verified_approval")
    print("   inputs: action_type, title, parameters (JSON), risk_level")
    print("   Use for: financial transactions, API calls with specific params")
    print("   The human sees EXACT parameters; content hash prevents tampering\n")

    print("3. CheckSpendingTool — Budget check")
    print("   name: check_spending_budget")
    print("   inputs: (none)")
    print("   Use before purchases to verify budget availability\n")

    print("Crew flow:")
    print("  1. Researcher agent analyzes market data (no approval needed)")
    print('  2. Executor agent decides to buy NVDA → calls check_spending_budget')
    print("  3. Executor calls request_verified_approval:")
    print('     → parameters=\'{"ticker":"NVDA","quantity":10,"price":189.50}\'')
    print("  4. Human sees exact trade parameters on phone")
    print("  5. Human approves with Face ID → executor proceeds")
    print("  6. Executor sends email → calls request_human_approval")
    print("  7. Human approves → email sent\n")

    print("Usage:")
    print("  from crewai_tool import RequestApprovalTool, WYSIWYSApprovalTool")
    print()
    print("  approval = RequestApprovalTool()")
    print("  wysiwys = WYSIWYSApprovalTool()")
    print()
    print("  agent = Agent(")
    print('    role="Trade Executor",')
    print("    tools=[approval, wysiwys],")
    print("    ...  # CrewAI agent config")
    print("  )\n")

    print("To run with a real crew:")
    print("  export SYNAUTH_API_KEY='aa_your_key_here'")
    print("  export OPENAI_API_KEY='sk-...'")
    print("  python crewai_tool.py")


# ─── Entry point ──────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="SynAuth + CrewAI Example")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show tool definitions and flow without making calls",
    )
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run()
    else:
        run_crew_example()


if __name__ == "__main__":
    main()
