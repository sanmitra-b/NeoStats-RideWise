"""Decimal arithmetic; policy constants are reviewed source rules, never canned answers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

D = lambda v: Decimal(str(v))
GST = D('0.18')
CUTOFF = datetime(2026, 6, 30, 18, 30, tzinfo=timezone.utc)
GRACE = {'STANDARD': 0, 'SILVER': 0, 'GOLD': 30}
REFUND_BANDS = {'refund_v1': [(24, '1'), (6, '0.5'), (0, '0')], 'refund_v2': [(48, '1'), (12, '0.75'), (2, '0.25'), (0, '0')]}

def timestamp(value):
    if not value:
        raise ValueError('A timestamp needed for this calculation is missing.')
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)

def money(value):
    return str(D(value).quantize(D('0.01'), rounding=ROUND_HALF_UP))

def total(payments, kind, field='amount'):
    return sum((D(p[field] or 0) for p in payments if p['payment_type'] == kind and p['payment_status'] == 'SUCCESS'), D(0))

def refund(b, payments):
    version = 'refund_v2' if timestamp(b['booked_at']) >= CUTOFF else 'refund_v1'
    paid, tax = total(payments, 'BOOKING'), total(payments, 'BOOKING', 'gst_amount')
    lead = None
    status = b['booking_status']
    if status == 'CNL_S':
        rate = D(1)
    elif status == 'NSH':
        rate = D(0)
    elif status == 'CNL_U':
        lead = D(str((timestamp(b['scheduled_start']) - timestamp(b['cancelled_at'])).total_seconds())) / D(3600)
        if lead < 0:
            raise ValueError('Cancellation is after pickup; the advance-cancellation schedule cannot establish entitlement.')
        rate = next(D(r) for threshold, r in REFUND_BANDS[version] if lead >= threshold)
    else:
        raise ValueError('This booking has no recorded cancellation/no-show. Specify a hypothetical cancellation time separately; no actual refund entitlement is established.')
    base, gst = D(money(paid * rate)), D(money(tax * rate))
    recorded = -(total(payments, 'REFUND') + total(payments, 'REFUND', 'gst_amount'))
    gap = base + gst - recorded
    return {'id': 'CALC-refund', 'kind': 'calculation', 'title': 'Refund entitlement vs recorded refund',
            'formula': 'successful BOOKING base × refund rate + proportional recorded GST; successful REFUND entries are negative',
            'inputs': {'booking_id': b['booking_id'], 'booked_at_UTC': b['booked_at'], 'cutoff_UTC': '2026-06-30 18:30:00', 'lead_hours': str(lead) if lead is not None else 'status override', 'rate': str(rate), 'paid_base': money(paid), 'paid_GST': money(tax)},
            'values': {'eligible_base': money(base), 'eligible_GST': money(gst), 'eligible_total': money(base + gst), 'recorded_refund': money(recorded), 'difference': money(gap)},
            'sources': ['SQL', 'PDF-' + version + ('-2' if version.endswith('v2') else '-1'), 'PDF-rental-1'],
            'warning': 'Deposit gateway returns are absent from this database. A difference is a reconciliation flag, not proof of an unpaid gateway transfer.' + (' Recorded refunds exceed calculated entitlement.' if gap < 0 else ''), 'version': version}

def charges(b, payments, damage):
    if b['customer_tier'] not in GRACE:
        raise ValueError('Unknown customer tier; grace cannot be determined.')
    late, fee, battery = D(0), D(0), D(0)
    notes = []
    hours = 0
    if b['booking_status'] == 'CMP':
        late = max(D(0), D(str((timestamp(b['actual_return_at']) - timestamp(b['scheduled_end'])).total_seconds())) / D(60))
        if late > GRACE[b['customer_tier']]:
            hours = int((late / D(60)).to_integral_value(rounding=ROUND_CEILING))
            fee = D(hours) * D('1.5') * D(b['hourly_rate'])
        if b['vehicle_type'].startswith('EV_'):
            pct = b['return_battery_pct']
            if pct is None or not 0 <= pct <= 100:
                notes.append('Return battery reading missing or invalid; battery fee cannot be confirmed.')
            elif pct < 10:
                battery = D(150)
    else:
        notes.append('Booking is not completed; no actual late-return/battery fee is established.')
    damage_fee = sum((D(r['assessed_cost']) for r in damage if r['claim_status'] == 'CHARGED'), D(0))
    unresolved = [r['report_id'] for r in damage if r['claim_status'] in ('OPEN', 'DISPUTED')]
    base = fee + battery + damage_fee
    tax = D(money(base * GST))
    paid = total(payments, 'PENALTY') + total(payments, 'PENALTY', 'gst_amount')
    return {'id': 'CALC-charges', 'kind': 'calculation', 'title': 'Policy charges vs recorded penalty payments',
            'formula': 'ceil(full late minutes / 60) × 1.5 × hourly rate after inclusive grace; EV below 10% adds 150; CHARGED damage only; GST 18%',
            'inputs': {'booking_id': b['booking_id'], 'tier': b['customer_tier'], 'grace_minutes': GRACE[b['customer_tier']], 'late_minutes': str(late), 'begun_hours': hours, 'hourly_rate': money(b['hourly_rate']), 'battery_percent': b['return_battery_pct']},
            'values': {'late_fee': money(fee), 'low_battery_fee': money(battery), 'charged_damage': money(damage_fee), 'GST': money(tax), 'expected_total': money(base + tax), 'recorded_penalty_paid': money(paid), 'difference': money(base + tax - paid)},
            'sources': ['SQL', 'PDF-penalty-1', 'PDF-penalty-3'],
            'warning': ' '.join(notes) + (' Unresolved damage reports: ' + ', '.join(unresolved) if unresolved else '') + ' Assessed charges and payment entries are compared, never added together.'}

def rental(b):
    seconds = (timestamp(b['scheduled_end']) - timestamp(b['scheduled_start'])).total_seconds()
    if seconds <= 0 or seconds % 3600:
        raise ValueError('Scheduled duration is not a positive whole number of hours.')
    hours = int(seconds / 3600)
    if hours < 2:
        raise ValueError('Scheduled duration conflicts with the two-hour minimum.')
    days, remainder = divmod(hours, 24)
    base = D(days) * D(b['daily_rate']) + min(D(remainder) * D(b['hourly_rate']), D(b['daily_rate']))
    deposit = D(1000) if b['vehicle_type'] in ('BIKE', 'EV_BIKE') else D(500) if hours >= 24 else D(0)
    return {'id': 'CALC-rental', 'kind': 'calculation', 'title': 'Scheduled rental estimate', 'formula': 'full 24-hour blocks × daily rate + remaining hours × hourly rate capped at daily rate; 18% GST',
            'inputs': {'duration_hours': hours, 'hourly_rate': money(b['hourly_rate']), 'daily_rate': money(b['daily_rate'])},
            'values': {'rental_base': money(base), 'GST': money(base * GST), 'rental_total': money(base * (1 + GST)), 'deposit_no_GST': money(deposit)},
            'sources': ['SQL', 'PDF-rental-1'], 'warning': 'Scheduled estimate, not a recorded payment. Deposit is separate and its gateway return cannot be verified.'}
