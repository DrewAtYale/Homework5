r"""Command line for the agent team (the FastAPI layer will call the same Team class).

    .\.venv\Scripts\python.exe backend\run_team.py --ticket 101
    .\.venv\Scripts\python.exe backend\run_team.py --all --reset

--reset restores data/campus_customs_new.db from the pristine original (through the MCP server's
human-only reset tool) before any work. Use it before every full ticket-resolution run.
Results print as JSON; every agent step is appended to output/audit_trail.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from team import Team  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Campus Customs agent team on tickets.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--ticket", type=int, action="append", help="Ticket id to work (repeatable).")
    which.add_argument("--all", action="store_true", help="Work every open ticket, in id order.")
    parser.add_argument("--reset", action="store_true", help="Reset the working database first.")
    args = parser.parse_args()

    async with Team() as team:
        if args.reset:
            print(json.dumps(await team.reset_database(), indent=2))
        ids = args.ticket or [t["id"] for t in (await team.call_mcp("list_open_tickets"))["tickets"]]
        for ticket_id in ids:
            result = await team.run_ticket(ticket_id)
            print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
