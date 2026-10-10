import pytest
from app.provider import Provider

@pytest.fixture(autouse=True)
def no_live_model_calls(monkeypatch):
    # Automated verification never consumes the event endpoint/rate budget.
    monkeypatch.setattr(Provider, 'configured', lambda self: False)
