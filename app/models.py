from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Principal(Strict):
    uid: str
    role: Literal['customer', 'support_agent', 'evaluator']
    customer_id: str | None = None

class SessionRequest(Strict):
    role: Literal['customer', 'support_agent'] = 'customer'
    customer_id: str | None = Field(default=None, pattern=r'^CUST\d{4}$')

class ChatRequest(Strict):
    session_id: str
    generation: int = Field(ge=0)
    message: str = Field(min_length=1, max_length=3000)
    request_id: str = Field(min_length=1, max_length=80, pattern=r'^[\w-]+$')

class Filter(Strict):
    field: Literal['booking_id', 'customer_id', 'vehicle_id', 'booking_status', 'hub_name', 'vehicle_type', 'model', 'status', 'customer_tier', 'kyc_status', 'scheduled_start', 'scheduled_end', 'booked_at', 'payment_status', 'payment_type', 'claim_status', 'damage_category']
    op: Literal['eq', 'gte', 'lte', 'contains'] = 'eq'
    value: str = Field(max_length=100)

class Plan(Strict):
    operation: Literal['bookings', 'payments', 'damage', 'vehicles', 'profile', 'analytics', 'policy', 'refund', 'charges', 'rental', 'clarify', 'refuse']
    booking_id: str | None = Field(default=None, pattern=r'^B-\d{4}$')
    customer_id: str | None = Field(default=None, pattern=r'^CUST\d{4}$')
    filters: list[Filter] = Field(default_factory=list, max_length=8)
    metric: Literal['count', 'revenue', 'refunds', 'penalties', 'late_returns', 'utilization'] = 'count'
    group_by: Literal['none', 'hub_name', 'vehicle_type', 'model', 'booking_status', 'customer_tier', 'month'] = 'none'
    topic: Literal['rental', 'refund', 'penalty', 'ev', 'all'] = 'all'
    clarification: str = Field(default='', max_length=400)
    profile_contact: bool = False

class Claim(Strict):
    text: str = Field(min_length=1, max_length=2000)
    citations: list[str] = Field(min_length=1, max_length=15)

class Explanation(Strict):
    claims: list[Claim] = Field(min_length=1, max_length=12)
