#!/usr/bin/env python3
"""Resume deltas de I/O somente na janela medida, sem usar medias desde o boot."""
import argparse
import json
from pathlib import Path


def summarize(samples, start, end):
    rows = [r for r in samples if start <= r['at'] <= end]
    assert len(rows) >= 2
    first, last = rows[0], rows[-1]
    duration = last['at'] - first['at']
    output = dict(host=first['host'], samples=len(rows), observed_seconds=duration, devices={})
    for name, old in first['diskstats'].items():
        new = last['diskstats'][name]
        delta = [b-a for a, b in zip(old, new)]
        assert all(v >= 0 for i, v in enumerate(delta) if i != 8), 'Contador de disco reiniciado'
        busy = []
        large_write_time_intervals = []
        for a, b in zip(rows, rows[1:]):
            elapsed = b['at']-a['at']
            busy.append((b['diskstats'][name][9]-a['diskstats'][name][9])/elapsed/10)
            write_ms = b['diskstats'][name][7]-a['diskstats'][name][7]
            # Sinal diagnostico, nao prova de defeito no contador ou no disco.
            # Preservar os valores brutos e impedir leitura acrítica das medias.
            if write_ms > 60_000:
                large_write_time_intervals.append(dict(at=b['at'], elapsed_seconds=elapsed,
                    write_time_delta_ms=write_ms,
                    writes=b['diskstats'][name][4]-a['diskstats'][name][4]))
        output['devices'][name] = dict(read_iops=delta[0]/duration, write_iops=delta[4]/duration,
            read_mib_per_second=delta[2]*512/duration/1024**2,
            write_mib_per_second=delta[6]*512/duration/1024**2,
            read_mean_ms=delta[3]/delta[0] if delta[0] else None,
            write_mean_ms=delta[7]/delta[4] if delta[4] else None,
            flush_iops=delta[15]/duration if len(delta) > 15 else None,
            flush_mean_ms=delta[16]/delta[15] if len(delta) > 16 and delta[15] else None,
            busy_percent=delta[9]/duration/10, highest_interval_busy_percent=max(busy),
            average_queue_depth=delta[10]/duration/1000,
            sampled_peak_in_flight=max(r['diskstats'][name][8] for r in rows),
            large_write_time_intervals=large_write_time_intervals,
            write_time_requires_investigation=bool(large_write_time_intervals))
    output['io_pressure_percent'] = {kind: (last['io_pressure'][kind]['total']-first['io_pressure'][kind]['total'])/duration/10000
        for kind in ['some', 'full']}
    ticks = [b-a for a, b in zip(first['cpu_ticks'][:8], last['cpu_ticks'][:8])]
    output['cpu_iowait_percent'] = 100*ticks[4]/sum(ticks)
    if 'mysql' in first:
        assert all('error' not in r['mysql'] for r in rows)
        a, b = first['mysql']['status'], last['mysql']['status']
        output['mysql_deltas'] = {k: b[k]-a[k] for k in a if k != 'Threads_running' and 'pending' not in k}
        output['mysql_peaks'] = {k: max(r['mysql']['status'][k] for r in rows)
                                 for k in a if k == 'Threads_running' or 'pending' in k}
        initial = {r['event']: r for r in first['mysql']['file_waits']}
        waits = {}
        for row in last['mysql']['file_waits']:
            old = initial[row['event']]
            count = row['count']-old['count']
            wait = row['wait_ps']-old['wait_ps']
            if count:
                waits[row['event']] = dict(events=count, total_wait_ms=wait/1e9,
                                          mean_wait_ms=wait/count/1e9)
        output['mysql_file_waits'] = waits
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('benchmark', type=Path)
    parser.add_argument('observations', type=Path, nargs='+')
    args = parser.parse_args()
    run = json.loads(args.benchmark.read_text(encoding='utf-8-sig'))
    start = run['measured_at_epoch']
    result = dict(benchmark=args.benchmark.name, observations=[
        summarize([json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines()], start, start+run['seconds'])
        for path in args.observations])
    print(json.dumps(result, indent=2))
