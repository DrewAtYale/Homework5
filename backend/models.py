"""Pydantic data types for the Campus Customs agent team.

Shop facts never live here: they come from the MCP server (see mcp_server/models.py for the
tool return types). These types describe what the agents hand back to each other, what the
team returns for a ticket, and what each audit-trail step records.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
SpecialistName = Literal["inventory", "accounting", "facilities", "customer_service"]
TicketDecisionKind = Literal["resolved", "awaiting_human_approval", "deferred", "needs_human"]


# ---------- what agents return ----------

class Fact(BaseModel):
    """One fact an agent relies on, tied to the MCP tool that returned it."""
    label: str = Field(description="What the fact is, e.g. 'CC-TEE-WHITE S on hand'.")
    value: str = Field(description="The value exactly as the tool returned it, e.g. '0'.")
    source_tool: str = Field(description="The MCP tool that returned it, e.g. 'check_stock'.")


class SpecialistReport(BaseModel):
    """What Inventory, Accounting, Facilities or Customer Service hand back to whoever asked."""
    agent: SpecialistName
    ticket_id: int | None = Field(description="The ticket worked on, if any.")
    summary: str = Field(description="Two to four sentences: what you found and what you did.")
    facts: list[Fact] = Field(description="Every number or date you relied on, with its source tool.")
    actions_taken: list[str] = Field(
        description="Records you created through MCP, e.g. 'payment request #2 (rent, $2400.00, pending approval)'."
    )
    payment_request_ids: list[int] = Field(default_factory=list, description="Ids of payment requests you prepared.")
    draft_ids: list[int] = Field(default_factory=list, description="Ids of message drafts you saved.")
    recommendation: str = Field(description="What you recommend the Boss decides, in one or two sentences.")
    concerns: list[str] = Field(default_factory=list, description="Risks, blockers, or anything a human should check.")


class BossDecision(BaseModel):
    """The Boss's final call on one ticket."""
    ticket_id: int
    decision: TicketDecisionKind = Field(
        description="resolved = nothing more to do; awaiting_human_approval = payments or drafts wait on a human; "
                    "deferred = parked on purpose (say until when/why); needs_human = the team can't decide."
    )
    summary: str = Field(description="Two to four sentences for the dashboard: the situation and the call.")
    rationale: str = Field(description="Why this call, including priorities weighed (cash, deadlines, customers).")
    agents_consulted: list[SpecialistName] = Field(description="Specialists you delegated to.")
    payment_request_ids: list[int] = Field(default_factory=list, description="Payment requests a human must review.")
    draft_ids: list[int] = Field(default_factory=list, description="Customer message drafts a human must review.")
    human_next_steps: list[str] = Field(description="Concrete actions for the human, e.g. 'Approve request #1 ($840).'")
    key_facts: list[Fact] = Field(description="The handful of facts the decision rests on.")


# ---------- what the team returns ----------

class UsageSummary(BaseModel):
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TicketRunResult(BaseModel):
    """One full team run on one ticket, as returned to the caller (and later the dashboard)."""
    run_id: str
    ticket_id: int
    status: Literal["completed", "error"]
    decision: BossDecision | None
    recorded_decision_id: int | None = Field(description="ticket_decisions.id written through MCP after validation.")
    dropped_ids: list[str] = Field(
        default_factory=list, description="Ids the Boss cited that don't exist in the database (removed in code)."
    )
    delegations: int
    usage: UsageSummary
    duration_ms: int
    model: str
    error: str | None = None


# ---------- audit trail ----------

class AuditToolCall(BaseModel):
    tool: str
    tool_call_id: str
    args: str = Field(description="Arguments as JSON, truncated.")


class AuditToolResult(BaseModel):
    tool: str
    tool_call_id: str
    result: str = Field(description="Result, truncated.")
    is_error: bool = False


class AuditStep(BaseModel):
    """One step of one agent's loop. Appended to output/audit_trail.json, never rewritten."""
    time: str
    run_id: str
    ticket_id: int | None
    agent: AgentName | Literal["human"] = Field(description="Which agent acted, or 'human' for dashboard actions.")
    agent_run_id: str = Field(description="Unique per agent invocation (one Boss run, one delegated run, ...).")
    parent_agent: AgentName | None = Field(description="Who delegated to this agent; None for the Boss.")
    depth: int = Field(description="0 = Boss, 1 = delegated by the Boss, 2 = consulted by a specialist.")
    step: int = Field(description="Step number inside this agent run.")
    kind: Literal["start", "model_response", "tool_results", "final_output", "error", "run_summary", "human_action"]
    model: str
    input: str | None = Field(default=None, description="The task given to the agent (start steps).")
    reasoning: str | None = Field(default=None, description="Reasoning summary from the model, if returned.")
    text: str | None = Field(default=None, description="Any plain text the model produced.")
    tool_calls: list[AuditToolCall] = Field(default_factory=list)
    tool_results: list[AuditToolResult] = Field(default_factory=list)
    output: str | None = Field(default=None, description="Final structured output, JSON, truncated.")
    summary: str | None = Field(default=None, description="Final steps: the agent's own summary, untruncated.")
    decision: str | None = Field(default=None, description="Boss final step: the decision kind.")
    usage: UsageSummary | None = Field(default=None, description="Cumulative team usage at this step.")
    error: str | None = None


# ---------- HTTP API (main.py) ----------

class TicketRow(BaseModel):
    """One ticket as the dashboard shows it."""
    id: int
    type: str
    requester: str
    subject: str
    notes: str | None
    status: str = Field(description="tickets.status: open, awaiting_human_approval, deferred, needs_human or resolved.")
    state: Literal["open", "resolved"] = Field(
        description="open = the team hasn't made a final call yet; resolved = the Boss's decision is recorded."
    )
    needs_human_action: bool = Field(description="True if a payment request for this ticket is pending approval.")
    pending_payment_request_ids: list[int]
    draft_ids: list[int]
    latest_decision: str | None = Field(description="Summary of the most recent recorded decision, if any.")


class TicketsResponse(BaseModel):
    shop_date_today: str
    tickets: list[TicketRow]


class EventsResponse(BaseModel):
    events: list[AuditStep] = Field(description="Oldest first, so the board can append them in order.")
    total: int = Field(description="Total entries in the audit trail.")
    latest_time: str | None = Field(description="Pass back as ?since= to fetch only newer events.")


class HumanApproval(BaseModel):
    approved_by: str = Field(min_length=2, max_length=80, description="Full name of the person approving.")
    account: str = "checking"


class HumanRejection(BaseModel):
    rejected_by: str = Field(min_length=2, max_length=80)
    note: str = ""


class HumanClose(BaseModel):
    closed_by: str = Field(min_length=2, max_length=80, description="Full name of the person closing the ticket.")
    note: str = ""


class CashResponse(BaseModel):
    shop_date_today: str
    account: str
    balance: float = Field(description="cash_accounts.balance for the account.")
    as_of: str
    pending_requests_total: float
    balance_after_pending: float = Field(description="Derived: balance - every pending payment request.")
