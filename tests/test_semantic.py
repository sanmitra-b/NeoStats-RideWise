import pytest
from qdrant_client import QdrantClient
from app import config, semantic
from app.policies import Policies, FILES

@pytest.mark.parametrize('question,expected', [
    ('Can I get some of my money back if I call off the reservation?', 'refund_v1'),
    ('How much leeway do loyalty members get when dropping a bike off late?', 'penalty'),
    ('My ride ran out of juice. How do I plug it in?', 'ev'),
    ('Do I need to leave a security amount before taking the scooter?', 'rental'),
])
def test_real_embeddings_retrieve_paraphrases(question, expected):
    p = Policies(config.DATA)
    hits, name = semantic.search(p.pages, question, set(FILES))
    assert name == 'BAAI/bge-small-en-v1.5'
    assert expected in [h.payload['key'] for h in hits[:3]]

def test_page_citations_scores_and_annexure_provenance():
    p = Policies(config.DATA)
    pages = p.retrieve('Calling off the reservation', 'refund')
    assert any(e['id'] == 'PDF-refund_v2-2' for e in pages)
    assert all(e['key'] in {'rental', 'refund_v1', 'refund_v2'} for e in pages)
    assert all(e['url'].endswith('#page=' + str(e['page'])) for e in pages)
    hits = [e for e in pages if e['retrieval']['score'] is not None]
    assert hits and all(e['retrieval']['chunks'] for e in hits)
    assert all('Qdrant' in e['retrieval']['method'] for e in hits)

class TinyEmbedding:
    name = 'controlled-test-embedding'
    remote = False
    def documents(self, texts):
        return [[1.0, 0.0] if 'alpha' in t else [0.0, 1.0] for t in texts]
    def query(self, text):
        return [1.0, 0.0]

def page(pid, key, text, digest='original'):
    return {'id': pid, 'key': key, 'excerpt': text, 'hash': digest}

def test_qdrant_persistence_filters_and_changed_source_rebuild(tmp_path):
    embedder = TinyEmbedding()
    original = [page('PDF-a-1', 'refund', 'alpha policy'), page('PDF-b-1', 'ev', 'beta policy')]
    client = QdrantClient(path=str(tmp_path / 'qdrant'))
    index = semantic.PolicyIndex(client, original, embedder)
    assert index.search('query', {'refund'})[0].payload['key'] == 'refund'
    assert all(h.payload['key'] == 'ev' for h in index.search('query', {'ev'}))
    collection = index.collection
    client.close()
    client = QdrantClient(path=str(tmp_path / 'qdrant'))
    try:
        class ReuseEmbedding(TinyEmbedding):
            def documents(self, texts):
                pytest.fail('A complete persisted collection must not be re-embedded')
        assert semantic.PolicyIndex(client, original, ReuseEmbedding()).collection == collection
        changed = semantic.PolicyIndex(client, [page('PDF-new-1', 'refund', 'alpha new policy', 'changed')], embedder)
        assert changed.collection != collection
        assert all(h.payload['page_id'] == 'PDF-new-1' for h in changed.search('query', {'refund'}))
    finally:
        client.close()

def test_embedding_failure_does_not_silently_use_keyword_search(monkeypatch):
    def unavailable(*args):
        raise RuntimeError('controlled embedding outage')
    monkeypatch.setattr(semantic, 'search', unavailable)
    p = Policies(config.DATA)
    with pytest.raises(ValueError, match='no keyword search was substituted'):
        p.retrieve('Refund rules')
    import asyncio
    from app.assistant import answer
    from app.sessions import Session
    async def emit(event):
        pass
    result = asyncio.run(answer('What are the refund rules?', Session('a', 'customer', None), p, emit, 0))
    assert result['state'] == 'unavailable' and not result['evidence']

def test_ev_charging_suggestion_routes_to_policy_without_model_planning():
    from app.assistant import local_plan
    from app.sessions import Session
    plan = local_plan('How do I charge an EV?', Session('a', 'customer', None))
    assert plan.operation == 'policy' and plan.topic == 'ev'

def test_personal_embedding_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(config, 'EMBEDDING_MODEL', 'provided-embedding')
    monkeypatch.setattr(config, 'BASE_URL', 'https://api.openai.com/v1')
    with pytest.raises(ValueError, match='only the embedding endpoint'):
        semantic.Embeddings()
