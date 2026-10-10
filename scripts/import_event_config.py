"""Read literal configuration from the provided wrapper without executing it or printing secrets."""
import ast
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config

def main():
    target = config.ROOT / '.env'
    tree = ast.parse((config.DATA / 'sample_open_ai_wrapper.py').read_text())
    symbols = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for name in node.targets:
                if isinstance(name, ast.Name):
                    symbols[name.id] = node.value.value
    def literal(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return symbols.get(node.id)
        if isinstance(node, ast.JoinedStr):
            pieces = [literal(n.value) if isinstance(n, ast.FormattedValue) and not n.format_spec and n.conversion == -1 else literal(n) for n in node.values]
            return ''.join(pieces) if all(p is not None for p in pieces) else None
        return None
    values = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for k in node.keywords:
                name = {'base_url': 'NEOSTATS_BASE_URL', 'api_key': 'NEOSTATS_API_KEY', 'model': 'NEOSTATS_MODEL'}.get(k.arg)
                value = literal(k.value)
                if name and value is not None:
                    values[name] = value
    text = target.read_text() if target.exists() else (config.ROOT / '.env.example').read_text()
    import json
    for name, value in values.items():
        if any(word in value.lower() for word in ('your_', 'your-', '<api', 'placeholder')):
            continue
        text = text.replace(name + '=\n', name + '=' + json.dumps(value) + '\n')
    target.write_text(text, encoding='utf-8')
    print('Blank event fields populated in ignored local environment file. Existing nonblank values preserved; no credentials displayed.')

if __name__ == '__main__':
    main()
