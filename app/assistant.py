import asyncio
import json
import re
from time import monotonic
from . import config, database, calculations
from .models import Plan
from .provider import provider, ProviderUnavailable

def local_plan(message, session):
    q = message.lower()
    booking = re.search(r'\bB-\d{4}\b', message, re.I)
    customer = re.search(r'\bCUST\d{4}\b', message, re.I)
    bid = booking[0].upper() if booking else session.booking_id if re.search(r'\b(it|that|this|refund|charge|penalt|payment)', q) else None
    cid = customer[0].upper() if customer else None
    if re.search(r'\b(delete|drop|update|insert|transfer|execute refund|cancel my|cancel booking)\b', q):
        return Plan(operation='refuse', clarification='I can explain records and policy, but cannot change bookings, payments, or the database.')
    if re.search(r'\b(api key|system prompt|service.account|private key|password|ignore.*instructions)\b', q):
        return Plan(operation='refuse', clarification='I cannot expose credentials or bypass access rules.')
    if re.search(r'\b(profile|kyc|tier|my account|my email|my phone|contact details)\b', q):
        return Plan(operation='profile', customer_id=cid, profile_contact=bool(re.search(r'\b(email|phone|contact|name)\b', q)))
    if bid:
        op = 'refund' if 'refund' in q else 'charges' if any(x in q for x in ('late', 'penalt', 'charge', 'damage', 'battery fee')) else 'rental' if any(x in q for x in ('rental cost', 'rental estimate', 'rental rate')) else 'payments' if 'pay' in q else 'bookings'
        return Plan(operation=op, booking_id=bid, customer_id=cid)
    if any(x in q for x in ('policy', 'rule', 'how to charge', 'charging', 'ev guide', 'deposit', 'eligib', 'licence', 'license', 'minimum age', 'no show', 'no-show', 'breakdown', 'refund', 'late return', 'cancellation')):
        topic = 'refund' if 'refund' in q or 'cancel' in q else 'penalty' if 'late' in q or 'damage' in q else 'ev' if any(x in q for x in ('ev', 'charging', 'battery', 'breakdown')) else 'rental'
        return Plan(operation='policy', topic=topic)
    if re.search(r'\b(my bookings|list bookings|show bookings|upcoming bookings)\b', q):
        return Plan(operation='bookings', customer_id=cid)
    return None

def facts_answer(evidence):
    parts = []
    for e in evidence:
        if e['kind'] == 'sql':
            if not e['rows']:
                parts.append(f"No matching permitted records were found. [{e['id']}]")
            else:
                parts.append('Retrieved records (timestamps UTC; amounts INR):\n' + json.dumps(e['rows'], ensure_ascii=False, indent=2) + f"\n[{e['id']}]" + ('\nOnly the first displayed rows are shown; this is not the full result count.' if e['truncated'] else ''))
        elif e['kind'] == 'calculation':
            parts.append(e['title'] + ':\n' + '\n'.join(f'{k.replace("_", " ")}: {v}' for k, v in e['values'].items()) + '\n' + e['warning'] + f"\n[{e['id']}]")
    return '\n\n'.join(parts)

def verify_claims(explanation, evidence):
    lookup = {e['id']: e for e in evidence}
    for claim in explanation.claims:
        if not all(ref in lookup for ref in claim.citations):
            return False
        cited = json.dumps([lookup[ref] for ref in claim.citations], ensure_ascii=False).lower()
        # Critical numeric values/IDs must be present in cited evidence.
        for token in re.findall(r'\b(?:B-\d{4}|CUST\d{4}|\d+(?:[.,]\d+)*)\b', claim.text, re.I):
            if token.lower().replace(',', '') not in cited.replace(',', ''):
                return False
    return True

