"""Fixed read-only dashboard queries. Session authorization happens before any query."""
from datetime import date, datetime, time, timedelta, timezone
from fastapi import HTTPException
from . import config, database

BOOKING_STATUSES = ('UPC', 'ONG', 'CMP', 'CNL_U', 'CNL_S', 'NSH')
PAYMENT_TYPES = ('BOOKING', 'DEPOSIT', 'PENALTY', 'REFUND')
PAYMENT_STATUSES = ('SUCCESS', 'FAILED', 'PENDING')
BOOKING_COLUMNS = '''b.booking_id,b.customer_id,b.vehicle_id,v.model,v.vehicle_type,v.hub_name,
    b.scheduled_start,b.scheduled_end,b.actual_return_at,b.booking_status,
    CASE WHEN b.actual_return_at>b.scheduled_end THEN 1 ELSE 0 END AS late_return,
    EXISTS(SELECT 1 FROM payments flag WHERE flag.booking_id=b.booking_id
        AND flag.payment_status IN ('FAILED','PENDING')) AS payment_attention'''
JOIN = ' FROM bookings b JOIN vehicles v ON v.vehicle_id=b.vehicle_id'
PAYMENT_COLUMNS = 'payment_id,booking_id,payment_type,amount,gst_amount,payment_method,payment_status,paid_at'
DAMAGE_COLUMNS = 'report_id,booking_id,vehicle_id,damage_category,severity,assessed_cost,claim_status,reported_by,reported_at'

class Queries:
    def __init__(self, c, scope):
        self.c, self.scope, self.evidence = c, scope, []
    def run(self, sql, args=(), cap=100):
        evidence = database.execute(self.c, sql, list(args), self.scope, cap=cap)
        self.evidence.append(evidence)
        return evidence['rows']
    def result(self, **data):
        return {**data, 'timezone': 'Asia/Kolkata', 'currency': 'INR', 'evidence': self.evidence}

def filters(items):
    clauses, args = [], []
    for column, value in items:
        if value:
            clauses.append(column + '=?')
            args.append(value)
    return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), args

def mask_name(value):
    return ' '.join(word[:1] + '***' for word in (value or '').split())

def customers(kyc='', tier='', city='', offset=0):
    # Customer PII is read only inside the existing protected profile store.
    with database.private_store(config.DB) as c:
        q = Queries(c, 'Support dashboard: masked customer directory; contact and identity fields excluded')
        where, args = filters([('kyc_status', kyc), ('customer_tier', tier), ('city', city)])
        total = q.run('SELECT COUNT(*) AS total FROM customers' + where, args)[0]['total']
        kyc_counts = q.run('SELECT kyc_status AS label,COUNT(*) AS count FROM customers' + where + ' GROUP BY kyc_status', args)
        tiers = q.run('SELECT customer_tier AS label,COUNT(*) AS count FROM customers' + where + ' GROUP BY customer_tier', args)
        cities = q.run('SELECT city AS label,COUNT(*) AS count FROM customers' + where + ' GROUP BY city ORDER BY count DESC', args)
        options = q.run('SELECT DISTINCT city FROM customers ORDER BY city')
        rows = q.run('SELECT customer_id,full_name,city,customer_tier,kyc_status,created_at FROM customers' + where + ' ORDER BY customer_id LIMIT 100 OFFSET ?', [*args, offset])
        for row in rows:
            row['full_name'] = mask_name(row['full_name'])
        q.evidence[-1]['redaction'] = 'Names are masked after query execution; contact and identity fields were not selected.'
        return q.result(total=total, kyc=kyc_counts, tiers=tiers, cities=cities,
                        city_options=[r['city'] for r in options], rows=rows, offset=offset, page_size=100)

