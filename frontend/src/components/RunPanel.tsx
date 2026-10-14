import { useEffect, useRef, type CSSProperties } from 'react'
import { AGENTS, DECISIONS, TEAM, TICKET_TYPES } from '../agents'
import { agentStates, buildFeed, type AgentCardState, type FeedItem } from '../feed'
import type { Actor, AgentEvent, AgentName, BossDecision, MessageDraft, TicketRow } from '../types'
import { ArrowIcon, MailIcon, PlayIcon, TicketIcon } from './Icons'

interface Props {
  ticket: TicketRow
  events: AgentEvent[]
  runId: string | null
  running: boolean
  busyElsewhere: boolean
  drafts: MessageDraft[]
  onRun: () => void
  onClose: () => void
  canClose: boolean
}

const time = (iso: string) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })

function Avatar({ agent, size = 'md' }: { agent: Actor; size?: 'sm' | 'md' }) {
  const a = AGENTS[agent]
  return <span className={`avatar ${size}`} style={{ background: a.color }} aria-hidden="true">{a.monogram}</span>
}

function AgentChip({ agent }: { agent: Actor }) {
  const a = AGENTS[agent]
  return <span className="agent-chip" style={{ color: a.color, background: a.soft }}><Avatar agent={agent} size="sm" />{a.label}</span>
}

// ---------- roster ----------

function Roster({ states, running }: { states: Record<AgentName, AgentCardState>; running: boolean }) {
  return (
    <div className="roster">
      {TEAM.map(name => {
        const a = AGENTS[name]
        const s = states[name as AgentName]
        const status =
          s.state === 'working' ? (s.lastAction ?? a.working)
          : s.state === 'done' ? (s.runs > 1 ? `Done · consulted ${s.runs}×` : 'Done')
          : s.state === 'skipped' ? 'Not needed'
          : running ? 'Standing by' : 'Ready'
        return (
          <div key={name} className={`member ${s.state}`} style={{ '--agent': a.color, '--agent-soft': a.soft } as CSSProperties}>
            <div className="member-head">
              <Avatar agent={name} />
              <div>
                <div className="member-name">{a.label}</div>
                <div className="member-role">{a.role}</div>
              </div>
            </div>
            <div className="member-status">
              {s.state === 'working' && <span className="pulse" />}
              {status}
            </div>
            <div className="member-motto" title={`Persona: after ${a.persona}`}>“{a.motto}”</div>
          </div>
        )
      })}
    </div>
  )
}

// ---------- outcome ----------

function parseBoss(events: AgentEvent[], runId: string | null): BossDecision | null {
  const final = [...events].reverse().find(e => e.run_id === runId && e.agent === 'boss' && e.kind === 'final_output')
  if (!final?.output) return null
  try { return JSON.parse(final.output) as BossDecision } catch { return null }
}

