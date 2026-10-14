"""The Campus Customs agent team: Boss, Inventory, Accounting, Facilities, Customer Service.

How it fits together:
  * One MCP connection (mcp_server/server.py over stdio) is the ONLY source of shop facts and the
    only way to change anything. There is no second tools layer: each agent sees a filtered view
    of that one MCP toolset, limited to the tools in config.AGENT_TOOLS.
  * Every agent runs on gpt-5.6-luna through Portkey and returns a typed result (models.py).
  * Agents are connected through one backend tool, `delegate(to, task)`. The Boss delegates to any
    specialist; a specialist can consult any other specialist. Depth and count are capped.
  * Each agent's loop (model response -> tool calls -> tool results -> ... -> output) is stepped
    with Agent.iter, and every step is appended to output/audit_trail.json.
  * After the Boss answers, the backend checks every id it cites against the database (through
    MCP), then records the decision through MCP.

Usage:
    async with Team() as team:
        result = await team.run_ticket(101)
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import RetryPromptPart, TextPart, ThinkingPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage, UsageLimits

import audit
import config
from models import (
    AgentName,
    AuditStep,
    AuditToolCall,
    AuditToolResult,
    BossDecision,
    SpecialistName,
    SpecialistReport,
    TicketRunResult,
    UsageSummary,
)

AGENTS: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")
SPECIALISTS: tuple[SpecialistName, ...] = ("inventory", "accounting", "facilities", "customer_service")
ROLE_LINE = {
    "inventory": "stock by SKU and size, shortages, which vendor can restock and when",
    "accounting": "cash, invoices, margins and discounts; prepares payments and POs for human approval",
    "facilities": "the Chapel Street shop space: lease, rent, landlord",
    "customer_service": "drafts (never sends) messages to customers",
}


# ---------- run state ----------

@dataclass
class RunState:
    """Shared by every agent working one ticket."""
    run_id: str
    ticket_id: int | None
    delegations: int = 0


@dataclass
class TeamDeps:
    """Per agent invocation. `state` is shared; the rest describes this agent's place in the chain."""
    agent: AgentName
    depth: int
    parent: AgentName | None
    agent_run_id: str
    state: RunState
    usage: RunUsage = field(default_factory=RunUsage)


class AgentStepLimitExceeded(RuntimeError):
    pass


def _usage(u: RunUsage) -> UsageSummary:
    return UsageSummary(
        requests=u.requests, tool_calls=u.tool_calls, input_tokens=u.input_tokens,
        output_tokens=u.output_tokens, total_tokens=u.input_tokens + u.output_tokens,
    )


def _load_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


# ---------- MCP access control (enforced in code) ----------

async def _guard_tool_call(ctx: RunContext[TeamDeps], call_tool, name: str, args: dict[str, Any]):
    """Runs before every MCP call an agent makes.

    Blocks tools outside the agent's allowlist (a second check after filtering) and stamps write
    tools with the real agent name, so an agent can't claim another's identity.
    """
    agent = ctx.deps.agent
    if name not in config.AGENT_TOOLS[agent]:
        return f"BLOCKED: {agent} is not allowed to call {name}."
    if name in config.IDENTITY_ARG:
        args = {**args, config.IDENTITY_ARG[name]: agent}
    return await call_tool(name, args)


