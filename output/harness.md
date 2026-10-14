# Harness — Homework 5: Campus Customs Multi-Agent Ops Team

Living documentation for the Campus Customs operations system: an MCP server, a FastAPI backend that runs a
team of five agents (Boss, Inventory, Accounting, Facilities, Customer Service), and a React dashboard where
humans watch the agents work and approve payments.

**Ground rules for this simulation:** the data is fictional. No agent ever emails a customer or contacts a real
vendor or landlord. Every message is a draft that stays on the dashboard. Any payment needs human approval, and
the pay tool refuses to let cash go negative.

This file has two parts. **Part A: Reference** describes the finished system (setup, tables, MCP tools, agents,
API routes, dashboard, safety rules, limits). **Part B: Build log** is the question-by-question record written as
the work happened. Part B is kept as written, so its counts reflect each point in time (for example "19 tools" in
Question 5; the final count is 20).

---

# Part A: Reference

## A1. What it is and how to run it

```
React dashboard (frontend/, :5173)  ──HTTP──▶  FastAPI backend (backend/main.py, :8000)
                                                   │  agent team (backend/team.py): Boss + 4 specialists, gpt-5.6-luna via Portkey
                                                   │  one MCP client (stdio)
                                                   ▼
                                         MCP server (mcp_server/server.py, FastMCP, 20 tools)
                                                   │  the only code that touches the database
                                                   ▼
                                  data/campus_customs_new.db (working copy)  ◀── reset ── data/campus_customs.db (pristine)
```

| Step | Command (Windows PowerShell, from `Homework 5`) |
|---|---|
| Python setup (once) | `python -m venv .venv` · `.\.venv\Scripts\Activate.ps1` · `pip install -r requirements.txt` |
| API key | `PORTKEY_API_KEY` in the AI Foundations `.env` (never printed or committed) |
| Backend | `cd backend` · `uvicorn main:app --reload --port 8000` → http://localhost:8000 (docs at `/docs`) |
| Dashboard (once: `npm install`) | `cd frontend` · `npm run dev` → opens http://localhost:5173 |
| Fresh run | **Fresh start** on the board (or `POST /api/reset`), then send each ticket to the team |
| Command-line alternative | `.\.venv\Scripts\python.exe backend\run_team.py --all --reset` |
| Claude Code (Vibe Coder) | `.mcp.json` registers the same MCP server; start Claude Code in `Homework 5` |

Python 3.14; FastMCP 4.1, Pydantic AI 2.54 (slim, with openai/mcp/fastmcp), FastAPI 0.142, uvicorn 0.54, Pydantic
2.14 (`requirements.txt`). React 19, Vite 8, TypeScript 6 (`frontend/package.json`).

### Files

| Path | What it is |
|---|---|
| `README.md` | How to set up and run everything: clean DB copy, MCP server, backend, board, reset before a full run |
| `AI_prompts.md` | Every prompt, word for word, by question |
| `requirements.txt` | Pinned Python dependencies |
| `.env.example`, `.gitignore` | Placeholder settings (the real `.env` is never committed); what stays out of git |
| `.mcp.json` | Registers the MCP server for Claude Code. Pre-approval lived in `.claude/settings.local.json`, which is local and not committed |
| `data/campus_customs.db` / `campus_customs_new.db` | Pristine original (never written) / working copy |
| `mcp_server/server.py`, `models.py`, `README.md` | MCP server, its Pydantic return types, its tool list |
| `backend/prompts/*.md` | One system prompt per agent |
| `backend/models.py` | Agent outputs, run results, audit steps, API bodies |
| `backend/config.py` | Model lock, spend limits, per-agent tool allowlists |
| `backend/team.py`, `audit.py`, `run_team.py`, `main.py` | Agent team and loop, audit writer, command line, FastAPI app |
| `frontend/` | React + Vite + TypeScript dashboard (`src/App.tsx`, `src/components/*`) |
| `output/harness.md` | This file |
| `output/mcp_smoke.json` | Question 4 evidence: each MCP tool called from Claude Code, matched to the database |
| `output/desk_tickets.html` | Question 6 plan (Expected), Question 9 results (Actual), the Cash ledger, and the Question 10 Reflection |
| `output/design.md` | Dashboard design choices |
| `output/audit_trail.json` | Append-only log of every agent step and human action |
| `output/resolved_tickets.json` | Question 9 outcome per ticket |
| `output/resolved_board.html`, `output/screenshots/` | Question 9 board screenshots, one per ticket |
| `output/github_url.txt` | The public repository URL |

## A2. Database tables

SQLite. "Today" is `desk.date_today` = **2026-08-31**, never the computer clock. The first nine tables come from
the data pack; the last three are workflow tables the MCP server adds to the working copy (`CREATE TABLE IF NOT
EXISTS`, recreated empty after every reset).

| Table | Key fields | Used for |
|---|---|---|
| `desk` | `date_today` | The shop's clock for overdue, due-soon and ETA logic |
| `cash_accounts` | `name` (PK), `balance`, `date` | Checking balance ($3,400.00 at start). Only the pay tool changes it, and never below 0 |
| `inventory` | `sku`+`size` (PK), `name`, `qty`, `location` | Stock and shortfalls by SKU and size |
| `pricing` | `sku` (PK), `unit_cost`, `list_price` | Margins, discount limits, PO amounts |
| `vendors` | `id`, `name`, `specialty`, `lead_days` | Restock choice (by specialty) and the only source of lead times |
| `invoices` | `id`, `vendor_id`, `amount`, `due_date`, `status` | What's owed; an `open` invoice blocks its vendor from shipping |
| `leases` | `id`, `space_name`, `landlord`, `monthly_rent`, `next_due` | Rent for the Chapel Street shop |
| `payments` | `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by` (NOT NULL) | Ledger of executed payments, each with a named human approver |
| `tickets` | `id`, `type`, `requester`, `subject`, `sku`/`size`/`qty`, `lease_id`, `invoice_id`, `status`, `notes` | The desk. `type` drives routing; `status` records the outcome |
| `payment_requests` *(workflow)* | `kind`, `ref_id`, `vendor_id`, `sku`/`size`/`qty`, `amount`, `reason`, `ticket_id`, `requested_by`, `status`, `decided_by` | The human approval queue (pending_approval → paid or rejected) |
| `message_drafts` *(workflow)* | `ticket_id`, `to_name`, `subject`, `body`, `drafted_by`, `status` = `draft` | Customer messages. Never sent by the system |
| `ticket_decisions` *(workflow)* | `ticket_id`, `decision`, `summary`, `decided_by` | The Boss's final calls and human closes |

## A3. MCP tools (20)

All 20 live in `mcp_server/server.py`. Read tools open the database read-only. Every id is validated, and unknown
ids or the wrong ticket type return an error instead of a guess. Payment amounts are always looked up by the
server, never taken from the caller.

