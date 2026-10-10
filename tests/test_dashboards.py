from datetime import date
import json
import pytest
from fastapi.testclient import TestClient
from app import auth, config, database, dashboards
from app.main import app
from app.models import Principal

@pytest.fixture
def client():
    app.dependency_overrides[auth.principal] = lambda: Principal(uid='dashboard-test', role='evaluator')
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()

def session(client, role='support_agent', cid=None):
    response = client.post('/api/session', json={'role':role,'customer_id':cid})
    assert response.status_code == 200
    return response.json()['session_id']

def test_support_endpoints_denied_in_customer_session(client):
    key = session(client, 'customer', 'CUST0001')
    for path in ['/api/dashboard/customers','/api/dashboard/hubs','/api/dashboard/bookings',
                 '/api/dashboard/damage','/api/dashboard/bookings/B-0001','/api/dashboard/damage/DMG0001']:
        assert client.get(path,params={'session_id':key}).status_code == 403
    app.dependency_overrides[auth.principal] = lambda: Principal(uid='another-user',role='evaluator')
    assert client.get('/api/my/bookings',params={'session_id':key}).status_code == 404

def test_customer_bookings_and_detail_are_own_only(client):
    key = session(client, 'customer', 'CUST0001')
    for tab in ['upcoming','ongoing','past','cancelled']:
        response = client.get('/api/my/bookings',params={'session_id':key,'tab':tab,'customer_id':'CUST0002'})
        assert response.status_code == 200
        assert all(r['customer_id']=='CUST0001' for r in response.json()['rows'])
    with database.source(config.DB) as c:
        own=c.execute('SELECT booking_id FROM bookings WHERE customer_id=? LIMIT 1',['CUST0001']).fetchone()[0]
        other=c.execute('SELECT booking_id FROM bookings WHERE customer_id<>? LIMIT 1',['CUST0001']).fetchone()[0]
    details=client.get('/api/my/bookings/'+own,params={'session_id':key}).json()
    assert details['booking']['customer_id']=='CUST0001'
    assert all(r['booking_id']==own for r in details['payments']+details['damage'])
    assert all(r['payment_type']=='REFUND' for r in details['refunds'])
    assert client.get('/api/my/bookings/'+other,params={'session_id':key}).status_code==404
    key=session(client)
    assert client.get('/api/my/bookings',params={'session_id':key}).status_code==403

def test_unlinked_customer_cannot_fetch_bookings(client):
    app.dependency_overrides[auth.principal]=lambda:Principal(uid='unlinked',role='customer')
    key=session(client,'customer')
    assert client.get('/api/my/bookings',params={'session_id':key}).status_code==403

def test_customers_counts_filters_and_masked_evidence(client):
    key=session(client)
    d=client.get('/api/dashboard/customers',params={'session_id':key}).json()
    with database.source(config.DB) as c:
        total=c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        original_names=[r[0] for r in c.execute('SELECT full_name FROM customers')]
    assert d['total']==total
    assert sum(r['count'] for r in d['kyc'])==total
    assert sum(r['count'] for r in d['tiers'])==total
    serialized=json.dumps(d)
    for forbidden in ['phone','email','date_of_birth','driving_license_no']:
        assert forbidden not in serialized
    assert all(name not in serialized for name in original_names)
    assert all('***' in r['full_name'] for r in d['rows'])
    filtered=client.get('/api/dashboard/customers',params={'session_id':key,'kyc':'VERIFIED','tier':'GOLD'}).json()
    assert all(r['kyc_status']=='VERIFIED' and r['customer_tier']=='GOLD' for r in filtered['rows'])
    assert client.get('/api/dashboard/customers',params={'session_id':key,'city':"' OR 1=1 --"}).json()['total']==0

