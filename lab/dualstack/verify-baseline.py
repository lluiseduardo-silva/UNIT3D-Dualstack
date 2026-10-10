#!/usr/bin/env python3
"""Gate do diagnostico original, nao uma aprovacao de dualstack ou performance."""
import json
from pathlib import Path

root = Path(__file__).parent / 'results' / 'baseline'
for mode in ('php', 'rust'):
    result = json.loads((root / f'baseline-{mode}.json').read_text())
    assert len(result['steps']) == 12, (mode, 'baseline incompleto')
    steps = {step['label']: step for step in result['steps']}
    for first, second in ((4, 6), (6, 4)):
        prefix = f'ipv{first}-ipv{second}'
        initial = steps[prefix + '/initial']
        assert 'failure reason' not in initial['response']
        assert initial['database_after_flush']['user'][0]['uploaded'] == 0
        duplicate = steps[prefix + '/second-started']
        if mode == 'php':
            assert 'failure reason' in duplicate['response']
        completed = steps[prefix + '/completed']['database_after_flush']
        assert len(completed['peer']) == 1
        assert (':' in completed['peer'][0]['ip']) == (second == 6)
        assert completed['user'][0]['uploaded'] == 100
        stopped = steps[prefix + '/stop-original']['database_after_flush']
        assert stopped['peer'][0]['active'] == 0
        assert stopped['user'][0]['uploaded'] == 200
        assert all(step['http_status'] == 200 and step['database_after_flush']['failed_jobs'][0]['count'] == 0 for step in result['steps'])
    print(f'{mode}: 12 passos completos, overwrite/intervalo/stop documentados; credito final 200 por sequencia')
