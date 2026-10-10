import json
import asyncio
import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Header, HTTPException
from . import config
from .models import Principal

def configured():
    return bool(config.PROJECT and config.WEB['apiKey'] and config.WEB['appId'])

def verify(token):
    if not configured():
        raise HTTPException(503, 'Firebase authentication setup required.')
    try:
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(credentials.ApplicationDefault(), {'projectId': config.PROJECT})
        claims = auth.verify_id_token(token, check_revoked=True)
        role = claims.get('role')
        if role not in ('customer', 'support_agent', 'evaluator'):
            raise ValueError('No trusted role')
        cid = None
        if role == 'customer':
            mapping = json.loads(config.MAPPING.read_text(encoding='utf-8'))
            cid = mapping.get(claims['uid'])
            if not cid:
                raise ValueError('Missing customer mapping')
        return Principal(uid=claims['uid'], role=role, customer_id=cid)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, 'Identity or assigned role could not be verified.') from None

async def principal(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer ') or len(authorization) > 12000:
        raise HTTPException(401, 'A Firebase ID token is required.')
    return await asyncio.to_thread(verify, authorization[7:])
