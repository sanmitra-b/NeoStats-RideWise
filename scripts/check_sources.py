import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config

manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in config.DATA.iterdir() if p.is_file()}
target = config.ROOT / 'derived' / 'source_manifest.json'
if target.exists():
    original = json.loads(target.read_text())
    if original != manifest:
        raise SystemExit('Source pack changed; review before continuing.')
    print('All original source hashes match the baseline.')
else:
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2))
    print('Source hash baseline recorded in ignored derived storage.')
