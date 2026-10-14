// Turns raw audit-trail steps into a calm, readable story of one ticket run.
import { TOOL_LABELS, WRITE_TOOLS } from './agents'
import type { Actor, AgentEvent, AgentName, Usage } from './types'

export type FeedItem =
  | { kind: 'pickup'; key: string; time: string; ticketId: number | null }
  | { kind: 'brief'; key: string; time: string; from: AgentName; to: Actor; brief: string; depth: number }
  | { kind: 'act'; key: string; time: string; agent: Actor; depth: number; reasoning: string | null; text: string | null;
      tools: { name: string; label: string; detail: string }[] }
  | { kind: 'outcome'; key: string; time: string; agent: Actor; depth: number; label: string; error: boolean }
  | { kind: 'report'; key: string; time: string; agent: Actor; depth: number; summary: string; decision: string | null }
  | { kind: 'done'; key: string; time: string; usage: Usage | null; durationMs: number | null; status: string }
  | { kind: 'error'; key: string; time: string; agent: Actor; message: string }
  | { kind: 'human'; key: string; time: string; message: string; error: string | null }

export const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })

function tryJson(s: string | null): Record<string, unknown> | null {
  if (!s) return null
  try {
    const v = JSON.parse(s)
    return v && typeof v === 'object' ? (v as Record<string, unknown>) : null
  } catch {
    return null
  }
}

/** The agent's own summary (newer events carry it directly; older ones only have truncated JSON). */
export function summaryOf(e: AgentEvent): string {
  if (e.summary) return e.summary
  const parsed = tryJson(e.output)
  if (parsed && typeof parsed.summary === 'string') return parsed.summary
  const m = e.output?.match(/"summary":\s*"((?:[^"\\]|\\.)*)"/)
  return m ? m[1].replace(/\\"/g, '"') : 'Report filed.'
}

export function decisionOf(e: AgentEvent): string | null {
  if (e.decision) return e.decision
  const m = e.output?.match(/"decision":\s*"([a-z_]+)"/)
  return m ? m[1] : null
}

function argDetail(tool: string, args: string): string {
  const a = tryJson(args) ?? {}
  if (tool === 'delegate') return ''
  const bits: string[] = []
  for (const k of ['ticket_id', 'sku', 'size', 'qty', 'invoice_id', 'lease_id', 'vendor_id', 'discount_pct']) {
    if (a[k] === undefined || a[k] === null) continue
    bits.push(k === 'discount_pct' ? `${a[k]}% off` : k === 'ticket_id' ? `#${a[k]}` : String(a[k]))
  }
  return bits.join(' · ')
}

/** What a write tool produced, e.g. "Request #2 · $2,400.00 · pending approval". */
function outcomeLabel(tool: string, result: string): string | null {
  if (!WRITE_TOOLS.has(tool)) return null
  const id = result.match(/"id":\s*(\d+)/)?.[1]
  if (tool === 'draft_customer_message') return id ? `Draft #${id} saved · not sent` : 'Draft saved · not sent'
  const amount = result.match(/"amount":\s*([\d.]+)/)?.[1]
  const existed = /"already_existed":\s*true/.test(result)
  return `Request #${id ?? '?'}${amount ? ` · ${money(Number(amount))}` : ''} · ${existed ? 'already pending' : 'pending approval'}`
}

/** Group a ticket's events into runs, newest last. */
export function runsOf(events: AgentEvent[]): string[] {
  const order: string[] = []
  for (const e of events) if (e.agent !== 'human' && !order.includes(e.run_id)) order.push(e.run_id)
  return order
}