def hubs(hub=''):
    with database.source(config.DB) as c:
        q = Queries(c, 'Support dashboard: fleet and hub operations')
        where, args = filters([('v.hub_name', hub)])
        rows = q.run('''SELECT v.vehicle_id,v.registration_no,v.vehicle_type,v.model,v.hub_name,
            v.hourly_rate,v.daily_rate,v.battery_capacity_kwh,v.status,v.commissioned_on,
            EXISTS(SELECT 1 FROM bookings b WHERE b.vehicle_id=v.vehicle_id AND b.booking_status='ONG') AS ongoing_booking
            FROM vehicles v''' + where + ' ORDER BY v.hub_name,v.vehicle_type,v.model,v.vehicle_id', args, cap=1000)
        counts = q.run('SELECT v.hub_name,v.status,COUNT(*) AS count FROM vehicles v' + where + ' GROUP BY v.hub_name,v.status', args)
        options = q.run('SELECT DISTINCT hub_name FROM vehicles ORDER BY hub_name')
        return q.result(rows=rows, counts=counts, total=len(rows), hub_options=[r['hub_name'] for r in options])

def date_bounds(start, end):
    if start and end and start > end:
        raise HTTPException(422, 'The start date must not be after the end date.')
    ist = timezone(timedelta(hours=5, minutes=30))
    def utc(d):
        return datetime.combine(d, time.min, ist).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return utc(start) if start else None, utc(end + timedelta(days=1)) if end else None

def bookings(status='', start=None, end=None, hub='', payment_type='', payment_status='', customer_id='', offset=0):
    lower, upper = date_bounds(start, end)
    where, args = filters([('b.booking_status', status), ('v.hub_name', hub), ('b.customer_id', customer_id)])
    clauses = [where[7:]] if where else []
    for clause, value in [('b.scheduled_start>=?', lower), ('b.scheduled_start<?', upper)]:
        if value:
            clauses.append(clause)
            args.append(value)
    payment_where, payment_args = filters([('pf.payment_type', payment_type), ('pf.payment_status', payment_status)])
    if payment_where:
        clauses.append('EXISTS(SELECT 1 FROM payments pf WHERE pf.booking_id=b.booking_id AND ' + payment_where[7:] + ')')
        args.extend(payment_args)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with database.source(config.DB) as c:
        q = Queries(c, 'Support dashboard: bookings and payments; no customer contact fields')
        total = q.run('SELECT COUNT(*) AS total' + JOIN + where, args)[0]['total']
        counts = q.run('SELECT b.booking_status AS label,COUNT(*) AS count' + JOIN + where + ' GROUP BY b.booking_status', args)
        rows = q.run('SELECT ' + BOOKING_COLUMNS + JOIN + where + ' ORDER BY b.scheduled_start DESC,b.booking_id LIMIT 100 OFFSET ?', [*args, offset])
        totals_where, totals_args = filters([('p.payment_type', payment_type), ('p.payment_status', payment_status)])
        payment_clause = (' AND ' if where else ' WHERE ') + totals_where[7:] if totals_where else ''
        totals = q.run('''SELECT p.payment_type,p.payment_status,COUNT(*) AS transactions,
            ROUND(SUM(p.amount),2) AS amount_ex_gst,ROUND(SUM(p.gst_amount),2) AS gst_amount
            FROM payments p JOIN bookings b ON b.booking_id=p.booking_id JOIN vehicles v ON v.vehicle_id=b.vehicle_id'''
            + where + payment_clause + ' GROUP BY p.payment_type,p.payment_status', [*args, *totals_args])
        flags = q.run('''SELECT SUM(CASE WHEN b.actual_return_at>b.scheduled_end THEN 1 ELSE 0 END) AS late_returns,
            SUM(EXISTS(SELECT 1 FROM payments f WHERE f.booking_id=b.booking_id AND f.payment_status IN ('FAILED','PENDING'))) AS payment_attention'''
            + JOIN + where, args)[0]
        options = q.run('SELECT DISTINCT hub_name FROM vehicles ORDER BY hub_name')
        return q.result(total=total, counts=counts, rows=rows, payment_totals=totals, flags=flags,
                        hub_options=[r['hub_name'] for r in options], offset=offset, page_size=100)