function Outcome({ events, runId, states }: { events: AgentEvent[]; runId: string | null; states: Record<AgentName, AgentCardState> }) {
  const boss = parseBoss(events, runId)
  const decision = boss ? DECISIONS[boss.decision] : null
  const specialists = TEAM.filter(n => n !== 'boss') as AgentName[]
  const involved = specialists.filter(n => states[n].runs > 0)
  const skipped = specialists.filter(n => states[n].runs === 0)
  return (
    <section className="outcome">
      <div className="decision-card">
        <div className="decision-top">
          <AgentChip agent="boss" />
          {decision && <span className={`pill tone-${decision.tone}`}>Boss's call: {decision.label}</span>}
        </div>
        <p className="decision-summary">{boss?.summary ?? states.boss.summaries.at(-1) ?? 'The Boss filed a decision.'}</p>
        {boss && boss.human_next_steps.length > 0 && (
          <div className="next-steps">
            <h4>Your next steps</h4>
            <ol>{boss.human_next_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
          </div>
        )}
        {boss?.rationale && (
          <details className="rationale"><summary>Why this call</summary><p>{boss.rationale}</p></details>
        )}
      </div>

      <h3 className="subhead">What each agent did</h3>
      <div className="did-grid">
        {involved.map(name => {
          const s = states[name]
          return (
            <div key={name} className="did" style={{ '--agent': AGENTS[name].color } as CSSProperties}>
              <AgentChip agent={name} />
              {s.summaries.map((text, i) => (
                <p key={i}>{s.summaries.length > 1 && <span className="muted">Run {i + 1}: </span>}{text}</p>
              ))}
            </div>
          )
        })}
      </div>
      {skipped.length > 0 && (
        <p className="skipped">Not needed on this ticket: {skipped.map(n => AGENTS[n].label).join(', ')}.</p>
      )}
    </section>
  )
}

// ---------- drafts ----------

function Drafts({ drafts }: { drafts: MessageDraft[] }) {
  if (!drafts.length) return null
  return (
    <section>
      <h3 className="subhead">Customer drafts</h3>
      {drafts.map(d => (
        <article key={d.id} className="letter">
          <div className="letter-stamp">Draft · not sent</div>
          <div className="letter-head">
            <MailIcon />
            <div>
              <div className="letter-to">To {d.to_name}</div>
              <div className="letter-subject">{d.subject}</div>
            </div>
          </div>
          <p className="letter-body">{d.body}</p>
          <div className="letter-foot">Draft #{d.id} · written by {AGENTS[d.drafted_by as Actor]?.label ?? d.drafted_by}</div>
        </article>
      ))}
    </section>
  )
}

// ---------- feed ----------

function FeedRow({ item }: { item: FeedItem }) {
  switch (item.kind) {
    case 'pickup':
      return <li className="feed-row system"><span className="when">{time(item.time)}</span><span>The Boss picked up ticket #{item.ticketId}.</span></li>
    case 'brief':
      return (
        <li className="feed-row brief" style={{ '--agent': AGENTS[item.to].color, marginLeft: (item.depth - 1) * 22 } as CSSProperties}>
          <span className="when">{time(item.time)}</span>
          <div className="brief-line">
            <AgentChip agent={item.from} /><ArrowIcon /><AgentChip agent={item.to} />
            {item.depth > 1 && <span className="muted small">teammate consult</span>}
          </div>
          <details><summary>{item.brief.slice(0, 150)}{item.brief.length > 150 ? '…' : ''}</summary><p>{item.brief}</p></details>
        </li>
      )
    case 'act':
      return (
        <li className="feed-row act" style={{ '--agent': AGENTS[item.agent].color, marginLeft: item.depth * 22 } as CSSProperties}>
          <span className="when">{time(item.time)}</span>
          <div>
            <AgentChip agent={item.agent} />
            {item.reasoning && <p className="thought">{item.reasoning.replace(/\*\*/g, '')}</p>}
            {item.text && <p className="said">{item.text}</p>}
            {item.tools.length > 0 && (
              <div className="tools">
                {item.tools.map((t, i) => (
                  <span key={i} className="tool" title={t.name}>{t.label}{t.detail && <em> {t.detail}</em>}</span>
                ))}
              </div>
            )}
          </div>
        </li>
      )
    case 'outcome':
      return (
        <li className={`feed-row outcome-row ${item.error ? 'bad' : ''}`} style={{ marginLeft: item.depth * 22 }}>
          <span className="when">{time(item.time)}</span>
          <span className="made">{item.label}</span>
        </li>
      )
    case 'report':
      return (
        <li className="feed-row report" style={{ '--agent': AGENTS[item.agent].color, marginLeft: item.depth * 22 } as CSSProperties}>
          <span className="when">{time(item.time)}</span>
          <div><AgentChip agent={item.agent} /> <span className="muted small">{item.agent === 'boss' ? 'made the call' : 'reported back'}</span><p>{item.summary}</p></div>
        </li>
      )
    case 'done':
      return (
        <li className="feed-row system done">
          <span className="when">{time(item.time)}</span>
          <span>
            Run {item.status === 'completed' ? 'complete' : 'failed'}
            {item.durationMs !== null && ` in ${Math.round(item.durationMs / 1000)}s`}
            {item.usage && ` · ${item.usage.requests} model calls · ${item.usage.tool_calls} tool calls · ${(item.usage.total_tokens / 1000).toFixed(1)}k tokens`}
          </span>
        </li>
      )
    case 'error':
      return <li className="feed-row outcome-row bad"><span className="when">{time(item.time)}</span><span className="made">{AGENTS[item.agent].label}: {item.message}</span></li>
    case 'human':
      return (
        <li className={`feed-row human ${item.error ? 'bad' : ''}`}>
          <span className="when">{time(item.time)}</span>
          <div><AgentChip agent="human" /> <span>{item.message.replace('approve_and_pay', 'Approved').replace('reject_payment_request', 'Rejected')}</span>
            {item.error && <p className="muted small">Refused: {item.error}</p>}</div>
        </li>
      )
  }
}

function Feed({ items, live }: { items: FeedItem[]; live: boolean }) {
  const end = useRef<HTMLLIElement>(null)
  useEffect(() => { if (live) end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [items.length, live])
  return (
    <ol className="feed">
      {items.map(i => <FeedRow key={i.key} item={i} />)}
      {live && <li ref={end} className="feed-row system typing"><span className="when" /><span><span className="pulse" /> The team is working…</span></li>}
    </ol>
  )
}

// ---------- panel ----------

export function RunPanel({ ticket, events, runId, running, busyElsewhere, drafts, onRun, onClose, canClose }: Props) {
  const finished = !!runId && events.some(e => e.run_id === runId && e.kind === 'run_summary')
  const states = agentStates(events, runId, finished)
  const items = buildFeed(events, runId)
  const steps = items.filter(i => i.kind !== 'human').length
  const lastRunTime = runId ? events.find(e => e.run_id === runId)?.time : null
  const staleRun = finished && ticket.state === 'open'

  return (
    <main className="run">
      <section className="ticket-hero">
        <div className="hero-icon"><TicketIcon type={ticket.type} size={22} /></div>
        <div className="hero-body">
          <div className="hero-meta">
            #{ticket.id} · {TICKET_TYPES[ticket.type] ?? ticket.type} · from {ticket.requester}
          </div>
          <h2>{ticket.subject}</h2>
          {ticket.notes && <p className="hero-notes">“{ticket.notes}”</p>}
        </div>
        <div className="hero-actions">
          <span className={`pill big ${running ? 'running' : ticket.state}`}>
            {running ? 'Agents working' : ticket.state === 'open' ? 'Open' : 'Resolved'}
          </span>
          {!running && ticket.state === 'resolved' && (
            <span className="hero-status">
              {ticket.status === 'resolved' ? 'Closed' : DECISIONS[ticket.status]?.label ?? ticket.status}
            </span>
          )}
          {!running && ticket.state === 'resolved' && ticket.status !== 'resolved' && !ticket.needs_human_action && (
            <button className="btn approve" onClick={onClose} disabled={!canClose || busyElsewhere}
              title={canClose ? 'Payments are decided and drafts reviewed: close it out' : 'Enter your name in Approvals first'}>
              Close ticket
            </button>
          )}
          <button className="btn primary" onClick={onRun} disabled={running || busyElsewhere}>
            <PlayIcon /> {running ? 'Team is on it…' : ticket.state === 'open' ? 'Send to agent team' : 'Run again'}
          </button>
        </div>
      </section>

      <Roster states={states} running={running} />

      {!runId && !running && (
        <div className="empty">
          <p>No run yet for this ticket.</p>
          <p className="muted">Send it to the team. The Boss reads it first, then briefs only the specialists it needs.</p>
        </div>
      )}

      {finished && !running && (
        <>
          {staleRun && lastRunTime && (
            <p className="note">Showing the last run ({new Date(lastRunTime).toLocaleString()}), from before the database was reset.</p>
          )}
          <Outcome events={events} runId={runId} states={states} />
        </>
      )}

      <Drafts drafts={drafts} />

      {(running || items.length > 0) && (
        running ? (
          <section>
            <h3 className="subhead">Live activity</h3>
            <Feed items={items} live />
          </section>
        ) : (
          <details className="activity">
            <summary>Full activity · {steps} steps {lastRunTime && `· ${new Date(lastRunTime).toLocaleTimeString()}`}</summary>
            <Feed items={items} live={false} />
          </details>
        )
      )}
    </main>
  )
}

