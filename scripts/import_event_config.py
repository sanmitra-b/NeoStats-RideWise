"""Read literal configuration from the provided wrapper without executing it or printing secrets."""
import ast
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config

def main():
    target = config.ROOT / '.env'
    if target.exists():
        raise SystemExit('.env already exists; preserving it. Update it manually if needed.')
    tree = ast.parse((config.DATA / 'sample_open_ai_wrapper.py').read_text())
    values = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for k in node.keywords:
                name = {'base_url': 'NEOSTATS_BASE_URL', 'api_key': 'NEOSTATS_API_KEY', 'model': 'NEOSTATS_MODEL'}.get(k.arg)
                if name and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str):
                    values[name] = k.value.value
    text = (config.ROOT / '.env.example').read_text()
    import json
    for name, value in values.items():
        if any(word in value.lower() for word in ('your_', 'your-', '<api', 'placeholder')):
            continue
        text = text.replace(name + '=\n', name + '=' + json.dumps(value) + '\n')
    target.write_text(text, encoding='utf-8')
    print('Ignored local environment file created. No credential values were displayed.')

if __name__ == '__main__':
    main()
