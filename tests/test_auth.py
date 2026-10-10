import pytest
from fastapi import HTTPException
from app import auth

def test_verified_roles_and_clock_tolerance(monkeypatch):
    monkeypatch.setattr(auth, 'configured', lambda: True)
    monkeypatch.setattr(auth.firebase_admin, 'get_app', lambda: object())
    received = {}
    def verify(token, **kwargs):
        received.update(kwargs)
        return {'uid': 'trusted-evaluator', 'role': 'evaluator'}
    monkeypatch.setattr(auth.auth, 'verify_id_token', verify)
    assert auth.verify('controlled-token').role == 'evaluator'
    assert received == {'check_revoked': True, 'clock_skew_seconds': 30}

def test_missing_trusted_role_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, 'configured', lambda: True)
    monkeypatch.setattr(auth.firebase_admin, 'get_app', lambda: object())
    monkeypatch.setattr(auth.auth, 'verify_id_token', lambda *a, **k: {'uid': 'unassigned'})
    with pytest.raises(HTTPException) as error:
        auth.verify('controlled-token')
    assert error.value.status_code == 401
