const $ = id => document.getElementById(id);
let config, firebaseAuth, firebaseApi, principal, session, selectedEvidence = [], activeTab = 'sql', controller, busy = false, renderGeneration = 0;
let creatingAccount = false, authBusy = false;
const blobs = new Set();
const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
const clearBlobs = () => { for (const url of blobs) URL.revokeObjectURL(url); blobs.clear(); };
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (firebaseAuth?.currentUser) headers.set('Authorization', 'Bearer ' + await firebaseAuth.currentUser.getIdToken());
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { ...options, headers, cache: 'no-store' });
  if (!response.ok) {
    let detail = 'Request failed. Please retry.';
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : 'Please check the entered values.'; } catch {}
    if (response.status === 401 || response.status === 403) $('authBadge').textContent = 'Access needs verification';
    throw new Error(detail);
  }
  return response;
}
function notice(text) { $('notice').textContent = text; }
function showDialog() { if (!$('sessionDialog').open) $('sessionDialog').showModal(); }
function clearConversation() {
  renderGeneration++;
  controller?.abort();
  $('messages').replaceChildren();
  selectedEvidence = [];
  renderEvidence(); clearBlobs();
}
function updateEnabled() { $('question').disabled = !session; $('send').disabled = !session || busy; $('stop').classList.toggle('hidden', !busy); }
async function init() {
  config = await (await fetch('/api/config')).json();
  if (matchMedia('(max-width:1050px)').matches) document.body.classList.add('drawer-closed');
  if (!config.auth_ready) { showDialog(); return; }
  $('setupState').classList.add('hidden'); $('loginState').classList.remove('hidden');
  $('authBadge').textContent = 'Sign-in required'; notice('Sign in to start a permitted customer or staff session.');
  setAuthBusy(true);
  try {
    const [core, authModule] = await Promise.all([import('https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js'), import('https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js')]);
    firebaseApi = authModule; firebaseAuth = authModule.getAuth(core.initializeApp(config.firebase));
    await authModule.setPersistence(firebaseAuth, authModule.inMemoryPersistence);
    showDialog();
  } catch { $('sessionError').textContent = 'Firebase could not load. Check your connection and web configuration.'; showDialog(); }
  finally { setAuthBusy(false); }
}
async function signedIn() {
  await api('/api/account/bootstrap', { method: 'POST', body: '{}' });
  await firebaseAuth.currentUser.getIdToken(true);
  principal = await (await api('/api/me')).json();
  $('password').value = ''; $('customToken').value = '';
  $('loginState').classList.add('hidden'); $('roleState').classList.remove('hidden');
  $('identity').textContent = 'Assigned role: ' + principal.role.replaceAll('_', ' ') + ' · Account UID: ' + principal.uid;
  const evaluator = principal.role === 'evaluator';
  $('role').disabled = !evaluator; $('customerId').disabled = !evaluator;
  $('role').value = evaluator ? 'customer' : principal.role;
  $('customerId').value = principal.customer_id || '';
  $('evaluationLabel').textContent = evaluator ? 'Evaluator privileges: select a narrower role for this session.' : principal.role === 'customer' && !principal.customer_id ? 'Customer access is active for policies. An administrator must link your existing RideWise customer record before bookings or payments become available.' : 'Your customer scope and role are assigned by the server.';
  $('authBadge').textContent = 'Firebase verified'; $('authBadge').classList.add('verified');
  roleChanged();
  if (!evaluator) await startSession();
}
function roleChanged() { $('customerField').classList.toggle('hidden', $('role').value !== 'customer' || (principal?.role === 'customer' && !principal.customer_id)); }
function authMode(signUp) {
  creatingAccount = signUp;
  $('signInTab').classList.toggle('selected', !signUp); $('signUpTab').classList.toggle('selected', signUp);
  $('emailLogin').textContent = signUp ? 'Create customer account' : 'Sign in';
  $('loginHint').textContent = signUp ? 'Create your Customer account with email or Google.' : 'Sign in with your email or Google account.';
  $('signUpHint').classList.toggle('hidden', !signUp); $('forgotPassword').classList.toggle('hidden', signUp);
  $('password').autocomplete = signUp ? 'new-password' : 'current-password'; $('password').minLength = signUp ? 8 : 1;
  $('sessionError').textContent = '';
}
function setAuthBusy(value) {
  authBusy = value;
  for (const id of ['emailLogin','googleLogin','tokenLogin','signInTab','signUpTab','forgotPassword']) $(id).disabled = value;
}
function authError(error) {
  const code = /^auth\/[a-z-]+$/.test(error?.code || '') ? ` (${error.code})` : '';
  const hints = {'auth/operation-not-allowed':'This sign-in method is not enabled in Firebase. Ask the administrator to enable it.', 'auth/popup-blocked':'Allow the Google sign-in popup and retry.', 'auth/popup-closed-by-user':'Google sign-in was closed. You can try again.', 'auth/account-exists-with-different-credential':'Use your existing sign-in method for this email first.', 'auth/invalid-credential':'The email or password could not be verified.', 'auth/email-already-in-use':'An account already exists for this email. Sign in instead.', 'auth/weak-password':'Choose a stronger password.', 'auth/network-request-failed':'The authentication service could not be reached. Check your connection and retry.'};
  $('sessionError').textContent = (hints[error?.code] || 'Sign-in or assigned access could not be verified. Check credentials and administrator role assignment.') + code;
}
async function login(custom = false) {
  $('sessionError').textContent = '';
  if (!firebaseAuth || authBusy) return;
  setAuthBusy(true);
  try {
    if (custom) { const token = $('customToken').value; $('customToken').value = ''; await firebaseApi.signInWithCustomToken(firebaseAuth, token); }
    else { const password = $('password').value; $('password').value = ''; const email = $('email').value.trim(); if (creatingAccount) await firebaseApi.createUserWithEmailAndPassword(firebaseAuth, email, password); else await firebaseApi.signInWithEmailAndPassword(firebaseAuth, email, password); }
    await signedIn();
  } catch (error) { authError(error); } finally { setAuthBusy(false); }
}
async function googleLogin() {
  if (!firebaseAuth || authBusy) return;
  $('sessionError').textContent = ''; setAuthBusy(true);
  try { const google = new firebaseApi.GoogleAuthProvider(); google.setCustomParameters({prompt:'select_account'}); await firebaseApi.signInWithPopup(firebaseAuth, google); await signedIn(); }
  catch (error) { authError(error); } finally { setAuthBusy(false); }
}
async function forgotPassword() {
  if (!firebaseAuth || authBusy) return;
  if (!$('email').value.trim() || !$('email').checkValidity()) { $('sessionError').textContent = 'Enter your email address first.'; return; }
  setAuthBusy(true);
  try { await firebaseApi.sendPasswordResetEmail(firebaseAuth, $('email').value.trim()); $('sessionError').textContent = 'If this account supports email sign-in, check your inbox for reset instructions.'; }
  catch { $('sessionError').textContent = 'Reset instructions could not be requested. Please retry.'; } finally { setAuthBusy(false); }
}
async function startSession() {
  $('sessionError').textContent = '';
  try {
    const role = $('role').value;
    const next = await (await api('/api/session', { method: 'POST', body: JSON.stringify({ role, customer_id: role === 'customer' ? ($('customerId').value.trim().toUpperCase() || null) : null }) })).json();
    clearConversation(); session = next;
    $('scope').textContent = role === 'customer' ? (session.customer_id ? 'Customer · ' + session.customer_id : 'Customer · policy access') : 'Support agent';
    $('principalLabel').textContent = principal.role === 'evaluator' ? 'Firebase evaluator · selected role' : 'Firebase verified · assigned role';
    $('sessionDialog').close(); updateEnabled();
    notice('Read-only session ready.' + (!config.model_ready ? ' NeoStats model setup is pending; direct lookups and source excerpts are available.' : ''));
    if (role === 'customer' && !session.customer_id) notice('Policies are available. Ask the administrator to link your customer record for personal bookings and payments.');
    const intro = el('div', undefined, 'welcome'); intro.append(el('div', 'YOUR SESSION IS READY', 'eyebrow'), el('h2', 'What would you\nlike to know?'), el('p', 'Ask about a booking, refund, charge or policy. Every answer includes its source.'));
    const suggestions = el('div', undefined, 'suggestions');
    for (const question of role === 'customer' ? (session.customer_id ? ['Show my bookings', 'What are the refund rules?', 'How do I charge an EV?', 'What is my KYC status?'] : ['What are the refund rules?', 'How do I charge an EV?', 'What are the late return penalties?', 'What is the deposit policy?']) : ['Count bookings by hub', 'What are the refund rules?', 'List active vehicles by hub', 'What are the late return penalties?']) {
      const b = el('button', question); b.addEventListener('click', () => sendQuestion(question)); suggestions.append(b);
    }
    intro.append(suggestions); $('messages').append(intro); $('question').focus();
  } catch (e) { $('sessionError').textContent = e.message; }
}
function messageNode(text, user = false) {
  if ($('messages').querySelector('.welcome')) $('messages').replaceChildren();
  const card = el('article', undefined, 'message ' + (user ? 'user' : 'assistant'));
  if (!user) card.append(el('div', 'RIDEWISE ASSIST', 'message-label'));
  const body = el('div', text, 'answer-text'); card.append(body); $('messages').append(card);
  return { card, body };
}
async function sendQuestion(text) {
  if (!session) { showDialog(); return; }
  if (busy || !text.trim()) return;
  busy = true; updateEnabled(); notice('Gathering permitted evidence…');
  const version = renderGeneration, current = { ...session }, requestId = crypto.randomUUID();
  messageNode(text, true); const { card, body } = messageNode('');
  const routing = el('details', undefined, 'routing'); routing.open = true; routing.append(el('summary', 'Routing & execution'));
  const workers = el('div', undefined, 'workers'), summaries = el('div', '', 'worker-summary'); routing.append(workers, summaries); card.insertBefore(routing, body);
  const nodes = new Map(); controller = new AbortController();
  let final = false;
  try {
    const response = await api('/api/chat/stream', { method: 'POST', signal: controller.signal, body: JSON.stringify({ session_id: current.session_id, generation: current.generation, message: text.trim(), request_id: requestId }) });
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
    while (true) {
      const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const blocks = buffer.split('\n\n'); buffer = blocks.pop();
      for (const block of blocks) {
        if (!block.startsWith('data: ')) continue;
        const event = JSON.parse(block.slice(6));
        if (renderGeneration !== version || event.request_id !== requestId || event.generation !== current.generation) continue;
        if (event.type === 'worker') {
          if (!nodes.has(event.worker)) { const node = el('span', '', 'worker'); workers.append(node); nodes.set(event.worker, node); }
          const node = nodes.get(event.worker); node.className = 'worker ' + event.status;
          node.textContent = (event.status === 'completed' ? '✓ ' : event.status === 'failed' ? '! ' : '· ') + event.worker + ' · ' + event.status;
          node.title = event.summary + ' · ' + event.elapsed_ms + ' ms since request start'; summaries.textContent = event.summary;
        } else if (event.type === 'final') {
          final = true; body.textContent = event.answer;
          const badges = el('div', undefined, 'evidence-badges');
          for (const [kind, label] of [['sql', 'Executed SQL'], ['pdf', 'PDF sources'], ['calculation', 'Calculation']]) {
            if (!event.evidence.some(e => e.kind === kind)) continue;
            const badge = el('button', label + ' ↗'); badge.addEventListener('click', () => { selectedEvidence = event.evidence; activeTab = kind; document.body.classList.remove('drawer-closed'); renderEvidence(); }); badges.append(badge);
          }
          card.append(badges);
          if (event.notices?.length) card.append(el('p', event.notices.join('\n'), 'notice'));
          notice(event.state === 'answered' ? 'Answer ready. Inspect its source badges.' : 'No business answer was issued: ' + event.state.replaceAll('_', ' '));
        }
      }
      $('messages').scrollTop = $('messages').scrollHeight;
      if (done) break;
    }
    if (!final && version === renderGeneration) throw new Error('Stream interrupted. No completed answer was received.');
    if (final && version === renderGeneration) $('question').value = '';
  } catch (e) {
    if (version === renderGeneration) { body.textContent = e.name === 'AbortError' ? 'Request stopped. No completed answer was issued.' : e.message; notice('You can edit and retry your question.'); $('question').value = text; }
  } finally { busy = false; updateEnabled(); }
}
function table(values) { const t = el('table'); for (const [k, v] of Object.entries(values)) { const row = el('tr'); row.append(el('td', k.replaceAll('_', ' ')), el('td', String(v ?? 'Not recorded'))); t.append(row); } return t; }
function renderEvidence() {
  for (const b of $('drawerTabs').querySelectorAll('button')) b.classList.toggle('selected', b.dataset.tab === activeTab);
  const container = $('evidenceContent'); container.replaceChildren();
  const items = selectedEvidence.filter(e => e.kind === activeTab);
  if (!items.length) { const empty = el('div', undefined, 'evidence-empty'); empty.append(el('span', '▤'), el('h3', 'Trust starts with proof.'), el('p', 'Select an answer’s evidence badge. No source is selected for this tab.')); container.append(empty); return; }
  for (const e of items) {
    const card = el('section', undefined, 'source-card'); card.append(el('h3', e.kind === 'pdf' ? e.filename : e.kind === 'sql' ? e.id + ' · Executed SQL' : e.title));
    const body = el('div', undefined, 'source-body'); card.append(body);
    if (e.kind === 'sql') {
      body.append(el('p', e.scope), el('pre', e.sql), el('p', 'Bound parameters'), el('pre', JSON.stringify(e.parameters, null, 2)), el('p', `${e.rows.length} displayed rows · ${e.duration_ms} ms${e.truncated ? ' · limited result' : ''}`), el('pre', JSON.stringify(e.rows, null, 2)));
    } else if (e.kind === 'pdf') {
      body.append(el('p', `Page ${e.page} · Version ${e.version}`), el('p', e.method), el('pre', e.excerpt), el('p', 'SHA-256 ' + e.hash, 'hash'));
      const open = el('button', 'Open original PDF ↗'); open.addEventListener('click', async () => {
        const blank = window.open('', '_blank');
        try { const response = await api(e.url.split('#')[0]); const url = URL.createObjectURL(await response.blob()); blobs.add(url); if (blank) { blank.opener = null; blank.location = url + '#page=' + e.page; } else notice('Allow the PDF popup to open the original document.'); } catch (err) { blank?.close(); notice(err.message); }
      }); body.append(open);
    } else { body.append(el('p', e.formula), el('p', 'Inputs'), table(e.inputs), el('p', 'Calculated / recorded'), table(e.values), el('p', e.warning), el('p', 'Sources: ' + e.sources.join(', '))); }
    container.append(card);
  }
}
async function reset() {
  if (!session) { showDialog(); return; }
  controller?.abort();
  try { const result = await (await api(`/api/conversation/${session.session_id}/reset`, { method: 'POST' })).json(); session.generation = result.generation; clearConversation(); $('question').value = ''; notice('New conversation started. Previous context and evidence cleared.'); } catch (e) { notice(e.message); }
}
$('chatForm').addEventListener('submit', e => { e.preventDefault(); sendQuestion($('question').value); });
$('question').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuestion($('question').value); } });
$('stop').addEventListener('click', () => controller?.abort());
$('newChat').addEventListener('click', reset);
$('newChatMobile').addEventListener('click', reset);
$('sessionNav').addEventListener('click', showDialog); $('switchSession').addEventListener('click', showDialog);
$('closeSession').addEventListener('click', () => $('sessionDialog').close());
$('closeDrawer').addEventListener('click', () => document.body.classList.add('drawer-closed'));
$('openEvidence').addEventListener('click', () => document.body.classList.toggle('drawer-closed'));
$('conversationNav').addEventListener('click', () => { $('sessionDialog').close(); $('question').focus(); });
$('role').addEventListener('change', roleChanged); $('emailAuthForm').addEventListener('submit', e => {e.preventDefault(); login();}); $('tokenLogin').addEventListener('click', () => login(true)); $('startSession').addEventListener('click', startSession);
$('signInTab').addEventListener('click', () => authMode(false)); $('signUpTab').addEventListener('click', () => authMode(true)); $('googleLogin').addEventListener('click', googleLogin); $('forgotPassword').addEventListener('click', forgotPassword);
$('drawerTabs').addEventListener('click', e => { if (e.target.dataset.tab) { activeTab = e.target.dataset.tab; renderEvidence(); } });
for (const b of document.querySelectorAll('[data-question]')) b.addEventListener('click', () => sendQuestion(b.dataset.question));
$('policiesNav').addEventListener('click', async () => {
  if (!session) { showDialog(); return; }
  try {
    const list = await (await api('/api/policies')).json(); document.body.classList.remove('drawer-closed'); activeTab = 'pdf'; selectedEvidence = list.map(p => ({ ...p, kind: 'pdf', page: 1, version: 'See original document', method: p.reviewed ? 'Hash matches reviewed source' : 'Source changed: re-review required', hash: 'Available in answer evidence', excerpt: 'Browse the original document. This catalogue does not imply a document was used in an answer.', url: '/api/policies/' + p.key })); renderEvidence();
  } catch (e) { notice(e.message); }
});
async function signOut() {
  controller?.abort();
  try { if (session) await api('/api/session/' + session.session_id, { method: 'DELETE' }); } catch {}
  await firebaseApi?.signOut(firebaseAuth); session = null; principal = null; clearConversation(); updateEnabled();
  authMode(false);
  $('scope').textContent = 'Not signed in'; $('principalLabel').textContent = 'Firebase authentication'; $('authBadge').textContent = config.auth_ready ? 'Sign-in required' : 'Setup required'; $('authBadge').classList.remove('verified'); $('roleState').classList.add('hidden'); if (config.auth_ready) $('loginState').classList.remove('hidden'); showDialog();
}
$('signOut').addEventListener('click', signOut);
$('signOutSession').addEventListener('click', signOut);
init().catch(() => notice('Application configuration could not load. Check the local server and retry.'));
