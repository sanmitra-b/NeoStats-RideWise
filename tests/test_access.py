import asyncio
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app import config, database, auth
from app.main import app
from app.models import Principal, Plan, Filter
from app.sessions import Session, Sessions

@pytest.fixture
def cid():
    with database.source(config.DB) as c:
        return c.execute('SELECT customer_id FROM customers ORDER BY customer_id').fetchone()[0]

def test_projection_excludes_pii_and_other_customer(cid):
    s = Session('test','customer',cid)
    with database.projection(config.DB,s) as c:
        assert c.execute('SELECT COUNT(*) FROM bookings WHERE customer_id!=?', [cid]).fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError): c.execute('SELECT * FROM customers')
        with pytest.raises(sqlite3.OperationalError): c.execute('SELECT full_name FROM customer_attributes')
        with pytest.raises(sqlite3.OperationalError): c.execute('DELETE FROM bookings')

def test_support_projection_omits_raw_pii():
    with database.projection(config.DB,Session('s','support_agent',None)) as c:
        assert c.execute('SELECT COUNT(*) FROM bookings').fetchone()[0] > 0
        with pytest.raises(sqlite3.OperationalError): c.execute('SELECT email FROM customers')

def test_scope_rechecks_and_injection_binding(cid):
    s = Session('t','customer',cid)
    with pytest.raises(PermissionError): database.query(config.DB,s,Plan(operation='bookings',customer_id='CUST9999'))
    with pytest.raises(PermissionError): database.query(config.DB,s,Plan(operation='analytics'))
    with pytest.raises(PermissionError): database.profile(config.DB,s,'CUST9999',True)
    e = database.query(config.DB,s,Plan(operation='bookings',filters=[Filter(field='booking_status',value="CMP' OR 1=1 --")]))
    assert not e[0]['rows']
    assert "CMP' OR 1=1 --" not in e[0]['sql']

def test_analytics_avoids_child_fanout():
    s = Session('s','support_agent',None)
    result = database.query(config.DB,s,Plan(operation='analytics',metric='revenue'))[0]['rows'][0]['value']
    with database.source(config.DB) as c:
        expected = c.execute("SELECT ROUND(SUM(amount),2) FROM payments WHERE payment_status='SUCCESS' AND payment_type='BOOKING'").fetchone()[0]
    assert result == expected

def test_payment_status_filters_and_vehicles():
    s=Session('s','support_agent',None)
    result=database.query(config.DB,s,Plan(operation='payments',filters=[Filter(field='payment_status',value='FAILED')]))
    assert result[0]['rows'] and all(r['payment_status']=='FAILED' for r in result[0]['rows'])
    result=database.query(config.DB,s,Plan(operation='vehicles',filters=[Filter(field='status',value='ACTIVE')]))
    assert result[0]['rows'] and all(r['status']=='ACTIVE' for r in result[0]['rows'])

def test_stream_and_protected_pdf_routes(cid):
    p=Principal(uid='stream-evaluator',role='evaluator')
    app.dependency_overrides[auth.principal]=lambda:p
    try:
        with TestClient(app) as c:
            s=c.post('/api/session',json={'role':'customer','customer_id':cid}).json()
            r=c.post('/api/chat/stream',json=dict(session_id=s['session_id'],generation=0,request_id='stream-check',message='Show my bookings'))
            assert r.status_code==200 and '"type": "final"' in r.text
            assert '"worker": "Booking / Payments"' in r.text
            pdf=c.get('/api/policies/refund_v2')
            assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
            assert c.get('/api/policies/ridewise.db').status_code==404
    finally:
        app.dependency_overrides.clear()

def test_unconfigured_auth_and_cross_origin_fail_closed():
    with TestClient(app) as c:
        assert c.get('/health').status_code == 200
        assert c.get('/api/me').status_code == 401
        assert c.post('/api/session',json={'role':'support_agent'},headers={'Origin':'https://evil.example'}).status_code == 403
        assert c.get('/static/../.env').status_code != 200
        assert c.get('/api/policies/../../ridewise.db').status_code != 200

def test_session_uid_generation_isolation(cid):
    sessions = Sessions()
    p = Principal(uid='a',role='customer',customer_id=cid)
    key,s = sessions.create(p,'customer',cid)
    with pytest.raises(Exception): sessions.get(key,Principal(uid='b',role='customer',customer_id=cid))
    s.booking_id = 'B-0001'; s.history.append('previous')
    sessions.reset(key,p)
    assert not s.history and not s.booking_id
    with pytest.raises(Exception): sessions.get(key,p,0)

def test_evaluator_selection_and_api_authorisation(cid):
    p = Principal(uid='eval',role='evaluator')
    app.dependency_overrides[auth.principal] = lambda: p
    try:
        with TestClient(app) as c:
            s = c.post('/api/session',json={'role':'customer','customer_id':cid}).json()
            body = dict(session_id=s['session_id'],generation=0,request_id='test-request',message='Show my bookings')
            r = c.post('/api/chat',json=body)
            assert r.status_code == 200
            assert r.json()['evidence'][0]['kind'] == 'sql'
            assert all(x['customer_id']==cid for x in r.json()['evidence'][0]['rows'])
            assert c.post('/api/chat',json=body).status_code == 409
            assert c.post('/api/conversation/'+s['session_id']+'/reset').json()['generation'] == 1
            assert c.post('/api/chat',json={**body,'request_id':'later'}).status_code == 409
    finally:
        app.dependency_overrides.clear()
