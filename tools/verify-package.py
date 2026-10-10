#!/usr/bin/env python3
"""Verifica o pacote publicado sem rede, infraestrutura ou dependências externas."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
import tarfile
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))

def digest(data):
    return hashlib.sha256(data).hexdigest()

def checked_path(path):
    target = ROOT / path
    if '..' in Path(path).parts or Path(path).is_absolute():
        raise ValueError('Caminho fora do pacote: ' + path)
    return target

def local_links(path):
    text = path.read_text(encoding='utf-8-sig')
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    for target in re.findall(r'\]\(([^)]+)\)', text):
        target = target.strip().strip('<>')
        if re.match(r'^(?:[a-zA-Z]+:|#)', target):
            continue
        yield unquote(target.split('#', 1)[0])

def verify():
    inventory = load('docs/data/package-files.json')
    sources = load('packages/source-files.json')
    manifest = load('packages/manifest.json')
    failures = []
    normalized = 0
    total = 0
    for row in inventory['files']:
        path = checked_path(row['path'])
        if not path.is_file() and not path.is_symlink():
            failures.append({'path': row['path'], 'error': 'missing'})
            continue
        data = path.readlink().as_posix().encode() if path.is_symlink() else path.read_bytes()
        total += len(data)
        if digest(data) != row['sha256']:
            if row.get('allow_crlf_normalization') and digest(data.replace(b'\r\n', b'\n')) == row['sha256']:
                normalized += 1
            else:
                failures.append({'path': row['path'], 'error': 'sha256_mismatch'})
    # The source inventory and actual candidate archive must contain exactly the same paths.
    archive_members = 0
    for product in manifest['products']:
        expected = {r['path'].removeprefix('repos/'): r for r in sources['files'] if r['path'].startswith(product['path'] + '/')}
        for item in product['archives'] + [product['patch']]:
            path = checked_path(item['path'])
            if digest(path.read_bytes()) != item['sha256']:
                failures.append({'path': item['path'], 'error': 'package_sha256_mismatch'})
        archive = next(a for a in product['archives'] if a['role'] == 'dualstack')
        actual = {}
        with tarfile.open(ROOT / archive['path'], 'r:gz') as handle:
            for member in handle:
                if member.isdir():
                    continue
                if member.isfile():
                    data = handle.extractfile(member).read()
                elif member.issym():
                    data = member.linkname.encode()
                else:
                    failures.append({'path': member.name, 'error': 'unexpected_tar_type'})
                    continue
                actual[member.name] = digest(data)
        archive_members += len(actual)
        if set(actual) != set(expected):
            failures.append({'path': archive['path'], 'error': 'source_path_set_mismatch'})
        for name, row in expected.items():
            if actual.get(name) != row['sha256']:
                failures.append({'path': name, 'error': 'source_archive_content_mismatch'})
    links = 0
    entry_docs = [ROOT / p for p in inventory['entry_documents']]
    for path in entry_docs:
        for target in local_links(path):
            links += 1
            if not (path.parent / target).exists():
                failures.append({'path': path.relative_to(ROOT).as_posix(), 'error': 'broken_link', 'target': target})
    for row in load('docs/data/key-metrics.json')['records']:
        path = checked_path(row['source'])
        if not path.exists():
            failures.append({'path': row['source'], 'error': 'metric_source_missing'})
        if row.get('json_pointer'):
            value = load(row['source'])
            for token in row['json_pointer'].lstrip('/').split('/'):
                token = token.replace('~1', '/').replace('~0', '~')
                value = value[int(token)] if isinstance(value, list) else value[token]
            if value != row['value']:
                failures.append({'path': row['source'], 'error': 'metric_value_mismatch', 'metric': row['id']})
    for case in load('docs/data/validation-matrix.json')['cases']:
        for field in ('test', 'evidence', 'report'):
            if not checked_path(case[field]).exists():
                failures.append({'path': case[field], 'error': 'validation_reference_missing'})
    evidence = load('docs/data/evidence-index.json')
    by_path = {r['path']: r for r in inventory['files']}
    for row in evidence['files']:
        if row['path'] not in by_path or by_path[row['path']]['sha256'] != row['sha256']:
            failures.append({'path': row['path'], 'error': 'evidence_inventory_mismatch'})
    return dict(status='passed' if not failures else 'failed', files_checked=len(inventory['files']),
                canonical_bytes=sum(r['bytes'] for r in inventory['files']), checkout_bytes=total,
                files_with_only_crlf_conversion=normalized, candidate_source_files=archive_members,
                public_evidence_files=len(evidence['files']), local_links_checked=links,
                failures=failures, scope='Integridade da entrega; não executa testes do produto ou benchmarks.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Salvar também o relatório JSON neste caminho')
    args = parser.parse_args()
    try:
        result = verify()
    except (OSError, ValueError, KeyError) as exc:
        result = dict(status='failed', error=str(exc))
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    display = dict(result)
    if len(display.get('failures', [])) > 20:
        display['failure_count'] = len(display['failures'])
        display['failures'] = display['failures'][:20]
        display['note'] = 'Saída limitada; use --output para salvar todas as falhas.'
    print(json.dumps(display, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    sys.exit(0 if result['status'] == 'passed' else 1)
