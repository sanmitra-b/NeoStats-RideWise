import asyncio
from app import config
from app.provider import Provider, ProviderUnavailable
import pytest
from app.models import Plan
from app.policies import Policies

def test_no_model_fallback(monkeypatch):
    monkeypatch.setattr(config,'BASE_URL','')
    p=Provider()
    with pytest.raises(ProviderUnavailable): asyncio.run(p.complete('test',{},Plan))

def test_changed_policy_hash_blocks_calculation(tmp_path):
    from app.policies import FILES
    import shutil
    for filename in FILES.values(): shutil.copy(config.DATA/filename,tmp_path/filename)
    with (tmp_path/FILES['refund_v2']).open('ab') as f: f.write(b'\nchanged')
    p=Policies(tmp_path)
    assert 'refund_v2' not in p.valid
    with pytest.raises(ValueError): p.require('refund_v2')
