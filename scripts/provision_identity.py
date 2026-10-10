"""Trusted operator CLI; never exposed as an HTTP endpoint."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config
import firebase_admin
from firebase_admin import auth, credentials

def main():
    p = argparse.ArgumentParser(description='Assign trusted Firebase role to an account.')
    p.add_argument('--uid', required=True)
    p.add_argument('--role', choices=['customer', 'support_agent', 'evaluator'], required=True)
    p.add_argument('--customer-id')
    args = p.parse_args()
    if not config.PROJECT:
        p.error('Set FIREBASE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS first.')
    if args.role == 'customer' and not args.customer_id:
        p.error('Customer role requires --customer-id.')
    if args.customer_id:
        from app.database import customer_exists
        if not customer_exists(config.DB, args.customer_id):
            p.error('Customer ID is not in the supplied database.')
    firebase_admin.initialize_app(credentials.ApplicationDefault(), {'projectId': config.PROJECT})
    try:
        auth.get_user(args.uid)
    except auth.UserNotFoundError:
        auth.create_user(uid=args.uid)
    auth.set_custom_user_claims(args.uid, {'role': args.role})
    mapping = json.loads(config.MAPPING.read_text()) if config.MAPPING.exists() else {}
    if args.role == 'customer':
        mapping[args.uid] = args.customer_id
    else:
        mapping.pop(args.uid, None)
    config.MAPPING.parent.mkdir(parents=True, exist_ok=True)
    config.MAPPING.write_text(json.dumps(mapping, indent=2), encoding='utf-8')
    print('Trusted role assigned. Reauthenticate to refresh claims.')

if __name__ == '__main__':
    main()
