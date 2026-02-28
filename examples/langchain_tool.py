#!/usr/bin/env python3
"""
SynAuth + LangChain — Biometric approval as an agent tool.

This wraps SynAuth as a LangChain tool so any LangChain agent can gate
sensitive actions through human approval (Face ID or TOTP).

Pattern:
  1. Agent reasons about what to do (LangChain handles this)
  2. Agent decides to take a sensitive action
  3. Agent calls the SynAuth tool → human gets a notification
  4. Human approves (Face ID / TOTP) or denies
  5. Agent receives the result and proceeds (or handles denial)

Prerequisites:
  pip install synauth langchain langchain-openai

  export SYNAUTH_API_KEY="aa_your_key_here"
  export OPENAI_API_KEY="sk-..."  # or use any LangChain-supported LLM

Usage:
  python langchain_tool.py                # run with a real LLM
  python langchain_tool.py --dry-run      # show the tool without LLM calls

Why this matters:
  LangChain agents can call any tool autonomously. Without SynAuth, there's
  no verification that a human approved the action. With SynAuth, the agent
  can reason freely but can't ACT without biometric proof.
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


# ─── SynAuth LangChain Tool ──────────────────────────────────────

# Import LangChain at module level for type checking.
# The actual tool class works with or without LangChain installed
# (the dry-run mode doesn't need it).
try:
    from langchain_core.tools import BaseTool
    from pydantic import BaseModel, Field

    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    # Stub for when LangChain isn't installed
    BaseTool = object

    class BaseModel:
        pass

    class Field:
        @staticmethod
        def __call__(*args, **kwargs):
            return None


if LANGCHAIN_AVAILABLE:

    class SynAuthApprovalInput(BaseModel):
        """Input schema for the SynAuth approval tool."""

        action_type: str = Field(
            description=(
                "Category of action: 'communication' (emails, messages), "
                "'purchase' (payments, subscriptions), 'data_access' (databases, files), "
                "'contract' (legal, signing), 'system' (infrastructure, deployments)."
            )
        )
        title: str = Field(
            description="Short description of what you want to do (shown to the human approver)."
        )
        description: str = Field(
            description="Detailed explanation of the action and why it's needed."
        )
        risk_level: str = Field(
            default="medium",
            description="Risk level: 'low', 'medium', 'high', or 'critical'.",
        )
        parameters: Optional[str] = Field(
            default=None,
            description=(
                "JSON string of exact parameters for the action (enables WYSIWYS — "
                "What You See Is What You Sign). The human sees these exact parameters "
                "and the content hash proves no bait-and-switch. Use for financial "
                "transactions, API calls, or any action where exact parameters matter."
            ),
        )

    class SynAuthApprovalTool(BaseTool):
        """LangChain tool that gates agent actions through SynAuth biometric approval.

        Add this tool to any LangChain agent. When the agent decides to take a
        sensitive action, it calls this tool — the human gets a notification and
        approves or denies via Face ID or TOTP.

        Example:
            from langchain_tool import SynAuthApprovalTool
            from langchain.agents import AgentExecutor, create_openai_tools_agent

            tool = SynAuthApprovalTool(api_key="aa_...")
            agent = create_openai_tools_agent(llm, [tool, ...], prompt)
            executor = AgentExecutor(agent=agent, tools=[tool, ...])
            executor.invoke({"input": "Send the quarterly report to investors"})
        """

        name: str = "request_human_approval"
        description: str = (
            "Request human approval for a sensitive action. The human receives a "
            "notification and approves or denies via Face ID or TOTP code. Use this "
            "BEFORE executing any action that sends data, spends money, modifies "
            "systems, or has real-world consequences. Returns 'approved', 'denied', "
            "or 'expired'. If 'parameters' is provided, WYSIWYS verification ensures "
            "the human sees exactly what will be executed."
        )
        args_schema: type = SynAuthApprovalInput

        # Instance attributes
        client: SynAuthClient = None
        timeout: int = 120

        class Config:
            arbitrary_types_allowed = True

        def __init__(
            self,
            api_key: str = None,
            base_url: str = "https://synauth.fly.dev",
            timeout: int = 120,
            **kwargs,
        ):
            """Initialize with SynAuth credentials.

            Args:
                api_key: SynAuth API key (starts with 'aa_'). Falls back to
                    SYNAUTH_API_KEY env var.
                base_url: SynAuth backend URL.
                timeout: Seconds to wait for human approval before timing out.
            """
            super().__init__(**kwargs)
            key = api_key or os.environ.get("SYNAUTH_API_KEY")
            if not key:
                raise ValueError(
                    "SynAuth API key required. Pass api_key= or set SYNAUTH_API_KEY env var."
                )
            self.client = SynAuthClient(api_key=key, base_url=base_url)
            self.timeout = timeout

        def _run(
            self,
            action_type: str,
            title: str,
            description: str,
            risk_level: str = "medium",
            parameters: Optional[str] = None,
        ) -> str:
            """Request human approval for an action.

            Returns a JSON string with the approval result:
              {"status": "approved", "id": "...", "verified_by": "..."}
              {"status": "denied", "id": "...", "reason": "..."}
              {"status": "expired", "id": "..."}
              {"status": "error", "detail": "..."}
            """
            try:
                # If parameters provided, use WYSIWYS for content verification
                if parameters:
                    try:
                        params = json.loads(parameters)
                    except json.JSONDecodeError:
                        return json.dumps(
                            {"status": "error", "detail": "Invalid JSON in parameters"}
                        )

                    action = self.client.wysiwys_action(
                        action_type=action_type,
                        params=params,
                        title=title,
                        risk_level=risk_level,
                    )
                else:
                    action = self.client.request_action(
                        action_type=action_type,
                        title=title,
                        description=description,
                        risk_level=risk_level,
                    )

                # If already resolved (auto-approve/deny by rules engine)
                if action["status"] != "pending":
                    return json.dumps(
                        {
                            "status": action["status"],
                            "id": action["id"],
                        }
                    )

                # Wait for human approval
                result = self.client.wait_for_result(
                    action["id"],
                    timeout=self.timeout,
                    poll_interval=2.0,
                )
                return json.dumps(
                    {
                        "status": result["status"],
                        "id": action["id"],
                        "verified_by": result.get("verified_by"),
                    }
                )

            except ActionDeniedError as e:
                return json.dumps(
                    {"status": "denied", "id": e.request_id, "reason": str(e.reason)}
                )
            except ActionExpiredError as e:
                return json.dumps({"status": "expired", "id": e.request_id})
            except ApprovalTimeoutError as e:
                return json.dumps(
                    {
                        "status": "timeout",
                        "id": e.request_id,
                        "detail": f"No response within {self.timeout}s",
                    }
                )
            except SynAuthAPIError as e:
                return json.dumps(
                    {"status": "error", "detail": f"API error {e.status_code}: {e.detail}"}
                )
            except Exception as e:
                return json.dumps({"status": "error", "detail": str(e)})


# ─── Example: Agent with SynAuth approval ────────────────────────


def run_agent_example():
    """Run a LangChain agent that uses SynAuth for approval."""
    if not LANGCHAIN_AVAILABLE:
        print("Error: langchain not installed. Run: pip install langchain langchain-openai")
        sys.exit(1)

    api_key = os.environ.get("SYNAUTH_API_KEY")
    if not api_key:
        print("Error: SYNAUTH_API_KEY not set.")
        print("  export SYNAUTH_API_KEY='aa_your_key_here'")
        sys.exit(1)

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        print("Error: OPENAI_API_KEY not set.")
        print("  export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain.agents import AgentExecutor, create_openai_tools_agent

    # Create the SynAuth tool
    approval_tool = SynAuthApprovalTool(api_key=api_key)

    # Create the agent
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a helpful assistant. Before taking any action that sends "
                "data, spends money, or modifies systems, you MUST use the "
                "request_human_approval tool to get explicit human approval. "
                "Never skip the approval step for consequential actions.",
            ),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )

    agent = create_openai_tools_agent(llm, [approval_tool], prompt)
    executor = AgentExecutor(agent=agent, tools=[approval_tool], verbose=True)

    # Run it
    result = executor.invoke(
        {"input": "Send a summary email to team@company.com about our Q4 results"}
    )
    print(f"\nAgent result: {result['output']}")


def run_dry_run():
    """Show what the tool does without making API calls."""
    print("SynAuth + LangChain Integration")
    print("=" * 50)
    print()
    print("The SynAuthApprovalTool wraps SynAuth as a LangChain tool.")
    print("Any LangChain agent can use it to gate sensitive actions.\n")

    print("Tool definition:")
    print(f"  name: request_human_approval")
    print(f"  inputs: action_type, title, description, risk_level, parameters")
    print(f"  output: JSON with status (approved/denied/expired/error)\n")

    print("Agent flow:")
    print("  1. LLM reasons about the task")
    print("  2. LLM decides to send an email → calls request_human_approval")
    print('     → action_type="communication", title="Send Q4 report",')
    print('       description="Email to team@company.com with Q4 results"')
    print("  3. SynAuth sends notification to your phone")
    print("  4. You approve with Face ID / TOTP")
    print('  5. Tool returns: {"status": "approved", "id": "..."}')
    print("  6. LLM proceeds with the action\n")

    print("WYSIWYS flow (for financial actions):")
    print("  1. LLM decides to execute a trade → calls request_human_approval")
    print('     → action_type="purchase",')
    print('       parameters=\'{"ticker":"NVDA","quantity":10,"price":189.50}\'')
    print("  2. You see EXACTLY these parameters on your phone")
    print("  3. Content hash proves no bait-and-switch")
    print("  4. You approve → agent executes with verified parameters\n")

    print("Usage:")
    print("  from langchain_tool import SynAuthApprovalTool")
    print('  tool = SynAuthApprovalTool(api_key="aa_...")')
    print("  # Add to any LangChain agent's tool list\n")

    print("To run with a real LLM:")
    print("  export SYNAUTH_API_KEY='aa_your_key_here'")
    print("  export OPENAI_API_KEY='sk-...'")
    print("  python langchain_tool.py")


# ─── Entry point ──────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="SynAuth + LangChain Example")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show tool definition and flow without making API calls",
    )
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run()
    else:
        run_agent_example()


if __name__ == "__main__":
    main()
