import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, API_URL } from './api'
import { DECISIONS } from './agents'
import { money, runsOf } from './feed'
import { Approvals } from './components/Approvals'
import { Header } from './components/Header'
import { RunPanel } from './components/RunPanel'
import { TicketList } from './components/TicketList'
import type { AgentEvent, Cash, MessageDraft, PaymentRequest, TicketRow } from './types'

const POLL_MS = 1500
const ticketFromUrl = Number(new URLSearchParams(location.search).get('ticket')) || null

interface Toast { id: number; tone: 'ok' | 'bad' | 'info'; title: string; body?: string }

export default function App() {
  const [tickets, setTickets] = useState<TicketRow[]>([])
  const [shopDate, setShopDate] = useState<string | null>(null)
  const [cash, setCash] = useState<Cash | null>(null)
  const [cashDelta, setCashDelta] = useState<number | null>(null)
  const [requests, setRequests] = useState<PaymentRequest[]>([])
  const [drafts, setDrafts] = useState<MessageDraft[]>([])
  const [connected, setConnected] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(ticketFromUrl)
  const [events, setEvents] = useState<Record<number, AgentEvent[]>>({})
  const [running, setRunning] = useState<{ ticketId: number; startedAt: string } | null>(null)
  const [busyElsewhere, setBusyElsewhere] = useState(false)
  const [approver, setApprover] = useState(() => localStorage.getItem('approver') ?? '')
  const [toasts, setToasts] = useState<Toast[]>([])
  const since = useRef<Record<number, string | null>>({})

  const toast = useCallback((t: Omit<Toast, 'id'>) => {
    const id = Date.now() + Math.random()
    setToasts(ts => [...ts, { ...t, id }])
    setTimeout(() => setToasts(ts => ts.filter(x => x.id !== id)), t.tone === 'bad' ? 9000 : 6000)
  }, [])

  // ----- loading -----

  const refresh = useCallback(async () => {
    try {
      const [t, c, r, d, h] = await Promise.all([api.tickets(), api.cash(), api.paymentRequests(), api.drafts(), api.health()])
      setTickets(t.tickets)
      setShopDate(t.shop_date_today)
      setCash(prev => {
        if (prev && prev.balance !== c.balance) setCashDelta(c.balance - prev.balance)
        return c
      })
      setRequests(r.requests)
      setDrafts(d.drafts)
      setConnected(h.ok)
      setBusyElsewhere(h.run_in_progress)
      setSelectedId(id => id ?? t.tickets.find(x => x.state === 'open')?.id ?? t.tickets[0]?.id ?? null)
    } catch (err) {
      setConnected(false)
      if (err instanceof ApiError && err.status === 0) return
      throw err
    }
  }, [])

  const loadEvents = useCallback(async (ticketId: number) => {
    const res = await api.events({ ticketId, since: since.current[ticketId] ?? null })
    since.current[ticketId] = res.latest_time
    if (res.events.length) setEvents(prev => ({ ...prev, [ticketId]: [...(prev[ticketId] ?? []), ...res.events] }))
  }, [])

  useEffect(() => { refresh().catch(() => undefined) }, [refresh])

  // Keep a quiet heartbeat so the board notices the backend coming up or a run started elsewhere.
  useEffect(() => {
    const id = setInterval(() => { if (!running) refresh().catch(() => undefined) }, connected ? 10000 : 3000)
    return () => clearInterval(id)
  }, [refresh, running, connected])

  useEffect(() => {
    if (selectedId !== null && events[selectedId] === undefined && since.current[selectedId] === undefined) {
      since.current[selectedId] = null
      loadEvents(selectedId).catch(() => undefined)
    }
  }, [selectedId, events, loadEvents])

  // While a run is going, poll its events (and the approval queue, which fills as Accounting works).
  useEffect(() => {
    if (!running) return
    let n = 0
    const id = setInterval(() => {
      loadEvents(running.ticketId).catch(() => undefined)
      if (++n % 3 === 0) Promise.all([api.paymentRequests(), api.drafts()])
        .then(([r, d]) => { setRequests(r.requests); setDrafts(d.drafts) }).catch(() => undefined)
    }, POLL_MS)
    return () => clearInterval(id)
  }, [running, loadEvents])

  // ----- actions -----

  const runTicket = async (ticketId: number) => {
    setRunning({ ticketId, startedAt: new Date().toISOString() })
    try {
      const result = await api.runTicket(ticketId)
      const d = result.decision
      toast({
        tone: 'ok',
        title: `Ticket #${ticketId} resolved`,
        body: d ? `${DECISIONS[d.decision]?.label ?? d.decision} · ${result.delegations} delegations · ${Math.round(result.duration_ms / 1000)}s` : undefined,
      })
    } catch (err) {
      toast({ tone: 'bad', title: `Run on #${ticketId} didn't finish`, body: err instanceof Error ? err.message : String(err) })
    } finally {
      await loadEvents(ticketId).catch(() => undefined)
      await refresh().catch(() => undefined)
      setRunning(null)
    }
  }

  const approve = async (id: number) => {
    try {
      const res = await api.approve(id, approver.trim())
      toast({ tone: 'ok', title: `Paid ${money(res.request.amount)}`, body: `Checking ${money(res.cash_before)} → ${money(res.cash_after)}` })
    } catch (err) {
      const body = err instanceof ApiError && err.body && typeof err.body === 'object' && 'message' in err.body
        ? String((err.body as { message: string }).message) : err instanceof Error ? err.message : String(err)
      toast({ tone: 'bad', title: 'Payment refused', body })
    }
    await refresh().catch(() => undefined)
    const ticketId = requests.find(r => r.id === id)?.ticket_id
    if (ticketId) await loadEvents(ticketId).catch(() => undefined)
  }

  const closeTicket = async (ticketId: number) => {
    try {
      await api.closeTicket(ticketId, approver.trim(), 'Payments decided and drafts reviewed on the dashboard.')
      toast({ tone: 'ok', title: `Ticket #${ticketId} closed`, body: `Marked resolved by ${approver.trim()}.` })
    } catch (err) {
      toast({ tone: 'bad', title: "Couldn't close the ticket", body: err instanceof Error ? err.message : String(err) })
    }
    await refresh().catch(() => undefined)
    await loadEvents(ticketId).catch(() => undefined)
  }

  const reject = async (id: number) => {
    try {
      await api.reject(id, approver.trim(), 'Rejected from the dashboard')
      toast({ tone: 'info', title: `Request #${id} rejected`, body: 'No money moved.' })
    } catch (err) {
      toast({ tone: 'bad', title: 'Reject failed', body: err instanceof Error ? err.message : String(err) })
    }
    await refresh().catch(() => undefined)
  }

  const reset = async () => {
    if (!window.confirm('Start fresh? This restores the shop database to its original values: tickets reopen, payments and drafts are cleared, and cash returns to $3,400. The audit trail is kept.')) return
    try {
      await api.reset()
      setCashDelta(null)
      toast({ tone: 'info', title: 'Fresh start', body: 'Database restored to original values.' })
    } catch (err) {
      toast({ tone: 'bad', title: 'Reset failed', body: err instanceof Error ? err.message : String(err) })
    }
    await refresh().catch(() => undefined)
  }

  const onApproverChange = (name: string) => { setApprover(name); localStorage.setItem('approver', name) }

  // ----- derived -----

  const selected = tickets.find(t => t.id === selectedId) ?? null
  const ticketEvents = useMemo(() => (selectedId !== null ? events[selectedId] ?? [] : []), [events, selectedId])
  const runId = useMemo(() => {
    const runs = runsOf(ticketEvents)
    if (running && running.ticketId === selectedId) {
      // Only show the run that started after we clicked, never the previous one.
      const fresh = runs.filter(r => (ticketEvents.find(e => e.run_id === r)?.time ?? '') >= running.startedAt)
      return fresh.at(-1) ?? null
    }
    return runs.at(-1) ?? null
  }, [ticketEvents, running, selectedId])

  return (
    <div className="app">
      <Header shopDate={shopDate} cash={cash} cashDelta={cashDelta} connected={connected} busy={!!running || busyElsewhere} onReset={reset} />

      {!connected && (
        <div className="banner">
          Can't reach the backend at <code>{API_URL}</code>. Start it from <code>backend/</code> with <code>uvicorn main:app --reload --port 8000</code>.
        </div>
      )}

      <div className="layout">
        <TicketList tickets={tickets} selectedId={selectedId} runningId={running?.ticketId ?? null} onSelect={setSelectedId} />
        {selected ? (
          <RunPanel
            ticket={selected}
            events={ticketEvents}
            runId={runId}
            running={running?.ticketId === selected.id}
            busyElsewhere={(!!running && running.ticketId !== selected.id) || (busyElsewhere && !running)}
            drafts={drafts.filter(d => d.ticket_id === selected.id)}
            onRun={() => runTicket(selected.id)}
            onClose={() => closeTicket(selected.id)}
            canClose={approver.trim().length >= 2}
          />
        ) : (
          <main className="run"><div className="empty">Pick a ticket.</div></main>
        )}
        <Approvals
          requests={requests}
          approver={approver}
          onApproverChange={onApproverChange}
          onApprove={approve}
          onReject={reject}
          locked={!!running}
          balance={cash?.balance ?? null}
        />
      </div>

      <div className="toasts" role="status">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <strong>{t.title}</strong>
            {t.body && <span>{t.body}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}
