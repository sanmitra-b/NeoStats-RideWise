"""Trusted operator CLI; never exposed as an HTTP endpoint. Output token to a private file."""
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
    p = argparse.ArgumentParser(description='Assign trusted Firebase role and optionally issue evaluator custom token.')
    p.add_argument('--uid', required=True)
    p.add_argument('--role', choices=['customer', 'support_agent', 'evaluator'], required=True)
    p.add_argument('--customer-id')
    p.add_argument('--token-file', type=Path)
    p.add_argument('--replace-token', action='store_true', help='Explicitly replace an existing private custom sign-in token file.')
    args = p.parse_args()
    if not config.PROJECT:
        p.error('Set FIREBASE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS first.')
    if args.role == 'customer' and not args.customer_id:
        p.error('Customer role requires --customer-id.')
    if args.token_file and args.token_file.exists() and not args.replace_token:
        p.error('Token file exists; use --replace-token to renew it explicitly.')
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
    if args.token_file:
        token = auth.create_custom_token(args.uid).decode()
        args.token_file.parent.mkdir(parents=True, exist_ok=True)
        with args.token_file.open('w' if args.replace_token else 'x', encoding='utf-8') as f:
            f.write(token)
        print('Custom sign-in token saved to the requested private file. Never commit or share it.')
    print('Trusted role assigned. Reauthenticate to refresh claims.')

if __name__ == '__main__':
    main()
