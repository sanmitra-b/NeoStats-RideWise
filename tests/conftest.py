import pytest
from app.provider import Provider

@pytest.fixture(autouse=True)
def no_live_model_calls(monkeypatch):
    # Automated verification never consumes the event endpoint/rate budget.
    monkeypatch.setattr(Provider, 'configured', lambda self: False)

@pytest.fixture(autouse=True)
def isolated_chat_history(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'HISTORY', tmp_path / 'test_chat_history.db')

@pytest.fixture(scope='session', autouse=True)
def isolated_policy_vectors(tmp_path_factory):
    from app import config, semantic
    original = config.VECTOR_PATH
    config.VECTOR_PATH = tmp_path_factory.mktemp('policy_vectors')
    try:
        yield
    finally:
        semantic.close()
        config.VECTOR_PATH = original
