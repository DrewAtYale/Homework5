// Thin client for the FastAPI backend at http://localhost:8000 (override with VITE_API_URL).
import type {
  Cash, EventsResponse, Health, MessageDraft, PaymentRequest, PaymentResult, TicketRunResult, TicketsResponse,
} from './types'

export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API_URL}. Is uvicorn running?`, null)
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : null
    const message =
      typeof detail === 'string' ? detail
      : body && typeof body === 'object' && 'message' in body ? String((body as { message: unknown }).message)
      : `Request failed (${res.status})`
    throw new ApiError(res.status, message, body)
  }
  return body as T
}

const post = (body?: unknown): RequestInit => ({ method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  health: () => request<Health>('/api/health'),
  tickets: () => request<TicketsResponse>('/api/tickets'),
  runTicket: (id: number) => request<TicketRunResult>(`/api/tickets/${id}/run`, post()),
  events: (params: { ticketId?: number; since?: string | null; limit?: number }) => {
    const q = new URLSearchParams({ limit: String(params.limit ?? 500) })
    if (params.ticketId !== undefined) q.set('ticket_id', String(params.ticketId))
    if (params.since) q.set('since', params.since)
    return request<EventsResponse>(`/api/events?${q}`)
  },
  paymentRequests: () => request<{ requests: PaymentRequest[]; total: number }>('/api/payment-requests'),
  approve: (id: number, approvedBy: string) =>
    request<PaymentResult>(`/api/payment-requests/${id}/approve`, post({ approved_by: approvedBy })),
  reject: (id: number, rejectedBy: string, note: string) =>
    request<PaymentRequest>(`/api/payment-requests/${id}/reject`, post({ rejected_by: rejectedBy, note })),
  closeTicket: (id: number, closedBy: string, note = '') =>
    request<{ id: number; decision: string }>(`/api/tickets/${id}/close`, post({ closed_by: closedBy, note })),
  drafts: () => request<{ drafts: MessageDraft[] }>('/api/drafts'),
  cash: () => request<Cash>('/api/cash'),
  reset: () => request<{ reset: boolean; message: string }>('/api/reset', post()),
}
