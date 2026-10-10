from copy import deepcopy
from decimal import Decimal
import pytest
from app.calculations import refund, charges, rental

def booking(**values):
    b = dict(booking_id='B-0001', booked_at='2026-06-30 18:30:00', scheduled_start='2026-07-04 12:00:00', scheduled_end='2026-07-04 14:00:00', cancelled_at='2026-07-02 12:00:00', actual_return_at='2026-07-04 14:30:00', booking_status='CNL_U', customer_tier='GOLD', vehicle_type='EV_BIKE', hourly_rate=100, daily_rate=800, return_battery_pct=10)
    b.update(values)
    return b

def payment(kind='BOOKING', amount=100, gst=18, status='SUCCESS'):
    return dict(payment_type=kind, payment_status=status, amount=amount, gst_amount=gst)

@pytest.mark.parametrize('cancel,rate', [('2026-07-02 12:00:00','1'),('2026-07-02 12:00:01','0.75'),('2026-07-04 00:00:00','0.75'),('2026-07-04 00:00:01','0.25'),('2026-07-04 10:00:00','0.25'),('2026-07-04 10:00:01','0')])
def test_v2_boundaries(cancel, rate):
    r = refund(booking(cancelled_at=cancel), [payment()])
    assert r['inputs']['rate'] == rate

def test_cutoff_and_instalments_exclude_failed_deposit():
    r = refund(booking(booked_at='2026-06-30 18:29:59', cancelled_at='2026-07-03 12:00:00'), [payment(), payment(amount=200,gst=36), payment(status='FAILED'), payment('DEPOSIT',1000,0), payment('REFUND',-100,-18)])
    assert r['version'] == 'refund_v1'
    assert r['values']['eligible_total'] == '354.00'
    assert r['values']['recorded_refund'] == '118.00'
    assert r['values']['difference'] == '236.00'

@pytest.mark.parametrize('cancel,expected',[('2026-07-03 12:00:00','118.00'),('2026-07-03 12:00:01','59.00'),('2026-07-04 06:00:00','59.00'),('2026-07-04 06:00:01','0.00')])
def test_v1_boundaries(cancel,expected):
    assert refund(booking(booked_at='2026-06-01 12:00:00', cancelled_at=cancel),[payment()])['values']['eligible_total'] == expected

@pytest.mark.parametrize('status,value',[('CNL_S','118.00'),('NSH','0.00')])
def test_company_and_no_show(status,value):
    assert refund(booking(booking_status=status),[payment()])['values']['eligible_total'] == value

@pytest.mark.parametrize('returned,expected',[('2026-07-04 14:30:00','0.00'),('2026-07-04 14:30:01','150.00'),('2026-07-04 15:00:00','150.00'),('2026-07-04 15:00:01','300.00')])
def test_gold_grace_full_lateness(returned,expected):
    assert charges(booking(booking_status='CMP', actual_return_at=returned),[],[])['values']['late_fee'] == expected

def test_ev_boundary_damage_and_reconciliation():
    reports = [dict(report_id='D1',claim_status='CHARGED',assessed_cost=200),dict(report_id='D2',claim_status='DISPUTED',assessed_cost=900)]
    r = charges(booking(booking_status='CMP', return_battery_pct=9),[payment('PENALTY',350,63)],reports)
    assert r['values']['expected_total'] == '413.00'
    assert r['values']['difference'] == '0.00'
    assert 'D2' in r['warning']

def test_rental_daily_cap_and_deposit():
    r = rental(booking(scheduled_end='2026-07-05 14:00:00'))
    assert r['values']['rental_base'] == '1000.00'
    assert r['values']['deposit_no_GST'] == '1000.00'

def test_unknown_tier_and_missing_timestamp_abstain():
    with pytest.raises(ValueError): charges(booking(customer_tier='PLATINUM'),[],[])
    with pytest.raises(ValueError): refund(booking(cancelled_at=None),[payment()])
