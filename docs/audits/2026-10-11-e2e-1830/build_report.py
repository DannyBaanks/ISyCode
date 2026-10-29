"""Render the saved audit and validate its screenshot references locally."""
from pathlib import Path
import re
from markdown_it import MarkdownIt

OUT = Path(__file__).resolve().parent
source = OUT / "AUDITORIA.md"
text = source.read_text()
# CommonMark requires angle brackets around destinations containing spaces.
text = re.sub(r'(!\[[^\]]*\])\((/home/[^\n)]*\.png)\)', r'\1(<\2>)', text)
source.write_text(text)
images = re.findall(r'!\[([^\]]*)\]\(<([^>]+)>\)', text)
assert len(images) == 24
for alt, filename in images:
    path = Path(filename)
    assert path.is_file() and path.parent == OUT, filename
    text = text.replace(f'![{alt}](<{filename}>)', f'![{alt}]({path.name})')
body = MarkdownIt().render(text)
assert body.count('<img ') == 24
# Source references are clickable in Codex Markdown; preserve them as labels
# with their full destination in a title when viewed over local HTTP.
body = re.sub(r'<a href="(/home/[^"]+)">([^<]+)</a>',
              r'<span title="\1">\2</span>', body)
for number in range(1, 7):
    body = body.replace(f'<h3>F{number} ', f'<h3 id="F{number}">F{number} ')
body = body.replace('<h2>Capturas inspeccionadas, en orden</h2>',
                    '<h2 id="capturas">Capturas inspeccionadas, en orden</h2>')
# Retain the presentation shell from the existing generated report.
shell = (OUT / 'report.html').read_text().split('<h1>', 1)[0]
(OUT / 'report.html').write_text(shell + body + '</main></html>\n')
print('Rendered 24 screenshot references and six finding anchors.')
