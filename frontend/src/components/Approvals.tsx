import { useState } from 'react'
import { AGENTS } from '../agents'
import { money } from '../feed'
import type { Actor, PaymentRequest } from '../types'
import { CheckIcon } from './Icons'

interface Props {
  requests: PaymentRequest[]
  approver: string
  onApproverChange: (name: string) => void
  onApprove: (id: number) => Promise<void>
  onReject: (id: number) => Promise<void>
  locked: boolean
  balance: number | null
}

const KIND: Record<PaymentRequest['kind'], string> = {
  invoice: 'Vendor invoice',
  rent: 'Rent',
  purchase_order: 'Purchase order',
}

function describe(r: PaymentRequest): string {
  if (r.kind === 'invoice') return `Invoice #${r.ref_id}`
  if (r.kind === 'rent') return `Lease #${r.ref_id}`
  return `${r.qty} × ${r.sku} ${r.size}`
}

export function Approvals({ requests, approver, onApproverChange, onApprove, onReject, locked, balance }: Props) {
  const [busy, setBusy] = useState<number | null>(null)
  const [confirmReject, setConfirmReject] = useState<number | null>(null)
  const pending = requests.filter(r => r.status === 'pending_approval')
  const decided = requests.filter(r => r.status !== 'pending_approval').slice(-5).reverse()
  const named = approver.trim().length >= 2

  const act = async (id: number, fn: (id: number) => Promise<void>) => {
    setBusy(id)
    try { await fn(id) } finally { setBusy(null); setConfirmReject(null) }
  }

  return (
    <aside className="approvals" aria-label="Approvals">
      <div className="section-head">
        <h2>Approvals</h2>
        {pending.length > 0 && <span className="count">{pending.length}</span>}
      </div>
      <p className="muted small">Agents only prepare payments. Nothing is paid until you approve it here.</p>

      <label className="approver">
        <span>Approving as</span>
        <input value={approver} onChange={e => onApproverChange(e.target.value)} placeholder="Your full name" maxLength={80} />
      </label>

      {pending.length === 0 && <div className="empty small">No payments waiting.</div>}

      <ul className="requests">
        {pending.map(r => {
          const overdraws = balance !== null && r.amount > balance
          const agent = AGENTS[r.requested_by as Actor]
          return (
            <li key={r.id} className="request">
              <div className="request-top">
                <span className="request-kind">{KIND[r.kind]}</span>
                <span className="request-amount">{money(r.amount)}</span>
              </div>
              <div className="request-what">{describe(r)} · ticket #{r.ticket_id ?? '—'} · request #{r.id}</div>
              <p className="request-reason">{r.reason}</p>
              <div className="request-by">
                Prepared by <span style={{ color: agent?.color }}>{agent?.label ?? r.requested_by}</span>
              </div>
              {overdraws && <div className="warn">More than the {money(balance!)} in checking. The pay tool will refuse it.</div>}
              <div className="request-actions">
                <button className="btn approve" disabled={!named || locked || busy !== null} onClick={() => act(r.id, onApprove)}
                  title={!named ? 'Enter your name first' : locked ? 'Wait for the run to finish' : 'Pay this now'}>
                  <CheckIcon /> {busy === r.id ? 'Paying…' : 'Approve & pay'}
                </button>
                {confirmReject === r.id ? (
                  <button className="btn danger" disabled={busy !== null} onClick={() => act(r.id, onReject)}>Confirm reject</button>
                ) : (
                  <button className="btn ghost" disabled={!named || busy !== null} onClick={() => setConfirmReject(r.id)}>Reject</button>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      {decided.length > 0 && (
        <div className="decided">
          <h3 className="subhead">Recently decided</h3>
          <ul>
            {decided.map(r => (
              <li key={r.id}>
                <span className={`pill ${r.status === 'paid' ? 'resolved' : 'muted'}`}>{r.status === 'paid' ? 'Paid' : 'Rejected'}</span>
                <span>{KIND[r.kind]} · {money(r.amount)}</span>
                <span className="muted small">by {r.decided_by}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  )
}
