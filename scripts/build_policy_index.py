"""Download/cache embeddings and build the local policy index before a demo."""
import sys
from pathlib import Path
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config, semantic
from app.policies import Policies

def main():
    started = perf_counter()
    try:
        policies = Policies(config.DATA)
        if not policies.ocr_ready:
            raise SystemExit('OCR incomplete. Check OCR dependencies and retry; unsuccessful pages are not cached.')
        print('OCR complete: all pages in PDFs 3, 4 and 5; cached by source hash, page, renderer and OCR version.')
        policies.prepare()
        if not policies.semantic_ready:
            raise SystemExit(policies.semantic_error)
        index = semantic.get_index(policies.pages)
        print(f'Qdrant index ready: {len(index.chunks)} passages from {len(policies.pages)} PDF pages; embedding model {index.embedder.name}; {perf_counter()-started:.2f} seconds.')
    finally:
        semantic.close()

if __name__ == '__main__':
    main()
