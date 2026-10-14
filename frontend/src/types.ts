// Shapes returned by the FastAPI backend (backend/models.py and mcp_server/models.py).

export type AgentName = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'
export type Actor = AgentName | 'human'

export interface TicketRow {
  id: number
  type: string
  requester: string
  subject: string
  notes: string | null
  status: string
  state: 'open' | 'resolved'
  needs_human_action: boolean
  pending_payment_request_ids: number[]
  draft_ids: number[]
  latest_decision: string | null
}

export interface TicketsResponse {
  shop_date_today: string
  tickets: TicketRow[]
}

export interface AuditToolCall { tool: string; tool_call_id: string; args: string }
export interface AuditToolResult { tool: string; tool_call_id: string; result: string; is_error: boolean }

export type StepKind =
  | 'start' | 'model_response' | 'tool_results' | 'final_output' | 'error' | 'run_summary' | 'human_action'

export interface Usage {
  requests: number
  tool_calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface AgentEvent {
  time: string
  run_id: string
  ticket_id: number | null
  agent: Actor
  agent_run_id: string
  parent_agent: AgentName | null
  depth: number
  step: number
  kind: StepKind
  model: string
  input: string | null
  reasoning: string | null
  text: string | null
  tool_calls: AuditToolCall[]
  tool_results: AuditToolResult[]
  output: string | null
  summary?: string | null
  decision?: string | null
  usage: Usage | null
  error: string | null
}

export interface EventsResponse {
  events: AgentEvent[]
  total: number
  latest_time: string | null
}

export interface Fact { label: string; value: string; source_tool: string }

export interface BossDecision {
  ticket_id: number
  decision: 'resolved' | 'awaiting_human_approval' | 'deferred' | 'needs_human'
  summary: string
  rationale: string
  agents_consulted: AgentName[]
  payment_request_ids: number[]
  draft_ids: number[]
  human_next_steps: string[]
  key_facts: Fact[]
}

export interface TicketRunResult {
  run_id: string
  ticket_id: number
  status: 'completed' | 'error'
  decision: BossDecision | null
  recorded_decision_id: number | null
  dropped_ids: string[]
  delegations: number
  usage: Usage
  duration_ms: number
  model: string
  error: string | null
}

export interface PaymentRequest {
  id: number
  kind: 'invoice' | 'rent' | 'purchase_order'
  ref_id: number | null
  vendor_id: number | null
  sku: string | null
  size: string | null
  qty: number | null
  amount: number
  reason: string
  ticket_id: number | null
  requested_by: string
  status: 'pending_approval' | 'paid' | 'rejected'
  created_at: string
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
}

export interface PaymentResult {
  paid: boolean
  request: PaymentRequest
  payment_id: number | null
  cash_before: number
  cash_after: number
  message: string
}

export interface MessageDraft {
  id: number
  ticket_id: number
  to_name: string
  subject: string
  body: string
  drafted_by: string
  status: 'draft'
  created_at: string
}

export interface Cash {
  shop_date_today: string
  account: string
  balance: number
  as_of: string
  pending_requests_total: number
  balance_after_pending: number
}

export interface Health {
  ok: boolean
  model: string
  run_in_progress: boolean
}
