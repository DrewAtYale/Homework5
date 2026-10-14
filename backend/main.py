"""FastAPI backend for the Campus Customs dashboard.

Start it from the backend folder (with the project venv active):

    uvicorn main:app --reload --port 8000

It serves http://localhost:8000. Interactive API docs (Swagger UI) are at http://localhost:8000/docs. On startup it starts the agent team
and its single MCP connection (mcp_server/server.py). Every shop read and write below goes through
that MCP server; this file never opens the database itself.

Agents only *prepare* payments. The approve route is the one place where cash changes, and only
because a human clicked Approve and gave their name.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic_ai.exceptions import ModelRetry

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit  # noqa: E402
import config  # noqa: E402
from models import (  # noqa: E402
    AuditStep,
    CashResponse,
    EventsResponse,
    HumanApproval,
    HumanClose,
    HumanRejection,
    TicketRow,
    TicketRunResult,
    TicketsResponse,
)
from team import Team  # noqa: E402

DASHBOARD_ORIGINS = os.environ.get(
    "DASHBOARD_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
).split(",")
MAX_EVENTS = 500

team: Team | None = None
run_lock = asyncio.Lock()  # one ticket run (or reset) at a time: they share cash and the database


@asynccontextmanager
async def lifespan(app: FastAPI):
    global team
    team = Team()
    async with team:
        yield
    team = None


app = FastAPI(
    title="Campus Customs Ops API",
    description="Backend for the multi-agent dashboard. Nothing is ever sent; every payment needs a human.",
    version="1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=DASHBOARD_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"],
)


# ---------- helpers ----------

async def mcp(name: str, args: dict[str, Any] | None = None) -> Any:
    """Call an MCP tool, turning tool errors (unknown id, bad state) into HTTP errors."""
    if team is None:
        raise HTTPException(503, "The agent team is not running.")
    try:
        return await team.call_mcp(name, args or {})
    except ModelRetry as err:
        message = str(err)
        raise HTTPException(404 if "does not exist" in message else 400, message) from err


def audit_human(action: str, ticket_id: int | None, details: dict, error: str | None = None) -> None:
    """Human dashboard actions go in the same append-only audit trail as agent steps."""
    audit.append(AuditStep(
        time=audit.now(), run_id=f"human-{uuid.uuid4().hex[:8]}", ticket_id=ticket_id, agent="human",
        agent_run_id="dashboard", parent_agent=None, depth=0, step=0, kind="human_action",
        model="none", input=action, output=audit.truncate(details, 2000), error=error,
    ))


# ---------- routes ----------

@app.get("/api/health")
async def health() -> dict:
    """Is the server up, and is the agent team connected to MCP?"""
    return {"ok": team is not None, "model": config.MODEL_NAME, "run_in_progress": run_lock.locked()}


@app.get("/api/tickets", response_model=TicketsResponse)
async def list_tickets() -> TicketsResponse:
    """Every ticket with its status, open or resolved, and anything waiting on a human."""
    listing = await mcp("list_tickets")
    rows = []
    for t in listing["tickets"]:
        detail = await mcp("get_ticket", {"ticket_id": t["id"]})
        pending = [r["id"] for r in detail["payment_requests"] if r["status"] == "pending_approval"]
        rows.append(TicketRow(
            id=t["id"], type=t["type"], requester=t["requester"], subject=t["subject"], notes=t["notes"],
            status=t["status"], state="open" if t["status"] == "open" else "resolved",
            needs_human_action=bool(pending), pending_payment_request_ids=pending,
            draft_ids=[d["id"] for d in detail["message_drafts"]],
            latest_decision=detail["decisions"][-1]["summary"] if detail["decisions"] else None,
        ))
    return TicketsResponse(shop_date_today=listing["shop_date_today"], tickets=rows)


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict:
    """One ticket in full, with its payment requests, drafts and decisions."""
    return await mcp("get_ticket", {"ticket_id": ticket_id})


@app.post("/api/tickets/{ticket_id}/run", response_model=TicketRunResult)
async def run_ticket(ticket_id: int) -> TicketRunResult:
    """Have the agent team work one ticket. Takes about 1 to 3 minutes; poll /api/events meanwhile."""
    await mcp("get_ticket", {"ticket_id": ticket_id})  # 404 if it doesn't exist
    if run_lock.locked():
        raise HTTPException(409, "A ticket run or reset is already in progress. Try again when it finishes.")
    async with run_lock:
        result = await team.run_ticket(ticket_id)
    if result.status == "error":
        return JSONResponse(status_code=502, content=result.model_dump(mode="json"))
    return result


@app.post("/api/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: int, body: HumanClose) -> dict:
    """A human marks a worked ticket fully resolved (payments decided, drafts reviewed).
    Refuses with 409 while any payment request for the ticket is still pending approval."""
    detail = await mcp("get_ticket", {"ticket_id": ticket_id})
    if detail["status"] == "open":
        raise HTTPException(409, "The agent team hasn't worked this ticket yet.")
    pending = [r["id"] for r in detail["payment_requests"] if r["status"] == "pending_approval"]
    if pending:
        raise HTTPException(409, f"Payment request(s) {pending} still need approval or rejection first.")
    summary = f"Closed by {body.closed_by}." + (f" {body.note.strip()}" if body.note.strip() else "")
    result = await mcp("record_ticket_decision", {
        "ticket_id": ticket_id, "decision": "resolved", "summary": summary, "decided_by": body.closed_by,
    })
    audit_human(f"close_ticket #{ticket_id} by {body.closed_by}", ticket_id, {"note": body.note})
    return result


@app.get("/api/events", response_model=EventsResponse)
async def events(
    limit: int = Query(100, ge=1, le=MAX_EVENTS, description="Most recent N events."),
    since: str | None = Query(None, description="Only events with time after this ISO timestamp."),
    ticket_id: int | None = Query(None),
    run_id: str | None = Query(None),
    agent: str | None = Query(None, description="boss, inventory, accounting, facilities, customer_service or human."),
) -> EventsResponse:
    """Recent agent and human events from output/audit_trail.json, oldest first."""
    if since:
        since = since.replace(" ", "+")  # an unencoded '+' in the timezone arrives as a space
    entries = audit.read_all()
    picked = [
        e for e in entries
        if (since is None or e.get("time", "") > since)
        and (ticket_id is None or e.get("ticket_id") == ticket_id)
        and (run_id is None or e.get("run_id") == run_id)
        and (agent is None or e.get("agent") == agent)
    ][-limit:]
    return EventsResponse(
        events=[AuditStep(**e) for e in picked], total=len(entries),
        latest_time=picked[-1]["time"] if picked else since,
    )


@app.get("/api/payment-requests")
async def payment_requests(
    status: Literal["pending_approval", "paid", "rejected"] | None = None, ticket_id: int | None = None,
) -> dict:
    """The approval queue: payments and purchase orders the agents prepared."""
    args = {k: v for k, v in {"status": status, "ticket_id": ticket_id}.items() if v is not None}
    return await mcp("list_payment_requests", args)


@app.post("/api/payment-requests/{request_id}/approve")
async def approve_payment(request_id: int, body: HumanApproval):
    """A human approves a pending payment or PO. This is the only route that moves cash.
    Returns 409 if the pay tool refuses (not enough cash, or the vendor still has an unpaid invoice)."""
    if run_lock.locked():  # don't move cash mid-run, while agents are reasoning about it
        raise HTTPException(409, "A ticket run is in progress. Approve when it finishes.")
    async with run_lock:
        try:
            result = await mcp("approve_and_pay", {
                "request_id": request_id, "approved_by": body.approved_by, "account": body.account,
            })
        except HTTPException as err:  # refused before any money moved: still audit the attempt
            audit_human(f"approve_and_pay request #{request_id} by {body.approved_by}", None, {}, error=err.detail)
            raise
    audit_human(
        f"approve_and_pay request #{request_id} by {body.approved_by}", result["request"]["ticket_id"],
        {k: result[k] for k in ("paid", "payment_id", "cash_before", "cash_after", "message")},
        error=None if result["paid"] else result["message"],
    )
    return result if result["paid"] else JSONResponse(status_code=409, content=result)


@app.post("/api/payment-requests/{request_id}/reject")
async def reject_payment(request_id: int, body: HumanRejection) -> dict:
    """A human rejects a pending payment or PO. No money moves."""
    result = await mcp("reject_payment_request", {
        "request_id": request_id, "rejected_by": body.rejected_by, "note": body.note,
    })
    audit_human(f"reject_payment_request #{request_id} by {body.rejected_by}", result["ticket_id"],
                {"status": result["status"], "note": body.note})
    return result


@app.get("/api/drafts")
async def drafts(ticket_id: int | None = None) -> dict:
    """Customer message drafts. They are never sent by the system."""
    return await mcp("list_message_drafts", {"ticket_id": ticket_id} if ticket_id is not None else {})


@app.get("/api/cash", response_model=CashResponse)
async def cash(account: str = "checking") -> CashResponse:
    """The current balance from cash_accounts (checking by default), plus what's pending approval."""
    pos = await mcp("get_cash_position")
    acct = next((a for a in pos["cash_accounts"] if a["name"] == account), None)
    if acct is None:
        raise HTTPException(404, f"Cash account '{account}' does not exist.")
    return CashResponse(
        shop_date_today=pos["shop_date_today"], account=account, balance=acct["balance"], as_of=acct["as_of"],
        pending_requests_total=pos["pending_requests_total"],
        balance_after_pending=round(acct["balance"] - pos["pending_requests_total"], 2),
    )


@app.post("/api/reset")
async def reset() -> dict:
    """Restore data/campus_customs_new.db to the original values for a fresh run. The audit trail is kept."""
    if run_lock.locked():
        raise HTTPException(409, "A ticket run is in progress. Reset when it finishes.")
    async with run_lock:
        result = await mcp("reset_working_database", {"confirm": True})
    audit_human("reset_working_database", None, result)
    return result
