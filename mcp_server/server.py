"""Campus Customs MCP server (FastMCP).

Shared tool layer for the Homework 5 agent team. Every agent (Boss, Inventory,
Accounting, Facilities, Customer Service) reaches the shop database only through
these tools.

Data rules:
  * Reads and writes data/campus_customs_new.db (the working copy). The pristine original
    is only ever read, by the human-only reset tool.
  * Read tools open the database read-only. Write tools only add workflow records
    (payment requests, message drafts, ticket decisions), except the human-only pay tool.
  * Values come from the database or from simple arithmetic on database values.
    Nothing is invented: unknown ids or mismatched ticket types raise an error.
    Payment amounts are always looked up by the server, never taken from the caller.
  * "Today" is desk.date_today, not the computer clock.
  * Nothing here sends email or contacts anyone. There is no send tool.
  * Money only moves through approve_and_pay, which needs a named human approver and
    refuses if cash would go negative.

Run (stdio):  .venv\\Scripts\\python.exe mcp_server\\server.py
"""

from __future__ import annotations

import calendar
import os
import shutil
import sqlite3
from contextlib import closing
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import (  # noqa: E402
    BulkOrderQuote,
    CashAccount,
    CashPosition,
    CustomerOrderFulfillment,
    InvoiceInfo,
    LeaseInfo,
    MessageDraft,
    MessageDraftList,
    OpenTickets,
    PaymentRequest,
    PaymentRequestList,
    PaymentRequestResult,
    PaymentResult,
    RentDueAndCash,
    ResetResult,
    SizeStock,
    SkuStock,
    TicketDecision,
    TicketDetail,
    TicketSummary,
    VendorInfo,
    VendorList,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_DB = DATA_DIR / "campus_customs_new.db"
DB_PATH = Path(os.environ.get("CAMPUS_CUSTOMS_DB", DEFAULT_DB)).resolve()
ORIGINAL_DB = Path(os.environ.get("CAMPUS_CUSTOMS_ORIGINAL_DB", DATA_DIR / "campus_customs.db")).resolve()

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
# Agent write tools only add workflow records; a repeat call returns the existing record.
RECORD_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
# Human-only tools change money or replace data. The backend never gives these to an agent.
HUMAN_ONLY = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}

AGENT_NAMES = {"boss", "inventory", "accounting", "facilities", "customer_service"}
NOT_A_HUMAN = AGENT_NAMES | {"agent", "system", "ai", "bot", "assistant", "claude", "model", ""}
MAX_DRAFT_CHARS = 2000

mcp = FastMCP(
    name="campus-customs",
    instructions=(
        "Tools for the Campus Customs shop database. Use desk.date_today as today. "
        "Only report values these tools return; never invent stock, prices, dates or balances. "
        "Nothing here sends email or contacts vendors. Payments and purchase orders are only "
        "prepared for human approval; approve_and_pay, reject_payment_request and "
        "reset_working_database are for humans only."
    ),
)

WORKFLOW_TABLES = """
CREATE TABLE IF NOT EXISTS payment_requests (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('invoice', 'rent', 'purchase_order')),
    ref_id INTEGER,
    vendor_id INTEGER,
    sku TEXT,
    size TEXT,
    qty INTEGER,
    amount REAL NOT NULL CHECK (amount > 0),
    reason TEXT NOT NULL,
    ticket_id INTEGER,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending_approval', 'paid', 'rejected')),
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT
);
CREATE TABLE IF NOT EXISTS message_drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    to_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    drafted_by TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'draft'),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_decisions (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    summary TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


# ---------- helpers ----------

def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise ToolError(f"Database not found: {DB_PATH}")
    _ensure_workflow_tables()
    conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_rw() -> sqlite3.Connection:
    """Read-write connection to the working copy. Refuses to open the pristine original."""
    if not DB_PATH.exists():
        raise ToolError(f"Database not found: {DB_PATH}")
    if DB_PATH == ORIGINAL_DB:
        raise ToolError("Refusing to write to the pristine original database.")
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_workflow_tables() -> None:
    """Add the workflow tables to the working copy if they're missing (e.g. right after a reset)."""
    if DB_PATH == ORIGINAL_DB:
        return
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as conn:
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"payment_requests", "message_drafts", "ticket_decisions"} <= have:
            conn.executescript(WORKFLOW_TABLES)