def booking_detail(booking_id, customer_id=None):
    with database.source(config.DB) as c:
        q = Queries(c, 'Own booking details: ' + customer_id if customer_id else 'Support dashboard: one booking details')
        where = ' WHERE b.booking_id=?' + (' AND b.customer_id=?' if customer_id else '')
        args = [booking_id, customer_id] if customer_id else [booking_id]
        rows = q.run('SELECT ' + BOOKING_COLUMNS + JOIN + where, args)
        if not rows:
            raise HTTPException(404, 'Booking unavailable for this session.')
        payments = q.run('SELECT ' + ','.join('p.' + col for col in PAYMENT_COLUMNS.split(',')) +
            ' FROM payments p JOIN bookings b ON b.booking_id=p.booking_id' + where + ' ORDER BY p.paid_at,p.payment_id', args, cap=1000)
        damage = q.run('SELECT ' + ','.join('d.' + col for col in DAMAGE_COLUMNS.split(',')) +
            ' FROM damage_reports d JOIN bookings b ON b.booking_id=d.booking_id' + where + ' ORDER BY d.reported_at', args, cap=1000)
        return q.result(booking=rows[0], payments=payments, refunds=[r for r in payments if r['payment_type']=='REFUND'], damage=damage)

def own_bookings(customer_id, tab='upcoming'):
    if not customer_id:
        raise HTTPException(403, 'An administrator must link your RideWise customer record before bookings are available.')
    codes = {'upcoming': ('UPC',), 'ongoing': ('ONG',), 'past': ('CMP','NSH'), 'cancelled': ('CNL_U','CNL_S')}[tab]
    with database.source(config.DB) as c:
        q = Queries(c, 'Own customer bookings: ' + customer_id)
        counts = q.run('SELECT booking_status AS label,COUNT(*) AS count FROM bookings WHERE customer_id=? GROUP BY booking_status', [customer_id])
        rows = q.run('SELECT ' + BOOKING_COLUMNS + JOIN + ' WHERE b.customer_id=? AND b.booking_status IN (' + ','.join('?' for _ in codes) + ') ORDER BY b.scheduled_start DESC', [customer_id, *codes], cap=1000)
        return q.result(rows=rows, counts=counts, total=len(rows), tab=tab)

def damage(claim_status='', category='', severity='', offset=0):
    with database.source(config.DB) as c:
        q = Queries(c, 'Support dashboard: damage claims; descriptions require explicit detail lookup')
        where, args = filters([('claim_status', claim_status), ('damage_category', category), ('severity', severity)])
        total = q.run('SELECT COUNT(*) AS total FROM damage_reports' + where, args)[0]['total']
        claims = q.run('SELECT claim_status AS label,COUNT(*) AS count,ROUND(SUM(assessed_cost),2) AS assessed_cost FROM damage_reports' + where + ' GROUP BY claim_status', args)
        categories = q.run('SELECT damage_category AS label,COUNT(*) AS count FROM damage_reports' + where + ' GROUP BY damage_category', args)
        severities = q.run('SELECT severity AS label,COUNT(*) AS count FROM damage_reports' + where + ' GROUP BY severity', args)
        rows = q.run('SELECT ' + DAMAGE_COLUMNS + ' FROM damage_reports' + where + ' ORDER BY reported_at DESC,report_id LIMIT 100 OFFSET ?', [*args, offset])
        return q.result(total=total, claims=claims, categories=categories, severities=severities, rows=rows, offset=offset, page_size=100)

def damage_detail(report_id):
    with database.source(config.DB) as c:
        q = Queries(c, 'Support dashboard: explicit damage description lookup')
        rows = q.run('SELECT ' + DAMAGE_COLUMNS + ',description FROM damage_reports WHERE report_id=?', [report_id])
        if not rows:
            raise HTTPException(404, 'Damage report unavailable.')
        return q.result(report=rows[0])
