"""Local OCR for mixed text/image policy pages; originals are never written."""
import hashlib
import json
import threading
from importlib.metadata import version
from . import config

TARGETS = {'refund_v2', 'penalty', 'ev'}
DPI = 240
_lock = threading.RLock()
_engine = None


def _recognize(path, page):
    global _engine
    import pymupdf
    from rapidocr_onnxruntime import RapidOCR
    with _lock:
        if _engine is None:
            _engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
        with pymupdf.open(path) as document:
            # Render the whole page, including images on pages with a text layer.
            pixmap = document[page - 1].get_pixmap(dpi=DPI, alpha=False)
            result, _ = _engine(pixmap.tobytes('png'))
    return result or []


def extract(path, digest, page):
    try:
        signature = f'rapidocr-onnxruntime:{version("rapidocr-onnxruntime")}:pymupdf:{version("pymupdf")}:dpi:{DPI}:rows:1'
        key = hashlib.sha256(f'{digest}:{page}:{signature}'.encode()).hexdigest()
        cache = config.OCR_CACHE / (key + '.json')
        if cache.exists():
            cached = json.loads(cache.read_text(encoding='utf-8'))
            if cached['key'] == key:
                return cached['text'], cached['metadata']
        items = _recognize(path, page)
        # Keep neighboring cells on one row, preserving table associations.
        rows = []
        for box, text, confidence in sorted(items, key=lambda item: (min(p[1] for p in item[0]), min(p[0] for p in item[0]))):
            y = sum(p[1] for p in box) / len(box)
            height = max(p[1] for p in box) - min(p[1] for p in box)
            if rows and abs(rows[-1]['y'] - y) <= max(5, height * .45):
                rows[-1]['cells'].append((min(p[0] for p in box), text))
            else:
                rows.append({'y': y, 'cells': [(min(p[0] for p in box), text)]})
        text = '\n'.join(' | '.join(cell[1] for cell in sorted(row['cells'])) for row in rows)
        metadata = {'engine': 'RapidOCR / ONNX CPU', 'status': 'complete' if items else 'empty',
                    'dpi': DPI, 'lines': len(items), 'mean_confidence': round(sum(float(i[2]) for i in items) / len(items), 3) if items else None}
        # Empty/failing pages are retried, never cached as successful coverage.
        if items:
            config.OCR_CACHE.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_suffix('.tmp')
            temporary.write_text(json.dumps({'key': key, 'text': text, 'metadata': metadata}, ensure_ascii=False), encoding='utf-8')
            temporary.replace(cache)
        return text, metadata
    except Exception:
        return '', {'engine': 'RapidOCR / ONNX CPU', 'status': 'failed',
                    'message': 'Page OCR unavailable. Check local OCR dependencies and rebuild the policy index.'}
