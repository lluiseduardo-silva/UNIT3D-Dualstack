#!/usr/bin/env python3
"""Reanalisa evidências públicas e reconstrói candidatos com os patches, sem rede."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, 'PYTHONUTF8': '1'}


def run(args, cwd=ROOT):
    return subprocess.check_output(args, cwd=cwd, env=ENV, stderr=subprocess.PIPE)


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(work):
    results = {}
    for name, folder, expected in [
        ('candidate_soak', 'soak-rust-six-hours-v3', 'six-hours-v3-summary.json'),
        ('original_soak', 'rust-original-six-hours-v1', 'rust-original-six-hours-v1/summary.json'),
    ]:
        actual = json.loads(run([
            sys.executable, 'lab/dualstack/summarize-soak.py',
            'lab/dualstack/results/soak/' + folder,
        ]))
        saved = read('lab/dualstack/results/soak/' + expected)
        fields = ['load', 'windows', 'completed_rps', 'window_metrics_median',
                  'roles', 'max_observed_persistence_lag']
        for key in fields:
            require(actual[key] == saved[key], name + ': divergência em ' + key)
        results[name] = dict(status='passed', matched_fields=fields,
                             accepted=actual['load']['accepted'])

    actual = json.loads(run([
        sys.executable, 'lab/dualstack/analyze-original-soak.py',
        'lab/dualstack/results/soak/rust-original-six-hours-v1',
    ]))
    require(actual == read('lab/dualstack/results/soak/rust-original-six-hours-v1/analysis.json'),
            'Divergência na análise horária do original')
    results['original_hourly_analysis'] = dict(status='passed', exact_json_match=True)

    out = work / 'cache-recomputed.json'
    run([sys.executable, 'lab/dualstack/compare-capacity-cache.py',
         'lab/dualstack/results/capacity', str(out)])
    require(json.loads(out.read_text(encoding='utf-8')) ==
            read('lab/dualstack/results/capacity/capacity-cache-ab-comparison.json'),
            'Divergência na comparação A1/B/A2')
    results['cache_ab_analysis'] = dict(status='passed', exact_json_match=True,
                                        series=3, trials=27)

    for product in read('packages/manifest.json')['products']:
        target = work / product['name']
        target.mkdir()
        base = next(a for a in product['archives'] if a['role'] == 'original')
        with tarfile.open(ROOT / base['path'], 'r:gz') as archive:
            for entry in archive:
                destination = (target / entry.name).resolve()
                require(destination.is_relative_to(target.resolve()), 'Caminho inválido no tar')
                require(entry.isfile() or entry.isdir(), 'Tipo inesperado no tar')
                if entry.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.extractfile(entry).read())
        checkout = target / product['name']
        run(['git', 'init', '-q'], checkout)
        run(['git', 'config', 'core.autocrlf', 'false'], checkout)
        # Upstream tracks some files matched by its own ignore rules.
        run(['git', 'add', '-f', '-A'], checkout)
        patch = str(ROOT / product['patch']['path'])
        run(['git', 'apply', '--check', patch], checkout)
        run(['git', 'apply', '--index', patch], checkout)
        tree = run(['git', 'write-tree'], checkout).decode().strip()
        require(tree == product['candidate_tree'], product['name'] + ': árvore divergente')
        results[product['name'] + '_patch'] = dict(
            status='passed', reconstructed_tree=tree, matches_candidate_tree=True,
            base=product['base'], candidate=product['candidate'],
        )
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Salvar o relatório JSON')
    args = parser.parse_args()
    local = ROOT / '.local'
    local.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='evidence-check-', dir=local))
    # Preserve generated outputs for inspection; never modify original evidence.
    try:
        result = dict(status='passed', checks=check(work))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        result = dict(status='failed', error=str(exc))
    result['scope'] = 'Análise offline e reconstrução de fontes; sem nova carga ou replay privado.'
    result['work_directory'] = str(work.relative_to(ROOT))
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    print(text)
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    sys.exit(0 if result['status'] == 'passed' else 1)
