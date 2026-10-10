import asyncio
import pytest
from app import config, database
from app.assistant import local_plan, answer
from app.models import Plan, Filter
from app.sessions import Session

@pytest.mark.parametrize('question,group', [('List customer count by tier','customer_tier'), ('Count customers by city','city'), ('How many customers by KYC status?','kyc_status'), ('Show number of customers','none')])
def test_customer_counts_route_before_profile(question, group):
    plan = local_plan(question, Session('test','support_agent',None))
    assert plan.operation == 'customer_analytics'
    assert plan.group_by == group

def test_customer_counts_count_people_not_bookings():
    s = Session('test','support_agent',None)
    result = database.query(config.DB, s, Plan(operation='customer_analytics',group_by='customer_tier'))[0]
    with database.source(config.DB) as c:
        expected = [dict(r) for r in c.execute('SELECT customer_tier AS group_value,COUNT(*) AS value FROM customers GROUP BY customer_tier ORDER BY value DESC')]
    assert result['rows'] == expected
    assert sum(r['value'] for r in result['rows']) == 200
    assert set(result['rows'][0]) == {'group_value','value'}
    for alias in ['BLR','Bangalore','Bengaluru']:
        rows = database.query(config.DB,s,Plan(operation='customer_analytics',filters=[Filter(field='city',value=alias)]))[0]['rows']
        assert rows == [{'value':164}]

def test_customer_summary_is_support_only_and_bounded():
    with pytest.raises(PermissionError):
        database.query(config.DB,Session('test','customer','CUST0001'),Plan(operation='customer_analytics'))
    for plan in [Plan(operation='customer_analytics',metric='revenue'), Plan(operation='customer_analytics',group_by='hub_name'), Plan(operation='customer_analytics',filters=[Filter(field='model',value='Ola')])]:
        with pytest.raises(ValueError):
            database.query(config.DB,Session('test','support_agent',None),plan)
    assert local_plan('Count customers by tier in Bengaluru',Session('test','support_agent',None)) is None
    assert local_plan('What is CUST0001 tier?',Session('test','support_agent',None)).operation == 'profile'

def test_screenshot_question_completes_with_sql_evidence():
    async def emit(event):
        events.append(event)
    events=[]
    result=asyncio.run(answer('List customer count by tier',Session('test','support_agent',None),None,emit,0))
    assert result['state']=='answered'
    assert result['operation']=='customer_analytics'
    assert result['evidence'][0]['kind']=='sql'
    assert 'FROM customers' in result['evidence'][0]['sql']
    assert any(e['worker']=='Analytics' and e['status']=='completed' for e in events)
    result=asyncio.run(answer('List customer count by tier',Session('test','customer','CUST0001'),None,emit,0))
    assert result['state']=='refused' and not result['evidence']
