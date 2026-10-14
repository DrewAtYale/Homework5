# Homework 5: Campus Customs Multi-Agent Ops Desk

A five-agent operations team for **Campus Customs**, a fictional Yale apparel shop on Chapel Street. The team
works the shop's open tickets, and a human watches and approves payments on a React dashboard.

```
React board (frontend/, :5173) ──HTTP──▶ FastAPI backend (backend/main.py, :8000)
                                             │ agent team: Boss, Inventory, Accounting, Facilities, Customer Service
                                             │ (every agent on gpt-5.6-luna via Portkey)
                                             ▼ MCP (stdio)
                                   MCP server (mcp_server/server.py, FastMCP, 20 tools)
                                             ▼
                                   data/campus_customs_new.db (working copy of data/campus_customs.db)
```

**Shop rules:** nothing is ever sent (customer messages stay drafts); `desk.date_today` (2026-08-31) is "today";
lead times come only from `vendors.lead_days`; a vendor won't ship with an unpaid invoice; **every payment needs
human approval**; the pay tool refuses if cash would go negative; reset the database before a full run.

---

## 1. Setup (once)

Requirements: Python 3.14, Node.js 20+ (tested with 24), a Portkey API key.

```powershell
# Windows PowerShell, from this folder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env          # then put your PORTKEY_API_KEY in .env

cd frontend
npm install
cd ..
```

macOS / Linux: `python3 -m venv .venv`, `source .venv/bin/activate`, `cp .env.example .env`. Everything else is the
same.

## 2. Copy the original database to the working copy (clean run)

`data/campus_customs.db` is the **pristine original** and is never written. Everything reads and writes
`data/campus_customs_new.db`. To get a clean working copy:

```powershell
copy data\campus_customs.db data\campus_customs_new.db      # macOS/Linux: cp data/campus_customs.db data/campus_customs_new.db
```

The committed working copy is the state **after** the Question 9 run (checking $160.00, all three tickets
resolved), so the outputs can be checked against it. Copy the original over it before running the tickets
yourself.

## 3. Start the MCP server

The backend starts the MCP server automatically as a child process (stdio), so for the app you don't need a
separate terminal. To run it on its own, or to inspect its tools:

```powershell
.\.venv\Scripts\python.exe mcp_server\server.py
```

For Claude Code, `.mcp.json` registers the same server as `campus-customs`. Start Claude Code in this folder and
approve the server. `.mcp.json` points at `.venv/Scripts/python.exe` (Windows); on macOS/Linux change it to
`.venv/bin/python`. Tool list: `mcp_server/README.md`.

## 4. Start the FastAPI backend

With the venv active (`.\.venv\Scripts\Activate.ps1`):

```powershell
cd backend
uvicorn main:app --reload --port 8000
```

API at **http://localhost:8000** (interactive docs at `/docs`). Routes: tickets, run a ticket, events, approve or
reject a payment, close a ticket, drafts, cash, reset. They're listed in `output/harness.md` (A5).

## 5. Start the React board

```powershell
cd frontend
npm run dev
```

This opens **http://localhost:5173**. Pick a ticket, click **Send to agent team**, and watch the agents work. Type
your name under **Approvals** to approve payments; the checking balance drops on approval.

## 6. Reset the database before a full three-ticket run

Before running all three tickets, restore the original values in either of these ways:
- click **Fresh start** in the board's header (calls `POST /api/reset`, which copies the original over the working
  copy through the MCP server's human-only reset tool), **or**
- stop the backend and copy the file as in step 2.

Then send **101 → 102 → 103** to the team one at a time, approve the payment requests you agree with, and close
each ticket. Command-line alternative (no board): `.\.venv\Scripts\python.exe backend\run_team.py --all --reset`.

---

## What's where

| Path | Contents |
|---|---|
| `AI_prompts.md` | Every prompt, word for word, by question |
| `mcp_server/` | `server.py` (20 MCP tools), `models.py` (return types), `README.md` |
| `backend/` | `main.py` (FastAPI routes), `team.py` (agents, delegation, audited loop), `models.py` (data types), `config.py` (model lock, spend caps, tool allowlists), `audit.py`, `run_team.py`, `prompts/` (one per agent) |
| `frontend/` | React + Vite + TypeScript dashboard |
| `data/` | `campus_customs.db` (original) and `campus_customs_new.db` (working copy) |
| `output/harness.md` | Full documentation: Part A reference (tables, tools, agents, routes, dashboard, safety) and Part B build log |
| `output/mcp_smoke.json` | Each MCP tool called from Claude Code, with values matched to the database |
| `output/desk_tickets.html` | Expected plan vs. actual run per ticket, the cash ledger, and the reflection |
| `output/design.md` | Dashboard design choices |
| `output/resolved_tickets.json`, `output/resolved_board.html` | Question 9 outcomes and board screenshots |
| `output/audit_trail.json` | Append-only log of every agent step and human action |
| `output/github_url.txt` | This repository's URL |

**Result of the full run:** checking **$3,400.00 → $160.00** ($840.00 invoice 501 for ticket 101 and $2,400.00
rent for ticket 102, both human-approved; ticket 103's $264.00 restock was refused for lack of cash). This matches
`cash_accounts` in `data/campus_customs_new.db`.

The real `.env` is not in this repository. `.env.example` shows the variables.