def test_hub_grouping_and_ongoing_flags(client):
    key=session(client)
    d=client.get('/api/dashboard/hubs',params={'session_id':key}).json()
    assert sum(r['count'] for r in d['counts'])==d['total']==len(d['rows'])
    hub=d['hub_options'][0]
    filtered=client.get('/api/dashboard/hubs',params={'session_id':key,'hub':hub}).json()
    assert all(r['hub_name']==hub for r in filtered['rows'])
    with database.source(config.DB) as c:
        busy={r[0] for r in c.execute("SELECT DISTINCT vehicle_id FROM bookings WHERE booking_status='ONG'")}
    assert all(bool(r['ongoing_booking'])==(r['vehicle_id'] in busy) for r in d['rows'])

def test_booking_totals_not_multiplied_and_payment_filters(client):
    key=session(client)
    d=client.get('/api/dashboard/bookings',params={'session_id':key}).json()
    with database.source(config.DB) as c:
        expected=c.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]
        totals={(r[0],r[1]):r[2:] for r in c.execute('SELECT payment_type,payment_status,COUNT(*),ROUND(SUM(amount),2),ROUND(SUM(gst_amount),2) FROM payments GROUP BY payment_type,payment_status')}
    assert d['total']==expected==sum(r['count'] for r in d['counts'])
    assert { (r['payment_type'],r['payment_status']):(r['transactions'],r['amount_ex_gst'],r['gst_amount']) for r in d['payment_totals']}==totals
    page2=client.get('/api/dashboard/bookings',params={'session_id':key,'offset':100}).json()
    assert d['payment_totals']==page2['payment_totals']
    filtered=client.get('/api/dashboard/bookings',params={'session_id':key,'payment_type':'REFUND','payment_status':'SUCCESS'}).json()
    assert all(r['payment_type']=='REFUND' and r['payment_status']=='SUCCESS' and r['amount_ex_gst']<=0 for r in filtered['payment_totals'])
    for row in filtered['rows'][:5]:
        detail=client.get('/api/dashboard/bookings/'+row['booking_id'],params={'session_id':key}).json()
        assert any(p['payment_type']=='REFUND' and p['payment_status']=='SUCCESS' for p in detail['payments'])

def test_ist_date_bounds_and_invalid_filters(client):
    assert dashboards.date_bounds(date(2026,7,1),date(2026,7,1))==('2026-06-30 18:30:00','2026-07-01 18:30:00')
    key=session(client)
    assert client.get('/api/dashboard/bookings',params={'session_id':key,'from':'2026-07-02','to':'2026-07-01'}).status_code==422
    assert client.get('/api/dashboard/bookings',params={'session_id':key,'status':"' OR 1=1"}).status_code==422
    d=client.get('/api/dashboard/bookings',params={'session_id':key,'from':'2026-07-01','to':'2026-07-01'}).json()
    assert all('2026-06-30 18:30:00'<=r['scheduled_start']<'2026-07-01 18:30:00' for r in d['rows'])

def test_damage_status_breakdowns_and_explicit_description(client):
    key=session(client)
    d=client.get('/api/dashboard/damage',params={'session_id':key,'claim_status':'OPEN'}).json()
    assert all(r['claim_status']=='OPEN' and 'description' not in r for r in d['rows'])
    assert sum(r['count'] for r in d['categories'])==d['total']
    assert sum(r['count'] for r in d['severities'])==d['total']
    with database.source(config.DB) as c:
        total=c.execute("SELECT ROUND(SUM(assessed_cost),2) FROM damage_reports WHERE claim_status='OPEN'").fetchone()[0]
    assert d['claims'][0]['assessed_cost']==total
    detail=client.get('/api/dashboard/damage/'+d['rows'][0]['report_id'],params={'session_id':key}).json()
    assert 'description' in detail['report']

def test_source_is_read_only_and_role_changes_block_dashboard(client):
    key=session(client)
    app.dependency_overrides[auth.principal]=lambda:Principal(uid='dashboard-test',role='customer',customer_id='CUST0001')
    assert client.get('/api/dashboard/customers',params={'session_id':key}).status_code==403
    with database.source(config.DB) as c:
        with pytest.raises(Exception, match='readonly'):
            c.execute("UPDATE vehicles SET status='RETIRED'")
