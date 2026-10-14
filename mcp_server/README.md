# Campus Customs MCP Server

**What it is for:** this is the shared tool layer for the Homework 5 agent team. Every agent (Boss, Inventory,
Accounting, Facilities, Customer Service) gets shop data only through this server's tools, so they all see the
same facts and nobody can invent stock, prices, dates or balances. Claude Code connects to the same server
through `../.mcp.json`. It is built with [FastMCP](https://gofastmcp.com) and serves the tools over MCP (stdio by
default).

**Database it uses:** `../data/campus_customs_new.db`, the working copy. The pristine original,
`../data/campus_customs.db`, is only ever read, by the human-only reset tool, which copies it over the working copy
before a full run. You can point the server at different files with the `CAMPUS_CUSTOMS_DB` and
`CAMPUS_CUSTOMS_ORIGINAL_DB` environment variables. "Today" is `desk.date_today` (2026-08-31), not the system clock.
**Nothing in this server sends email or contacts vendors. There is no send tool.**

**Workflow tables:** the server adds three tables to the working copy if they're missing (`CREATE TABLE IF NOT
EXISTS`): `payment_requests` (the human approval queue), `message_drafts` (customer drafts, status always
`draft`) and `ticket_decisions` (the Boss's final calls). A reset removes them, and they're recreated empty on the
next call. The original database is never altered.

## Tools (20)

### Ticket overview tools (read-only)

| Tool | For ticket | Reads | Returns |
|---|---|---|---|
| `check_customer_order_fulfillment(ticket_id)` | 101: tee size S | tickets, inventory, invoices, vendors, desk | Stock for the requested SKU and size, other sizes in stock, the linked invoice with days overdue, and its vendor's lead time and whether an unpaid invoice blocks it |
| `check_rent_due_and_cash(ticket_id)` | 102: rent notice | tickets, leases, desk, cash_accounts, invoices | Rent, due date and days until due, cash on hand, cash left after rent, and cash left after rent plus open invoices |
| `quote_bulk_order_discount(ticket_id, discount_pct=0)` | 103: bulk hoodies | tickets, inventory, pricing, vendors, invoices, desk | Shortfall, stock for every size, cost and list price, margin and profit at the discount, the largest discount before a loss, restock cost, and every vendor's lead time and block status |

### General read tools (read-only)

| Tool | Reads | Returns |
|---|---|---|
| `list_open_tickets()` | tickets, desk | Every ticket with status `open` |
| `list_tickets()` | tickets, desk | Every ticket with its current status (used by the dashboard's ticket list) |
| `get_ticket(ticket_id)` | tickets, payment_requests, message_drafts, ticket_decisions | The full ticket row, plus the requests, drafts and decisions already recorded for it |
| `check_stock(sku, size=None)` | inventory, pricing, desk | Stock for one size or every size, with unit cost and list price |
| `list_vendors()` | vendors, invoices, desk | Every vendor: specialty, lead_days, open invoices, block status, earliest ETA if unblocked today |
| `get_lease(lease_id)` | leases, desk | Space, landlord, monthly rent, next due date, days until due, overdue flag |
| `get_cash_position()` | cash_accounts, invoices, payment_requests, leases, desk | Cash on hand, open invoices, pending approval requests, cash after pending, rent due within 14 days |
| `list_payment_requests(status=None, ticket_id=None)` | payment_requests | The approval queue, filterable |
| `list_message_drafts(ticket_id=None)` | message_drafts | Customer drafts, filterable |

### Agent write tools (they only add workflow records, and no money moves)

| Tool | Reads | Writes | Notes |
|---|---|---|---|
| `prepare_invoice_payment(invoice_id, reason, ticket_id=None)` | invoices, vendors, cash_accounts, payment_requests | payment_requests | The amount comes from the invoice. Status `pending_approval`. A duplicate pending request is returned, not re-created |
| `prepare_rent_payment(lease_id, reason, ticket_id=None)` | leases, cash_accounts, payment_requests | payment_requests | The amount is `leases.monthly_rent` |
| `prepare_purchase_order(vendor_id, sku, size, qty, reason, ticket_id=None)` | vendors, inventory, pricing, invoices, cash_accounts, payment_requests | payment_requests | The amount is qty × `pricing.unit_cost`. It flags if the vendor is blocked by an unpaid invoice |
| `draft_customer_message(ticket_id, subject, body)` | tickets | message_drafts | The recipient is `tickets.requester`. Status is always `draft`, and there is no send tool |
| `record_ticket_decision(ticket_id, decision, summary)` | tickets | ticket_decisions, tickets.status | Called by the backend after it validates the Boss's output. It is not given to agents |

Each `prepare_*` and `draft_*` tool also takes a `requested_by` / `drafted_by` argument. The backend hides it from
the agents and fills in the real agent name.

### Human-only tools (never given to an agent)

| Tool | Reads | Writes | Rules |
|---|---|---|---|
| `approve_and_pay(request_id, approved_by, account="checking")` | payment_requests, cash_accounts, invoices, leases, desk | cash_accounts, payments, payment_requests, invoices.status or leases.next_due | Needs a named human (agent names are rejected). **Refuses if cash would go negative.** Refuses a PO while the vendor has an unpaid invoice. Runs as one transaction |
| `reject_payment_request(request_id, rejected_by, note="")` | payment_requests | payment_requests | No money moves |
| `reset_working_database(confirm=true)` | the original `campus_customs.db` | the working copy, replaced entirely | Run before every full ticket-resolution run |

Each tool validates its ids (ticket, invoice, lease, vendor, SKU/size, request) and returns an MCP error instead
of guessing. Return types are Pydantic models in `models.py`.

## Run

From the `Homework 5` folder:

```powershell
.\.venv\Scripts\python.exe -m pip install fastmcp
.\.venv\Scripts\python.exe mcp_server\server.py
```

The agent backend starts this same server as a child process. See `../backend/config.py` for which agent can
see which tool.
