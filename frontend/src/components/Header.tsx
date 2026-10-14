import { useEffect, useRef, useState } from 'react'
import { money } from '../feed'
import type { Cash } from '../types'
import { ResetIcon } from './Icons'

/** Counts smoothly from the old balance to the new one, so a payment visibly "drops" the cash. */
function useAnimatedNumber(target: number | null, ms = 900): number | null {
  const [value, setValue] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    if (target === null) return
    const start = from.current ?? target
    if (start === target) { setValue(target); return }
    const t0 = performance.now()
    let raf = 0
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / ms)
      const eased = 1 - Math.pow(1 - p, 3)
      setValue(start + (target - start) * eased)
      if (p < 1) raf = requestAnimationFrame(tick)
      else from.current = target
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return value
}

function CashCard({ cash, delta }: { cash: Cash | null; delta: number | null }) {
  const shown = useAnimatedNumber(cash?.balance ?? null)
  const pending = cash?.pending_requests_total ?? 0
  const after = cash?.balance_after_pending ?? 0
  const pct = cash && cash.balance > 0 ? Math.min(100, (pending / cash.balance) * 100) : 0
  return (
    <div className="cash" aria-live="polite">
      <div className="cash-top">
        <span className="eyebrow">Checking balance</span>
        {delta !== null && delta !== 0 && (
          <span key={`${delta}-${cash?.balance}`} className={`cash-delta ${delta < 0 ? 'down' : 'up'}`}>
            {delta < 0 ? '−' : '+'}{money(Math.abs(delta))}
          </span>
        )}
      </div>
      <div className="cash-amount">{shown === null ? '—' : money(shown)}</div>
      <div className="cash-bar" title="Share of the balance already promised to pending requests">
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="cash-sub">
        {pending > 0 ? (
          <>
            <span>{money(pending)} awaiting approval</span>
            <span className={after < 0 ? 'neg' : ''}>{money(after)} if all approved</span>
          </>
        ) : (
          <span>Nothing awaiting approval</span>
        )}
      </div>
    </div>
  )
}

interface Props {
  shopDate: string | null
  cash: Cash | null
  cashDelta: number | null
  connected: boolean
  busy: boolean
  onReset: () => void
}

export function Header({ shopDate, cash, cashDelta, connected, busy, onReset }: Props) {
  const date = shopDate
    ? new Date(`${shopDate}T12:00:00`).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
    : '—'
  return (
    <header className="masthead">
      <div className="brand">
        <div className="crest" aria-hidden="true">CC</div>
        <div>
          <h1>Campus Customs <span>Ops Desk</span></h1>
          <p className="dateline">
            <span className={`dot ${connected ? 'on' : 'off'}`} />
            {connected ? 'Agent team online' : 'Backend offline'} · Shop date {date} · 1 Chapel Street, New Haven
          </p>
        </div>
      </div>
      <div className="masthead-right">
        <CashCard cash={cash} delta={cashDelta} />
        <button className="btn ghost" onClick={onReset} disabled={busy || !connected} title="Restore the database to its original values">
          <ResetIcon /> Fresh start
        </button>
      </div>
    </header>
  )
}
