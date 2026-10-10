#!/usr/bin/env python3
"""SIGKILL controlado do Rust no laboratorio, com evidencia contábil por etapa."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--ssh-key', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
assert not args.output.exists(), 'Preserve a tentativa anterior com outro nome'
base = '/opt/unit3d-dualstack'
hosts = {'tracker': '10.0.1.27', 'clients': '10.0.1.25', 'data': '10.0.1.26'}
report = dict(status='running', rust_commit='9e8b54626334db11940e3ebf939cbf40ba4426a3', steps=[])
started = False
block = None
verified = False


def command(host, text):
    return ['ssh', '-i', args.ssh_key, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', 'lab@'+hosts[host], text]


def ssh(host, text, timeout=55):
    result = subprocess.run(command(host, text), capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    assert result.returncode == 0, 'Falha SSH/comando em '+host+'; consultar somente logs locais'
    return result.stdout.strip()


def record(label, value):
    report['steps'].append(dict(label=label, at=datetime.datetime.now(datetime.timezone.utc).isoformat(), result=value))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(label, flush=True)
    return value


def state():
    return json.loads(ssh('clients', f'sudo python3 {base}/fault-rust-client.py state'))


def wait_for(predicate, limit=40):
    deadline = time.monotonic()+limit
    while True:
        value = state()
        if predicate(value):
            return value
        assert time.monotonic() < deadline, 'Estado SQL esperado nao apareceu'
        time.sleep(.2)


def consistent(value, uploaded, credit, version):
    return (len(value['peer']) == len(value['history']) == 1
        and value['peer'][0] == dict(uploaded=uploaded, state_version=version)
        and value['history'][0] == dict(uploaded=credit, actual_uploaded=credit, state_version=version)
        and value['user'][0]['uploaded'] == credit
        and [e['family'] for e in value['endpoints']] == [4, 6]
        and value['counts'][0] == dict(seeders=1, seeders_ipv4=1, seeders_ipv6=1))


def confirmed(label, uploaded, credit, version):
    return record(label, wait_for(lambda v: consistent(v, uploaded, credit, version), 8))


def burst(label, uploaded, step, count):
    value = json.loads(ssh('clients', f'sudo python3 {base}/fault-rust-client.py burst --base {uploaded} --step {step} --count {count}'))
    assert value['accepted'] == count
    return record(label, value)


def kill(label):
    value = ssh('tracker', 'sudo docker kill --signal=KILL unit3d-ds-rust >/dev/null && sudo docker inspect -f "{{.State.ExitCode}}" unit3d-ds-rust')
    assert value == '137'
    record(label, dict(signal='SIGKILL', exit_code=137))
    ssh('tracker', 'sudo docker rm unit3d-ds-rust >/dev/null')


def restart(label):
    began = time.monotonic()
    wait_for(lambda v: v['owner'][0]['live'] == 0)
    elapsed = time.monotonic()-began
    ssh('tracker', f'sudo bash {base}/lab/start-candidate-rust.sh resume direct', 180)
    record(label, dict(natural_lease_wait_seconds=elapsed))


try:
    for host in hosts:
        assert ssh(host, 'hostname') == 'unit3d-ds-'+host
    assert not ssh('tracker', 'sudo docker ps -a --format "{{.Names}}"')
    assert int(ssh('data', "df -B1 --output=avail / | tail -1")) > 3*1024**3
    started = True
    ssh('tracker', f'sudo bash {base}/lab/start-candidate-rust.sh fresh direct', 180)
    for family in [4, 6]:
        value = json.loads(ssh('clients', f'python3 {base}/fault-announce.py --family {family} --uploaded 1000 --event started'))
        assert value['success']
        record('referencia-inicial-'+str(family), value)
    confirmed('referencia-confirmada', 1000, 0, 2)
    burst('delta-antes-da-queda', 1000, 100, 1)
    confirmed('credito-confirmado', 1100, 100, 3)
    kill('queda-depois-do-commit')
    confirmed('credito-preservado-apos-sigkill', 1100, 100, 3)
    restart('restart-depois-do-commit')
    confirmed('credito-restaurado', 1100, 100, 3)
    burst('reenvio-nas-duas-familias', 1100, 0, 2)
    confirmed('reenvio-sem-duplicacao', 1100, 100, 5)
    burst('novo-delta', 1100, 100, 1)
    before = confirmed('referencia-antes-do-bloqueio', 1200, 200, 6)

    block = subprocess.Popen(command('clients', f'sudo python3 {base}/fault-rust-client.py block'),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    assert json.loads(block.stdout.readline()) == dict(ready=True)
    blocked_at = time.monotonic()
    accepted = burst('rajada-com-escritor-bloqueado', 1200, 100, 100)
    pending = state()
    assert consistent(pending, 1200, 200, 6), 'O bloqueio nao preservou a referencia SQL'
    assert pending['queries'][0]['n'] >= 1, 'O escritor nao ficou bloqueado'
    record('sql-antes-da-queda-bloqueada', pending)
    kill('queda-antes-do-commit')
    block.stdin.write('\n')
    block.stdin.flush()
    tail, error = block.communicate(timeout=5)
    assert block.returncode == 0 and json.loads(tail.strip()) == dict(released=True)
    block = None
    record('bloqueio-liberado', dict(seconds=time.monotonic()-blocked_at))
    after = wait_for(lambda v: v['queries'][0]['n'] == 0, 8)
    assert consistent(after, 1200, 200, 6)
    assert after['endpoints'] == before['endpoints']
    record('rollback-sem-efeitos-parciais', after)
    record('pendencia-perdida-na-memoria', dict(acknowledged_transitions=accepted['accepted'],
        confirmed_transitions=after['peer'][0]['state_version']-before['peer'][0]['state_version'],
        cumulative_bytes_not_yet_credited=accepted['uploaded']-after['peer'][0]['uploaded']))
    restart('restart-depois-do-rollback')
    confirmed('referencia-antiga-restaurada', 1200, 200, 6)
    burst('contador-cumulativo-reenviado', 11200, 0, 2)
    confirmed('delta-recuperado-uma-vez', 11200, 10200, 8)
    burst('delta-apos-recuperacao', 11200, 100, 1)
    confirmed('credito-final-unico', 11300, 10300, 9)
    verified = True
except Exception as error:
    report['status'] = 'failed'
    record('falha', dict(type=type(error).__name__, reason=str(error) if isinstance(error, AssertionError) else 'Consultar logs locais'))
    raise
finally:
    if block is not None:
        try:
            block.communicate('\n', timeout=12)
        except Exception:
            block.kill()
    if started:
        # Somente o container deste ensaio; processo ja morto nao precisa de drain.
        running = ssh('tracker', 'sudo docker ps --filter name=^unit3d-ds-rust$ -q')
        if running:
            ssh('tracker', f'sudo bash {base}/lab/benchmark-backend.sh stop rust candidate', 190)
        else:
            ssh('tracker', 'sudo docker rm unit3d-ds-rust >/dev/null 2>&1 || true')
    try:
        final = state()
        assert final['owner'][0]['live'] == 0 and final['queries'][0]['n'] == 0
        if verified:
            report['status'] = 'passed'
        record('encerramento', final)
    except Exception as error:
        report['status'] = 'failed'
        record('falha-no-encerramento', dict(type=type(error).__name__))
        raise
