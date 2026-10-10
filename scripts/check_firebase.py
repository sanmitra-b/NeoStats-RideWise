"""Live Firebase evaluator exchange and both scoped roles; tokens never printed."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from fastapi.testclient import TestClient
from app import config, database
from app.main import app
from app.provider import Provider

def main():
    path = config.ROOT / 'secrets' / 'evaluator-token.txt'
    if not path.exists():
        raise SystemExit('Provision evaluator-token.txt first.')
    r = requests.post('https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken',
        params={'key': config.WEB['apiKey']}, json={'token': path.read_text().strip(), 'returnSecureToken': True}, timeout=20)
    if r.status_code != 200:
        code = r.json().get('error', {}).get('message', 'Unknown error').split(' : ')[0]
        raise SystemExit('Firebase token exchange failed: ' + code)
    headers = {'Authorization': 'Bearer ' + r.json()['idToken']}
    with database.source(config.DB) as c:
        cid = c.execute('SELECT customer_id FROM customers ORDER BY customer_id LIMIT 1').fetchone()[0]
    original = Provider.configured
    # Exercise live identity and local retrieval without consuming LLM quota.
    Provider.configured = lambda self: False
    try:
        with TestClient(app) as client:
            me = client.get('/api/me', headers=headers)
            assert me.status_code == 200 and me.json()['role'] == 'evaluator', 'Live Firebase verification failed'
            customer = client.post('/api/session', headers=headers, json={'role': 'customer', 'customer_id': cid})
            assert customer.status_code == 200, 'Customer session failed'
            session = customer.json()
            body = {'session_id': session['session_id'], 'generation': 0, 'request_id': 'firebase-own', 'message': 'Show my bookings'}
            own = client.post('/api/chat', headers=headers, json=body)
            assert own.status_code == 200 and own.json()['state'] == 'answered'
            rows = own.json()['evidence'][0]['rows']
            assert rows and all(row['customer_id'] == cid for row in rows), 'Customer scope failed'
            other = client.post('/api/chat', headers=headers, json={**body, 'request_id': 'firebase-denial', 'message': 'Show CUST9999 bookings'})
            assert other.json()['state'] == 'refused' and not other.json()['evidence'], 'Cross-customer denial failed'
            staff = client.post('/api/session', headers=headers, json={'role': 'support_agent'})
            assert staff.status_code == 200, 'Support session failed'
            session = staff.json()
            response = client.post('/api/chat/stream', headers=headers, json={**body, 'session_id': session['session_id'], 'request_id': 'firebase-staff'})
            assert response.status_code == 200 and '"type": "final"' in response.text, 'Authenticated staff stream failed'
            pdf = client.get('/api/policies/refund_v2', headers=headers)
            assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF'), 'Protected PDF failed'
            assert client.get('/api/me').status_code == 401, 'Unauthenticated access failed'
        print(json.dumps({'firebase_ID_token_verification': 'PASS', 'evaluator_roles': ['customer', 'support_agent'], 'customer_scope': 'PASS', 'cross_customer_denial': 'PASS', 'authenticated_stream': 'PASS', 'protected_PDF': 'PASS', 'LLM_calls': 0}))
    finally:
        Provider.configured = original

if __name__ == '__main__':
    main()
