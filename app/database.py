"""Immutable source, scoped operational projection, isolated private PII store."""
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .models import Plan

TABLES = ('vehicles', 'bookings', 'payments', 'damage_reports')
EXCLUDED = {'payments': {'transaction_ref', 'remarks'}, 'damage_reports': {'description'}}

@contextmanager
def source(path):
    c = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    c.enable_load_extension(False)
    try:
        yield c
    finally:
        c.close()

@contextmanager
def private_store(path):
    # This handle never reaches a planner or general query executor.
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    with source(path) as original:
        schema = original.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='customers'").fetchone()[0]
        c.execute(schema)
        rows = original.execute('SELECT * FROM customers').fetchall()
        c.executemany('INSERT INTO customers VALUES (' + ','.join('?' for _ in rows[0]) + ')', [tuple(r) for r in rows])
    c.execute('PRAGMA query_only=ON')
    try:
        yield c
    finally:
        c.close()

def customer_exists(path, cid):
    with source(path) as c:
        return c.execute('SELECT 1 FROM customers WHERE customer_id=?', (cid,)).fetchone() is not None

def profile(path, session, cid=None, contact=False):
    target = session.customer_id if session.role == 'customer' else cid
    if not target:
        raise ValueError('Specify a customer ID for a work-related profile lookup.')
    if session.role == 'customer' and cid and cid != target:
        raise PermissionError('Other customer information is not available.')
    columns = 'customer_id,customer_tier,kyc_status'
    if contact:
        columns += ',full_name,phone,email'
    sql = f'SELECT {columns} FROM customers WHERE customer_id = ?'
    with private_store(path) as c:
        evidence = execute(c, sql, [target], 'Protected profile service', cap=1)
    if contact and session.role == 'support_agent':
        for r in evidence['rows']:
            r['phone'] = '******' + r['phone'][-4:] if r['phone'] else None
            r['email'] = r['email'][:1] + '***@' + r['email'].split('@')[-1] if r['email'] else None
    evidence['sensitive'] = contact
    return evidence

@contextmanager
def projection(path, session):
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    with source(path) as original:
        scope = session.customer_id if session.role == 'customer' else None
        ids = [r[0] for r in original.execute('SELECT booking_id FROM bookings' + (' WHERE customer_id=?' if scope else ''), (scope,) if scope else ())]
        for table in TABLES:
            info = original.execute(f'PRAGMA table_info({table})').fetchall()
            cols = [r['name'] for r in info if r['name'] not in EXCLUDED.get(table, set())]
            c.execute(f'CREATE TABLE {table} (' + ','.join(f"{r['name']} {r['type']}" for r in info if r['name'] in cols) + ')')
            sql = f'SELECT {",".join(cols)} FROM {table}'
            args = []
            if scope:
                if table == 'vehicles':
                    sql += ' WHERE vehicle_id IN (SELECT vehicle_id FROM bookings WHERE customer_id=?)'
                    args = [scope]
                elif table == 'bookings':
                    sql += ' WHERE customer_id=?'
                    args = [scope]
                else:
                    sql += ' WHERE booking_id IN (' + ','.join('?' for _ in ids) + ')'
                    args = ids
            rows = original.execute(sql, args).fetchall()
            c.executemany(f'INSERT INTO {table} VALUES (' + ','.join('?' for _ in cols) + ')', [tuple(r) for r in rows])
        c.execute('CREATE TABLE customer_attributes (customer_id TEXT, customer_tier TEXT, kyc_status TEXT)')
        rows = original.execute('SELECT customer_id, customer_tier, kyc_status FROM customers' + (' WHERE customer_id=?' if scope else ''), [scope] if scope else []).fetchall()
        c.executemany('INSERT INTO customer_attributes VALUES (?,?,?)', [tuple(r) for r in rows])
    c.execute('PRAGMA query_only=ON')
    c.enable_load_extension(False)
    try:
        yield c
    finally:
        c.close()

def execute(c, sql, args, scope, cap=50):
    started = time.monotonic()
    c.set_progress_handler(lambda: int(time.monotonic() - started > 2), 1000)
    rows = c.execute(sql, args).fetchmany(cap + 1)
    c.set_progress_handler(None, 0)
    return {'id': 'SQL-' + uuid.uuid4().hex[:8], 'kind': 'sql', 'sql': sql,
            'parameters': args, 'scope': scope, 'rows': [dict(r) for r in rows[:cap]],
            'truncated': len(rows) > cap, 'limit': cap, 'duration_ms': round((time.monotonic() - started) * 1000, 1)}

BASE = ' FROM bookings b JOIN vehicles v ON v.vehicle_id=b.vehicle_id LEFT JOIN customer_attributes a ON a.customer_id=b.customer_id'
FIELDS = {f: 'b.' + f for f in ('booking_id', 'customer_id', 'vehicle_id', 'booking_status', 'scheduled_start', 'scheduled_end', 'booked_at')}
FIELDS.update({f: 'v.' + f for f in ('hub_name', 'vehicle_type', 'model')})
FIELDS.update({f: 'a.' + f for f in ('customer_tier', 'kyc_status')})

