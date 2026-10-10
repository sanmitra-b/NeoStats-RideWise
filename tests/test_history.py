import pytest
from fastapi import HTTPException
from app import config, history
from app.models import Principal, ChatRequest
from app.sessions import Session, Sessions

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'HISTORY', tmp_path / 'history.db')

def save(s, request='turn-1', generation=0):
    body = ChatRequest(session_id='s', generation=generation, message='Show my bookings', request_id=request)
    result = {'state': 'answered', 'answer': 'Saved response', 'evidence': [{'kind': 'sql', 'sql': 'SELECT 1', 'rows': []}]}
    history.save_turn(s, body, result, [{'type': 'worker', 'worker': 'SQL', 'status': 'completed'}])

def test_history_survives_session_loss_and_retains_evidence(store):
    s = Session('alice', 'customer', 'CUST0001', booking_id='B-0001')
    save(s)
    owner = Principal(uid='alice', role='customer', customer_id='CUST0001')
    listing = history.list_chats(owner)
    loaded = history.load_chat(listing[0]['id'], owner)
    assert loaded['booking_id'] == 'B-0001'
    assert loaded['turns'][0]['result']['evidence'][0]['sql'] == 'SELECT 1'
    assert loaded['turns'][0]['events'][0]['worker'] == 'SQL'
    save(s)
    assert len(history.load_chat(s.conversation_id, owner)['turns']) == 1

def test_history_uid_and_role_scope_isolation(store):
    s = Session('alice', 'support_agent', None)
    save(s)
    for p in [Principal(uid='bob', role='evaluator'), Principal(uid='alice', role='customer', customer_id='CUST0001')]:
        assert history.list_chats(p) == []
        with pytest.raises(HTTPException):
            history.load_chat(s.conversation_id, p)
        with pytest.raises(HTTPException):
            history.delete_chat(s.conversation_id, p)

def test_changed_customer_mapping_hides_old_history(store):
    s = Session('alice', 'customer', 'CUST0001')
    save(s)
    assert history.list_chats(Principal(uid='alice', role='customer', customer_id='CUST0002')) == []

def test_new_conversation_preserves_previous_and_stale_turn_is_not_saved(store):
    p = Principal(uid='alice', role='evaluator')
    sessions = Sessions()
    key, s = sessions.create(p, 'support_agent', None)
    save(s)
    original = s.conversation_id
    sessions.reset(key, p)
    save(s, request='stale', generation=0)
    assert len(history.list_chats(p)) == 1
    save(s, request='new', generation=1)
    assert len(history.list_chats(p)) == 2
    history.delete_chat(original, p)
    assert len(history.list_chats(p)) == 1

def test_authenticated_routes_resume_scope_and_delete_active_chat(store):
    from fastapi.testclient import TestClient
    from app import auth
    from app.main import app
    from app.sessions import sessions
    evaluator = Principal(uid='history-evaluator', role='evaluator')
    app.dependency_overrides[auth.principal] = lambda: evaluator
    try:
        with TestClient(app) as c:
            s = c.post('/api/session', json={'role': 'customer', 'customer_id': 'CUST0001'}).json()
            response = c.post('/api/chat/stream', json={'session_id': s['session_id'], 'generation': 0,
                'request_id': 'history-api', 'message': 'Show my bookings'})
            assert '"type": "final"' in response.text
            listing = c.get('/api/history').json()
            cid = listing[0]['id']
            assert c.post('/api/conversation/' + s['session_id'] + '/reset').status_code == 200
            resumed = c.post('/api/history/' + cid + '/resume').json()
            assert resumed['role'] == 'customer' and resumed['customer_id'] == 'CUST0001'
            assert resumed['turns'][0]['result']['evidence'][0]['kind'] == 'sql'
            app.dependency_overrides[auth.principal] = lambda: Principal(uid='other', role='evaluator')
            assert c.get('/api/history').json() == []
            assert c.post('/api/history/' + cid + '/resume').status_code == 404
            assert c.delete('/api/history/' + cid).status_code == 404
            app.dependency_overrides[auth.principal] = lambda: evaluator
            deleted = c.delete('/api/history/' + cid).json()
            assert deleted['reset_sessions'][resumed['session_id']] == 1
            assert c.get('/api/history').json() == []
            assert sessions.items[resumed['session_id']].conversation_id is None
    finally:
        app.dependency_overrides.clear()
