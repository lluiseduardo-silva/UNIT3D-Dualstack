#!/usr/bin/env python3
"""Confere provas públicas do A/B antes de liberar a próxima série."""
import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text())


def verify(root, series):
    assert series.startswith('capacity-cache-') and series.replace('-','').isalnum()
    folder=root/'supervisor/capacity'/series
    state=load(folder/'status.json'); variant=load(folder/'variant.json')
    assert state['status']=='completed' and state['resources_restored'], 'serie_ou_restauracao'
    assert not state.get('probe_failures'), 'falha_do_coletor'
    expected_trials=1 if state['mode']=='calibration' else 9
    assert len(state['results'])==expected_trials, 'rodadas_incompletas'
    total=credit=observations=0; drains=[]
    for entry in state['results']:
        name=entry['trial'];r=load(folder/(name+'-result.json'))
        assert r['status']=='passed' and r['accounting_passed'] and r['drained'], 'auditoria'
        assert not r['errors'] and not r['supervisor_reason'] and not r['stop_reason'], 'rodada_interrompida'
        after=r['after']
        assert after['versions']==r['accepted'] and after['peers']==10000, 'identidade_versoes'
        assert all(after[k]==r['expected_credit'] for k in ('credit','history_credit','actual_credit','user_credit')), 'credito'
        assert after['endpoints']=={'n':20000,'v4':10000,'v6':10000,'invalid':0}, 'endpoints'
        assert all(after[k]==0 for k in ('mismatches','over_limit','bad_torrent_counts')), 'invariantes'
        drain=load(folder/(name+'-tracker-drain.json'))
        assert drain['exit_code']==0 and not drain['oom_killed'], 'drenagem'
        assert drain['binary_sha256']==variant['binary_sha256'], 'binario'
        for role in ('tracker','data','clients','proxmox'):
            base=root/'supervisor/capacity' if role=='proxmox' else root/role/'results/capacity'
            rows=[json.loads(line) for line in (base/name/(role+'-observer.jsonl')).read_text().splitlines()]
            assert rows and all(not row.get('failures') for row in rows), 'observador'
            observations+=len(rows)
        total+=r['accepted'];credit+=r['expected_credit'];drains.append(r['drain_seconds'])
    memory=[json.loads(line) for line in (root/'data/results/capacity'/series/'memory.jsonl').read_text().splitlines()]
    assert memory and all(not row.get('failures') for row in memory), 'coletor_memoria'
    resources=load(folder/'resources-after.json')
    for vm in ('120','121','122'):
        c=resources[vm]['configured']
        assert (int(c['cores']),int(c['memory']),int(c['balloon']))==(4,8192,0), 'recursos'
        assert resources[vm]['cpu_online']==4, 'cpu_efetiva'
    result={'passed':True,'series':series,'variant':variant['variant'],'trials':expected_trials,
            'accepted':total,'credit_bytes':credit,'errors':0,'accounting_mismatches':0,
            'all_drains_exit_zero':True,'max_drain_seconds':max(drains),
            'resources_restored':True,'observer_samples':observations,'memory_samples':len(memory),
            'scope':'integridade e restauração; não aprova desempenho ou teto sustentado'}
    (folder/'analysis-verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('series')
    args=p.parse_args();print(json.dumps(verify(args.root,args.series)))
