"""Read-only validation for the documentation change, not application tests."""
from pathlib import Path
import json
import re
import struct
import subprocess
from urllib.parse import unquote, urlsplit
import yaml

ROOT = Path(__file__).resolve().parents[3]
FILES = [ROOT / 'README.md', ROOT / '.github/pull_request_template.md',
         *sorted((ROOT / 'docs/reference').glob('*.md')),
         ROOT / 'docs/screenshots/2026-10-12-product/GUIA.md',
         ROOT / 'docs/audits/2026-10-12-github-product/README.md']
errors = []
links = 0
images = []

def anchors(source):
    seen = {}
    result = set()
    for heading in re.findall(r'^#{1,6}\s+(.+)$', source, re.M):
        slug = re.sub(r'[^\w\- ]', '', heading.lower().replace('`', '')).replace(' ', '-')
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug + (f'-{count}' if count else ''))
    return result

for file in FILES:
    source = file.read_text()
    for match in re.finditer(r'(!?)\[[^\]]*\]\(([^)]+)\)', source):
        destination = match.group(2).split(' "', 1)[0].strip('<>')
        url = urlsplit(destination)
        if url.scheme or url.netloc:
            continue
        target = (file.parent / unquote(url.path)).resolve() if url.path else file
        links += 1
        if not target.exists():
            errors.append(f'{file.relative_to(ROOT)}: missing {destination}')
        elif url.fragment and target.is_file() and target.suffix == '.md':
            if unquote(url.fragment) not in anchors(target.read_text()):
                errors.append(f'{file.relative_to(ROOT)}: missing anchor {destination}')
        if match.group(1):
            images.append(target)

for path in sorted(set(images)):
    header = path.read_bytes()[:24]
    if header[:8] != b'\x89PNG\r\n\x1a\n':
        errors.append(f'Invalid PNG: {path.relative_to(ROOT)}')
    else:
        width, height = struct.unpack('>II', header[16:24])
        if width < 800 or height < 500:
            errors.append(f'Unexpected image size: {width}x{height}')
        print(f'PNG {path.relative_to(ROOT)}: {width}x{height}')

forms = sorted((ROOT / '.github/ISSUE_TEMPLATE').glob('*.yml'))
for path in forms:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data['name'], str) and isinstance(data['description'], str)
    assert isinstance(data['body'], list) and data['body']
    ids = [field['id'] for field in data['body'] if field.get('type') != 'markdown']
    assert len(ids) == len(set(ids))
    assert all(field['type'] in {'markdown','input','textarea','dropdown','checkboxes'} for field in data['body'])
    assert all('label' in field['attributes'] for field in data['body'] if field['type'] != 'markdown')
    print(f'Issue form parsed: {path.relative_to(ROOT)}')

check = subprocess.run(['git','diff','--check'], cwd=ROOT, capture_output=True, text=True)
if check.returncode:
    errors.append(check.stdout + check.stderr)

print(json.dumps({'markdown_files':len(FILES),'local_links':links,'readme_images':len(set(images)),
                  'issue_forms':len(forms),'diff_check_exit':check.returncode,'errors':errors}, indent=2))
raise SystemExit(1 if errors else 0)
