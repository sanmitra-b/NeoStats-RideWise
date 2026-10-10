"""Dense policy retrieval: local Qdrant, with local or event-provided embeddings."""
import hashlib
import json
from threading import RLock
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5
from qdrant_client import QdrantClient, models
from . import config

CHUNK_WORDS = 220
OVERLAP_WORDS = 40
_lock = RLock()
_clients = {}
_indexes = {}
_embedders = {}

def chunks_for(pages):
    chunks = []
    for p in pages:
        # Keep native/reviewed text intact; OCR adds independent passages.
        for segment, content in enumerate(p.get('source_segments', [p['excerpt']])):
            words = content.split()
            for offset in range(0, len(words), CHUNK_WORDS - OVERLAP_WORDS):
                text = ' '.join(words[offset:offset + CHUNK_WORDS])
                chunks.append({'chunk_id': f"{p['id']}-segment-{segment}-chunk-{offset}", 'page_id': p['id'],
                               'key': p['key'], 'text': text})
                if offset + CHUNK_WORDS >= len(words):
                    break
    return chunks

class Embeddings:
    def __init__(self):
        self.remote = bool(config.EMBEDDING_MODEL)
        self.name = config.EMBEDDING_MODEL or config.LOCAL_EMBEDDING_MODEL
        if self.remote:
            from openai import OpenAI
            u = urlparse(config.BASE_URL)
            if not config.API_KEY or u.scheme != 'https' or not u.hostname or u.hostname in ('api.openai.com', 'generativelanguage.googleapis.com'):
                raise ValueError('Use only the embedding endpoint and credentials supplied by NeoStats.')
            self.model = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL, timeout=config.TIMEOUT, max_retries=0)
        else:
            from fastembed import TextEmbedding
            self.model = TextEmbedding(self.name, cache_dir=str(config.EMBEDDING_CACHE),
                                       threads=2, providers=['CPUExecutionProvider'])

    def documents(self, texts):
        if self.remote:
            response = self.model.embeddings.create(model=self.name, input=texts)
            return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
        return [v.tolist() for v in self.model.passage_embed(texts, batch_size=16)]

    def query(self, text):
        if self.remote:
            return self.documents([text])[0]
        return next(self.model.query_embed(text)).tolist()

def embedding():
    key = (config.EMBEDDING_MODEL, config.LOCAL_EMBEDDING_MODEL,
           str(config.EMBEDDING_CACHE), config.BASE_URL if config.EMBEDDING_MODEL else '')
    if key not in _embedders:
        _embedders[key] = Embeddings()
    return _embedders[key]

class PolicyIndex:
    def __init__(self, client, pages, embedder):
        self.client, self.embedder = client, embedder
        self.chunks = chunks_for(pages)
        fingerprint = json.dumps({'model': embedder.name,
            'provider': config.BASE_URL if embedder.remote else 'local', 'schema': 1,
            'chunks': self.chunks, 'sources': [(p['id'], p['hash']) for p in pages]}, sort_keys=True)
        self.collection = 'ridewise_policies_' + hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
        if not self.chunks:
            raise ValueError('No policy passages available for semantic search.')
        if client.collection_exists(self.collection):
            if client.count(self.collection, exact=True).count == len(self.chunks):
                return
            client.delete_collection(self.collection)
        vectors = embedder.documents([c['text'] for c in self.chunks])
        if len(vectors) != len(self.chunks) or not vectors or not vectors[0]:
            raise ValueError('Embedding provider returned an incomplete policy index.')
        client.create_collection(self.collection, vectors_config=models.VectorParams(
            size=len(vectors[0]), distance=models.Distance.COSINE))
        client.upsert(self.collection, points=[models.PointStruct(
            id=str(uuid5(NAMESPACE_URL, self.collection + c['chunk_id'])), vector=v, payload=c)
            for c, v in zip(self.chunks, vectors)], wait=True)

    def search(self, question, keys, limit=8):
        return self.client.query_points(self.collection, query=self.embedder.query(question),
            query_filter=models.Filter(must=[models.FieldCondition(key='key',
                match=models.MatchAny(any=sorted(keys)))]), limit=limit, with_payload=True).points

def get_index(pages):
    # Local Qdrant is a single-process store. Serialize client/index creation and inference.
    path = str(config.VECTOR_PATH)
    signature = hashlib.sha256(json.dumps(pages, sort_keys=True).encode()).hexdigest()
    key = (path, signature, config.EMBEDDING_MODEL, config.LOCAL_EMBEDDING_MODEL,
           config.BASE_URL if config.EMBEDDING_MODEL else '')
    with _lock:
        if key not in _indexes:
            if path not in _clients:
                config.VECTOR_PATH.mkdir(parents=True, exist_ok=True)
                _clients[path] = QdrantClient(path=path, force_disable_check_same_thread=True)
            _indexes[key] = PolicyIndex(_clients[path], pages, embedding())
        return _indexes[key]

def search(pages, question, keys):
    with _lock:
        index = get_index(pages)
        return index.search(question, keys), index.embedder.name

def close():
    with _lock:
        for client in _clients.values():
            client.close()
        _clients.clear()
        _indexes.clear()
        for key, embedder in list(_embedders.items()):
            if embedder.remote:
                embedder.model.close()
                del _embedders[key]