def _now() -> str:
    """Wall-clock timestamp for audit columns. Shop logic uses desk.date_today instead."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _total_cash(conn: sqlite3.Connection) -> float:
    return round(sum(r["balance"] for r in conn.execute("SELECT balance FROM cash_accounts")), 2)


def _pending(conn: sqlite3.Connection) -> list[PaymentRequest]:
    rows = conn.execute("SELECT * FROM payment_requests WHERE status = 'pending_approval' ORDER BY id")
    return [PaymentRequest(**dict(r)) for r in rows]


def _request(conn: sqlite3.Connection, request_id: int) -> PaymentRequest:
    row = conn.execute("SELECT * FROM payment_requests WHERE id = ?", (request_id,)).fetchone()
    if row is None:
        raise ToolError(f"Payment request {request_id} does not exist.")
    return PaymentRequest(**dict(row))


def _lease_info(row: sqlite3.Row, today: date) -> LeaseInfo:
    days = (date.fromisoformat(row["next_due"]) - today).days
    return LeaseInfo(
        shop_date_today=today.isoformat(), id=row["id"], space_name=row["space_name"],
        landlord=row["landlord"], monthly_rent=row["monthly_rent"], next_due=row["next_due"],
        days_until_due=days, is_overdue=days < 0, notes=row["notes"],
    )


def _check_ticket_id(conn: sqlite3.Connection, ticket_id: int | None) -> None:
    if ticket_id is not None and conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
        raise ToolError(f"Ticket {ticket_id} does not exist.")


def _create_request(
    conn: sqlite3.Connection, today: date, *, kind: str, ref_id: int | None, vendor_id: int | None,
    sku: str | None, size: str | None, qty: int | None, amount: float, reason: str,
    ticket_id: int | None, requested_by: str, vendor_blocked: bool | None, note: str,
) -> PaymentRequestResult:
    """Insert a pending request (or return the matching pending one) plus the cash picture."""
    if not reason.strip():
        raise ToolError("A reason is required so the human approver knows why.")
    existing = conn.execute(
        "SELECT * FROM payment_requests WHERE status = 'pending_approval' AND kind = ? "
        "AND ref_id IS ? AND vendor_id IS ? AND sku IS ? AND size IS ? AND qty IS ?",
        (kind, ref_id, vendor_id, sku, size, qty),
    ).fetchone()
    if existing is None:
        cur = conn.execute(
            "INSERT INTO payment_requests (kind, ref_id, vendor_id, sku, size, qty, amount, reason, ticket_id, "
            "requested_by, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?)",
            (kind, ref_id, vendor_id, sku, size, qty, round(amount, 2), reason.strip(), ticket_id,
             requested_by.strip() or "unknown", _now()),
        )
        conn.commit()
        req = _request(conn, cur.lastrowid)
    else:
        req = PaymentRequest(**dict(existing))
    cash = _total_cash(conn)
    pending_total = round(sum(p.amount for p in _pending(conn)), 2)
    return PaymentRequestResult(
        request=req, already_existed=existing is not None, cash_on_hand=cash,
        pending_requests_total=pending_total, cash_after_all_pending=round(cash - pending_total, 2),
        would_overdraw_if_all_approved=cash - pending_total < 0,
        vendor_blocked_by_unpaid_invoice=vendor_blocked,
        note=note.rstrip() + " Status is pending_approval: nothing is paid until a human approves it.",
    )


def _today(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    if row is None:
        raise ToolError("desk table has no date_today row.")
    return date.fromisoformat(row["date_today"])


def _ticket(conn: sqlite3.Connection, ticket_id: int, expected_type: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise ToolError(f"Ticket {ticket_id} does not exist.")
    if row["type"] != expected_type:
        raise ToolError(f"Ticket {ticket_id} is type '{row['type']}', this tool handles '{expected_type}'.")
    return row


def _ticket_summary(row: sqlite3.Row) -> TicketSummary:
    return TicketSummary(**{k: row[k] for k in TicketSummary.model_fields})


def _invoice(row: sqlite3.Row, today: date) -> InvoiceInfo:
    overdue = (today - date.fromisoformat(row["due_date"])).days if row["status"] == "open" else 0
    return InvoiceInfo(
        id=row["id"], vendor_id=row["vendor_id"], amount=row["amount"], due_date=row["due_date"],
        status=row["status"], description=row["description"], days_overdue=max(0, overdue),
    )


def _open_invoices(conn: sqlite3.Connection, today: date, vendor_id: int | None = None) -> list[InvoiceInfo]:
    sql, args = "SELECT * FROM invoices WHERE status = 'open'", ()
    if vendor_id is not None:
        sql, args = sql + " AND vendor_id = ?", (vendor_id,)
    return [_invoice(r, today) for r in conn.execute(sql + " ORDER BY due_date", args)]


def _vendor(conn: sqlite3.Connection, row: sqlite3.Row, today: date) -> VendorInfo:
    open_inv = _open_invoices(conn, today, row["id"])
    return VendorInfo(
        id=row["id"], name=row["name"], specialty=row["specialty"], lead_days=row["lead_days"],
        open_invoices=open_inv, blocked_by_unpaid_invoice=bool(open_inv),
        earliest_eta_if_unblocked_today=(today + timedelta(days=row["lead_days"])).isoformat(),
    )


def _sizes(conn: sqlite3.Connection, sku: str) -> list[sqlite3.Row]:
    rows = conn.execute("SELECT * FROM inventory WHERE sku = ? ORDER BY rowid", (sku,)).fetchall()
    if not rows:
        raise ToolError(f"SKU {sku} is not in inventory.")
    return rows


def _stock_row(rows: list[sqlite3.Row], sku: str, size: str) -> sqlite3.Row:
    for r in rows:
        if r["size"] == size:
            return r
    raise ToolError(f"SKU {sku} has no size {size} in inventory.")


# ---------- tools ----------

@mcp.tool(annotations=READ_ONLY)
def check_customer_order_fulfillment(
    ticket_id: Annotated[int, Field(description="A customer_order ticket id, e.g. 101.")],
) -> CustomerOrderFulfillment:
    """For a customer_order ticket: can we fill it from stock, and if not, what blocks the restock?

    Reads tickets, inventory, invoices, vendors and desk. Returns stock for the requested
    SKU/size, other sizes in stock, the invoice linked to the ticket (with days overdue),
    and that invoice's vendor with lead time and whether unpaid invoices block shipping.
    """
    with closing(_connect()) as conn:
        today = _today(conn)
        t = _ticket(conn, ticket_id, "customer_order")
        sizes = _sizes(conn, t["sku"])
        stock = _stock_row(sizes, t["sku"], t["size"])
        qty = t["qty"] or 0

        invoice = vendor = None
        if t["invoice_id"] is not None:
            inv_row = conn.execute("SELECT * FROM invoices WHERE id = ?", (t["invoice_id"],)).fetchone()
            if inv_row is None:
                raise ToolError(f"Ticket {ticket_id} links invoice {t['invoice_id']}, which does not exist.")
            invoice = _invoice(inv_row, today)
            v_row = conn.execute("SELECT * FROM vendors WHERE id = ?", (inv_row["vendor_id"],)).fetchone()
            vendor = _vendor(conn, v_row, today) if v_row else None

        return CustomerOrderFulfillment(
            shop_date_today=today.isoformat(),
            ticket=_ticket_summary(t),
            sku=t["sku"], product_name=stock["name"], size_requested=t["size"], qty_requested=qty,
            qty_on_hand=stock["qty"], location=stock["location"],
            can_fill_from_stock=stock["qty"] >= qty, shortfall=max(0, qty - stock["qty"]),
            other_sizes_in_stock=[
                SizeStock(size=r["size"], qty=r["qty"], location=r["location"])
                for r in sizes if r["size"] != t["size"] and r["qty"] > 0
            ],
            linked_invoice=invoice, linked_vendor=vendor,
        )


@mcp.tool(annotations=READ_ONLY)
def check_rent_due_and_cash(
    ticket_id: Annotated[int, Field(description="A rent_notice ticket id, e.g. 102.")],
) -> RentDueAndCash:
    """For a rent_notice ticket: how much rent is due, when, and can cash cover it?

    Reads tickets, leases, desk, cash_accounts and invoices. Returns the lease's rent and
    next due date, days until due, cash on hand, cash left after rent, and cash left after
    rent plus every open invoice (so rent is weighed against bills already owed).
    """
    with closing(_connect()) as conn:
        today = _today(conn)
        t = _ticket(conn, ticket_id, "rent_notice")
        if t["lease_id"] is None:
            raise ToolError(f"Ticket {ticket_id} has no lease_id.")
        lease = conn.execute("SELECT * FROM leases WHERE id = ?", (t["lease_id"],)).fetchone()
        if lease is None:
            raise ToolError(f"Ticket {ticket_id} links lease {t['lease_id']}, which does not exist.")

        accounts = [CashAccount(name=r["name"], balance=r["balance"], as_of=r["date"])
                    for r in conn.execute("SELECT * FROM cash_accounts ORDER BY name")]
        total = round(sum(a.balance for a in accounts), 2)
        rent = lease["monthly_rent"]
        days = (date.fromisoformat(lease["next_due"]) - today).days
        open_inv = _open_invoices(conn, today)

        return RentDueAndCash(
            shop_date_today=today.isoformat(),
            ticket=_ticket_summary(t),
            lease_id=lease["id"], space_name=lease["space_name"], landlord=lease["landlord"],
            monthly_rent=rent, next_due=lease["next_due"], days_until_due=days, is_overdue=days < 0,
            cash_accounts=accounts, total_cash=total,
            can_cover_rent=total >= rent, cash_after_rent=round(total - rent, 2),
            other_open_invoices=open_inv,
            cash_after_rent_and_open_invoices=round(total - rent - sum(i.amount for i in open_inv), 2),
        )


@mcp.tool(annotations=READ_ONLY)
def quote_bulk_order_discount(
    ticket_id: Annotated[int, Field(description="A price_override ticket id, e.g. 103.")],
    discount_pct: Annotated[float, Field(ge=0, le=100, description="Proposed discount off list price, 0-100.")] = 0,
) -> BulkOrderQuote:
    """For a price_override (bulk discount) ticket: stock shortfall plus margin at a proposed discount.

    Reads tickets, inventory, pricing, vendors, invoices and desk. Returns stock for every
    size of the SKU, the shortfall for the requested size, unit cost and list price, the
    margin and order profit at `discount_pct`, the largest discount before selling at a
    loss, the cost to restock the shortfall, and every vendor with lead time and whether
    an unpaid invoice blocks it.
    """
    with closing(_connect()) as conn:
        today = _today(conn)
        t = _ticket(conn, ticket_id, "price_override")
        sizes = _sizes(conn, t["sku"])
        stock = _stock_row(sizes, t["sku"], t["size"])
        price = conn.execute("SELECT * FROM pricing WHERE sku = ?", (t["sku"],)).fetchone()
        if price is None:
            raise ToolError(f"SKU {t['sku']} has no pricing row.")

        qty = t["qty"] or 0
        cost, listp = price["unit_cost"], price["list_price"]
        unit = round(listp * (1 - discount_pct / 100), 2)
        margin = round(unit - cost, 2)
        shortfall = max(0, qty - stock["qty"])

        return BulkOrderQuote(
            shop_date_today=today.isoformat(),
            ticket=_ticket_summary(t),
            sku=t["sku"], product_name=stock["name"], size_requested=t["size"], qty_requested=qty,
            qty_on_hand=stock["qty"], shortfall=shortfall,
            all_sizes=[SizeStock(size=r["size"], qty=r["qty"], location=r["location"]) for r in sizes],
            unit_cost=cost, list_price=listp, discount_pct=discount_pct,
            quoted_unit_price=unit, margin_per_unit=margin,
            margin_pct=round(margin / unit * 100, 1) if unit else 0.0,
            order_revenue=round(unit * qty, 2), order_gross_profit=round(margin * qty, 2),
            max_discount_pct_before_loss=round((listp - cost) / listp * 100, 1),
            restock_cost_at_unit_cost=round(shortfall * cost, 2),
            vendors=[_vendor(conn, r, today) for r in conn.execute("SELECT * FROM vendors ORDER BY id")],
        )


# ---------- general read tools (Question 5) ----------

@mcp.tool(annotations=READ_ONLY)
def list_open_tickets() -> OpenTickets:
    """List every ticket whose status is 'open' (the Boss's inbox). Reads tickets and desk."""
    with closing(_connect()) as conn:
        today = _today(conn)
        rows = conn.execute("SELECT * FROM tickets WHERE status = 'open' ORDER BY id").fetchall()
        return OpenTickets(shop_date_today=today.isoformat(), tickets=[_ticket_summary(r) for r in rows])


@mcp.tool(annotations=READ_ONLY)
def list_tickets() -> OpenTickets:
    """List every ticket with its current status (open, awaiting_human_approval, resolved, ...).
    Reads tickets and desk."""
    with closing(_connect()) as conn:
        today = _today(conn)
        rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
        return OpenTickets(shop_date_today=today.isoformat(), tickets=[_ticket_summary(r) for r in rows])


@mcp.tool(annotations=READ_ONLY)
def get_ticket(
    ticket_id: Annotated[int, Field(description="Any ticket id, e.g. 101.")],
) -> TicketDetail:
    """One ticket in full (sku, size, qty, lease_id, invoice_id) plus the payment requests,
    message drafts and decisions already recorded for it. Check this first so work isn't repeated.

    Reads tickets, payment_requests, message_drafts and ticket_decisions.
    """
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise ToolError(f"Ticket {ticket_id} does not exist.")
        q = lambda table: conn.execute(f"SELECT * FROM {table} WHERE ticket_id = ? ORDER BY id", (ticket_id,))  # noqa: E731
        return TicketDetail(
            **dict(row),
            payment_requests=[PaymentRequest(**dict(r)) for r in q("payment_requests")],
            message_drafts=[MessageDraft(**dict(r)) for r in q("message_drafts")],
            decisions=[TicketDecision(**dict(r)) for r in q("ticket_decisions")],
        )


@mcp.tool(annotations=READ_ONLY)
def check_stock(
    sku: Annotated[str, Field(description="Inventory SKU, e.g. CC-HOOD-NAVY.")],
    size: Annotated[str | None, Field(description="Optional size (S, M, L, XL, OS). Omit for every size.")] = None,
) -> SkuStock:
    """Stock on hand by SKU (and optionally size), with unit cost and list price.

    Reads inventory, pricing and desk.
    """
    with closing(_connect()) as conn:
        today = _today(conn)
        rows = _sizes(conn, sku)
        if size is not None:
            rows = [_stock_row(rows, sku, size)]
        price = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone()
        return SkuStock(
            shop_date_today=today.isoformat(), sku=sku, product_name=rows[0]["name"],
            unit_cost=price["unit_cost"] if price else None, list_price=price["list_price"] if price else None,
            sizes=[SizeStock(size=r["size"], qty=r["qty"], location=r["location"]) for r in rows],
            total_qty=sum(r["qty"] for r in rows),
        )


@mcp.tool(annotations=READ_ONLY)
def list_vendors() -> VendorList:
    """Every vendor with specialty, lead_days, open invoices, whether it is blocked from shipping
    (shop rule: no shipping while any invoice is unpaid) and its earliest ETA if unblocked today.

    Reads vendors, invoices and desk. There is no SKU-to-vendor table: choose by specialty.
    """
    with closing(_connect()) as conn:
        today = _today(conn)
        return VendorList(
            shop_date_today=today.isoformat(),
            vendors=[_vendor(conn, r, today) for r in conn.execute("SELECT * FROM vendors ORDER BY id")],
        )


@mcp.tool(annotations=READ_ONLY)
def get_lease(
    lease_id: Annotated[int, Field(description="A lease id, e.g. 1.")],
) -> LeaseInfo:
    """One lease: space, landlord, monthly rent, next due date and days until due. Reads leases and desk."""
    with closing(_connect()) as conn:
        today = _today(conn)
        row = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if row is None:
            raise ToolError(f"Lease {lease_id} does not exist.")
        return _lease_info(row, today)


@mcp.tool(annotations=READ_ONLY)
def get_cash_position() -> CashPosition:
    """The whole cash picture: cash on hand, open invoices, payment requests already waiting for
    approval, cash left if every pending request were paid, and rent due in the next 14 days.

    Reads cash_accounts, invoices, payment_requests, leases and desk.
    """
    with closing(_connect()) as conn:
        today = _today(conn)
        accounts = [CashAccount(name=r["name"], balance=r["balance"], as_of=r["date"])
                    for r in conn.execute("SELECT * FROM cash_accounts ORDER BY name")]
        total = round(sum(a.balance for a in accounts), 2)
        open_inv = _open_invoices(conn, today)
        pending = _pending(conn)
        pending_total = round(sum(p.amount for p in pending), 2)
        leases = [_lease_info(r, today) for r in conn.execute("SELECT * FROM leases ORDER BY next_due")]
        return CashPosition(
            shop_date_today=today.isoformat(), cash_accounts=accounts, total_cash=total,
            open_invoices=open_inv, open_invoices_total=round(sum(i.amount for i in open_inv), 2),
            pending_payment_requests=pending, pending_requests_total=pending_total,
            cash_after_pending_requests=round(total - pending_total, 2),
            leases_due_within_14_days=[lease for lease in leases if lease.days_until_due <= 14],
        )


@mcp.tool(annotations=READ_ONLY)
def list_payment_requests(
    status: Annotated[
        Literal["pending_approval", "paid", "rejected"] | None,
        Field(description="Filter by status. Omit for all."),
    ] = None,
    ticket_id: Annotated[int | None, Field(description="Filter by ticket. Omit for all.")] = None,
) -> PaymentRequestList:
    """Payment requests and purchase orders (the human approval queue). Reads payment_requests."""
    with closing(_connect()) as conn:
        sql, args = "SELECT * FROM payment_requests WHERE 1=1", []
        if status is not None:
            sql, args = sql + " AND status = ?", args + [status]
        if ticket_id is not None:
            sql, args = sql + " AND ticket_id = ?", args + [ticket_id]
        reqs = [PaymentRequest(**dict(r)) for r in conn.execute(sql + " ORDER BY id", args)]
        return PaymentRequestList(requests=reqs, total=round(sum(r.amount for r in reqs), 2))


@mcp.tool(annotations=READ_ONLY)
def list_message_drafts(
    ticket_id: Annotated[int | None, Field(description="Filter by ticket. Omit for all.")] = None,
) -> MessageDraftList:
    """Customer message drafts waiting on the dashboard. Reads message_drafts."""
    with closing(_connect()) as conn:
        sql, args = "SELECT * FROM message_drafts", ()
        if ticket_id is not None:
            sql, args = sql + " WHERE ticket_id = ?", (ticket_id,)
        return MessageDraftList(drafts=[MessageDraft(**dict(r)) for r in conn.execute(sql + " ORDER BY id", args)])


# ---------- agent write tools: prepare for human approval, draft (Question 5) ----------

REQUESTED_BY = Annotated[str, Field(description="Agent name. The backend fills this in; any value you pass is replaced.")]
REASON = Annotated[str, Field(description="One or two sentences for the human approver: why, and which ticket.")]
TICKET = Annotated[int | None, Field(description="The ticket this is for, if any.")]


@mcp.tool(annotations=RECORD_WRITE)
def prepare_invoice_payment(
    invoice_id: Annotated[int, Field(description="An open invoice id, e.g. 501.")],
    reason: REASON,
    ticket_id: TICKET = None,
    requested_by: REQUESTED_BY = "unknown",
) -> PaymentRequestResult:
    """Queue payment of an open vendor invoice for HUMAN approval. Does not pay anything.

    The amount is read from the invoice, never supplied by the caller. Reads invoices, vendors,
    cash_accounts and payment_requests; writes one payment_requests row (status pending_approval).
    """
    with closing(_connect_rw()) as conn:
        today = _today(conn)
        _check_ticket_id(conn, ticket_id)
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if inv is None:
            raise ToolError(f"Invoice {invoice_id} does not exist.")
        if inv["status"] != "open":
            raise ToolError(f"Invoice {invoice_id} is '{inv['status']}', not open. Nothing to pay.")
        info = _invoice(inv, today)
        return _create_request(
            conn, today, kind="invoice", ref_id=invoice_id, vendor_id=inv["vendor_id"], sku=None, size=None,
            qty=None, amount=inv["amount"], reason=reason, ticket_id=ticket_id, requested_by=requested_by,
            vendor_blocked=None,
            note=f"Invoice {invoice_id} for ${inv['amount']:.2f}, {info.days_overdue} days overdue. "
                 "Paying it unblocks the vendor.",
        )


@mcp.tool(annotations=RECORD_WRITE)
def prepare_rent_payment(
    lease_id: Annotated[int, Field(description="A lease id, e.g. 1.")],
    reason: REASON,
    ticket_id: TICKET = None,
    requested_by: REQUESTED_BY = "unknown",
) -> PaymentRequestResult:
    """Queue this month's rent for a lease for HUMAN approval. Does not pay anything.

    The amount is leases.monthly_rent. Reads leases, cash_accounts and payment_requests; writes one
    payment_requests row (status pending_approval).
    """
    with closing(_connect_rw()) as conn:
        today = _today(conn)
        _check_ticket_id(conn, ticket_id)
        lease = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if lease is None:
            raise ToolError(f"Lease {lease_id} does not exist.")
        info = _lease_info(lease, today)
        return _create_request(
            conn, today, kind="rent", ref_id=lease_id, vendor_id=None, sku=None, size=None, qty=None,
            amount=lease["monthly_rent"], reason=reason, ticket_id=ticket_id, requested_by=requested_by,
            vendor_blocked=None,
            note=f"Rent ${lease['monthly_rent']:.2f} to {lease['landlord']}, due {lease['next_due']} "
                 f"({info.days_until_due} days).",
        )


@mcp.tool(annotations=RECORD_WRITE)
def prepare_purchase_order(
    vendor_id: Annotated[int, Field(description="The vendor to restock from (choose by specialty).")],
    sku: Annotated[str, Field(description="SKU to restock.")],
    size: Annotated[str, Field(description="Size to restock.")],
    qty: Annotated[int, Field(ge=1, le=500, description="Units to order.")],
    reason: REASON,
    ticket_id: TICKET = None,
    requested_by: REQUESTED_BY = "unknown",
) -> PaymentRequestResult:
    """Queue a restock purchase order for HUMAN approval. Does not order or pay anything.

    The amount is qty x pricing.unit_cost. Also reports whether the vendor is blocked by an unpaid
    invoice (it won't ship until that is paid). Reads vendors, inventory, pricing, invoices,
    cash_accounts and payment_requests; writes one payment_requests row (status pending_approval).
    """
    with closing(_connect_rw()) as conn:
        today = _today(conn)
        _check_ticket_id(conn, ticket_id)
        v = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if v is None:
            raise ToolError(f"Vendor {vendor_id} does not exist.")
        _stock_row(_sizes(conn, sku), sku, size)
        price = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if price is None:
            raise ToolError(f"SKU {sku} has no pricing row, so a PO amount can't be computed.")
        vendor = _vendor(conn, v, today)
        blocked_note = (
            f"{v['name']} is BLOCKED by unpaid invoice(s) {[i.id for i in vendor.open_invoices]} and won't ship "
            "until they are paid. " if vendor.blocked_by_unpaid_invoice else ""
        )
        return _create_request(
            conn, today, kind="purchase_order", ref_id=None, vendor_id=vendor_id, sku=sku, size=size, qty=qty,
            amount=qty * price["unit_cost"], reason=reason, ticket_id=ticket_id, requested_by=requested_by,
            vendor_blocked=vendor.blocked_by_unpaid_invoice,
            note=f"PO {qty} x {sku} {size} at ${price['unit_cost']:.2f} = ${qty * price['unit_cost']:.2f} from "
                 f"{v['name']} ({v['lead_days']} lead days). {blocked_note}",
        )


@mcp.tool(annotations=RECORD_WRITE)
def draft_customer_message(
    ticket_id: Annotated[int, Field(description="The ticket the message answers.")],
    subject: Annotated[str, Field(max_length=150, description="Short subject line.")],
    body: Annotated[str, Field(description=f"Message body, at most {MAX_DRAFT_CHARS} characters.")],
    drafted_by: REQUESTED_BY = "unknown",
) -> MessageDraft:
    """Save a DRAFT message to the ticket's requester. It is never sent: there is no send tool.

    The recipient is the ticket's requester from the database. Reads tickets; writes one
    message_drafts row (status 'draft'). Drafting again for the same ticket adds a new version.
    """
    if not subject.strip() or not body.strip():
        raise ToolError("Subject and body are both required.")
    if len(body) > MAX_DRAFT_CHARS:
        raise ToolError(f"Body is {len(body)} characters; keep it under {MAX_DRAFT_CHARS}.")
    with closing(_connect_rw()) as conn:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            raise ToolError(f"Ticket {ticket_id} does not exist.")
        cur = conn.execute(
            "INSERT INTO message_drafts (ticket_id, to_name, subject, body, drafted_by, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'draft', ?)",
            (ticket_id, t["requester"], subject.strip(), body.strip(), drafted_by.strip() or "unknown", _now()),
        )
        conn.commit()
        return MessageDraft(**dict(conn.execute("SELECT * FROM message_drafts WHERE id = ?", (cur.lastrowid,)).fetchone()))


@mcp.tool(annotations=RECORD_WRITE)
def record_ticket_decision(
    ticket_id: Annotated[int, Field(description="The ticket decided.")],
    decision: Annotated[
        Literal["resolved", "awaiting_human_approval", "deferred", "needs_human"],
        Field(description="The Boss's final call. Becomes tickets.status."),
    ],
    summary: Annotated[str, Field(description="What was decided and why, for the dashboard.")],
    decided_by: REQUESTED_BY = "boss",
) -> TicketDecision:
    """Record the Boss's final call on a ticket and set tickets.status to the decision.

    Called by the backend after validating the Boss's output, not offered to agents as a tool.
    Reads tickets; writes ticket_decisions and tickets.status.
    """
    with closing(_connect_rw()) as conn:
        if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            raise ToolError(f"Ticket {ticket_id} does not exist.")
        cur = conn.execute(
            "INSERT INTO ticket_decisions (ticket_id, decision, summary, decided_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (ticket_id, decision, summary.strip(), decided_by.strip() or "boss", _now()),
        )
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (decision, ticket_id))
        conn.commit()
        return TicketDecision(**dict(conn.execute("SELECT * FROM ticket_decisions WHERE id = ?", (cur.lastrowid,)).fetchone()))


