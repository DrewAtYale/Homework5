# Design — Campus Customs Ops Desk

The dashboard (`frontend/`, React + Vite + TypeScript) is where a person watches the five-agent team work a
ticket and then signs off on money. The design goal: **a calm, credible tool a shop manager would actually keep
open all day.** It should feel like it belongs to a Yale apparel shop and to *this* team, without being a theme
park. Every choice below asks two questions: does it help someone see what happened at a glance, and does it make
the human's job (approving money) safe and obvious?

---

## 1. Overall look: "warm paper, navy ink"

| Choice | Why |
|---|---|
| **Warm off-white page** (`#f5f3ee`) with white cards | Softer than pure white for a screen left open all day. Reads like a desk blotter, not a server console. |
| **Yale navy masthead** (`#0f2a4a`) with a thin **gold rule** | Ties the tool to a Yale shop on Chapel Street. Gold is used sparingly (masthead rule, cash bar, toast edge) so it signals "money and identity" rather than decoration. |
| **Serif for headings, names and amounts** (Iowan Old Style / Palatino / Georgia); **sans for everything operational** | The serif gives an editorial, slightly literary feel that suits the personas. The sans keeps data, buttons and tool chips crisp. Both are system fonts: nothing downloads, and it works offline. |
| A **"CC" crest** in the corner and as the favicon | A small brand anchor. One of the only purely decorative elements. |
| Rounded 14px cards, soft shadows, no gradients, no dark panels except the masthead | Keeps the visual noise low so colour can carry meaning (agent, status, money). |

Status colours are used **only** for status: amber = open or waiting, blue = agents working, green = resolved or
paid, red = refused, error, or "not sent". Nothing else on the page uses them, so a glance at the colour tells
you where things stand.

## 2. Layout: three columns, one question each

```
┌──────────────────────────── Masthead: brand · shop date · CHECKING BALANCE · Fresh start ───────────────────────────┐
│ DESK (tickets)        │ THE SELECTED TICKET                                         │ APPROVALS                     │
│ #101 Bulldog tee  ✓   │ Ticket hero: subject · requester · "Send to agent team"     │ Approving as [ your name ]    │
│ #102 Rent due  Open   │ Team roster: 5 agent cards (working / done / not needed)    │ $840.00 Vendor invoice        │
│ #103 Hoodies   Open   │ Outcome: Boss decision + next steps → "What each agent did" │ [Approve & pay] [Reject]      │
│                       │ Customer drafts (letter, "DRAFT · NOT SENT" stamp)          │ Recently decided              │
│                       │ Activity feed (live while running, folded away after)       │                               │
└───────────────────────┴─────────────────────────────────────────────────────────────┴───────────────────────────────┘
```

- **Left, "What's on the desk?"** The three tickets as cards: icon by type (shirt, building, price tag), id,
  subject, requester, and an **Open / Resolved** pill. A ticket with money waiting shows an amber line: "1 payment
  needs your approval". While the agents work on it, the pill turns blue: "Agents working".
- **Centre, "What happened on this ticket?"** Read top to bottom, it tells the story in the order a manager wants
  it: *what's the ask → who worked it → what did they decide → what did they write → (if you care) every step*.
- **Right, "What do I need to do?"** The approval queue, sticky so it stays in view while you read. It's the only
  place with consequential buttons.
- **The cash balance sits in the masthead**, visible from every view, because it's the number every decision
  is weighed against.

Responsive: the approvals panel drops below at about 1250px, and everything stacks to one column under 860px.
Under 560px, feed indentation and the draft stamp reflow so nothing scrolls sideways.

## 3. How the agents read differently

The personas live in the prompts (`backend/prompts/*.md`). The board borrows **three quiet signals** from each,
never costumes:

| Agent | Persona (from its prompt) | Accent | Monogram | Motto on its card | Busy state |
|---|---|---|---|---|---|
| Boss | Miranda Priestly: exacting, decisive | Near-black ink `#1f2430` | **B** | "Facts, not feelings." | weighing the reports |
| Inventory | Dwight Schrute: literal, exact counts | Mustard `#a65f0a` | **I** | "If a tool didn't count it, it isn't a count." | counting stock |
| Accounting | Ben Wyatt: calm budget hawk | Ledger green `#1e7a4c` | **A** | "Protect the essentials first." | balancing the books |
| Facilities | Mr. Carson: formal keeper of the house | Claret `#7a2c4f` | **F** | "Obligations are met on time." | reviewing the lease |
| Customer Service | Ted Lasso: warm, honest | Harbour teal `#13718a` | **C** | "Honest news, warmly told." | drafting a reply |

- **Colour = identity, everywhere.** Each agent's accent appears on its roster card's top edge, its chip in the
  feed, the left border of its feed rows, its "What each agent did" card, and its name on a payment request.
  After one run you can spot Accounting's work anywhere on the page.
- **The Boss is ink-black on purpose.** It's the editor, not a specialist. Its decision card has a heavy black
  left rule and the largest type on the page, like an editor's note.
