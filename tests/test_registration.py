from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app import auth, config, database
from app.main import app
from app.models import Principal, Plan
from app.sessions import Session

def test_default_customer_assignment_preserves_other_claims(monkeypatch):
    monkeypatch.setattr(auth.auth, 'get_user', lambda uid: SimpleNamespace(uid=uid,custom_claims={'preexisting':'value'}))
    changes=[]
    monkeypatch.setattr(auth.auth, 'set_custom_user_claims', lambda uid,claims: changes.append((uid,claims)))
    result=auth.register_customer({'uid':'new-user'})
    assert result=={'role':'customer','refresh_required':True}
    assert changes==[('new-user',{'preexisting':'value','role':'customer'})]

@pytest.mark.parametrize('role',['support_agent','evaluator','customer'])
def test_bootstrap_never_overwrites_assigned_role(monkeypatch,role):
    monkeypatch.setattr(auth.auth, 'get_user', lambda uid: SimpleNamespace(uid=uid,custom_claims={'role':role}))
    monkeypatch.setattr(auth.auth, 'set_custom_user_claims', lambda *a: pytest.fail('Existing role must not be replaced'))
    assert auth.register_customer({'uid':'trusted','role':role})['role']==role

def test_unlinked_customer_cannot_retrieve_any_business_records():
    s=Session('new','customer',None)
    with pytest.raises(PermissionError):
        with database.projection(config.DB,s): pass
    with pytest.raises(PermissionError): database.query(config.DB,s,Plan(operation='bookings'))
    with pytest.raises(PermissionError): database.profile(config.DB,s,'CUST0001',True)

def test_signup_role_payload_is_rejected_and_policy_session_safe(monkeypatch):
    p=Principal(uid='new-account',role='customer',customer_id=None)
    app.dependency_overrides[auth.principal]=lambda:p
    app.dependency_overrides[auth.identity]=lambda:{'uid':'new-account'}
    monkeypatch.setattr(auth,'register_customer',lambda claims:{'role':'customer','refresh_required':True})
    try:
        with TestClient(app) as c:
            headers=c.get('/').headers
            assert 'https://apis.google.com' in headers['content-security-policy']
            assert headers['cross-origin-opener-policy']=='same-origin-allow-popups'
            assert c.post('/api/account/bootstrap',json={'role':'support_agent'}).status_code==422
            assert c.post('/api/account/bootstrap',json={}).json()['role']=='customer'
            s=c.post('/api/session',json={'role':'customer'}).json()
            assert s['role']=='customer' and s['customer_id'] is None
            assert c.get('/api/policies').status_code==200
            assert c.post('/api/session',json={'role':'customer','customer_id':'CUST0001'}).status_code==403
            assert c.post('/api/session',json={'role':'support_agent'}).status_code==403
            body=dict(session_id=s['session_id'],generation=0,request_id='unlinked-lookup',message='Show my bookings')
            answer=c.post('/api/chat',json=body).json()
            assert answer['state']=='refused' and not answer['evidence']
    finally:
        app.dependency_overrides.clear()
