import { TICKET_TYPES } from '../agents'
import type { TicketRow } from '../types'
import { TicketIcon } from './Icons'

interface Props {
  tickets: TicketRow[]
  selectedId: number | null
  runningId: number | null
  onSelect: (id: number) => void
}

export function TicketList({ tickets, selectedId, runningId, onSelect }: Props) {
  const open = tickets.filter(t => t.state === 'open').length
  return (
    <nav className="tickets" aria-label="Tickets">
      <div className="section-head">
        <h2>Desk</h2>
        <span className="muted">{open} open · {tickets.length - open} resolved</span>
      </div>
      <ul>
        {tickets.map(t => {
          const running = runningId === t.id
          const pill = running ? 'running' : t.state
          return (
            <li key={t.id}>
              <button
                className={`ticket ${selectedId === t.id ? 'selected' : ''} ${t.state}`}
                onClick={() => onSelect(t.id)}
                aria-current={selectedId === t.id}
              >
                <span className="ticket-icon"><TicketIcon type={t.type} /></span>
                <span className="ticket-body">
                  <span className="ticket-top">
                    <span className="ticket-id">#{t.id}</span>
                    <span className={`pill ${pill}`}>
                      {running ? 'Agents working' : t.state === 'open' ? 'Open' : 'Resolved'}
                    </span>
                  </span>
                  <span className="ticket-subject">{t.subject}</span>
                  <span className="ticket-meta">{TICKET_TYPES[t.type] ?? t.type} · {t.requester}</span>
                  {t.needs_human_action && !running && (
                    <span className="ticket-flag">
                      {t.pending_payment_request_ids.length === 1
                        ? '1 payment needs your approval'
                        : `${t.pending_payment_request_ids.length} payments need your approval`}
                    </span>
                  )}
                  {!t.needs_human_action && !running && t.state === 'resolved' && t.status !== 'resolved' && (
                    <span className="ticket-flag soft">
                      {t.status === 'deferred' ? 'Deferred by the Boss'
                        : t.status === 'needs_human' ? 'Needs a human decision'
                        : 'Team done · ready for you to close'}
                    </span>
                  )}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      <p className="fineprint">
        Nothing on this desk is ever sent. Messages stay drafts, and money moves only when a person approves it.
      </p>
    </nav>
  )
}