- **Mottos are small italic serif lines** under each role, with the persona's name in a hover tooltip ("after
  Ben Wyatt"). The personality is there if you look and invisible if you don't. That's the line between
  stylistic and campy.
- **Reasoning summaries** appear as italic serif "thoughts". **Tool calls** are plain grey chips in English
  ("Checked stock · CC-HOOD-NAVY · M", "Prepared rent payment · 1"), not raw function names. **Records an agent
  created** (payment requests, drafts) get a green "outcome" row, because those are what a human will act on.
- **Delegation is drawn, not described.** A brief shows as `Boss → Inventory` chips with the brief folded under it
  (click to expand). A specialist consulting another specialist is **indented one level** and labelled "teammate
  consult", so the chain (e.g. Facilities → Accounting on rent) is visible as a shape.

## 4. Watching a run

1. **Send to agent team** turns the ticket's pill blue and starts the roster.
2. **Roster cards come alive.** The working agent's card fills with its soft accent colour, gets a solid accent
   ring and a pulsing dot, and shows its latest action ("Checked cash", "Briefing inventory & accounting"). Done
   agents show ✓ (and "consulted 2×" if they ran twice). Agents the Boss never called fade to 45% and say **Not
   needed**. That fade is deliberate: the Question 6 plan says not every specialist should work every ticket, and
   the board makes that visible.
3. **Live activity** polls `/api/events?since=…` every 1.5s and slides new steps in at the bottom, with a "The
   team is working…" line that auto-scrolls. The approval queue and drafts also refresh during the run, so
   Accounting's request appears on the right as soon as it's prepared.

## 5. How resolved tickets show up

When the run returns:

- The ticket's pill flips to green **✓ Resolved**, and a toast confirms it ("Ticket #101 resolved · Awaiting your
  approval · 3 delegations · 184s").
- The centre column switches from *live* to *summary*:
  - **The Boss's decision card**: a decision pill ("Awaiting your approval", "Resolved", "Deferred",
    "Needs a human"), the summary in large serif, a **"Your next steps"** numbered list, and "Why this call" folded
    away.
  - **"What each agent did"**: one card per specialist that worked, with its own report summary. Then one quiet
    line for the agents that weren't needed.
  - **Customer drafts** as letters: paper-white with a teal top edge (Customer Service's colour) and a red
    rubber-stamp **"DRAFT · NOT SENT"**. The stamp is the one playful flourish, and it does a safety job: no one
    can mistake a draft for a sent email.
  - **The full activity log** is folded into "Full activity · N steps", so it's there for audit without
    overwhelming the summary.
- "Resolved" means *the team made its final call*. If money is still waiting, the ticket also keeps the amber
  "payment needs your approval" line, so resolved never hides unfinished human work.

## 6. How cash and approvals show up

- **The balance is the biggest number on the page** (masthead, serif, tabular figures).
- **A thin gold bar** under it shows how much of the balance is already promised to pending requests, with
  "$X awaiting approval · $Y if all approved". If that second figure would be negative, it turns red. That's the
  shop's $160 squeeze, made visible before anyone clicks.
- **Approving** needs a name in "Approving as" (remembered in the browser). That name is sent as `approved_by`
  and written to `payments.approved_by` and the audit trail. Buttons stay disabled until there's a name, and while
  a run is in progress.
- **Each request card** shows kind, amount (large), what it's for, ticket, request #, the agent's own reason, and
  "Prepared by Accounting" in Accounting's green. If the amount is more than current checking, a red note warns
  that the pay tool will refuse it **before** you click.
- **On approve, the cash visibly drops.** The balance counts down from the old figure to the new one over about
  a second, a red **"−$840.00"** chip pops in beside it, and a toast says "Paid $840.00 · Checking $3,400.00 →
  $2,560.00". The request moves to **Recently decided** with "Paid · by <name>". If the pay tool refuses (409),
  the toast is red and quotes the refusal ("The balance can never go negative"), and nothing changes.
- **Reject** is a two-step button (Reject → Confirm reject) so a mis-click can't throw away an agent's work.
- **Fresh start** (masthead) asks for confirmation, explains what it resets, and notes that the audit trail is
  kept.

## 7. Small things that make it pleasant

- **Plain English everywhere.** Ticket types ("Rent notice"), decisions ("Awaiting your approval"), tool chips
  and the dateline ("Shop date Monday, August 31, 2026 · 1 Chapel Street, New Haven") use human words. The shop
  date comes from `desk.date_today`, not the computer clock, matching the agents.
- **Honest connection state.** A green or red dot in the masthead shows whether the backend is up. If it's down,
  a banner shows the exact `uvicorn` command to start it.
- **A fine-print reminder under the desk:** "Nothing on this desk is ever sent. Messages stay drafts, and money
  moves only when a person approves it."
- **Accessible by default.** Real buttons and focus rings, `aria-live` on the balance, a status region for
  toasts, readable contrast, and `prefers-reduced-motion` turns off every animation.
- **Restraint list (things deliberately *not* done):** no character photos, catchphrase banners, or
  per-agent fonts. No dark-mode neon "AI" look. No raw JSON on the main view. No auto-approve. One playful element
  (the draft stamp), and it does a safety job.
