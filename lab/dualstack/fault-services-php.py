#!/usr/bin/env python3
"""Orquestra falhas apenas nos containers do laboratorio; executa no host com SSH."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import time


BASE = '/opt/unit3d-dualstack'
HOSTS = {'tracker': '10.0.1.27', 'data': '10.0.1.26', 'clients': '10.0.1.25'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-key', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'status': 'running', 'backend': 'php-standalone',
              'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps': []}
    down = set()
    paused = False

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')

    def ssh(host, command, timeout=50):
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                                 '-i', str(args.ssh_key), 'lab@'+HOSTS[host], command],
                                capture_output=True, text=True, encoding='utf-8', timeout=timeout)
        if result.returncode:
            raise RuntimeError('Comando do laboratorio falhou em '+host+'; saida omitida por seguranca.')
        return result.stdout.strip()

    def record(label, value):
        report['steps'].append({'label': label, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'result': value})
        save()
        print(label, flush=True)
        return value

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def state():
        return json.loads(ssh('tracker', 'sudo docker run --rm --network host '
                              '-e DB_DATABASE=unit3d_dualstack_journal_test '
                              '-v '+BASE+'/repos/UNIT3D:/app -v '+BASE+'/lab:/lab:ro '
                              'unit3d-ds-php:baseline php /lab/fault-state.php'))

    def wait_for(fn, predicate, seconds=45):
        deadline = time.monotonic() + seconds
        while True:
            value = fn()
            if predicate(value):
                return value
            if time.monotonic() >= deadline:
                raise AssertionError('Estado esperado nao foi atingido dentro do prazo do ensaio.')
            time.sleep(1)

    def announce(label, family, upload, event='completed', success=True):
        value = json.loads(ssh('clients', f'python3 {BASE}/fault-announce.py --family {family} --uploaded {upload} --event {event}'))
        record(label, value)
        check(value['success'] == success, label+': resultado HTTP divergiu do esperado.')
        return value

    def coordinator():
        return json.loads(ssh('tracker', "sudo docker inspect -f '{{json .State}}' unit3d-ds-coordinator"))

    def confirmed(upload, credit):
        current = wait_for(state, lambda s: s['mysql']['available'] and s['redis']['available']
                           and s['redis']['ready'] == '1' and s['redis']['backlog'] == 0
                           and int(s['mysql']['user']['uploaded']) == credit)
        sql = current['mysql']
        check(len(sql['peers']) == 1 and int(sql['peers'][0]['uploaded']) == upload, 'Referencia SQL incorreta.')
        check(int(sql['history']['actual_uploaded']) == credit, 'Historico divergiu do credito confirmado.')
        check(int(current['redis']['uploaded']) == upload, 'Referencia Redis divergiu do SQL.')
        check(sql['peers'][0]['state_version'] == current['redis']['peer_version'], 'Versoes SQL/Redis divergentes.')
        check([e['family'] for e in sql['endpoints']] == [4, 6], 'Recuperacao perdeu um endpoint.')
        check(sql['torrent']['seeders'] == 1 and sql['torrent']['seeders_ipv4'] == 1 and sql['torrent']['seeders_ipv6'] == 1, 'Contadores divergentes.')
        return current

    try:
        for host in HOSTS:
            expected = 'unit3d-ds-'+host
            check(ssh(host, 'hostname') == expected, 'Host fora do laboratorio: '+host)
        check(ssh('tracker', 'sudo docker ps -a --format {{.Names}}') == '', 'Encerre containers do ensaio anterior.')
        data_containers = ssh('data', 'sudo docker ps --format {{.Names}}').splitlines()
        check(all('unit3d-ds-'+s in data_containers for s in ['mysql', 'redis']), 'Servicos de dados precisam estar ativos.')
        record('preparacao-fixture-isolada', ssh('tracker', 'sudo bash '+BASE+'/lab/start-candidate-php.sh fresh'))
        record('entrada-pronta', wait_for(state, lambda s: s['redis']['available'] and s['redis']['ready'] == '1'))
        announce('baseline-ipv4', 4, 1000, 'started')
        announce('baseline-ipv6', 6, 1000, 'started')
        announce('credito-confirmado-inicial', 6, 1100)
        record('baseline-confirmado', confirmed(1100, 100))

        for service, upload, credit in [('mysql', 1200, 200), ('redis', 1300, 300)]:
            ssh('tracker', 'sudo docker pause unit3d-ds-coordinator')
            paused = True
            announce(service+'-announce-pendente', 6, upload)
            pending = record(service+'-antes-da-falha', state())
            check(pending['redis']['backlog'] == 1, 'O ensaio exige uma transicao pendente antes da falha.')
            check(int(pending['mysql']['user']['uploaded']) == credit - 100, 'Credito pendente foi confirmado cedo demais.')
            # Stop real do servico. Redis faz fsync do AOF no encerramento;
            # perda de dados nao sincronizados num SIGKILL e um ensaio separado.
            down.add(service)
            ssh('data', 'sudo docker stop -t 20 unit3d-ds-'+service)
            record(service+'-servico-parado', {'running': False})
            ssh('tracker', 'sudo docker unpause unit3d-ds-coordinator')
            paused = False
            stopped = wait_for(coordinator, lambda s: not s['Running'], seconds=20)
            record(service+'-coordenador-interrompido', {'running': stopped['Running'], 'exit_code': stopped['ExitCode']})
            check(stopped['ExitCode'] != 0, 'Coordenador deve sinalizar a indisponibilidade.')
            announce(service+'-recusa-durante-falha', 4, upload + 100, success=False)
            during = record(service+'-durante-falha', state())
            check(not during[service]['available'], 'Servico nao ficou indisponivel.')
            if service == 'mysql':
                check(during['redis']['backlog'] == 1 and during['redis']['ready'] == '0', 'Journal/entrada incoerentes durante falha MySQL.')
            else:
                check(int(during['mysql']['user']['uploaded']) == credit - 100, 'Redis indisponivel alterou credito SQL.')
            ssh('data', 'sudo docker start unit3d-ds-'+service)
            down.remove(service)
            restored = wait_for(state, lambda s: s['mysql']['available'] and s['redis']['available']
                                and float(s['mysql']['ownership']['lease_remaining_seconds'] or 0) <= 0)
            record(service+'-servico-restaurado-lease-vencida', restored)
            ssh('tracker', 'sudo docker start unit3d-ds-coordinator')
            recovered = record(service+'-recuperado', confirmed(upload, credit))
            check(recovered['redis']['generation'] > pending['redis']['generation'], 'Recuperacao precisa adquirir nova geracao.')
            announce(service+'-reenvio-sem-credito-extra', 4, upload)
            record(service+'-depois-do-reenvio', confirmed(upload, credit))

        announce('novo-delta-depois-das-falhas', 6, 1400)
        record('estado-final-confirmado', confirmed(1400, 400))
        record('encerramento-com-drenagem', ssh('tracker', 'sudo bash '+BASE+'/lab/stop-candidate-php.sh', timeout=150))
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
        report['error'] = str(error) if isinstance(error, AssertionError) else 'Falha de infraestrutura; saida bruta omitida.'
    finally:
        cleanup = []
        for service in sorted(down):
            try:
                ssh('data', 'sudo docker start unit3d-ds-'+service)
                cleanup.append(service+' restaurado')
            except Exception:
                cleanup.append(service+' exige recuperacao manual')
        if paused:
            try:
                ssh('tracker', 'sudo docker unpause unit3d-ds-coordinator')
                cleanup.append('coordenador retomado')
            except Exception:
                cleanup.append('coordenador exige recuperacao manual')
        if report['status'] != 'passed':
            # Fecha a entrada, preservando containers/filas para diagnostico.
            try:
                ssh('tracker', 'sudo docker stop -t 15 unit3d-ds-nginx unit3d-ds-php')
                cleanup.append('entrada HTTP fechada')
            except Exception:
                cleanup.append('verificar entrada HTTP manualmente')
        report['cleanup'] = cleanup
        report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
        print(json.dumps({'status': report['status'], 'error': report.get('error'), 'steps': len(report['steps'])}), flush=True)
    raise SystemExit(0 if report['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