def where(plan, fields=FIELDS):
    pieces, args = [], []
    filters = list(plan.filters)
    for f in filters:
        if f.field not in fields:
            raise ValueError('That filter does not apply to this operation.')
        col = fields[f.field]
        op = {'eq': '=', 'gte': '>=', 'lte': '<=', 'contains': 'LIKE'}[f.op]
        if f.op == 'contains':
            pieces.append(f"{col} LIKE ? ESCAPE '\\'")
            args.append('%' + f.value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
        else:
            pieces.append(f'{col} {op} ?')
            args.append(f.value)
    for field in ('booking_id', 'customer_id'):
        value = getattr(plan, field)
        if value and field in fields:
            pieces.append(fields[field] + ' = ?')
            args.append(value)
    return (' WHERE ' + ' AND '.join(pieces)) if pieces else '', args

def query(path, session, plan: Plan):
    if session.role == 'customer':
        if plan.customer_id and plan.customer_id != session.customer_id:
            raise PermissionError('Other customer information is not available.')
        if plan.operation in ('analytics', 'vehicles'):
            raise PermissionError('Internal operational information is restricted to support agents.')
        for f in plan.filters:
            if f.field == 'customer_id' and (f.op != 'eq' or f.value != session.customer_id):
                raise PermissionError('Other customer information is not available.')
    evidence = []
    scope = 'Own customer records: ' + session.customer_id if session.role == 'customer' else 'Support operational records; no personal customer fields'
    with projection(path, session) as c:
        if plan.operation == 'vehicles':
            fields = {f: f for f in ('vehicle_id', 'vehicle_type', 'hub_name', 'model', 'status')}
            w, args = where(plan, fields)
            evidence.append(execute(c, 'SELECT vehicle_id,vehicle_type,model,hub_name,hourly_rate,daily_rate,status FROM vehicles' + w + ' ORDER BY vehicle_id LIMIT 51', args, scope))
        elif plan.operation == 'analytics':
            # Aggregate each child table BEFORE joining: one row per booking.
            totals = " LEFT JOIN (SELECT booking_id,SUM(CASE WHEN payment_type='BOOKING' AND payment_status='SUCCESS' THEN amount ELSE 0 END) revenue,SUM(CASE WHEN payment_type='REFUND' AND payment_status='SUCCESS' THEN -(amount+gst_amount) ELSE 0 END) refunds,SUM(CASE WHEN payment_type='PENALTY' AND payment_status='SUCCESS' THEN amount+gst_amount ELSE 0 END) penalties FROM payments GROUP BY booking_id) p ON p.booking_id=b.booking_id"
            metric = {'count': 'COUNT(*)', 'revenue': 'ROUND(SUM(COALESCE(p.revenue,0)),2)', 'refunds': 'ROUND(SUM(COALESCE(p.refunds,0)),2)', 'penalties': 'ROUND(SUM(COALESCE(p.penalties,0)),2)', 'late_returns': 'SUM(CASE WHEN b.actual_return_at > b.scheduled_end THEN 1 ELSE 0 END)', 'utilization': "ROUND(SUM(CASE WHEN b.booking_status='CMP' THEN (julianday(b.actual_return_at)-julianday(b.scheduled_start))*24 ELSE 0 END),2)"}[plan.metric]
            group = "substr(b.scheduled_start,1,7)" if plan.group_by == 'month' else FIELDS.get(plan.group_by)
            w, args = where(plan)
            sql = 'SELECT ' + (group + ' AS group_value,' if group else '') + metric + ' AS value' + BASE + totals + w
            if group:
                sql += ' GROUP BY ' + group + ' ORDER BY value DESC LIMIT 51'
            evidence.append(execute(c, sql, args, scope))
        else:
            if not plan.booking_id and plan.operation in ('payments', 'damage'):
                table, alias = ('payments', 'p') if plan.operation == 'payments' else ('damage_reports', 'd')
                fields = dict(FIELDS)
                fields.update({f: alias + '.' + f for f in (('payment_status', 'payment_type') if alias == 'p' else ('claim_status', 'damage_category'))})
                w, args = where(plan, fields)
                return [execute(c, 'SELECT ' + alias + '.*,b.customer_id,v.hub_name' + BASE + f' JOIN {table} {alias} ON {alias}.booking_id=b.booking_id' + w + ' ORDER BY ' + alias + ('.paid_at' if alias == 'p' else '.reported_at') + ' DESC LIMIT 51', args, scope)]
            w, args = where(plan)
            sql = 'SELECT b.*,v.vehicle_type,v.model,v.hub_name,v.hourly_rate,v.daily_rate,a.customer_tier,a.kyc_status' + BASE + w + ' ORDER BY b.scheduled_start DESC LIMIT 51'
            evidence.append(execute(c, sql, args, scope))
            if plan.booking_id:
                for table in ('payments', 'damage_reports'):
                    evidence.append(execute(c, f'SELECT * FROM {table} WHERE booking_id = ? ORDER BY ' + ('paid_at' if table == 'payments' else 'reported_at'), [plan.booking_id], scope, cap=200))
    return evidence