async def answer(message, session, policies, emit, generation):
    evidence, notices = [], []
    started = monotonic()
    async def event(worker, status, summary='', ids=None):
        await emit({'type': 'worker', 'worker': worker, 'status': status, 'summary': summary,
                    'elapsed_ms': round((monotonic() - started) * 1000), 'evidence_ids': ids or []})
    def check_scope(plan):
        if session.role == 'customer':
            for cid in re.findall(r'\bCUST\d{4}\b', message, re.I):
                if cid.upper() != session.customer_id:
                    raise PermissionError('I can only retrieve your own customer information.')
            if plan.customer_id and plan.customer_id != session.customer_id:
                raise PermissionError('I can only retrieve your own customer information.')
        if plan.operation == 'profile' and session.role == 'support_agent' and not plan.customer_id:
            raise ValueError('Specify one customer ID for a work-related profile lookup. Bulk contact lists are unavailable.')
    try:
        await event('Router', 'running', 'Authorising and selecting bounded tools')
        # Block explicit cross-customer requests before they reach the model.
        if session.role == 'customer' and any(c.upper() != session.customer_id for c in re.findall(r'\bCUST\d{4}\b', message, re.I)):
            raise PermissionError('I can only retrieve your own customer information.')
        plan = local_plan(message, session)
        if plan is None:
            plan = await provider.plan(message, session)
        check_scope(plan)
        await event('Router', 'completed', 'Selected: ' + plan.operation)
        if plan.operation in ('clarify', 'refuse'):
            return {'state': 'clarification' if plan.operation == 'clarify' else 'refused', 'answer': plan.clarification or 'Please specify a RideWise question and any relevant booking ID.', 'evidence': []}
        if plan.operation in ('refund', 'charges', 'rental') and not plan.booking_id:
            return {'state': 'clarification', 'answer': 'Which booking ID should I use? Enter an ID such as B-0001.', 'evidence': []}
        if plan.operation == 'profile':
            await event('Profile', 'running', 'Using the isolated profile service')
            result = await asyncio.to_thread(database.profile, config.DB, session, plan.customer_id, plan.profile_contact)
            evidence.append(result)
            await event('Profile', 'completed', 'Retrieved permitted profile fields', [result['id']])
        elif plan.operation != 'policy':
            worker = 'Analytics' if plan.operation == 'analytics' else 'Booking / Payments'
            await event(worker, 'running', 'Executing compiled SQL over authorised records')
            evidence.extend(await asyncio.to_thread(database.query, config.DB, session, plan))
            await event(worker, 'completed', 'Retrieved permitted operational facts', [e['id'] for e in evidence])
            if plan.booking_id and evidence[0]['rows']:
                if session.generation == generation:
                    session.booking_id = plan.booking_id
        if plan.operation in ('refund', 'charges', 'rental', 'policy'):
            worker = 'EV Guide' if plan.topic == 'ev' else 'Policy'
            await event(worker, 'running', 'Retrieving original policy pages and reviewed visuals')
            if plan.operation == 'policy':
                pages = policies.retrieve(message, plan.topic)
            else:
                rows = evidence[0]['rows']
                if not rows:
                    return {'state': 'no_records', 'answer': 'No matching permitted booking was found.', 'evidence': evidence}
                b = rows[0]
                if plan.operation == 'refund':
                    version = 'refund_v2' if calculations.timestamp(b['booked_at']) >= calculations.CUTOFF else 'refund_v1'
                    policies.require('rental', version)
                    pages = policies.pages_for('rental', version)
                else:
                    policies.require('rental', 'penalty')
                    pages = policies.pages_for('rental', 'penalty')
            evidence.extend(pages)
            await event(worker, 'completed', 'Policy pages selected with file hashes and provenance', [e['id'] for e in pages])
        if plan.operation in ('refund', 'charges', 'rental'):
            await event('Charges', 'running', 'Calculating in Python using source rules')
            b, payments, damages = evidence[0]['rows'][0], evidence[1]['rows'], evidence[2]['rows']
            if evidence[1]['truncated'] or evidence[2]['truncated']:
                raise ValueError('Transaction evidence exceeds the calculation limit; no partial total was calculated.')
            result = calculations.refund(b, payments) if plan.operation == 'refund' else calculations.charges(b, payments, damages) if plan.operation == 'charges' else calculations.rental(b)
            result['sources'] = [e['id'] for e in evidence if e['kind'] == 'sql'] + [r for r in result['sources'] if r != 'SQL']
            evidence.append(result)
            await event('Charges', 'completed', 'Calculated entitlement/charges separately from recorded payments', [result['id']])
        if not evidence:
            raise ValueError('No usable evidence is available for this request.')
        await event('Answer', 'running', 'Preparing a source-grounded response')
        # Private contact fields never enter a model prompt; calculations remain exact.
        deterministic = plan.operation in ('profile', 'refund', 'charges', 'rental') or not provider.configured()
        explanation = None
        if not deterministic:
            try:
                explanation = await provider.explain(message, evidence)
            except ProviderUnavailable as exc:
                notices.append(str(exc))
        if explanation and verify_claims(explanation, evidence):
            text = '\n\n'.join(c.text + ' [' + ', '.join(c.citations) + ']' for c in explanation.claims)
        else:
            if explanation:
                notices.append('Generated explanation failed the citation/value check. Showing verified source facts instead.')
            if plan.operation == 'policy':
                text = 'Relevant original policy excerpts:\n\n' + '\n\n'.join(f"{e['filename']}, page {e['page']} (v{e['version']}):\n{e['excerpt']}\n[{e['id']}]" for e in evidence)
            elif plan.operation in ('refund', 'charges', 'rental'):
                text = facts_answer([e for e in evidence if e['kind'] == 'calculation'])
            else:
                text = facts_answer(evidence)
        await event('Answer', 'completed', 'Response prepared')
        await event('Verification', 'running', 'Checking citations, numeric provenance, and session generation')
        if session.generation != generation:
            raise asyncio.CancelledError()
        await event('Verification', 'completed', 'Evidence attached; generated numeric values checked. Semantic inference is not formally proven.', [e['id'] for e in evidence])
        if len(session.history) >= 8:
            session.history.pop(0)
        session.history.append(message)
        return {'state': 'answered', 'answer': text, 'evidence': evidence, 'notices': notices, 'operation': plan.operation}
    except (PermissionError, ValueError, ProviderUnavailable) as exc:
        await event('Router', 'failed', str(exc))
        return {'state': 'refused' if isinstance(exc, PermissionError) else 'unavailable' if isinstance(exc, ProviderUnavailable) else 'clarification', 'answer': str(exc), 'evidence': evidence}