# ---------- human-only tools (never given to an agent) ----------

@mcp.tool(annotations=HUMAN_ONLY, tags={"human_only"})
def approve_and_pay(
    request_id: Annotated[int, Field(description="A pending payment request id.")],
    approved_by: Annotated[str, Field(description="Full name of the HUMAN approving this payment.")],
    account: Annotated[str, Field(description="Cash account to pay from.")] = "checking",
) -> PaymentResult:
    """HUMAN ONLY. Pay a pending request. Refuses if cash would go negative.

    Checks in one transaction: the request is pending, the approver is a named human, the account
    has enough cash, and (for purchase orders) the vendor has no unpaid invoice. Then it debits
    cash_accounts, writes payments (with approved_by), marks the request paid, and marks an invoice
    'paid' or moves a lease's next_due forward one month.
    """
    approver = approved_by.strip()
    if approver.lower() in NOT_A_HUMAN:
        raise ToolError("approve_and_pay needs the name of the human approver. Agents cannot approve payments.")
    with closing(_connect_rw()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            req = _request(conn, request_id)
            if req.status != "pending_approval":
                raise ToolError(f"Request {request_id} is '{req.status}', not pending_approval.")
            acct = conn.execute("SELECT * FROM cash_accounts WHERE name = ?", (account,)).fetchone()
            if acct is None:
                raise ToolError(f"Cash account '{account}' does not exist.")
            before = round(acct["balance"], 2)
            if before - req.amount < 0:
                conn.rollback()
                return PaymentResult(
                    paid=False, request=req, payment_id=None, cash_before=before, cash_after=before,
                    message=f"REFUSED: ${req.amount:.2f} exceeds the ${before:.2f} in '{account}'. "
                            "The balance can never go negative.",
                )
            if req.kind == "purchase_order":
                blocking = conn.execute(
                    "SELECT id FROM invoices WHERE vendor_id = ? AND status = 'open'", (req.vendor_id,)
                ).fetchall()
                if blocking:
                    conn.rollback()
                    return PaymentResult(
                        paid=False, request=req, payment_id=None, cash_before=before, cash_after=before,
                        message=f"REFUSED: vendor {req.vendor_id} has unpaid invoice(s) {[r['id'] for r in blocking]} "
                                "and won't ship. Pay those first.",
                    )
            if req.kind == "invoice":
                inv = conn.execute("SELECT status FROM invoices WHERE id = ?", (req.ref_id,)).fetchone()
                if inv is None or inv["status"] != "open":
                    raise ToolError(f"Invoice {req.ref_id} is no longer open.")

            after = round(before - req.amount, 2)
            today = _today(conn)
            conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?", (after, today.isoformat(), account))
            cur = conn.execute(
                "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
                (req.kind, req.ref_id if req.kind != "purchase_order" else req.id, req.amount, account,
                 today.isoformat(), approver),
            )
            if req.kind == "invoice":
                conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (req.ref_id,))
            elif req.kind == "rent":
                lease = conn.execute("SELECT next_due FROM leases WHERE id = ?", (req.ref_id,)).fetchone()
                nxt = _add_month(date.fromisoformat(lease["next_due"])).isoformat()
                conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (nxt, req.ref_id))
            conn.execute(
                "UPDATE payment_requests SET status = 'paid', decided_by = ?, decided_at = ? WHERE id = ?",
                (approver, _now(), request_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return PaymentResult(
            paid=True, request=_request(conn, request_id), payment_id=cur.lastrowid, cash_before=before,
            cash_after=after, message=f"Paid ${req.amount:.2f} from '{account}', approved by {approver}.",
        )


@mcp.tool(annotations=HUMAN_ONLY, tags={"human_only"})
def reject_payment_request(
    request_id: Annotated[int, Field(description="A pending payment request id.")],
    rejected_by: Annotated[str, Field(description="Full name of the HUMAN rejecting it.")],
    note: Annotated[str, Field(description="Why it was rejected.")] = "",
) -> PaymentRequest:
    """HUMAN ONLY. Reject a pending payment request. No money moves. Writes payment_requests."""
    if rejected_by.strip().lower() in NOT_A_HUMAN:
        raise ToolError("reject_payment_request needs the name of the human reviewer.")
    with closing(_connect_rw()) as conn:
        req = _request(conn, request_id)
        if req.status != "pending_approval":
            raise ToolError(f"Request {request_id} is '{req.status}', not pending_approval.")
        conn.execute(
            "UPDATE payment_requests SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? "
            "WHERE id = ?",
            (rejected_by.strip(), _now(), note.strip() or None, request_id),
        )
        conn.commit()
        return _request(conn, request_id)


@mcp.tool(annotations=HUMAN_ONLY, tags={"human_only"})
def reset_working_database(
    confirm: Annotated[bool, Field(description="Must be true. Replaces every change in the working copy.")],
) -> ResetResult:
    """HUMAN ONLY. Copy the pristine data/campus_customs.db over the working copy, undoing every
    payment, request, draft and decision. Run this before every full ticket-resolution run.
    """
    if not confirm:
        raise ToolError("Pass confirm=true to reset the working database.")
    if not ORIGINAL_DB.exists():
        raise ToolError(f"Original database not found: {ORIGINAL_DB}")
    if DB_PATH == ORIGINAL_DB:
        raise ToolError("The working database path points at the original. Refusing to reset.")
    shutil.copyfile(ORIGINAL_DB, DB_PATH)
    _ensure_workflow_tables()
    return ResetResult(
        reset=True, source=ORIGINAL_DB.name, target=DB_PATH.name,
        message="Working copy restored to original values; workflow tables recreated empty.",
    )


if __name__ == "__main__":
    mcp.run()
