#!/usr/bin/env python3
"""Consolida metricas publicas; numeros historicos reportados mantem fonte e escopo."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def write_json(path,data):
    p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def load(path):return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))
def metrics():
    records=[]
    def add(i,profile,metric,value,unit,statistic,source,notes='',pointer=None):
        record=dict(id=i,profile=profile,metric=metric,value=value,unit=unit,statistic=statistic,source=source,notes=notes)
        if pointer:record['json_pointer']=pointer
        records.append(record)
    for variant,path,report in [('candidate','lab/dualstack/results/soak/six-hours-v3-summary.json','docs/dualstack-prolongado-v3.md'),('original','lab/dualstack/results/soak/rust-original-six-hours-v1/summary.json','docs/dualstack-rust-original-prolongado.md')]:
        d=load(path);profile='six-hours-'+variant
        for key in ['accepted','errors','main_accepted']:
            add(profile+'-'+key,profile,key,d['load'][key],'count','total',path,pointer='/load/'+key)
        for key in ['p95','p99']:
            add(profile+'-'+key,profile,'http_response',d['window_metrics_median']['response_ms'][key],'ms','median_of_window_'+key,path,'Não é percentil global; perfis original/candidato distintos.',f'/window_metrics_median/response_ms/{key}')
        for key in ['min','median']:
            add(profile+'-rps-'+key,profile,'completed_rps',d['completed_rps'][key],'requests/s',key+'_of_windows',path,'Janelas com pausas entre elas.',f'/completed_rps/{key}')
        add(profile+'-credit',profile,'credit',8500225800 if variant=='candidate' else 17520000000,'bytes','confirmed_total',report,'Oráculos de crédito diferem entre os perfis.')
        add(profile+'-rss-hourly',profile,'rust_rss',[32.15,33.20] if variant=='candidate' else [26.95,27.92],'MiB','range_of_hourly_medians',report)
        add(profile+'-rss-peak',profile,'rust_rss',125.31 if variant=='candidate' else 38.61,'MiB','sampled_max',report)
    add('candidate-expiry','six-hours-candidate','ipv6_expiry_elapsed',7221,'s','observed', 'docs/dualstack-prolongado-v3.md','TTL 7200; endpoints 20000→19999; peers 10000; restauração posterior.')
    add('candidate-lag-max','six-hours-candidate','observed_version_lag',89007,'versions','sampled_max','lab/dualstack/results/soak/six-hours-v3-summary.json','Inclui defasagem de observação; valor final zero.','/max_observed_persistence_lag')
    for peers,v in [(50,.2390),(150,.2454),(250,.2483),(1000,.2555),(2500,.2745),(5000,.3155),(10000,.4038),(20000,.5836),(40000,1.1346)]:
        add('density-'+str(peers),'density-1000rps','http_response',v,'ms','median_of_repetition_p99','docs/dualstack-densidade.md',f'{peers} peers no torrent alvo; teste curto exploratório.')
    boot='lab/dualstack/results/bootstrap/summary.json'
    for row in load(boot)['results']:
        add(f"bootstrap-{row['peers']}-{row['layout']}",f"bootstrap-{row['layout']}",'bootstrap_seconds',[row['bootstrap_min_seconds'],row['bootstrap_max_seconds']],'s','range',boot,f"{row['peers']} peers; carregamento, não throughput.")
    ab='lab/dualstack/results/capacity/capacity-cache-ab-comparison.json'
    for series,d in load(ab)['series'].items():
        for key in ['accepted','credit_bytes']:
            add(series+'-'+key,series,key,d[key],'count' if key=='accepted' else 'bytes','total',ab,pointer=f'/series/{series}/{key}')
        for key in ['rss_mib','pss_mib','Prepared_stmt_count','prepared_mem_root_mib']:
            if key in d['memory_ranges']:
                add(series+'-'+key,series,key,d['memory_ranges'][key]['max'],'count' if key=='Prepared_stmt_count' else 'MiB','sampled_max',ab,'A1/A2 são candidato dualstack; B experimental.',f'/series/{series}/memory_ranges/{key}/max')
        for j,trial in enumerate(d['trials']):
            if '-confirm-' not in trial['name']:continue
            prefix=f'/series/{series}/trials/{j}'
            note='Janela de 300 s a 5500 req/s; estabilidade='+str(trial['stable'])+'; não teto sustentado.'
            add(trial['name']+'-p99',trial['name'],'http_response',trial['metrics']['response_ms']['p99'],'ms','window_p99',ab,note,prefix+'/metrics/response_ms/p99')
            for role in ['tracker','data']:
                add(trial['name']+'-'+role+'-cpu',trial['name'],role+'_cpu',trial['resources'][role]['process']['cpu_one_core_percent'],'percent_of_one_core','process_average',ab,note,prefix+f'/resources/{role}/process/cpu_one_core_percent')
            for key,unit in [('write_iops','writes/s'),('write_mib_s','MiB/s'),('flush_iops','flushes/s')]:
                add(trial['name']+'-'+key,trial['name'],key,trial['resources']['data']['disk'][key],unit,'window_average',ab,note,prefix+'/resources/data/disk/'+key)
    for i,v in [(4,6),(6,18),('dual',24)]:add('compact-'+str(i),'protocol','compact_endpoint_bytes',v,'bytes','representation_size','docs/resultados-consolidados.md','Por peer selecionado; exclui envelope.')
    for name,writes,mib,redo in [('original-3s',[118,133],[2.15,2.28],[.157,.158]),('original-100ms',476,5.54,.524),('candidate-100ms',[432,497],[7.36,7.69],[1.54,1.55])]:
        for key,value,unit in [('writes',writes,'writes/s'),('write_volume',mib,'MiB/s'),('redo',redo,'MiB/s')]:
            add('initial-io-'+name+'-'+key,'initial-io-'+name,key,value,unit,'observed_value_or_range','docs/dualstack-benchmarks.md','Controle intermediário, anterior às otimizações do escritor.')
    for name,value,unit in [('vm_write',33.24,'MiB/s'),('vm_writes',2080,'writes/s'),('vm_flushes',691,'flushes/s')]:
        add('lease-io-8000-'+name,'load-8000-v1',name,value,unit,'window_average','docs/dualstack-lease-io.md','180 s; disco virtual; não requisito universal de SSD.')
    add('cache-rss-reduction','cache-A1-B-A2','mysql_peak_rss_reduction',[55.1,59.7],'percent','observed_comparison_range','docs/dualstack-capacidade-recursos.md','B experimental; host compartilhado; confirmações de 300 s.')
    add('cache-mysql-cpu-cost','cache-A1-B-A2','mysql_cpu_increase',[5.0,7.9],'percentage_points_of_one_core','observed_comparison_range','docs/dualstack-capacidade-recursos.md')
    add('cache-rust-cpu-cost','cache-A1-B-A2','rust_cpu_increase',[3.4,3.8],'percentage_points_of_one_core','observed_comparison_range','docs/dualstack-capacidade-recursos.md')
    write_json('docs/data/key-metrics.json',dict(format_version=1,evidence_cutoff='2026-10-10',notes=['Valores usam ponto decimal conforme JSON.','Medianas de percentis por janela não são percentis globais.','Sem aprovação global de performance original/candidato ou PHP.'],records=records))
    cases=[
        ('schema','Identidade e endpoints limitados por família','repos/UNIT3D/tests/Integration/DualstackSchemaTest.php','lab/dualstack/results/schema','docs/arquitetura-e-contratos.md'),
        ('contract','Contadores, repetição e famílias','repos/UNIT3D-Announce/tests/dualstack_contract.rs','lab/dualstack/results/contract','docs/plans/2026-10-08-dualstack-execucao.md'),
        ('mysql','Persistência, recuperação e reentrega','repos/UNIT3D-Announce/tests/dualstack_mysql.rs','lab/dualstack/results/lease-recovery/mysql.txt','docs/dualstack-recuperacao-lease.md'),
        ('refund','Reembolso sob concorrência','repos/UNIT3D/tests/Integration/DownloadRefundContentionTest.php','lab/dualstack/results/refund-rust-contention.txt','docs/dualstack-reembolso-concorrencia.md'),
        ('rollback','Originais e reativação após reconciliação','repos/UNIT3D-Announce/tests/dualstack_legacy.rs','lab/dualstack/results/legacy-rust-roundtrip.txt','docs/dualstack-rollback-legado.md'),
        ('clients','Transferência, handshake e falha de família','lab/dualstack/real-clients.py','lab/dualstack/results/real-clients','docs/dualstack-clientes-reais.md'),
        ('tls','Origem, proxies, conectividade e cache','lab/dualstack/network-client.py','lab/dualstack/results/tls-memory','docs/dualstack-tls-memoria.md'),
        ('bootstrap','Restauração e escala de inicialização','repos/UNIT3D-Announce/tests/dualstack_bootstrap.rs','lab/dualstack/results/bootstrap/summary.json','docs/dualstack-bootstrap.md'),
        ('crash','Crédito confirmado e perda da fila volátil','lab/dualstack/run-rust-crash.py','lab/dualstack/results/rust-crash','docs/dualstack-falha-abrupta.md'),
        ('soak','Seis horas do candidato','lab/dualstack/audit-soak-samples.py','lab/dualstack/results/soak/six-hours-v3-validation.json','docs/dualstack-prolongado-v3.md'),
        ('original','Seis horas do original','lab/dualstack/audit-rust-comparison-samples.py','lab/dualstack/results/soak/rust-original-six-hours-v1/onsite-verification.json','docs/dualstack-rust-original-prolongado.md'),
        ('cache','A1/B/A2 e custo de RAM/CPU','lab/dualstack/compare-capacity-cache.py','lab/dualstack/results/capacity/capacity-cache-ab-comparison.json','docs/dualstack-capacidade-recursos.md'),
    ]
    write_json('docs/data/validation-matrix.json',dict(format_version=1,scope='Validações históricas nos checkpoints dos relatórios; não cobertura percentual de linhas.',cases=[dict(id=i,requirement=req,test=test,evidence=ev,report=rep,status='completed_experiment_not_global_approval' if i=='cache' else 'validated_with_reported_limits') for i,req,test,ev,rep in cases]))

if __name__ == "__main__":
    metrics()
