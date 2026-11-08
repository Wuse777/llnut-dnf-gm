#!/usr/bin/env python3
"""Small offline check of public entry-point links, screenshots and versions."""
from pathlib import Path
import ast
import json
import re
import sys
import tomllib
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]
DOCS=('README.md','CHANGELOG.md','docs/README.md','docs/DEPLOYMENT.md',
      'docs/DEVELOPMENT.md','docs/SCREENSHOTS.md','docs/DOCUMENTATION.md',
      'docs/RELEASING.md','docs/images/README.md',
      'docs/history/DEPLOYMENT-BATCHES-202610-20261106.md',
      'docs/reports/PUBLIC-DOCS-20261107.md')


def check():
    errors=[]
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    files=[ROOT/p for p in DOCS]+[ROOT/f'docs/releases/v{version}.md']
    for path in files:
        text=path.read_text(encoding='utf-8')
        targets=re.findall(r'\]\(([^\s)]+)(?:\s+"[^"]*")?\)',text)
        targets+=re.findall(r'(?:src|href)="([^"]+)"',text)
        for target in targets:
            if target.startswith(('#','https://','http://','mailto:')):continue
            relative=unquote(target.split('#')[0])
            if not relative:continue
            dest=(path.parent/relative).resolve()
            if not dest.is_relative_to(ROOT) or not dest.exists():
                errors.append(f'{path.relative_to(ROOT)}: missing or external local path {target}')
    package=json.loads((ROOT/'web/package.json').read_text(encoding='utf-8'))
    lock=json.loads((ROOT/'web/package-lock.json').read_text(encoding='utf-8'))
    tree=ast.parse((ROOT/'src/dnfgm/__init__.py').read_text(encoding='utf-8'))
    namespace={target.id:ast.literal_eval(node.value) for node in tree.body
               if isinstance(node,ast.Assign) for target in node.targets
               if isinstance(target,ast.Name) and target.id=='__version__'}
    for label,value in [('python',namespace['__version__']),('web',package['version']),
                        ('lock',lock['version']),('lock-root',lock['packages']['']['version'])]:
        if value!=version:errors.append(f'{label} version mismatch: {value} vs {version}')
    app=(ROOT/'src/dnfgm/app.py').read_text(encoding='utf-8')
    if "return {'ok':True,'version':__version__}" not in app:
        errors.append('Readiness must use shared application version')
    for name in ('mail-desktop.jpg','picker-mobile.jpg','character-mobile.jpg'):
        image=ROOT/'docs/images'/name
        if not image.read_bytes().startswith(b'\xff\xd8\xff') or image.stat().st_size>1024*1024:
            errors.append(f'Invalid or unnecessarily large screenshot: {name}')
    if errors:
        print('\n'.join(errors),file=sys.stderr);return 1
    print(f'PASS: {len(files)} document entry points, local paths, 3 screenshots and version {version}; no network/database used.')
    return 0


if __name__=='__main__':raise SystemExit(check())