| Tool | Tables | Used by |
|---|---|---|
| `check_customer_order_fulfillment(ticket_id)` | tickets, inventory, invoices, vendors, desk | Boss, Inventory, Customer Service |
| `check_rent_due_and_cash(ticket_id)` | tickets, leases, desk, cash_accounts, invoices | Boss, Accounting, Facilities |
| `quote_bulk_order_discount(ticket_id, discount_pct)` | tickets, inventory, pricing, vendors, invoices, desk | Boss, Inventory, Accounting, Customer Service |
| `list_open_tickets()` | tickets, desk | Boss |
| `list_tickets()` | tickets, desk | Backend (dashboard ticket list) |
| `get_ticket(ticket_id)` | tickets, payment_requests, message_drafts, ticket_decisions | All five agents, backend |
| `check_stock(sku, size)` | inventory, pricing, desk | Inventory, Accounting, Customer Service |
| `list_vendors()` | vendors, invoices, desk | Inventory, Accounting |
| `get_lease(lease_id)` | leases, desk | Facilities |
| `get_cash_position()` | cash_accounts, invoices, payment_requests, leases, desk | Boss, Accounting, Facilities, backend |
| `list_payment_requests(status, ticket_id)` | payment_requests | Boss, Accounting, backend |
| `list_message_drafts(ticket_id)` | message_drafts | Boss, Customer Service, backend |
| `prepare_invoice_payment(invoice_id, reason, ticket_id)` | invoices, vendors, cash_accounts → **writes** payment_requests | Accounting |
| `prepare_rent_payment(lease_id, reason, ticket_id)` | leases, cash_accounts → **writes** payment_requests | Accounting |
| `prepare_purchase_order(vendor_id, sku, size, qty, reason, ticket_id)` | vendors, inventory, pricing, invoices, cash_accounts → **writes** payment_requests | Accounting |
| `draft_customer_message(ticket_id, subject, body)` | tickets → **writes** message_drafts | Customer Service |
| `record_ticket_decision(ticket_id, decision, summary)` | tickets → **writes** ticket_decisions, tickets.status | Backend only (after validating the Boss's output; human closes) |
| `approve_and_pay(request_id, approved_by)` | payment_requests, cash_accounts, invoices, leases → **writes** cash_accounts, payments, payment_requests, invoices/leases | **Humans only** (dashboard Approve) |
| `reject_payment_request(request_id, rejected_by, note)` | **writes** payment_requests | **Humans only** |
| `reset_working_database(confirm)` | copies campus_customs.db over the working copy | **Humans only** (Fresh start) |

## A4. The five agents

Every agent runs on **`gpt-5.6-luna`** through Portkey (model locked in `config.py`), with reasoning effort `low`
and concise reasoning summaries for the audit trail. Prompts are in `backend/prompts/`. Each prompt sets the
agent's scope, shop rules, tools, teammates, method, output format and a "Never" list, plus a persona that sets
tone only.

| Agent | Persona | Owns | MCP tools | Returns |
|---|---|---|---|---|
| **Boss** | Miranda Priestly | Reads the ticket, briefs only the specialists it needs, weighs reports, makes the final call | list_open_tickets, get_ticket, the 3 overview tools, get_cash_position, list_payment_requests, list_message_drafts | `BossDecision` |
| **Inventory** | Dwight Schrute | Stock by SKU/size, shortfalls, alternatives, restock vendor (by specialty), lead time and block status | get_ticket, check_stock, list_vendors, check_customer_order_fulfillment, quote_bulk_order_discount | `SpecialistReport` |
| **Accounting** | Ben Wyatt | Cash, invoices, margins and discounts; **prepares** payments and POs only if cash covers them | get_ticket, get_cash_position, list_payment_requests, list_vendors, check_stock, check_rent_due_and_cash, quote_bulk_order_discount, prepare_invoice_payment, prepare_rent_payment, prepare_purchase_order | `SpecialistReport` |
| **Facilities** | Mr. Carson | Lease, rent timing, the Chapel Street space | get_ticket, get_lease, check_rent_due_and_cash, get_cash_position | `SpecialistReport` |
| **Customer Service** | Ted Lasso | **Drafts** customer replies from verified facts only (never sends, no unbacked dates or prices) | get_ticket, check_customer_order_fulfillment, check_stock, quote_bulk_order_discount, list_message_drafts, draft_customer_message | `SpecialistReport` |

**How they connect:** every agent has a backend `delegate(to, task)` tool. The Boss briefs specialists, and a
specialist can consult another specialist (never itself or the Boss), at most 2 levels deep and 8 delegations per
ticket. Each agent's loop (model response → tool calls → results → … → typed output) is stepped with
`Agent.iter`, and every step is appended to `output/audit_trail.json` (time, run, agent, parent, depth, step kind,
brief, reasoning summary, text, tool calls and arguments, results, output, summary, cumulative usage, errors).
After the Boss answers, the backend drops any request or draft id that doesn't exist and records the decision
through MCP.

## A5. API routes (`backend/main.py`, http://localhost:8000)

| Method | URL | What it does |
|---|---|---|
| GET | `/api/health` | Server up, agent team connected, model, whether a run is in progress |
| GET | `/api/tickets` | All tickets: status, open/resolved, pending payment ids, draft ids, latest decision |
| GET | `/api/tickets/{id}` | One ticket with its requests, drafts and decisions |
| POST | `/api/tickets/{id}/run` | Run the agent team on the ticket; returns the run result (409 if a run is already going) |
| POST | `/api/tickets/{id}/close` | **Human** marks a worked ticket resolved. Body `{"closed_by": "Name"}`. 409 while a payment is pending |
| GET | `/api/events?limit=&since=&ticket_id=&run_id=&agent=` | Recent agent and human events from the audit trail, oldest first; poll with `since` |
| GET | `/api/payment-requests?status=&ticket_id=` | The approval queue |
| POST | `/api/payment-requests/{id}/approve` | **Human** Approve button. Body `{"approved_by": "Name"}`. The only route that moves cash; 409 if refused |
| POST | `/api/payment-requests/{id}/reject` | **Human** rejects a request. No money moves |
| GET | `/api/drafts?ticket_id=` | Customer drafts (never sent) |
| GET | `/api/cash` | Current checking balance from `cash_accounts`, pending total, balance after pending |
| POST | `/api/reset` | Restore the working database to original values (the audit trail is kept) |

CORS allows the Vite origin `http://localhost:5173` (and `127.0.0.1:5173`). A single lock means a run, an approval,
a close or a reset never overlap.

## A6. Dashboard (`frontend/`)

The **Ops Desk**: navy masthead with the checking balance (it animates down on every approval and shows "−$X"),
a ticket list with Open/Resolved pills, the selected ticket's agent roster (working, done, or "Not needed"), a live
activity feed while the team works, then the Boss's decision with "Your next steps", a "What each agent did" card
per specialist, customer drafts stamped "DRAFT · NOT SENT", and an Approvals panel (name, Approve & pay,
two-step Reject). Each agent has one accent colour, a monogram and a one-line motto. Full rationale is in
`output/design.md`; Question 9 screenshots are in `output/resolved_board.html`.

## A7. Safety rules

**Shop rules (from Question 1, enforced in code as well as prompts):**

| Rule | Where it's enforced |
|---|---|
| Nothing is ever sent | No send tool exists. Drafts have `status = 'draft'` by a CHECK constraint. The recipient comes from the ticket |
| `desk.date_today` is today | Every MCP tool computes overdue, due and ETA from `desk`, never the system clock |
| Lead times only from `vendors.lead_days` | ETA = date_today + lead_days in the server; prompts forbid estimates |
| A vendor won't ship with an unpaid invoice | Tools flag `blocked_by_unpaid_invoice`. The pay tool refuses a PO to a blocked vendor |
| Every payment needs human approval | Agents can only create `pending_approval` requests. `approve_and_pay` is in no agent's allowlist, a pre-call guard blocks it anyway, and the server rejects agent names as approvers |
| The pay tool refuses insufficient cash | One transaction checks `balance − amount ≥ 0` before debiting, otherwise "REFUSED" (HTTP 409) |
| Reset before a full run | Human-only `reset_working_database` copies the pristine file. The original is never opened for writing |
| Never invent data | Values come from the database or arithmetic on it. Amounts are set by the server. Unknown ids raise errors. Cited ids are validated |

**Real money and real customer data (guardrails a real business would want):** least-privilege tool allowlists
per agent; the agent identity (`requested_by`, `drafted_by`) is stamped by the backend, not the model; every
payment is tied to a named human (`payments.approved_by`) and the audit trail; duplicate requests are returned
instead of re-created; reject needs a confirm click; human approvals, rejections, closes and resets are all
audited; the API key stays in `.env`, never in logs or the audit trail; the customer-facing prompt forbids
revealing costs, margins, cash problems, vendor issues or other customers.

**Tokenomics (spend):** one cheap model (`gpt-5.6-luna`, enforced at startup) with low reasoning effort. Hard caps
per ticket across the whole team: 40 model requests, 60 tool calls, 400k tokens. Also at most 10 steps per agent
run, 8 delegations, depth 2. Plus a 120 s request timeout with 2 retries, one-call overview tools, and briefs that
pass facts along. Measured cost of the Question 9 run: **151,195 tokens for all three tickets** (59k / 30k / 62k).

## A8. Known limitations

- **Approver identity is a typed name, not a login.** A real deployment needs authentication on the approve,
  close and reset routes.
- **Agents sometimes over-consult.** In Question 9: 10 delegations against the 8 planned, both extras being
  specialist → Accounting consults. The duplicate guard kept them harmless, but they cost tokens.
- **Draft wording isn't checked in code.** Draft #2 (ticket 103) quoted a restock date the shop couldn't fund. A
  next step would be a backend check that blocks ETA language unless the restock's PO is paid.
- **The audit trail is one JSON array** that is rewritten on each append (under a lock). That's fine at this
  scale; a real system would use JSON Lines or a table.
- **Windows `--reload`** only works when uvicorn runs in a normal terminal (see Question 7).
- **One run at a time.** The backend serialises runs and money actions with a single lock (single-user desk).

---

# Part B: Build log

---

## Question 2: Study the Campus Customs Database

### Data files

| File | Purpose |
|---|---|
| `data/campus_customs.db` | **Pristine original** from the data pack (`data (2).zip`). Never written to. It is the source for "reset to original values" before every full ticket run. |
| `data/campus_customs_new.db` | **Working copy**. The agents and tools read and write this file. Reset means copying the original over it. |

SQLite, 9 tables, 24 rows in total. The shop's "today" is **2026-08-31** (`desk.date_today`). That date, not
the computer's clock, decides what is overdue.

### Tables, fields and why they matter

**`desk`** (1 row): `date_today`, `notes`
Why it matters: it is the shop's clock. Every agent uses `date_today` for overdue and due-soon logic and for
lead-time ETAs.

**`cash_accounts`** (1 row): `name` (PK), `balance`, `date`
Why it matters: Accounting reads this before preparing any payment. The pay tool must refuse if `balance` would
go below 0 (it is currently `checking` = **$3,400.00**).

**`inventory`** (10 rows): `sku` + `size` (composite PK), `name`, `qty`, `location`
Why it matters: Inventory checks stock by SKU and size here to find shortages (qty 0, or less than requested)
and to tell staff which aisle to pick from.

**`pricing`** (4 rows): `sku` (PK), `unit_cost`, `list_price`
Why it matters: Accounting uses cost against price for margin and profitability checks, for example how big a
bulk discount can be. Inventory uses `unit_cost` to price restock purchase orders.

**`vendors`** (3 rows): `id` (PK), `name`, `specialty`, `lead_days`
Why it matters: Inventory matches a shortage to the right supplier by `specialty`. `lead_days` is the
**only** source for restock ETAs.

**`invoices`** (1 row): `id` (PK), `vendor_id` (FK to vendors), `amount`, `due_date`, `status`, `description`
Why it matters: Accounting tracks what the shop owes. An `open` invoice past `date_today` is overdue, and a
vendor with an unpaid invoice **will not ship**, so this table can block Inventory's restocks.

**`leases`** (1 row): `id` (PK), `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`
Why it matters: Facilities owns this table (rent amount, landlord and next due date for the Chapel Street shop)
and passes rent payments to Accounting.

**`payments`** (0 rows): `id` (PK), `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`
Why it matters: it is the ledger of executed payments. `approved_by` (NOT NULL) records the human who approved
each one, which gives an audit trail for the human-approval rule. It starts empty.

**`tickets`** (3 rows): `id` (PK), `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id` (FK),
`invoice_id` (FK), `status`, `notes`, `created_at`
Why it matters: it is the Boss's inbox. `type` drives routing, and the optional `sku`/`size`/`qty`/`lease_id`/
`invoice_id` columns link each ticket into the other tables.

### Relationships

```
tickets ──sku,size──▶ inventory ──sku──▶ pricing
   │ ──invoice_id──▶ invoices ──vendor_id──▶ vendors (lead_days)
   │ ──lease_id────▶ leases
payments ──kind + ref_id──▶ invoices.id / leases.id   (soft link, no FK)
cash_accounts ◀── every payment debits this, guarded so it never goes below 0
desk.date_today ── the clock for all due-date and ETA logic
```

### The three open tickets

All three were created on 2026-08-31 (today) and are `open`.

**Ticket 101: `customer_order`, Tauhid Zaman, Bulldog tee size S x 1**
- `inventory`: CC-TEE-WHITE size S has **qty 0**, so we can't fill it from stock (M=5, L=3, XL=2 are in stock).
- Linked `invoice_id` 501: **$840.00** to Bulldog Print Co (vendor 1, apparel reprint, 5 lead days),
  "Rush reprint CC-TEE-WHITE S". It was due 2026-08-28 and is still `open`, so it is **3 days overdue**.
- Chain: the vendor won't ship while invoice 501 is unpaid. Accounting has to prepare the $840 payment, a human
  approves it, and then the reprint can ship. The earliest ETA is 2026-08-31 + 5 = **2026-09-05**.
  Customer Service drafts a delay or ETA message (it stays a draft).
- Agents involved: Boss, Inventory, Accounting, Customer Service.

**Ticket 102: `rent_notice`, Elm City Properties, rent due**
- Linked `lease_id` 1: Chapel Street shop, **$2,400.00/month**, `next_due` **2026-09-02**, so it is due in
  2 days and not overdue yet.
- Facilities confirms the lease details. Accounting checks cash and prepares the payment for human approval.
- Agents involved: Boss, Facilities, Accounting.

**Ticket 103: `price_override`, Yale AI Club, 20 x Basic Hoodie size M with a bulk discount**
- `inventory`: CC-HOOD-NAVY size M has **qty 8**, so we are **12 short** (S=4, L=14, XL=6 are other sizes).
- `pricing`: cost $22.00 and list price $58.00, so the margin is $36.00/unit (62%). At list price the order is
  $1,160 with $720 profit. Accounting can decide how much discount still leaves a healthy margin. The Boss
  makes the final call on the override.
- Restocking 12 M from Bulldog Print Co (the apparel vendor) costs about 12 x $22 = **$264** at cost and takes
  5 days. But it is **blocked by the same unpaid invoice 501**.
- Agents involved: Boss, Inventory, Accounting, Customer Service.

### How the tickets interact (the key constraint)

| Commitment | Amount | Cash after |
|---|---:|---:|
| Starting checking balance | | $3,400.00 |
| Pay invoice 501 (overdue, unblocks Bulldog Print Co) | $840.00 | $2,560.00 |
| Pay rent, lease 1 (due 09-02) | $2,400.00 | **$160.00** |
| Restock 12 hoodies M (PO at cost) | $264.00 | **would be -$104, so it is refused** |

The tickets are connected. Invoice 501 blocks both 101 and 103, and the cash can't cover every payment. Paying
the invoice and the rent fits ($160 left). Adding the hoodie restock PO would push the balance negative, so the
pay tool must refuse it unless it is reordered, the order is deferred or reduced, or the club pays a deposit
first. The agents have to prioritise. Rent has a hard deadline, the invoice is already overdue, and the
discounted bulk order is optional revenue. A human approves each payment.

---

## Question 3: Build the MCP Server

**What was built:** `mcp_server/server.py`, a FastMCP server (FastMCP 4.1, stdio) that every agent will use
to reach the shop database, plus `mcp_server/models.py` (Pydantic return types) and `mcp_server/README.md`.

**Database:** `data/campus_customs_new.db` (the working copy). You can override it with the `CAMPUS_CUSTOMS_DB`
environment variable. The original `data/campus_customs.db` is never opened by the server.

**No invented data:**
- Every connection is opened with SQLite `mode=ro`, so these three tools physically cannot change the database.
- Every returned value is either a database value or simple arithmetic on database values. Those fields are
  marked *Derived* in `models.py`.
- Unknown ticket, invoice, lease or SKU ids, or a ticket of the wrong `type`, raise an MCP `ToolError` instead of
  returning a guess.
- Days overdue, days until due and ETAs use `desk.date_today`, never the system clock.
- Tool annotations mark all three as `readOnlyHint=True`, `openWorldHint=False`, so they reach nothing outside the
  database.

### The three MCP tools

**1. `check_customer_order_fulfillment(ticket_id)`**
- **Tables read:** `tickets` (the order), `inventory` (stock for that SKU and size and the other sizes), `invoices`
  (the invoice linked by `tickets.invoice_id`), `vendors` (that invoice's vendor: lead time and open invoices),
  `desk` (today).
- **Ticket:** **101.** Tauhid Zaman needs 1 Classic Bulldog Tee (CC-TEE-WHITE) in size S.
- **Why it fits:** S is at 0, and the only way to get more is a reprint from Bulldog Print Co. That vendor is blocked
  by invoice 501 ($840, 3 days overdue), so one call gives the Boss the whole chain: out of stock, why the restock
  is stuck, what has to be paid, the earliest ETA once it is paid (2026-09-05), and which sizes Customer Service
  could offer instead (M 5 / L 3 / XL 2).

**2. `check_rent_due_and_cash(ticket_id)`**
- **Tables read:** `tickets` (the notice), `leases` (rent, landlord and `next_due` for the linked `lease_id`),
  `desk` (today), `cash_accounts` (cash on hand), `invoices` (other open bills).
- **Ticket:** **102.** Elm City Properties' notice that rent for the Chapel Street shop is due in 2 days.
- **Why it fits:** Facilities and Accounting need to know whether the $2,400 rent (due 2026-09-02) can be paid
  without starving the overdue $840 invoice. The tool shows cash goes $3,400 → $1,000 after rent → **$160** after
  rent and the open invoice, so the agents see the real cash squeeze, not just "rent is affordable".

**3. `quote_bulk_order_discount(ticket_id, discount_pct=0)`**
- **Tables read:** `tickets` (the request), `inventory` (all sizes of the SKU), `pricing` (unit cost and list
  price), `vendors` and `invoices` (who could restock, lead times, who is blocked), `desk` (today).
- **Ticket:** **103.** The Yale AI Club wants 20 Basic Hoodies (CC-HOOD-NAVY) in size M at a bulk discount.
- **Why it fits:** the Boss has to decide two things at once. How much discount still makes money: at 15% off,
  $49.30 per unit, a $27.30 margin and $546 profit; any discount above 62.1% loses money. And whether the
  order can be filled at all: only 8 M on hand, so 12 short, a $264 restock at cost, and the apparel vendor is
  blocked by invoice 501. This tool puts both answers in one result.

**Note on vendors (ticket 103):** the database has no table linking a SKU to its vendor, so the tool doesn't pick
one. It returns every vendor with `specialty`, `lead_days` and its block status, and the agent reasons from
`specialty`. Bulldog Print Co is "apparel reprint". That way the tool never invents a supplier relationship.

**Verification:** each tool was called once through an in-memory FastMCP client against the working copy. The
results matched the Question 2 analysis exactly. A wrong-type call (ticket 101 to the rent tool) returned an error.
Both `.db` files had identical MD5 hashes before and after, so nothing was changed.

---

## Question 4: Add the MCP Server to Vibe Coder and Test Each Tool

### How the server is connected

The Vibe Coder here is Claude Code. It loads project MCP servers from `.mcp.json` at the `Homework 5` root:

```json
{
  "mcpServers": {
    "campus-customs": {
      "type": "stdio",
      "command": ".venv/Scripts/python.exe",
      "args": ["mcp_server/server.py"],
      "env": {
        "CAMPUS_CUSTOMS_DB": "data/campus_customs_new.db",
        "FASTMCP_SHOW_SERVER_BANNER": "false"
      }
    }
  }
}
```

- **stdio transport.** Claude Code starts the server as a child process and talks to it over stdin/stdout. No
  network port is opened.
- **Relative paths.** The command uses the project's own `.venv` Python, and the paths resolve from the
  `Homework 5` folder. A session therefore has to be **started in `Homework 5`** for the server to load.
- **`CAMPUS_CUSTOMS_DB`** points the server at the working copy explicitly. The pristine
  `data/campus_customs.db` is never opened.
- **`FASTMCP_SHOW_SERVER_BANNER=false`** keeps FastMCP's startup banner off the stdio channel.
- **Pre-approval.** `.claude/settings.local.json` contains `"enabledMcpjsonServers": ["campus-customs"]`, so
  Claude Code loads the server without an approval prompt each session.
- `.mcp.json` was written by hand because the `claude` CLI isn't on PATH on this machine. It has the same format
  that `claude mcp add --scope project` writes.

Once connected, the tools appear in Claude Code as `mcp__campus-customs__check_customer_order_fulfillment`,
`mcp__campus-customs__check_rent_due_and_cash` and `mcp__campus-customs__quote_bulk_order_discount`, together
with the server's instructions (use `desk.date_today`, never invent values, nothing is sent).

### How the smoke test was run

1. A new Claude Code session was started in `Homework 5` so it would pick up `.mcp.json` and load the server.
2. Claude Code called each tool **natively through MCP**, once per ticket: 101, 102, and 103. Ticket 103 doesn't
   name a discount, so `discount_pct=15` was used as a test value.
3. Separately, every table in `data/campus_customs_new.db` was read with plain SQL (read-only), and each tool's
   output was checked against those values by hand.
4. The evidence was saved to `output/mcp_smoke.json`. For each call it records the prompt given to Claude Code,
   the tool name, the arguments, the full tool output, and a `db_check` line.

### Results

| Tool | Ticket | Key values returned | Database check |
|---|---|---|---|
| `check_customer_order_fulfillment` | 101 | TEE S qty 0 (M 5 / L 3 / XL 2); invoice 501 $840, 3 days overdue; Bulldog Print Co blocked; ETA 2026-09-05 once paid | `inventory`, `invoices`, `vendors.lead_days`=5, `desk` → **MATCH** |
| `check_rent_due_and_cash` | 102 | Rent $2,400 due 2026-09-02 (2 days); cash $3,400 → $1,000 after rent → $160 after open invoices | `leases`, `cash_accounts`, `invoices` → **MATCH** |
| `quote_bulk_order_discount` (15%) | 103 | 8 M on hand, 12 short; $49.30/unit, $27.30 margin (55.4%); $986 revenue, $546 profit; break-even 62.1%; restock $264 | `inventory`, `pricing` (22/58), `vendors` → **MATCH** |

All three tools ran through MCP and every returned value matched the database. The tools are read-only, so the
working copy was not changed.

---

## Question 5: Build the Agent Team and Grow the MCP Tools

### What was built

```
backend/
├── prompts/               # one system prompt per agent
│   ├── boss.md
│   ├── inventory.md
│   ├── accounting.md
│   ├── facilities.md
│   └── customer_service.md
├── models.py              # data types: SpecialistReport, BossDecision, TicketRunResult, AuditStep, ...
├── config.py              # model lock, spend limits, per-agent MCP tool allowlists
├── team.py                # the five agents, delegation, the audited agent loop, MCP connection
├── audit.py               # append-only writer for output/audit_trail.json
└── run_team.py            # command line: --ticket N / --all, optional --reset
```

The MCP server grew from 3 to **19 tools** (see `mcp_server/README.md`). The FastAPI layer that will serve this
team to the dashboard calls the same `Team` class.

### The five agents

Every agent runs on **`gpt-5.6-luna`** through Portkey (`PORTKEY_API_KEY` from the AI Foundations `.env`). The
model name is locked in `config.py`: any other value stops the backend at startup. Each prompt contains the shop
rules that agent needs, its scope (what it owns and what it doesn't), its tools and when to use each, its
teammates, a step-by-step method, the output format, and a "Never" list. Each agent also has a persona based on a
famous media character. The persona sets tone only, and every prompt says the shop rules beat the persona.

| Agent | Persona | Job | Returns |
|---|---|---|---|
| **Boss** | Miranda Priestly (*The Devil Wears Prada*): exacting, decisive, facts not feelings | Reads the ticket, delegates, weighs reports, makes the final call | `BossDecision` |
| **Inventory** | Dwight Schrute (*The Office*): intense, literal, obsessed with exact counts | Stock by SKU/size, shortfalls, alternatives, which vendor can restock (by specialty) and when | `SpecialistReport` |
| **Accounting** | Ben Wyatt (*Parks and Recreation*): calm budget hawk who says no to what the cash can't cover | Cash, invoices, margins and discounts; **prepares** payments and POs for human approval | `SpecialistReport` |
| **Facilities** | Mr. Carson (*Downton Abbey*): formal, punctilious, protective of the house | The Chapel Street space: lease, rent timing, landlord | `SpecialistReport` |
| **Customer Service** | Ted Lasso: warm, honest, never spins bad news | **Drafts** (never sends) customer messages using only verified facts | `SpecialistReport` |

### How the agents connect and loop

- **One tool layer.** The backend starts `mcp_server/server.py` once per team (stdio, the same server Claude
  Code uses). Each agent gets a *filtered view* of that single MCP toolset. There is no second shop-tools layer:
  every shop fact and every write goes through MCP.
- **Delegation.** Every agent has one backend tool, `delegate(to, task)`. The Boss can delegate to any
  specialist. A specialist can consult any *other* specialist, for example Facilities asking Accounting to
  prepare rent. A delegated agent runs its own full loop and returns its `SpecialistReport` to the caller.
  Agents can't delegate to themselves or to the Boss, the chain stops at depth 2, and a ticket gets at most 8
  delegations. The tool disappears from the agent's tool list once either limit is reached.
- **The loop.** Each agent run is stepped with Pydantic AI's `Agent.iter`. The model responds (reasoning
  summary, text, tool calls), the tools run, and the results go back to the model, until the agent returns its
  typed output. Every step is audited.
- **After the Boss answers**, the backend (in code, through MCP):
  1. checks every payment request and draft id the Boss cites, and drops any that don't exist (`dropped_ids`);
  2. changes a `resolved` decision to `awaiting_human_approval` if money or drafts still wait on a human;
  3. records the decision with `record_ticket_decision`, which also sets `tickets.status`.

### Each agent's MCP tools and the tables they touch

| Tool | Tables | Boss | Inventory | Accounting | Facilities | Customer Service |
|---|---|:-:|:-:|:-:|:-:|:-:|
| `list_open_tickets` | tickets, desk | ✓ | | | | |
| `get_ticket` | tickets, payment_requests, message_drafts, ticket_decisions | ✓ | ✓ | ✓ | ✓ | ✓ |
| `check_customer_order_fulfillment` | tickets, inventory, invoices, vendors, desk | ✓ | ✓ | | | ✓ |
| `check_rent_due_and_cash` | tickets, leases, desk, cash_accounts, invoices | ✓ | | ✓ | ✓ | |
| `quote_bulk_order_discount` | tickets, inventory, pricing, vendors, invoices, desk | ✓ | ✓ | ✓ | | ✓ |
| `check_stock` | inventory, pricing, desk | | ✓ | ✓ | | ✓ |
| `list_vendors` | vendors, invoices, desk | | ✓ | ✓ | | |
| `get_lease` | leases, desk | | | | ✓ | |
| `get_cash_position` | cash_accounts, invoices, payment_requests, leases, desk | ✓ | | ✓ | ✓ | |
| `list_payment_requests` | payment_requests | ✓ | | ✓ | | |
| `list_message_drafts` | message_drafts | ✓ | | | | ✓ |
| `prepare_invoice_payment` | invoices, vendors, cash_accounts → **writes** payment_requests | | | ✓ | | |
| `prepare_rent_payment` | leases, cash_accounts → **writes** payment_requests | | | ✓ | | |
| `prepare_purchase_order` | vendors, inventory, pricing, invoices, cash_accounts → **writes** payment_requests | | | ✓ | | |
| `draft_customer_message` | tickets → **writes** message_drafts | | | | | ✓ |
| `delegate` (backend, not MCP) | none; it runs another agent | ✓ | ✓ | ✓ | ✓ | ✓ |

**Not given to any agent:** `record_ticket_decision` (writes ticket_decisions and tickets.status; the backend calls
it after validation), and the human-only `approve_and_pay` (writes cash_accounts, payments, payment_requests,
invoices/leases), `reject_payment_request` (writes payment_requests) and `reset_working_database` (replaces the
working copy from the original).

### Audit trail

`output/audit_trail.json` is a JSON array, **appended to and never wiped**. Each agent loop step adds one
`AuditStep` (`backend/models.py`):

| Field | Meaning |
|---|---|
| `time`, `run_id`, `ticket_id` | When it happened, and which ticket run it belongs to |
| `agent`, `agent_run_id`, `parent_agent`, `depth` | Who acted, which invocation, who delegated to them, and how deep in the chain |
| `step`, `kind` | Step number and type: `start`, `model_response`, `tool_results`, `final_output`, `error`, `run_summary` |
| `input` | The task brief the agent received (start steps) |
| `reasoning`, `text` | The model's reasoning summary (when returned) and any plain text |
| `tool_calls`, `tool_results` | Tool name, call id and arguments; result (truncated), with an error flag for retries and refusals |
| `output` | The agent's final typed output (final steps) |
| `usage` | Cumulative team requests, tool calls and tokens at that step |
| `error` | Exception text if the step failed. Failed runs are audited too |

Tool call ids link each call to its result, so any payment request or draft can be traced back to the agent,
the brief, and the facts behind it.

### First test (ticket 101 only)

`run_team.py --ticket 101` ran once against the working copy:

- The **Boss** read the ticket, the order overview and the cash position, then delegated to Inventory, Accounting
  and Customer Service.
- **Inventory** confirmed TEE S = 0 (M 5 / L 3 / XL 2), and that Bulldog Print Co is blocked by invoice 501 with an
  ETA of 2026-09-05 once unblocked.
- **Accounting** checked cash and created **payment request #1** (invoice 501, $840.00, `pending_approval`,
  `requested_by` = accounting). It noted that rent still fits: $3,400 − $840 − $2,400 = $160.
- **Customer Service** saved **draft #1** to Tauhid Zaman, offering M/L/XL or waiting for S. Status: `draft`, not
  sent.
- **Boss decision:** `awaiting_human_approval`. Rent comes first; approve #1 to unblock the restock; review the
  draft.
- Cash was still $3,400 and `payments` was empty afterwards. Nothing was paid or sent.
- **Cost:** 12 model requests, 13 tool calls, 43,604 tokens, 2 min 11 s. That works out to 29 audit steps.

Tickets 102 and 103 haven't been run yet. The full run starts with `--all --reset`.

### Safety guardrails

What a real business would want around real money, real customer data, and model spend. Each item is enforced
in code, not only in prompts.

**Money**
- **No agent can move money.** Agents can only *prepare* `pending_approval` requests. `approve_and_pay` is
  human-only: it isn't in any agent's allowlist, a pre-call guard blocks it anyway, and the server rejects agent
  names as `approved_by`.
- **Cash can never go negative.** The pay tool checks the balance inside one database transaction and refuses
  otherwise. It also refuses a PO to a vendor with an unpaid invoice.
- **Amounts come from the database**, never from the model (invoice amount, monthly rent, qty × unit cost).
- **No duplicate requests.** A matching pending request is returned instead of creating a second one.
- **Every payment is traceable** to a named human (`payments.approved_by`), the agent that prepared it
  (`requested_by`, stamped by the backend, not the model) and the audit trail.
- **Least privilege.** Each agent sees only the tools its job needs (table above).

**Customer and partner data**
- **Nothing is sent.** There is no send tool. Drafts are stored with status `draft` for a human to review.
- **Recipients come from the ticket**, so an agent can't redirect a message to a made-up address.
- Customer Service is told not to reveal internal finances, vendor problems, costs or other customers'
  details. Drafts are capped at 2,000 characters.
- **Secrets stay out.** The Portkey key is read from `.env` and never logged, printed or written to the audit
  trail. The working database is separate from the pristine original, which is never written.

**Tokenomics (spend)**
- **One cheap model.** `gpt-5.6-luna` for every agent, enforced at startup. Reasoning effort is `low`.
- **Hard caps per ticket, across the whole team** (shared usage counter): 40 model requests, 60 tool calls,
  400,000 tokens. Plus at most 10 steps per agent run, 8 delegations per ticket, and a delegation depth of 2.
  Exceeding any cap stops the run, and the stop is audited.
- **Cheap context.** One-call ticket overview tools replace chains of lookups. Prompts tell agents to brief
  teammates with facts already found so lookups aren't repeated. Audit fields are truncated.
- **Timeouts and retries.** A 120 s request timeout and 2 client retries. MCP tool errors get 2 retries before
  the agent must move on.
- **Measured.** Every run records requests, tool calls and tokens. The first ticket used about 44k tokens.

---

## Question 6: Plan the Three Tickets

**What was built:** `output/desk_tickets.html`, a single self-contained page (no external files). It has a tab
for each open ticket (101, 102, 103) and an empty **Cash & Reflection** tab reserved for later questions. Tabs
open on a click or double click, the arrow keys move between them, and `#101`, `#102`, `#103` or `#cash` in the
URL opens that tab directly.

**Each ticket tab has:**
- **Ticket facts:** the values from the MCP tools that the plan rests on.
- **Expected:**
  1. who the Boss calls first, and why;
  2. the ordered delegation chain, with depth, plus which agents are **not** called and why;
  3. the MCP tools each agent is expected to use, with arguments and read/write type, plus the tools that
     **must not** appear;
  4. the expected result: payment requests, drafts, decision, cash, and rough request counts.
- **Actual:** an empty comparison table (Actual / Matches plan?) to fill in after the full run.

**The plan in short (8 of 12 possible specialist-ticket pairings):**

| Ticket | First call | Delegations | Key expected outcome |
|---|---|---|---|
| 101 Tee S | Inventory | Boss→Inventory, Boss→Accounting, Boss→Customer Service | Request #1 (invoice 501, $840), draft #1 to Tauhid, `awaiting_human_approval` |
| 102 Rent | Facilities | Boss→Facilities, Facilities→Accounting (specialist-to-specialist) | Request #2 (rent, $2,400), no draft, `awaiting_human_approval`, $160 left after pending |
| 103 Hoodies | Inventory | Boss→Inventory, Boss→Accounting, Boss→Customer Service | **No PO** ($264 > $160, and the vendor is blocked), draft #2 with a 10–15% discount, `awaiting_human_approval` |

The plan assumes the full run resets the database and works the tickets in id order. That's why ticket 103
sees requests #1 and #2 already pending and has to refuse the restock PO.

---

## Question 7: Backend Routes

**What was built:** `backend/main.py`, a FastAPI app the React dashboard calls. Start it from the `backend`
folder with the project venv active:

```powershell
uvicorn main:app --reload --port 8000
```

It serves **http://localhost:8000** (interactive docs at `/docs`). On startup it starts the agent team and its
single MCP connection. Every route reads or changes shop data **only through MCP tools**: `main.py` never opens
the database. CORS allows the dashboard's dev origins (`localhost:5173`, `localhost:3000`).

### Routes

| Method | URL | What it does |
|---|---|---|
| GET | `http://localhost:8000/api/tickets` | All tickets with `status`, `state` (open or resolved), pending payment request ids, draft ids, and the latest decision |
| GET | `http://localhost:8000/api/tickets/{ticket_id}` | One ticket in full, with its payment requests, drafts and decisions |
| POST | `http://localhost:8000/api/tickets/{ticket_id}/run` | Runs the agent team on the ticket and returns the `TicketRunResult` (takes 1–3 minutes; 409 if a run is already going) |
| GET | `http://localhost:8000/api/events?limit=&since=&ticket_id=&run_id=&agent=` | Recent agent and human events from `audit_trail.json`, oldest first. Pass `latest_time` back as `since` to poll for new ones |
| GET | `http://localhost:8000/api/payment-requests?status=&ticket_id=` | The approval queue: the payments and POs the agents prepared |
| POST | `http://localhost:8000/api/payment-requests/{request_id}/approve` | **The human Approve button.** Body `{"approved_by": "Full Name"}`. The only route that moves cash; 409 if the pay tool refuses |
| POST | `http://localhost:8000/api/payment-requests/{request_id}/reject` | Human rejects a request. Body `{"rejected_by": "Full Name", "note": "..."}`. No money moves |
| GET | `http://localhost:8000/api/drafts?ticket_id=` | Customer message drafts (never sent by the system) |
| GET | `http://localhost:8000/api/cash` | Current `checking` balance from `cash_accounts`, plus the pending total and the balance after pending |
| POST | `http://localhost:8000/api/reset` | Restores the working database to its original values for a fresh run. The audit trail is kept |
| GET | `http://localhost:8000/api/health` | Server up, agent team connected, model name, whether a run is in progress |

**Open vs. resolved:** a ticket is `open` until the Boss records a final call. After that it's `resolved`, and
`status` keeps the detail (`awaiting_human_approval`, `deferred`, `needs_human`, `resolved`).
`needs_human_action` flags tickets with payment requests still waiting for approval.

**Supporting changes:**
- A 20th MCP tool, `list_tickets` (reads tickets and desk), because `list_open_tickets` hides tickets that have
  been worked.
- `AuditStep` now accepts `agent: "human"` and `kind: "human_action"`.
- `audit.read_all()` reads the trail under the writer's lock.

### Guardrails in the routes

- **Approve needs a human name** (2–80 characters). The MCP pay tool rejects agent names, refuses if cash would go
  negative, and refuses a PO while the vendor has an unpaid invoice. Refusals return **409** with the reason.
  Unknown ids return **404**.
- **One thing at a time.** A shared lock means a ticket run, an approval, or a reset can't overlap. Cash can't
  change while agents are reasoning about it. A second run returns 409.
- **Human actions are audited too.** Every approve (including refused attempts), reject and reset is appended to
  `output/audit_trail.json` as a `human_action` with the person's name.
- **No send route exists.** Drafts can be listed, never sent.

### Tests (server started with the command above)

| Check | Result |
|---|---|
| `GET /api/tickets`, `/cash`, `/payment-requests`, `/drafts`, `/events` | 200, values matched the database |
| Approve with `approved_by: "accounting"` | 400 "Agents cannot approve payments", audited |
| Approve with no name / unknown request 999 | 422 / 404 |
| Approve request #1 ($840) as "QA Tester" | 200, cash $3,400 → $2,560, `payments` row written, audited |
| Approve #1 again | 400 "not pending_approval" |
| `POST /api/reset` | Cash back to $3,400, all three tickets `open`, workflow tables empty, audited |
| `POST /api/tickets/102/run` while polling `/api/events` | 200 in about 2 min 47 s: Facilities and Accounting consulted, **one** rent request ($2,400, pending), decision `awaiting_human_approval`. 50k tokens, 14 requests. Events streamed in as each agent stepped |
| Second run / approve while a run is going | 409 both |
| `--reload` in a normal terminal | An edit to `main.py` triggered a clean shutdown (including the MCP process) and restart |

**Note for graders:** on Windows, uvicorn's `--reload` restarts the server by sending Ctrl+C. It works from a
normal terminal (tested), but not from a background process with no console window.

**Plan vs. actual, early sign (ticket 102):** the Boss briefed Facilities *and* Accounting in the same turn, and
Facilities also consulted Accounting, so two Accounting runs happened. This is the "wasteful but harmless" variant
flagged in `desk_tickets.html`: the duplicate guard returned the existing request, so only one rent request exists.

---

## Question 8: Agent Dashboard

**What was built:** `frontend/`, a React 19 + Vite 8 + TypeScript dashboard (the "Ops Desk"). It talks only to the
FastAPI backend at `http://localhost:8000`. Start it from `frontend/` with:

```powershell
npm run dev
```

This opens **http://localhost:5173** in the browser. The port is pinned (`strictPort`) because that is the origin
the backend allows: `main.py`'s CORS list includes `http://localhost:5173` and `http://127.0.0.1:5173`, and can be
extended with the `DASHBOARD_ORIGINS` environment variable. The browser's preflight (`OPTIONS`) requests returned
200 in testing.

### What the board does (the required minimum, and how)

| Requirement | How the board does it | Route(s) |
|---|---|---|
| List all tickets | "Desk" column: a card per ticket with type icon, subject, requester, **Open / Resolved** pill, and a flag if a payment awaits approval | `GET /api/tickets` |
| Pick a ticket and send it to the team | Select a card, then **Send to agent team** | `POST /api/tickets/{id}/run` |
| Show each agent and what it's saying and doing | Five roster cards light up (working / done / not needed, with the latest action). The live feed shows reasoning summaries, plain-English tool chips, briefs between agents (consults indented) and records created. Polls every 1.5 s | `GET /api/events?ticket_id=&since=` |
| Mark the ticket resolved when the run finishes | The pill flips to green ✓ Resolved, plus a toast with the decision, delegations and duration | `GET /api/tickets` |
| Short summary of what each agent did | The Boss's decision card (decision, summary, "Your next steps", "Why this call"), then a "What each agent did" card per specialist from its own report, and a line listing agents not needed | events (`final_output` steps) |
| Human approves a payment or purchase | "Approvals" panel: name field ("Approving as"), request cards with amount, reason and preparing agent, **Approve & pay** / two-step **Reject**. Refusals (409) shown as a red toast quoting the pay tool | `GET /api/payment-requests`, `POST …/approve`, `POST …/reject` |
| Checking balance drops after approval | Masthead cash card: the balance animates down, a "−$840.00" chip appears, a toast shows "Checking $3,400.00 → $2,560.00", and a bar shows what's already promised to pending requests | `GET /api/cash` |

Also: customer drafts shown as letters stamped **"DRAFT · NOT SENT"** (`GET /api/drafts`), a **Fresh start**
button with confirmation (`POST /api/reset`), a backend online/offline indicator (`GET /api/health`), and the
full activity log folded away after a run. Design choices are explained in **`output/design.md`**.

### Backend changes for the board

- Final audit steps now carry `summary` (the agent's own summary, untruncated) and `decision`, and keep up to
  12,000 characters of the final output, so the board can show each agent's report and the Boss's next steps
  without guessing.
- CORS already allowed the Vite origin (`http://localhost:5173`) from Question 7, and the board's requests
  passed preflight.

### End-to-end test (in the browser, through the UI)

| Step | Result |
|---|---|
| Open the board with the backend down, then start it | "Backend offline" banner with the start command; it connected automatically about 3 s after uvicorn was up |
| **Fresh start** | All three tickets back to Open, cash $3,400.00 |
| Select #101, **Send to agent team** | Pill turned blue. The feed streamed the Boss's tool calls, then the briefs to Inventory, Accounting and Customer Service. Facilities stayed "Standing by" |
| Run finished (184 s, 3 delegations) | #101 flipped to ✓ Resolved; toast "Ticket #101 resolved · Awaiting your approval". Roster: Boss, Inventory, Accounting, Customer Service ✓; Facilities "Not needed". Decision card, agent summaries and draft #1 letter shown. $840 request appeared in Approvals |
| **Approve & pay** as "QA Tester" | Balance animated $3,400.00 → **$2,560.00**, "−$840.00" chip, toast, request moved to "Recently decided · Paid · by QA Tester", and an audited `human_action` |
| Narrow window (≈320 px) | Fixed horizontal overflow (cash card, feed indentation, draft stamp) found in testing |
| `npm run build` (tsc + vite) | Clean. No console errors in the browser |

Bugs found and fixed during the test: an approval from a run before the reset showed up in the new run's feed
(human events are now scoped to the run they follow); "1 payment need" grammar; the draft stamp overlapping the
recipient on narrow screens.

---

## Question 9: Resolve the Tickets

### How the run was done

1. **Reset:** the board's **Fresh start** at 15:11:46 UTC. Read back from the database: `cash_accounts.checking` =
   **$3,400.00**, no payments, invoice 501 `open`, rent due 2026-09-02, all tickets `open`, workflow tables empty.
2. **Full run on the React board:** tickets sent to the agent team in id order, 101 → 102 → 103, each started
   only after the previous one finished. Every agent step was appended to `output/audit_trail.json` (entries after
   index 97).
3. **Human approvals:** done on the board by **Drew Hoffman**. Each payment was approved a few seconds after its
   ticket's run finished (#1 at 15:16:48, #2 at 15:20:08). Ticket 102 was closed on the board, and ticket 101 was
   closed after the user chose to close it. Ticket 103 (the Boss's call: `deferred`) was at first left deferred, then
   **closed as resolved by Drew Hoffman in Question 11** with the note: "Quote stands pending a customer deposit; restock PO waits for funding; draft #2 to be rewritten without the Sept 5 date before sending." No money moved.
4. **Evidence:** screenshots of each ticket on the React board (headless Chrome at 1440 px,
   `http://localhost:5173/?ticket=N`).

### Results

| Ticket | Agents (delegations) | Created | Boss's call → final status | Cash |
|---|---|---|---|---|
| 101 Tee size S | Boss → Inventory, Accounting, then Customer Service; Inventory → Accounting consult (4) | Request #1 invoice 501 $840.00 · draft #1 | awaiting_human_approval → **resolved** (approved, closed) | −$840.00 |
| 102 Rent | Boss → Facilities and Accounting (2) | Request #2 rent $2,400.00 | awaiting_human_approval → **resolved** (approved, closed) | −$2,400.00 |
| 103 Hoodies | Boss → Inventory, Accounting, Customer Service; Customer Service → Accounting consult (4) | Draft #2 (20% off). **No PO**: $264 > $160 | deferred → **resolved** (human close, Q11; restock still unfunded) | $0.00 |

**Cash:** $3,400.00 − $840.00 − $2,400.00 − $0.00 = **$160.00**. This equals `cash_accounts.checking` (160.0) in
the database after the run. `SUM(payments.amount)` = $3,240.00 in two rows, both `approved_by` = Drew Hoffman.
Invoice 501 is `paid`, the lease's `next_due` moved to 2026-10-02, and inventory is unchanged.

**Cost:** 41 model requests, 47 tool calls, 151,195 tokens, 620 s of agent time.

### Plan vs. actual (details in `desk_tickets.html`)

- **Held:** the right first owner on every ticket; Facilities only on 102; Inventory and Customer Service not on
  102; one request per obligation; no PO on 103; every amount from the database; nothing sent.
- **Missed:** two unplanned specialist → Accounting consults (10 delegations against 8). On 103 the Boss briefed
  Customer Service before the facts were in. Draft #2 states a September 5 completion date that isn't funded
  (flagged "do not send as written"). The discount was 20% against the planned 10–15% (still 52.6% margin).
- **Why the path differed:** the plan assumed no approvals until all three tickets had run. The human approved
  as each ticket finished, so 103 saw the vendor *unblocked*, and the **cash rule alone** stopped the restock. The
  ending balance was the predicted $160.00.

### Files produced

| File | Contents |
|---|---|
| `output/desk_tickets.html` | Actual sections filled for 101, 102 and 103 next to the untouched Expected sections, with a "Matches plan?" verdict per row; the Cash tab ledger ($3,400.00 → $160.00, each change and why, checked against the database); a reflection |
| `output/resolved_tickets.json` | Per ticket: id, final status, Boss's decision, outcome, each agent's contribution and tools, requests, drafts, human approvals, cash change, run stats |
| `output/resolved_board.html` | Double-click page: run summary, then each ticket's outcome, human actions and an embedded screenshot of the React board |
| `output/screenshots/board_ticket_{101,102,103}.png` | The same screenshots as standalone files |
| `output/audit_trail.json` | Appended with every step of the three runs and the human approvals and closes (never wiped) |

### Changes made for this question

- **Human close:** `POST /api/tickets/{id}/close` and a **Close ticket** button on the board. They let a person
  mark a worked ticket resolved once its payments are decided and drafts reviewed. The route refuses while a
  payment is pending and is audited.
- **Board details:** `?ticket=N` in the board's URL (used for screenshots); the decision card is labelled "Boss's
  call", so a closed ticket doesn't look like it's still waiting; deferred tickets say "Deferred by the Boss".
- **`requirements.txt`** with pinned versions, and **Part A: Reference** at the top of this file.

---

## Question 10: Reflection

**Where:** `output/desk_tickets.html` now has five tabs: Ticket 101, Ticket 102, Ticket 103, **Cash** (the Question 9
ledger) and a new **Reflection** tab. The short plan-vs-actual note that used to sit under the Cash ledger moved
into Reflection and was expanded. Every claim in the tab links to its evidence on the same page (20 links that
switch to the ticket or Cash tab).

**What the Reflection tab covers:**

1. **How the agents are evaluated.** A money gate first: human approval, cash never below $0, amounts from the
   database. All three tickets pass, ending at $160.00 = `cash_accounts.checking`. Then six criteria scored 1–5
   (routing, delegation economy, tool use, shop-rule compliance, output quality, cost):

   | Ticket | Average | One-line reason |
   |---|---|---|
   | 101 | **4.2 · Strong** | Right owner, one request, a draft that could be sent as written; one redundant Inventory → Accounting consult |
   | 102 | **4.5 · Best** | Planned 2 delegations, one rent request, no draft; parallel briefing beat the planned hand-off; rent check repeated 3× |
   | 103 | **2.8 · Correct on money, weak on communication** | Accounting refused the $264 PO (cash rule alone, vendor unblocked); Customer Service briefed too early, an extra consult, `quote_bulk_order_discount` ×8, and draft #2 promised an unfunded Sept 5 date |

2. **"One agent with the tools would have been simpler": mostly agree for this desk today, disagree long-term.**
   - **For one agent:** the overview tools already join the tables. The team made 37 MCP calls (`get_ticket` ×11,
     `get_cash_position` ×8) to create 4 records. Draft #2's error came from briefing Customer Service before
     Accounting's facts existed. The real money guardrails live in code (MCP and the pay tool), not in the team.
     151,195 tokens for three tickets.
   - **For the team:** least-privilege write tools, Accounting's independent refusal on 103, Facilities checking
     the landlord's claim on 102, a focused Customer Service prompt that kept draft #1 clean, and per-agent
     accountability (`requested_by`, "What each agent did").
   - **Recommendation:** a *sequential* team, where one desk agent decides and then hands Customer Service a
     finished fact sheet, with writes kept split by role.

3. **Three new problems the team can solve with today's tools:**
   - The sold-out Crest Mug: Elm City Gifts, unblocked, ETA 2026-09-03, a $84.00 PO that fits the $160.
   - October rent with $160 in checking: a 32-day early warning; Accounting won't queue an overdraw.
   - 30 Yale Caps from stock at 15% off: $381.00 profit, no PO needed.

4. **Three problems it can't solve yet, and the tools needed:**
   - Taking the club's deposit: `record_customer_payment` and a `receipts` table.
   - Receiving the Sept 5 reprint and fulfilling Tauhid's tee: `advance_shop_date`, `receive_purchase_order`,
     `record_sale`, and a `purchase_orders` table.
   - Closing the loop with customers: human-gated `send_approved_message`, `supersede_draft`, `create_ticket`,
     `ingest_reply`, and a `validate_draft` check that would have caught draft #2.

   **The pattern:** the team decides and prepares well, but every missing tool is on an edge where something enters
   or leaves the shop (money in, goods in, goods out, messages out), and each should stay human-gated like
   `approve_and_pay`.

---

## Question 11: Submit to GitHub

**Repository:** https://github.com/DrewAtYale/Homework5 (public), also in `output/github_url.txt`. Files sit at the
repo root, which plays the role of the `hw5/` folder in the required layout.

### Pre-submission review (graded against every prompt)

| Check | Finding | Fix |
|---|---|---|
| Required layout | Missing `README.md`, `.env.example`, `.gitignore`, `output/github_url.txt` | Added all four. Every other required path already existed |
| README content | The README must explain copying the original DB, starting the MCP server, backend and board, and resetting before a full run | Root `README.md` covers each, in that order, with Windows and macOS/Linux commands |
| Secrets | The real `.env` must not be pushed | `.gitignore` excludes `.env`. A byte scan of every file found the real Portkey key in **none** |
| Databases | Both DBs must be included | `data/campus_customs.db` and `data/campus_customs_new.db` committed. The working copy holds the post-run state the outputs describe ($160.00) |
| Q9 "until they are resolved" | Ticket 103 had ended `deferred` | With the user's approval, a human close was recorded (Drew Hoffman, note: quote pending deposit, PO unfunded, draft #2 to be rewritten). All three tickets `resolved`; cash unchanged at $160.00. `resolved_tickets.json`, `resolved_board.html`, the 103 screenshot, `desk_tickets.html` and the Q9 section above were updated |
| Code health | — | Python compiles; `npm run build` (tsc + vite) clean; no browser console errors |
| Local-only files | `SESSION_HANDOFF.md` (session hand-off note) and `.claude/` (local Claude Code settings) aren't part of the layout | Kept locally, excluded by `.gitignore` |

Not committed: `.env`, `.venv/`, `frontend/node_modules/`, `frontend/dist/`, `__pycache__/`.
