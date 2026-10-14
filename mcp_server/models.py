"""Pydantic return types for the Campus Customs MCP tools.

Every value is either read straight from the database or is simple arithmetic on
database values (fields described as "derived"). Nothing is estimated or invented.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- shared pieces ----------

class TicketSummary(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    status: str
    notes: str | None
    created_at: str


class SizeStock(BaseModel):
    size: str
    qty: int
    location: str


class InvoiceInfo(BaseModel):
    id: int
    vendor_id: int
    amount: float
    due_date: str
    status: str
    description: str | None
    days_overdue: int = Field(description="Derived: desk.date_today - due_date, 0 if not yet due or not open.")


class VendorInfo(BaseModel):
    id: int
    name: str
    specialty: str
    lead_days: int
    open_invoices: list[InvoiceInfo]
    blocked_by_unpaid_invoice: bool = Field(
        description="Shop rule: a vendor will not ship while it has any open invoice."
    )
    earliest_eta_if_unblocked_today: str = Field(
        description="Derived: desk.date_today + lead_days. Only valid once open invoices are paid."
    )


class CashAccount(BaseModel):
    name: str
    balance: float
    as_of: str


# ---------- tool 1: ticket 101 ----------

class CustomerOrderFulfillment(BaseModel):
    shop_date_today: str
    ticket: TicketSummary
    sku: str
    product_name: str
    size_requested: str
    qty_requested: int
    qty_on_hand: int
    location: str
    can_fill_from_stock: bool
    shortfall: int = Field(description="Derived: max(0, qty_requested - qty_on_hand).")
    other_sizes_in_stock: list[SizeStock] = Field(description="Same SKU, other sizes with qty > 0.")
    linked_invoice: InvoiceInfo | None = Field(description="From tickets.invoice_id; None if the ticket has none.")
    linked_vendor: VendorInfo | None = Field(description="The vendor on the linked invoice; None if no invoice.")


# ---------- tool 2: ticket 102 ----------

class RentDueAndCash(BaseModel):
    shop_date_today: str
    ticket: TicketSummary
    lease_id: int
    space_name: str
    landlord: str
    monthly_rent: float
    next_due: str
    days_until_due: int = Field(description="Derived: next_due - desk.date_today (negative means overdue).")
    is_overdue: bool
    cash_accounts: list[CashAccount]
    total_cash: float
    can_cover_rent: bool
    cash_after_rent: float = Field(description="Derived: total_cash - monthly_rent.")
    other_open_invoices: list[InvoiceInfo] = Field(description="Competing obligations already owed.")
    cash_after_rent_and_open_invoices: float = Field(
        description="Derived: total_cash - monthly_rent - sum(open invoice amounts)."
    )


# ---------- tool 3: ticket 103 ----------

class BulkOrderQuote(BaseModel):
    shop_date_today: str
    ticket: TicketSummary
    sku: str
    product_name: str
    size_requested: str
    qty_requested: int
    qty_on_hand: int
    shortfall: int = Field(description="Derived: max(0, qty_requested - qty_on_hand).")
    all_sizes: list[SizeStock]
    unit_cost: float
    list_price: float
    discount_pct: float
    quoted_unit_price: float = Field(description="Derived: list_price * (1 - discount_pct/100).")
    margin_per_unit: float = Field(description="Derived: quoted_unit_price - unit_cost.")
    margin_pct: float = Field(description="Derived: margin_per_unit / quoted_unit_price * 100.")
    order_revenue: float
    order_gross_profit: float
    max_discount_pct_before_loss: float = Field(description="Derived: (list_price - unit_cost) / list_price * 100.")
    restock_cost_at_unit_cost: float = Field(description="Derived: shortfall * unit_cost.")
    vendors: list[VendorInfo] = Field(
        description="All vendors. The database has no SKU-to-vendor link, so the agent picks by specialty."
    )


# ---------- general read tools (Question 5) ----------

class TicketDetail(BaseModel):
    """A full tickets row plus the work already recorded against it (so agents don't duplicate it)."""
    id: int
    type: str
    requester: str
    subject: str
    sku: str | None
    size: str | None
    qty: int | None
    lease_id: int | None
    invoice_id: int | None
    status: str
    notes: str | None
    created_at: str
    payment_requests: list["PaymentRequest"] = Field(description="payment_requests rows with this ticket_id.")
    message_drafts: list["MessageDraft"] = Field(description="message_drafts rows with this ticket_id.")
    decisions: list["TicketDecision"] = Field(description="ticket_decisions rows with this ticket_id.")


class OpenTickets(BaseModel):
    shop_date_today: str
    tickets: list[TicketSummary]


class SkuStock(BaseModel):
    shop_date_today: str
    sku: str
    product_name: str
    unit_cost: float | None = Field(description="From pricing; None if the SKU has no pricing row.")
    list_price: float | None
    sizes: list[SizeStock] = Field(description="Every size row for the SKU, or only the requested size.")
    total_qty: int = Field(description="Derived: sum of qty over the sizes returned.")


class VendorList(BaseModel):
    shop_date_today: str
    vendors: list[VendorInfo]


class LeaseInfo(BaseModel):
    shop_date_today: str
    id: int
    space_name: str
    landlord: str
    monthly_rent: float
    next_due: str
    days_until_due: int = Field(description="Derived: next_due - desk.date_today (negative means overdue).")
    is_overdue: bool
    notes: str | None


class CashPosition(BaseModel):
    shop_date_today: str
    cash_accounts: list[CashAccount]
    total_cash: float
    open_invoices: list[InvoiceInfo]
    open_invoices_total: float
    pending_payment_requests: list["PaymentRequest"]
    pending_requests_total: float
    cash_after_pending_requests: float = Field(
        description="Derived: total_cash - pending_requests_total. Negative means not every pending request can be paid."
    )
    leases_due_within_14_days: list[LeaseInfo]


# ---------- workflow records (Question 5) ----------

class PaymentRequest(BaseModel):
    """A payment or purchase order prepared by an agent. Nothing moves until a human approves it."""
    id: int
    kind: str = Field(description="invoice | rent | purchase_order")
    ref_id: int | None = Field(description="invoices.id for invoice, leases.id for rent, None for purchase_order.")
    vendor_id: int | None
    sku: str | None
    size: str | None
    qty: int | None
    amount: float = Field(description="Set by the server from the database, never by the agent.")
    reason: str
    ticket_id: int | None
    requested_by: str
    status: str = Field(description="pending_approval | paid | rejected")
    created_at: str
    decided_by: str | None
    decided_at: str | None
    decision_note: str | None


class PaymentRequestResult(BaseModel):
    """What an agent gets back after preparing a payment request."""
    request: PaymentRequest
    already_existed: bool = Field(description="True if a matching pending request existed and was returned instead.")
    cash_on_hand: float
    pending_requests_total: float = Field(description="Every pending request, including this one.")
    cash_after_all_pending: float
    would_overdraw_if_all_approved: bool
    vendor_blocked_by_unpaid_invoice: bool | None = Field(
        description="Purchase orders only: the vendor will not ship until its open invoices are paid."
    )
    note: str


class PaymentRequestList(BaseModel):
    requests: list[PaymentRequest]
    total: float


class MessageDraft(BaseModel):
    id: int
    ticket_id: int
    to_name: str = Field(description="Taken from tickets.requester, not from the agent.")
    subject: str
    body: str
    drafted_by: str
    status: str = Field(description="Always 'draft'. There is no send tool.")
    created_at: str


class MessageDraftList(BaseModel):
    drafts: list[MessageDraft]


class TicketDecision(BaseModel):
    id: int
    ticket_id: int
    decision: str
    summary: str
    decided_by: str
    created_at: str


class PaymentResult(BaseModel):
    """Human-only pay tool result."""
    paid: bool
    request: PaymentRequest
    payment_id: int | None
    cash_before: float
    cash_after: float
    message: str


class ResetResult(BaseModel):
    reset: bool
    source: str
    target: str
    message: str


TicketDetail.model_rebuild()
CashPosition.model_rebuild()
