"""Private, persistent conversation storage. Never writes the supplied ridewise.db."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import HTTPException
from . import config

@contextmanager
def connection():
    config.HISTORY.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.HISTORY, timeout=5)
    try:
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('''CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY, uid TEXT NOT NULL, role TEXT NOT NULL,
            customer_id TEXT, title TEXT NOT NULL, updated_at TEXT NOT NULL, booking_id TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS turns (
            conversation_id TEXT REFERENCES chats(id) ON DELETE CASCADE,
            request_id TEXT NOT NULL, question TEXT NOT NULL, result TEXT NOT NULL,
            events TEXT NOT NULL, PRIMARY KEY(conversation_id, request_id))''')
        c.execute('CREATE INDEX IF NOT EXISTS chats_owner ON chats(uid, updated_at)')
        with c:
            yield c
    finally:
        c.close()

def allowed(row, p):
    return row['uid'] == p.uid and (p.role == 'evaluator' or
        (row['role'] == p.role and row['customer_id'] == p.customer_id))

def save_turn(s, body, result, events):
    # Called only after the generation check, without yielding to a reset.
    if s.generation != body.generation:
        return
    cid = s.conversation_id or uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with connection() as c:
        c.execute('INSERT OR IGNORE INTO chats VALUES (?,?,?,?,?,?,?)',
                  (cid, s.uid, s.role, s.customer_id, body.message[:80], now, s.booking_id))
        c.execute('INSERT OR IGNORE INTO turns VALUES (?,?,?,?,?)',
                  (cid, body.request_id, body.message, json.dumps(result), json.dumps(events)))
        c.execute('UPDATE chats SET updated_at=?, booking_id=? WHERE id=? AND uid=?',
                  (now, s.booking_id, cid, s.uid))
    s.conversation_id = cid

def list_chats(p):
    with connection() as c:
        rows = c.execute('SELECT * FROM chats WHERE uid=? ORDER BY updated_at DESC, rowid DESC', (p.uid,)).fetchall()
    return [{k: r[k] for k in ('id', 'title', 'role', 'customer_id', 'updated_at')}
            for r in rows if allowed(r, p)][:100]

def load_chat(cid, p):
    with connection() as c:
        row = c.execute('SELECT * FROM chats WHERE id=? AND uid=?', (cid, p.uid)).fetchone()
        if not row or not allowed(row, p):
            raise HTTPException(404, 'Saved conversation unavailable for your assigned access.')
        turns = c.execute('SELECT * FROM turns WHERE conversation_id=? ORDER BY rowid', (cid,)).fetchall()
    return {**dict(row), 'turns': [{'question': t['question'], 'result': json.loads(t['result']),
                                 'events': json.loads(t['events'])} for t in turns]}

def delete_chat(cid, p):
    load_chat(cid, p)
    with connection() as c:
        c.execute('DELETE FROM chats WHERE id=? AND uid=?', (cid, p.uid))
