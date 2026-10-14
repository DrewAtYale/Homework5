// Visual identity for each agent. Personas come from backend/prompts/*.md; the board only borrows
// a colour, a monogram and one line of voice from each, so the theming stays quiet.
import type { Actor } from './types'

export interface AgentStyle {
  label: string
  role: string
  persona: string // the media archetype in the agent's prompt
  motto: string // one line in the persona's voice, shown small
  working: string // what "busy" looks like for this agent
  color: string
  soft: string
  monogram: string
}

export const AGENTS: Record<Actor, AgentStyle> = {
  boss: {
    label: 'Boss', role: 'Reads, delegates, decides', persona: 'Miranda Priestly',
    motto: 'Facts, not feelings.', working: 'weighing the reports',
    color: '#1f2430', soft: '#eceae4', monogram: 'B',
  },
  inventory: {
    label: 'Inventory', role: 'Stock, shortages, restock', persona: 'Dwight Schrute',
    motto: "If a tool didn't count it, it isn't a count.", working: 'counting stock',
    color: '#a65f0a', soft: '#fbf1e1', monogram: 'I',
  },
  accounting: {
    label: 'Accounting', role: 'Cash, margins, payments', persona: 'Ben Wyatt',
    motto: 'Protect the essentials first.', working: 'balancing the books',
    color: '#1e7a4c', soft: '#e6f3ec', monogram: 'A',
  },
  facilities: {
    label: 'Facilities', role: 'Lease, rent, the shop space', persona: 'Mr. Carson',
    motto: 'Obligations are met on time.', working: 'reviewing the lease',
    color: '#7a2c4f', soft: '#f6e8ee', monogram: 'F',
  },
  customer_service: {
    label: 'Customer Service', role: 'Drafts customer replies', persona: 'Ted Lasso',
    motto: 'Honest news, warmly told.', working: 'drafting a reply',
    color: '#13718a', soft: '#e3f2f5', monogram: 'C',
  },
  human: {
    label: 'You', role: 'Approves payments', persona: '',
    motto: '', working: '',
    color: '#0f2a4a', soft: '#e7edf5', monogram: '✓',
  },
}

export const TEAM: Actor[] = ['boss', 'inventory', 'accounting', 'facilities', 'customer_service']

// Plain-English names for the MCP tools.
export const TOOL_LABELS: Record<string, string> = {
  get_ticket: 'Read the ticket',
  list_open_tickets: 'Scanned the inbox',
  list_tickets: 'Scanned all tickets',
  check_customer_order_fulfillment: 'Checked the order',
  check_rent_due_and_cash: 'Checked rent vs. cash',
  quote_bulk_order_discount: 'Priced the bulk order',
  check_stock: 'Checked stock',
  list_vendors: 'Looked up vendors',
  get_lease: 'Read the lease',
  get_cash_position: 'Checked cash',
  list_payment_requests: 'Checked the approval queue',
  list_message_drafts: 'Checked drafts',
  prepare_invoice_payment: 'Prepared invoice payment',
  prepare_rent_payment: 'Prepared rent payment',
  prepare_purchase_order: 'Prepared purchase order',
  draft_customer_message: 'Saved a draft',
  delegate: 'Delegated',
  final_result: 'Filed report',
}

export const WRITE_TOOLS = new Set([
  'prepare_invoice_payment', 'prepare_rent_payment', 'prepare_purchase_order', 'draft_customer_message',
])

export const TICKET_TYPES: Record<string, string> = {
  customer_order: 'Customer order',
  rent_notice: 'Rent notice',
  price_override: 'Bulk discount',
}

export const DECISIONS: Record<string, { label: string; tone: 'ok' | 'wait' | 'warn' | 'muted' }> = {
  resolved: { label: 'Resolved', tone: 'ok' },
  awaiting_human_approval: { label: 'Awaiting your approval', tone: 'wait' },
  deferred: { label: 'Deferred', tone: 'muted' },
  needs_human: { label: 'Needs a human', tone: 'warn' },
}
