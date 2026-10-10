"""Live bootstrap smoke check with a disposable Auth identity; no emails or passwords."""
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from firebase_admin import auth as firebase_auth
from fastapi.testclient import TestClient
from app import auth, config
from app.main import app

def main():
    import firebase_admin
    from firebase_admin import credentials
    try: firebase_admin.get_app()
    except ValueError: firebase_admin.initialize_app(credentials.ApplicationDefault(), {'projectId':config.PROJECT})
    uid='signup-smoke-'+uuid4().hex
    firebase_auth.create_user(uid=uid)
    try:
        token=firebase_auth.create_custom_token(uid).decode()
        def sign_in():
            r=requests.post('https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken',params={'key':config.WEB['apiKey']},json={'token':token,'returnSecureToken':True},timeout=20)
            r.raise_for_status()
            return {'Authorization':'Bearer '+r.json()['idToken']}
        headers=sign_in()
        with TestClient(app) as c:
            r=c.post('/api/account/bootstrap',headers=headers,json={})
            assert r.status_code==200 and r.json()['role']=='customer'
            headers=sign_in()
            me=c.get('/api/me',headers=headers)
            assert me.status_code==200 and me.json()['role']=='customer' and me.json()['customer_id'] is None
            s=c.post('/api/session',headers=headers,json={'role':'customer'})
            assert s.status_code==200 and s.json()['customer_id'] is None
            assert c.post('/api/session',headers=headers,json={'role':'support_agent'}).status_code==403
            assert c.post('/api/session',headers=headers,json={'role':'customer','customer_id':'CUST0001'}).status_code==403
            c.delete('/api/session/'+s.json()['session_id'],headers=headers)
        print('Live default Customer assignment, policy-only session, self-promotion denial and arbitrary-record-link denial: PASS')
    finally:
        firebase_auth.delete_user(uid)
        print('Disposable smoke-test identity removed. No emails/passwords or supplied records changed.')

if __name__=='__main__': main()
