import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATA = Path(os.getenv('RIDEWISE_DATA_DIR', str(ROOT / 'Neostats Hackathon AI Usecase 3' / 'Neostats Hackathon AI Usecase')))
DB = DATA / 'ridewise.db'
PROJECT = os.getenv('FIREBASE_PROJECT_ID', '')
WEB = {k: os.getenv(v, '') for k, v in {
    'apiKey': 'FIREBASE_WEB_API_KEY', 'authDomain': 'FIREBASE_AUTH_DOMAIN',
    'projectId': 'FIREBASE_PROJECT_ID', 'appId': 'FIREBASE_APP_ID'}.items()}
BASE_URL = os.getenv('NEOSTATS_BASE_URL', '')
API_KEY = os.getenv('NEOSTATS_API_KEY', '')
MODEL = os.getenv('NEOSTATS_MODEL', '')
MAPPING = Path(os.getenv('CUSTOMER_MAPPING_FILE', str(ROOT / 'secrets' / 'customer_mapping.json')))
# Set the embedding model ONLY if supplied by NeoStats; otherwise use the FAQ local exception.
EMBEDDING_MODEL = os.getenv('NEOSTATS_EMBEDDING_MODEL', '')
LOCAL_EMBEDDING_MODEL = os.getenv('LOCAL_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')
VECTOR_PATH = ROOT / 'derived' / 'qdrant'
EMBEDDING_CACHE = ROOT / 'derived' / 'embedding_models'
HISTORY = ROOT / 'derived' / 'chat_history.db'
TIMEOUT = min(45, max(5, int(os.getenv('MODEL_TIMEOUT_SECONDS', '25'))))
