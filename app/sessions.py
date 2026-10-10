from dataclasses import dataclass, field
from time import monotonic
from secrets import token_urlsafe
from fastapi import HTTPException
from .models import Principal

@dataclass
class Session:
    uid: str
    role: str
    customer_id: str | None
    generation: int = 0
    booking_id: str | None = None
    history: list = field(default_factory=list)
    busy: bool = False
    seen: set = field(default_factory=set)
    touched: float = field(default_factory=monotonic)

class Sessions:
    def __init__(self):
        self.items = {}

    def create(self, p: Principal, role, cid):
        if p.role != 'evaluator' and (role != p.role or cid != p.customer_id):
            raise HTTPException(403, 'This session is outside your assigned access.')
        if p.role == 'evaluator' and role == 'customer' and not cid:
            raise HTTPException(422, 'Enter a customer ID.')
        for key, session in list(self.items.items()):
            if session.uid == p.uid or monotonic() - session.touched > 3600:
                session.generation += 1
                self.items.pop(key)
        if len(self.items) >= 200:
            raise HTTPException(503, 'Session capacity reached.')
        key = token_urlsafe(24)
        self.items[key] = Session(p.uid, role, cid)
        return key, self.items[key]

    def get(self, key, p, generation=None):
        s = self.items.get(key)
        if not s or s.uid != p.uid or monotonic() - s.touched > 3600:
            raise HTTPException(404, 'Session unavailable. Start a new session.')
        if p.role != 'evaluator' and (s.role != p.role or s.customer_id != p.customer_id):
            raise HTTPException(403, 'Assigned access has changed.')
        if generation is not None and generation != s.generation:
            raise HTTPException(409, 'Conversation has been reset.')
        s.touched = monotonic()
        return s

    def reset(self, key, p):
        s = self.get(key, p)
        s.generation += 1
        s.booking_id = None
        s.history.clear()
        s.seen.clear()
        # A previous turn owns its busy flag until its finally block runs.
        return s.generation

sessions = Sessions()
