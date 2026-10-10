import pytest
from app import config, database, dashboards
from app.locations import canonical_city, normalize_question
from app.models import Plan, Filter
from app.sessions import Session

@pytest.mark.parametrize('alias', ['Bangalore', 'BLR', 'Bengaluru', ' bangalore ', ' bLr '])
def test_city_alias_filters_merge_original_variants(alias):
    with database.source(config.DB) as c:
        expected = c.execute("SELECT COUNT(*) FROM customers WHERE lower(trim(city)) IN ('bangalore','bengaluru','blr')").fetchone()[0]
    result = dashboards.customers(city=alias)
    assert result['total'] == expected == 164
    assert result['cities'] == [{'label': 'Bengaluru', 'count': expected}]
    assert all(row['city'] == 'Bengaluru' for row in result['rows'])
    assert not {'Bangalore', 'BLR', 'bangalore '}.intersection(result['city_options'])
    assert sum(row['count'] for row in dashboards.customers()['cities']) == 200

def test_booking_analytics_normalizes_city_and_keeps_scope():
    support = Session('test', 'support_agent', None)
    results = []
    for alias in ['BLR', 'Bangalore', 'Bengaluru']:
        result = database.query(config.DB, support, Plan(operation='analytics', filters=[Filter(field='city', value=alias)]))
        assert result[0]['parameters'] == ['Bengaluru']
        results.append(result[0]['rows'])
    assert results[0] == results[1] == results[2]
    customer = Session('test', 'customer', 'CUST0001')
    with pytest.raises(PermissionError):
        database.query(config.DB, customer, Plan(operation='analytics', filters=[Filter(field='city',value='BLR')]))
    bookings = database.query(config.DB, customer, Plan(operation='bookings', filters=[Filter(field='city',value='BLR')]))
    assert all(row['customer_id'] == 'CUST0001' for row in bookings[0]['rows'])

def test_city_grouping_and_unknown_names_are_not_fuzzy_matched():
    results = database.query(config.DB, Session('test','support_agent',None), Plan(operation='analytics',group_by='city'))
    assert 'Bengaluru' in {r['group_value'] for r in results[0]['rows']}
    assert not {'BLR','Bangalore','bangalore '}.intersection(r['group_value'] for r in results[0]['rows'])
    assert canonical_city('Mangaluru') == 'Mangaluru'
    assert canonical_city('Bangalore Rural') == 'Bangalore Rural'
    assert normalize_question('BLR and Bangalore, not BLR123') == 'Bengaluru and Bengaluru, not BLR123'
    assert dashboards.customers(city="BLR' OR 1=1 --")['total'] == 0
