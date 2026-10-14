# Campus Customs Ops Desk (frontend)

React + Vite + TypeScript dashboard for the Homework 5 agent team. It calls the FastAPI backend at
`http://localhost:8000` (override with `VITE_API_URL`).

```powershell
# 1. backend (from Homework 5\backend, with the venv active)
uvicorn main:app --reload --port 8000

# 2. board (from Homework 5\frontend)
npm install
npm run dev     # opens http://localhost:5173
```

The dev server is pinned to port 5173 because that's the origin the backend's CORS allows.

| File | What it does |
|---|---|
| `src/App.tsx` | State, polling (events every 1.5s during a run), approve, reject and reset actions, toasts |
| `src/api.ts` | Typed client for every backend route |
| `src/types.ts` | TypeScript mirrors of the backend's Pydantic models |
| `src/agents.ts` | Each agent's colour, monogram and motto; plain-English tool names |
| `src/feed.ts` | Turns audit-trail steps into the activity feed and the roster states |
| `src/components/` | `Header` (cash), `TicketList`, `RunPanel` (roster, outcome, drafts, feed), `Approvals` |

See `../output/design.md` for the design choices.
