import asyncio
import json
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import config, auth, database
from .models import SessionRequest, ChatRequest, Principal
from .sessions import sessions
from .policies import Policies, FILES
from .provider import provider
from .assistant import answer

policies = None

@asynccontextmanager
async def lifespan(app):
    global policies
    policies = await asyncio.to_thread(Policies, config.DATA)
    yield
    await provider.close()

app = FastAPI(title='RideWise Assist', lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=config.ROOT / 'static'), name='static')

@app.middleware('http')
async def protect_origin(request: Request, call_next):
    host = request.headers.get('host', '').split(':')[0]
    if host not in ('127.0.0.1', 'localhost', 'testserver'):
        return JSONResponse({'detail': 'Localhost host required.'}, status_code=400)
    origin = request.headers.get('origin')
    if origin and (urlparse(origin).netloc != request.headers.get('host') or urlparse(origin).scheme not in ('http', 'https')):
        return JSONResponse({'detail': 'Cross-origin requests are blocked.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://www.gstatic.com; connect-src 'self' https://*.googleapis.com https://*.firebaseapp.com; style-src 'self'; img-src 'self' data:; frame-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    return response

@app.get('/')
def index():
    return FileResponse(config.ROOT / 'static' / 'index.html')

@app.get('/health')
def health():
    return {'status': 'ok', 'database_ready': config.DB.exists(), 'policy_ready': bool(policies and len(policies.valid) == 5), 'firebase_ready': auth.configured(), 'model_ready': provider.configured()}

@app.get('/api/config')
def public_config():
    return {'firebase': config.WEB, 'auth_ready': auth.configured(), 'auth_mode': 'firebase', 'model_ready': provider.configured()}

@app.get('/api/me')
def me(p: Principal = Depends(auth.principal)):
    return p

@app.post('/api/session')
async def start_session(body: SessionRequest, p: Principal = Depends(auth.principal)):
    # Permission check before existence check: do not reveal another customer's existence.
    if p.role != 'evaluator' and (body.role != p.role or body.customer_id != p.customer_id):
        raise HTTPException(403, 'This session is outside your assigned access.')
    if body.role == 'customer' and (not body.customer_id or not await asyncio.to_thread(database.customer_exists, config.DB, body.customer_id)):
        raise HTTPException(422, 'Customer ID is not available for this session.')
    key, s = sessions.create(p, body.role, body.customer_id if body.role == 'customer' else None)
    return {'session_id': key, 'generation': s.generation, 'role': s.role, 'customer_id': s.customer_id, 'principal_role': p.role}

@app.post('/api/conversation/{key}/reset')
def reset(key: str, p: Principal = Depends(auth.principal)):
    return {'generation': sessions.reset(key, p)}

@app.delete('/api/session/{key}')
def sign_out(key: str, p: Principal = Depends(auth.principal)):
    s = sessions.get(key, p)
    s.generation += 1
    sessions.items.pop(key)
    return {'ok': True}

@app.get('/api/policies')
def policy_list(p: Principal = Depends(auth.principal)):
    return [{'key': key, 'filename': filename, 'reviewed': key in policies.valid} for key, filename in FILES.items()]

@app.get('/api/policies/{key}')
def policy_file(key: str, p: Principal = Depends(auth.principal)):
    if key not in FILES or not (config.DATA / FILES[key]).exists():
        raise HTTPException(404, 'Policy unavailable.')
    return FileResponse(config.DATA / FILES[key], media_type='application/pdf')

def begin(body, p):
    s = sessions.get(body.session_id, p, body.generation)
    if s.busy:
        raise HTTPException(409, 'Another turn is still finishing.')
    if body.request_id in s.seen:
        raise HTTPException(409, 'This request has already been submitted.')
    if len(s.seen) >= 300:
        raise HTTPException(429, 'Start a new conversation to continue.')
    s.busy = True
    s.seen.add(body.request_id)
    return s

@app.post('/api/chat')
async def chat(body: ChatRequest, p: Principal = Depends(auth.principal)):
    s = begin(body, p)
    events = []
    async def emit(value):
        events.append(value)
    try:
        result = await asyncio.wait_for(answer(body.message, s, policies, emit, body.generation), timeout=60)
        sessions.get(body.session_id, p, body.generation)
        return {**result, 'events': events, 'request_id': body.request_id, 'generation': body.generation}
    except asyncio.TimeoutError:
        return {'state': 'unavailable', 'answer': 'Request deadline reached. Please retry.', 'evidence': [], 'events': events}
    finally:
        s.busy = False

@app.post('/api/chat/stream')
async def stream(body: ChatRequest, request: Request, p: Principal = Depends(auth.principal)):
    s = begin(body, p)
    queue = asyncio.Queue()
    async def emit(value):
        if s.generation != body.generation:
            raise asyncio.CancelledError()
        await queue.put({**value, 'request_id': body.request_id, 'generation': body.generation})
    async def work():
        try:
            result = await asyncio.wait_for(answer(body.message, s, policies, emit, body.generation), timeout=60)
            if s.generation == body.generation:
                await emit({'type': 'final', **result})
        except asyncio.CancelledError:
            pass
        except Exception:
            if s.generation == body.generation:
                await emit({'type': 'final', 'state': 'unavailable', 'answer': 'The request could not finish safely. Please retry.', 'evidence': []})
        finally:
            s.busy = False
            await queue.put(None)
    async def generate():
        task = asyncio.create_task(work())
        try:
            while True:
                try:
                    value = await asyncio.wait_for(queue.get(), timeout=1)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ': keepalive\n\n'
                    continue
                if value is None:
                    break
                if s.generation == body.generation:
                    yield 'data: ' + json.dumps(value, ensure_ascii=False) + '\n\n'
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    return StreamingResponse(generate(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})