export function buildFeed(events: AgentEvent[], runId: string | null): FeedItem[] {
  const items: FeedItem[] = []
  const pending = new Map<string, string>() // tool_call_id -> tool name
  // Human actions (approvals) belong to the run they follow, not to earlier runs.
  const runStart = events.find(e => e.run_id === runId)?.time ?? ''
  const nextRun = events.find(e => e.agent !== 'human' && e.time > runStart && e.run_id !== runId)?.time ?? '￿'
  for (const e of events) {
    const key = `${e.time}-${e.agent_run_id}-${e.kind}-${e.step}`
    if (e.agent === 'human') {
      if (!runId || e.time < runStart || e.time >= nextRun) continue
      items.push({ kind: 'human', key, time: e.time, message: (e.input ?? 'Human action').replace('close_ticket', 'Closed ticket'), error: e.error })
      continue
    }
    if (e.run_id !== runId) continue
    switch (e.kind) {
      case 'start':
        if (e.depth === 0) items.push({ kind: 'pickup', key, time: e.time, ticketId: e.ticket_id })
        else items.push({ kind: 'brief', key, time: e.time, from: e.parent_agent ?? 'boss', to: e.agent, brief: e.input ?? '', depth: e.depth })
        break
      case 'model_response': {
        const tools = e.tool_calls
          .filter(t => t.tool !== 'final_result' && t.tool !== 'delegate')
          .map(t => ({ name: t.tool, label: TOOL_LABELS[t.tool] ?? t.tool, detail: argDetail(t.tool, t.args) }))
        e.tool_calls.forEach(t => pending.set(t.tool_call_id, t.tool))
        if (tools.length || e.reasoning || e.text)
          items.push({ kind: 'act', key, time: e.time, agent: e.agent, depth: e.depth, reasoning: e.reasoning, text: e.text, tools })
        break
      }
      case 'tool_results':
        for (const r of e.tool_results) {
          const tool = r.tool || pending.get(r.tool_call_id) || ''
          if (tool === 'final_result' || tool === 'delegate') continue
          const label = r.is_error || r.result.startsWith('BLOCKED')
            ? `${TOOL_LABELS[tool] ?? tool} didn't go through: ${r.result.slice(0, 160)}`
            : outcomeLabel(tool, r.result)
          if (label) items.push({ kind: 'outcome', key: `${key}-${r.tool_call_id}`, time: e.time, agent: e.agent, depth: e.depth, label, error: r.is_error })
        }
        break
      case 'final_output':
        items.push({ kind: 'report', key, time: e.time, agent: e.agent, depth: e.depth, summary: summaryOf(e), decision: decisionOf(e) })
        break
      case 'error':
        items.push({ kind: 'error', key, time: e.time, agent: e.agent, message: e.error ?? 'Unknown error' })
        break
      case 'run_summary': {
        const parsed = tryJson(e.output)
        items.push({
          kind: 'done', key, time: e.time, usage: e.usage,
          durationMs: typeof parsed?.duration_ms === 'number' ? parsed.duration_ms : null,
          status: typeof parsed?.status === 'string' ? parsed.status : 'completed',
        })
        break
      }
    }
  }
  return items
}

export type AgentState = 'idle' | 'working' | 'done' | 'skipped'

export interface AgentCardState {
  state: AgentState
  lastAction: string | null
  runs: number
  summaries: string[]
}

/** Where each agent stands in one run: who's working, who's done, who wasn't needed. */
export function agentStates(events: AgentEvent[], runId: string | null, finished: boolean): Record<AgentName, AgentCardState> {
  const blank = (): AgentCardState => ({ state: finished ? 'skipped' : 'idle', lastAction: null, runs: 0, summaries: [] })
  const out: Record<AgentName, AgentCardState> = {
    boss: blank(), inventory: blank(), accounting: blank(), facilities: blank(), customer_service: blank(),
  }
  const open: Record<string, number> = {}
  for (const e of events) {
    if (e.run_id !== runId || e.agent === 'human') continue
    const s = out[e.agent]
    if (e.kind === 'start') { s.runs += 1; open[e.agent] = (open[e.agent] ?? 0) + 1 }
    if (e.kind === 'final_output' || e.kind === 'error') { open[e.agent] = (open[e.agent] ?? 1) - 1 }
    if (e.kind === 'final_output') s.summaries.push(summaryOf(e))
    if (e.kind === 'model_response') {
      const calls = e.tool_calls.filter(t => t.tool !== 'final_result')
      const delegations = calls.filter(t => t.tool === 'delegate')
      if (delegations.length) {
        const to = delegations.map(t => (tryJson(t.args)?.to as string | undefined) ?? '').filter(Boolean)
        s.lastAction = `Briefing ${to.map(n => n.replace('_', ' ')).join(' & ')}`
      } else if (calls.length) s.lastAction = TOOL_LABELS[calls[calls.length - 1].tool] ?? calls[calls.length - 1].tool
      else s.lastAction = 'Writing report'
    }
  }
  for (const name of Object.keys(out) as AgentName[]) {
    const s = out[name]
    if (s.runs === 0) continue
    s.state = (open[name] ?? 0) > 0 ? 'working' : 'done'
  }
  return out
}
