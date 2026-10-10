import asyncio
from app import config, database
from app.assistant import answer, local_plan, verify_claims
from app.models import Explanation, Claim
from app.policies import Policies
from app.sessions import Session

def test_followup_and_cross_customer_refusal():
    s = Session('a','customer','CUST0001',booking_id='B-0001')
    assert local_plan('What about its refund?',s).booking_id == 'B-0001'
    events=[]
    async def emit(x): events.append(x)
    r = asyncio.run(answer('Show CUST0002 bookings',s,Policies(config.DATA),emit,0))
    assert r['state']=='refused' and not r['evidence']

def test_filtered_language_is_not_silently_dropped():
    s=Session('a','customer','CUST0001')
    p=local_plan('Show my upcoming bookings',s)
    assert p.filters[0].value=='UPC'
    assert local_plan('Show my bookings in July at Koramangala',s) is None

def test_scan_annexures_are_present_and_cited():
    policies=Policies(config.DATA)
    assert len(policies.valid)==5
    pages=policies.retrieve('refund','refund')
    assert any(p['id']=='PDF-refund_v2-2' and '48 hours' in p['excerpt'] for p in pages)
    assert any(p['id']=='PDF-penalty-3' and 'GOLD 30' in p['excerpt'] for p in policies.pages_for('penalty'))

def test_citation_and_critical_value_rejection():
    evidence=[dict(id='SQL-a',kind='sql',rows=[dict(amount='100.00')])]
    assert verify_claims(Explanation(claims=[Claim(text='Recorded amount is 100.00',citations=['SQL-a'])]),evidence)
    assert not verify_claims(Explanation(claims=[Claim(text='Recorded amount is 900.00',citations=['SQL-a'])]),evidence)
    assert not verify_claims(Explanation(claims=[Claim(text='Recorded amount is 100.00',citations=['SQL-z'])]),evidence)

def test_real_refund_turn_has_sql_pdf_formula():
    with database.source(config.DB) as c:
        b=c.execute("SELECT booking_id,customer_id FROM bookings WHERE booking_status='CNL_U' LIMIT 1").fetchone()
    s=Session('c','customer',b['customer_id'])
    events=[]
    async def emit(x): events.append(x)
    r=asyncio.run(answer('Explain refund for '+b['booking_id'],s,Policies(config.DATA),emit,0))
    assert r['state']=='answered'
    assert {e['kind'] for e in r['evidence']}=={'sql','pdf','calculation'}
    assert any(e['worker']=='Charges' and e['status']=='completed' for e in events)
    assert s.booking_id==b['booking_id']