def _hide_identity_args(ctx: RunContext[TeamDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
    """Remove requested_by/drafted_by from the schemas agents see. The backend fills them in."""
    out = []
    for td in tool_defs:
        arg = config.IDENTITY_ARG.get(td.name)
        if arg:
            schema = dict(td.parameters_json_schema)
            schema["properties"] = {k: v for k, v in schema.get("properties", {}).items() if k != arg}
            schema["required"] = [r for r in schema.get("required", []) if r != arg]
            td = replace(td, parameters_json_schema=schema)
        out.append(td)
    return out


# ---------- the team ----------

class Team:
    def __init__(self) -> None:
        api_key = os.environ.get("PORTKEY_API_KEY")
        if not api_key:
            raise RuntimeError("PORTKEY_API_KEY is not set. Add it to the AI Foundations .env file.")

        self.model = OpenAIResponsesModel(
            config.MODEL_NAME,
            provider=OpenAIProvider(
                openai_client=AsyncOpenAI(
                    api_key=api_key, base_url=config.BASE_URL, timeout=config.REQUEST_TIMEOUT_S, max_retries=2,
                )
            ),
        )
        self.settings = OpenAIResponsesModelSettings(
            openai_reasoning_effort=config.REASONING_EFFORT,
            openai_reasoning_summary=config.REASONING_SUMMARY,
        )
        self.limits = UsageLimits(
            request_limit=config.TEAM_REQUEST_LIMIT,
            tool_calls_limit=config.TEAM_TOOL_CALL_LIMIT,
            total_tokens_limit=config.TEAM_TOTAL_TOKENS_LIMIT,
        )

        # One MCP server process for the whole team.
        transport = StdioTransport(
            command=config.MCP_COMMAND, args=[str(config.MCP_SERVER_SCRIPT)],
            env=config.MCP_ENV, cwd=str(config.ROOT),
        )
        self.mcp = MCPToolset(
            Client(transport), id="campus-customs", max_retries=2, process_tool_call=_guard_tool_call,
        )
        self.agents: dict[AgentName, Agent] = {name: self._build_agent(name) for name in AGENTS}

    async def __aenter__(self) -> "Team":
        await self.mcp.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.mcp.__aexit__(*exc)

    # ----- building agents -----

    def _build_agent(self, name: AgentName) -> Agent:
        allowed = config.AGENT_TOOLS[name]
        toolset = self.mcp.filtered(lambda ctx, td, allowed=allowed: td.name in allowed).prepared(_hide_identity_args)
        agent = Agent(
            self.model,
            name=name,
            deps_type=TeamDeps,
            output_type=BossDecision if name == "boss" else SpecialistReport,
            instructions=_load_prompt(name),
            toolsets=[toolset],
            tools=[Tool(self._delegate, name="delegate", prepare=self._prepare_delegate)],
            model_settings=self.settings,
            retries=2,
        )

        @agent.instructions
        def run_context(ctx: RunContext[TeamDeps]) -> str:
            d = ctx.deps
            asked_by = f"You were asked by: {d.parent}." if d.parent else "You were started by the ticket queue."
            teammates = [a for a in SPECIALISTS if a != d.agent]
            can_delegate = d.depth < config.MAX_DEPTH
            return (
                f"Run {d.state.run_id}. Ticket: {d.state.ticket_id}. {asked_by} "
                f"Delegation depth {d.depth} of max {config.MAX_DEPTH}. "
                + (
                    "Teammates you can delegate to: "
                    + "; ".join(f"{t} ({ROLE_LINE[t]})" for t in teammates)
                    + f". Delegations left for this ticket: {config.MAX_DELEGATIONS_PER_TICKET - d.state.delegations}."
                    if can_delegate else "You are at max depth: do the work yourself with your own tools."
                )
            )

        return agent

    async def _prepare_delegate(self, ctx: RunContext[TeamDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
        """Hide `delegate` once the chain is at max depth or the ticket's delegation budget is spent."""
        if ctx.deps.depth >= config.MAX_DEPTH or ctx.deps.state.delegations >= config.MAX_DELEGATIONS_PER_TICKET:
            return None
        return tool_def

    async def _delegate(self, ctx: RunContext[TeamDeps], to: SpecialistName, task: str) -> dict | str:
        """Hand a focused task to the teammate who owns it and get their report back.

        Args:
            to: inventory, accounting, facilities or customer_service. Not yourself, never the boss.
            task: A self-contained brief: the ticket id, what you need, the facts you already have
                (with source tools) so they don't repeat lookups, and what to return.
        """
        d = ctx.deps
        if to == d.agent:
            return "Refused: you can't delegate to yourself. Use your own tools."
        if to not in SPECIALISTS:
            return f"Refused: unknown teammate {to!r}."
        if d.depth >= config.MAX_DEPTH:
            return "Refused: max delegation depth reached. Do the work with your own tools."
        if d.state.delegations >= config.MAX_DELEGATIONS_PER_TICKET:
            return "Refused: this ticket's delegation budget is spent. Decide with what you have."
        d.state.delegations += 1
        child = TeamDeps(
            agent=to, depth=d.depth + 1, parent=d.agent, agent_run_id=uuid.uuid4().hex[:12], state=d.state,
            usage=ctx.usage,
        )
        try:
            report: SpecialistReport = await self._run_agent(child, task)
        except Exception as err:  # noqa: BLE001 - the delegator gets the error and decides what to do
            return f"{to} could not finish: {type(err).__name__}: {err}"
        return report.model_dump()

    # ----- the agent loop -----

    def _step(self, d: TeamDeps, step: int, kind: str, **fields) -> None:
        audit.append(AuditStep(
            time=audit.now(), run_id=d.state.run_id, ticket_id=d.state.ticket_id, agent=d.agent,
            agent_run_id=d.agent_run_id, parent_agent=d.parent, depth=d.depth, step=step, kind=kind,
            model=config.MODEL_NAME, usage=_usage(d.usage), **fields,
        ))

    async def _run_agent(self, d: TeamDeps, task: str):
        """Run one agent to completion, auditing every step of its loop."""
        agent = self.agents[d.agent]
        step = 0
        self._step(d, step, "start", input=audit.truncate(task, 2000))
        try:
            async with agent.iter(
                task, deps=d, usage=d.usage, usage_limits=self.limits, model_settings=self.settings,
            ) as run:
                async for node in run:
                    if Agent.is_call_tools_node(node):
                        # The model just answered: reasoning, text and the tool calls it wants.
                        step += 1
                        parts = node.model_response.parts
                        self._step(
                            d, step, "model_response",
                            reasoning=audit.truncate(
                                " ".join(p.content for p in parts if isinstance(p, ThinkingPart) and p.content), 1500
                            ) or None,
                            text=audit.truncate(" ".join(p.content for p in parts if isinstance(p, TextPart))) or None,
                            tool_calls=[
                                AuditToolCall(tool=p.tool_name, tool_call_id=p.tool_call_id, args=audit.truncate(p.args_as_dict()))
                                for p in parts if isinstance(p, ToolCallPart)
                            ],
                        )
                        if step > config.PER_AGENT_STEP_LIMIT:
                            raise AgentStepLimitExceeded(f"{d.agent} exceeded {config.PER_AGENT_STEP_LIMIT} steps.")
                    elif Agent.is_model_request_node(node):
                        # Tool results (or retry prompts) about to go back to the model.
                        results = [
                            AuditToolResult(
                                tool=p.tool_name or "", tool_call_id=p.tool_call_id or "",
                                result=audit.truncate(p.content if isinstance(p, ToolReturnPart) else p.model_response()),
                                is_error=isinstance(p, RetryPromptPart),
                            )
                            for p in node.request.parts if isinstance(p, (ToolReturnPart, RetryPromptPart))
                        ]
                        if results:
                            self._step(d, step, "tool_results", tool_results=results)
            output = run.result.output
        except Exception as err:
            self._step(d, step, "error", error=audit.truncate(f"{type(err).__name__}: {err}", 1000))
            raise
        self._step(
            d, step, "final_output", output=audit.truncate(output.model_dump(), 12000), summary=output.summary,
            decision=getattr(output, "decision", None),
        )
        return output

    # ----- public entry points -----

    async def call_mcp(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Backend (not agent) call to the MCP server, e.g. validation, recording, human actions."""
        return await self.mcp.direct_call_tool(name, args or {})

    async def reset_database(self) -> Any:
        """Human/operator action: restore the working copy from the pristine original (via MCP)."""
        return await self.call_mcp("reset_working_database", {"confirm": True})

    async def run_ticket(self, ticket_id: int) -> TicketRunResult:
        state = RunState(run_id=uuid.uuid4().hex[:12], ticket_id=ticket_id)
        boss = TeamDeps(agent="boss", depth=0, parent=None, agent_run_id=uuid.uuid4().hex[:12], state=state)
        started = time.perf_counter()
        task = (
            f"Work ticket {ticket_id}. Read it, delegate to the right teammates, and make the final call. "
            "Return your BossDecision."
        )
        try:
            decision: BossDecision = await self._run_agent(boss, task)
            if decision.ticket_id != ticket_id:
                decision.ticket_id = ticket_id
            dropped = await self._validate_ids(decision)
            recorded = await self.call_mcp("record_ticket_decision", {
                "ticket_id": ticket_id, "decision": decision.decision,
                "summary": decision.summary, "decided_by": "boss",
            })
            result = TicketRunResult(
                run_id=state.run_id, ticket_id=ticket_id, status="completed", decision=decision,
                recorded_decision_id=(recorded or {}).get("id"), dropped_ids=dropped,
                delegations=state.delegations, usage=_usage(boss.usage),
                duration_ms=int((time.perf_counter() - started) * 1000), model=config.MODEL_NAME,
            )
        except Exception as err:  # noqa: BLE001 - failed runs are audited and returned, not hidden
            result = TicketRunResult(
                run_id=state.run_id, ticket_id=ticket_id, status="error", decision=None, recorded_decision_id=None,
                delegations=state.delegations, usage=_usage(boss.usage),
                duration_ms=int((time.perf_counter() - started) * 1000), model=config.MODEL_NAME,
                error=f"{type(err).__name__}: {err}",
            )
        self._step(boss, 0, "run_summary", output=audit.truncate(result.model_dump(exclude={"decision"}), 2000))
        return result

    async def _validate_ids(self, decision: BossDecision) -> list[str]:
        """Drop payment request / draft ids that don't exist; never leave a ticket 'resolved' while money waits."""
        requests = (await self.call_mcp("list_payment_requests", {}))["requests"]
        drafts = (await self.call_mcp("list_message_drafts", {}))["drafts"]
        by_id = {r["id"]: r for r in requests}
        draft_ids = {dr["id"] for dr in drafts}
        dropped = [f"payment_request:{i}" for i in decision.payment_request_ids if i not in by_id]
        dropped += [f"draft:{i}" for i in decision.draft_ids if i not in draft_ids]
        decision.payment_request_ids = [i for i in decision.payment_request_ids if i in by_id]
        decision.draft_ids = [i for i in decision.draft_ids if i in draft_ids]
        pending = [i for i in decision.payment_request_ids if by_id[i]["status"] == "pending_approval"]
        if decision.decision == "resolved" and (pending or decision.draft_ids):
            decision.decision = "awaiting_human_approval"
        return dropped
