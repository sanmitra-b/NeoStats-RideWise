import hashlib
from app import config, ocr
from app.policies import Policies, HASHES, VISUALS


def test_real_image_pages_are_embedded_with_citations():
    policies = Policies(config.DATA)
    assert policies.ocr_ready
    targets = [p for p in policies.pages if p['key'] in ocr.TARGETS]
    assert len(targets) == 7
    for page in targets:
        assert page['ocr']['status'] == 'complete'
        assert page['ocr']['lines'] > 0
        assert 'OCR extraction' in page['excerpt']
        assert page['url'].endswith('#page=' + str(page['page']))
        assert page['hash'] == HASHES[page['key']]
    annexures = {(p['key'], p['page']): p for p in targets}
    assert '75%' in annexures['refund_v2', 2]['excerpt'].split('Reviewed signed')[0]
    assert 'GOLD | 30 minutes' in annexures['penalty', 3]['excerpt']
    for key, visual in VISUALS.items():
        assert visual in annexures[key]['excerpt']


def test_cache_is_bound_to_content_and_page(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'OCR_CACHE', tmp_path)
    calls = []
    def recognize(path, page):
        calls.append(page)
        return [([[0, 0], [10, 0], [10, 10], [0, 10]], 'Image text', .95)]
    monkeypatch.setattr(ocr, '_recognize', recognize)
    digest = hashlib.sha256(b'original').hexdigest()
    first = ocr.extract(tmp_path / 'policy.pdf', digest, 1)
    assert ocr.extract(tmp_path / 'policy.pdf', digest, 1) == first
    assert calls == [1]
    ocr.extract(tmp_path / 'policy.pdf', hashlib.sha256(b'changed').hexdigest(), 1)
    ocr.extract(tmp_path / 'policy.pdf', digest, 2)
    assert calls == [1, 1, 2]


def test_failed_ocr_is_visible_and_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'OCR_CACHE', tmp_path)
    def fail(*args):
        raise RuntimeError('local OCR failed')
    monkeypatch.setattr(ocr, '_recognize', fail)
    assert ocr.extract(tmp_path / 'policy.pdf', 'hash', 1)[1]['status'] == 'failed'
    assert not list(tmp_path.glob('*.json'))
    policies = Policies(config.DATA)
    assert not policies.ocr_ready
    page = next(p for p in policies.pages if p['key'] == 'refund_v2' and p['page'] == 2)
    assert VISUALS['refund_v2', 2] in page['excerpt']
    assert page['ocr']['status'] == 'failed'
