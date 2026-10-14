"""Settings for the Campus Customs agent team: paths, model, spend limits and per-agent tool access.

Every limit here is enforced in code. The prompts describe the same rules, but the code doesn't
rely on the model obeying them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent  # Homework 5
PROMPTS_DIR = BACKEND_DIR / "prompts"
AUDIT_PATH = ROOT / "output" / "audit_trail.json"
MCP_SERVER_SCRIPT = ROOT / "mcp_server" / "server.py"
WORKING_DB = ROOT / "data" / "campus_customs_new.db"

# The Portkey key lives in the project-root .env (AI Foundations/.env), or a .env inside Homework 5.
for candidate in (ROOT / ".env", ROOT.parent / ".env"):
    if candidate.exists():
        load_dotenv(candidate)
        break
else:
    load_dotenv()

# ---- Model: gpt-5.6-luna for every agent, never anything pricier (AGENTS.md) ----
ALLOWED_MODELS = {"gpt-5.6-luna"}
MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")
if MODEL_NAME not in ALLOWED_MODELS:
    raise RuntimeError(f"OPENAI_MODEL={MODEL_NAME!r} is not allowed. Every agent must use gpt-5.6-luna.")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.portkey.ai/v1")
REASONING_EFFORT = "low"      # cheapest useful reasoning; summaries go into the audit trail
REASONING_SUMMARY = "concise"
REQUEST_TIMEOUT_S = 120

# ---- Spend guardrails (whole team, per ticket) ----
TEAM_REQUEST_LIMIT = 40         # model requests across all agents for one ticket
TEAM_TOOL_CALL_LIMIT = 60       # tool calls across all agents for one ticket
TEAM_TOTAL_TOKENS_LIMIT = 400_000
PER_AGENT_STEP_LIMIT = 10       # model responses inside one agent run
MAX_DELEGATIONS_PER_TICKET = 8  # delegate() calls across the whole run
MAX_DEPTH = 2                   # Boss (0) -> specialist (1) -> specialist (2), no deeper
AUDIT_TRUNCATE = 600            # characters kept per argument/result in the audit trail

# ---- MCP server process (same server Claude Code uses via .mcp.json) ----
MCP_COMMAND = sys.executable    # the project venv's python
MCP_ENV = {
    "CAMPUS_CUSTOMS_DB": str(WORKING_DB),
    "FASTMCP_SHOW_SERVER_BANNER": "false",
}

# ---- Which MCP tools each agent may see (least privilege) ----
# approve_and_pay, reject_payment_request and reset_working_database are human-only and appear in
# no list. record_ticket_decision is called by the backend after it validates the Boss's output.
HUMAN_ONLY_TOOLS = {"approve_and_pay", "reject_payment_request", "reset_working_database"}
SYSTEM_TOOLS = {"record_ticket_decision"}

AGENT_TOOLS: dict[str, set[str]] = {
    "boss": {
        "list_open_tickets", "get_ticket", "check_customer_order_fulfillment", "check_rent_due_and_cash",
        "quote_bulk_order_discount", "get_cash_position", "list_payment_requests", "list_message_drafts",
    },
    "inventory": {
        "get_ticket", "check_stock", "list_vendors", "check_customer_order_fulfillment", "quote_bulk_order_discount",
    },
    "accounting": {
        "get_ticket", "get_cash_position", "list_payment_requests", "list_vendors", "check_stock",
        "check_rent_due_and_cash", "quote_bulk_order_discount",
        "prepare_invoice_payment", "prepare_rent_payment", "prepare_purchase_order",
    },
    "facilities": {
        "get_ticket", "get_lease", "check_rent_due_and_cash", "get_cash_position",
    },
    "customer_service": {
        "get_ticket", "check_customer_order_fulfillment", "check_stock", "quote_bulk_order_discount",
        "list_message_drafts", "draft_customer_message",
    },
}
assert not any(tools & (HUMAN_ONLY_TOOLS | SYSTEM_TOOLS) for tools in AGENT_TOOLS.values())

# Write tools whose "who did this" argument the backend fills in from the real agent identity.
IDENTITY_ARG = {
    "prepare_invoice_payment": "requested_by",
    "prepare_rent_payment": "requested_by",
    "prepare_purchase_order": "requested_by",
    "draft_customer_message": "drafted_by",
}
