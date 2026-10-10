import json
import asyncio
import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Header, HTTPException
from . import config
from .models import Principal

def configured():
    return bool(config.PROJECT and config.WEB['apiKey'] and config.WEB['appId'])

def verified_identity(token):
    if not configured():
        raise HTTPException(503, 'Firebase authentication setup required.')
    try:
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(credentials.ApplicationDefault(), {'projectId': config.PROJECT})
        # Allow modest laptop clock drift; signatures/audience/revocation remain checked.
        claims = auth.verify_id_token(token, check_revoked=True, clock_skew_seconds=30)
        return claims
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, 'Identity could not be verified.') from None

def verify(token):
    claims = verified_identity(token)
    try:
        role = claims.get('role')
        if role not in ('customer', 'support_agent', 'evaluator'):
            raise ValueError('No trusted role')
        cid = None
        if role == 'customer':
            mapping = json.loads(config.MAPPING.read_text(encoding='utf-8')) if config.MAPPING.exists() else {}
            cid = mapping.get(claims['uid'])
        return Principal(uid=claims['uid'], role=role, customer_id=cid)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, 'Identity or assigned role could not be verified.') from None

async def principal(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer ') or len(authorization) > 12000:
        raise HTTPException(401, 'A Firebase ID token is required.')
    return await asyncio.to_thread(verify, authorization[7:])

async def identity(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer ') or len(authorization) > 12000:
        raise HTTPException(401, 'A Firebase ID token is required.')
    return await asyncio.to_thread(verified_identity, authorization[7:])

def register_customer(claims):
    # No user-provided role/customer ID. Preserve any already assigned trusted role.
    try:
        user = auth.get_user(claims['uid'])
        current = user.custom_claims or {}
        role = current.get('role')
        if role is None:
            auth.set_custom_user_claims(user.uid, {**current, 'role': 'customer'})
            role = 'customer'
        if role not in ('customer', 'support_agent', 'evaluator'):
            raise ValueError('Unrecognised assigned role')
        return {'role': role, 'refresh_required': claims.get('role') != role}
    except Exception:
        raise HTTPException(503, 'Account access could not be assigned. Retry or contact the administrator.') from None
