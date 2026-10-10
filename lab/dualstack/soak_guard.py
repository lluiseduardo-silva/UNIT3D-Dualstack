"""Limites da execução; funções puras usadas pelo supervisor e pelos testes."""
GIB=1024**3


def failures(sample):
    reasons=[]
    role=sample['role']
    if sample['ssd_free'] < (8 if role=='data' else 1)*GIB:reasons.append('ssd_low')
    if sample['archive_free'] < 20*GIB:reasons.append('archive_low')
    if sample['memory_available'] < 512*1024**2:reasons.append('memory_low')
    if role=='data':
        if not sample.get('archive_paused_for_comparison',False):
            if not sample['archive_timer_active'] or sample['archive_failed']:reasons.append('archiver_unhealthy')
            if sample['archive_age']>240:reasons.append('archiver_stale')
        if sample['closed_binlog_bytes']>4*GIB:reasons.append('binlog_backlog')
        if sample['mysql_restarts']!=0:reasons.append('mysql_restarted')
        if sample.get('owner_lease_required',True) and not sample['owner_live']:reasons.append('owner_lease_lost')
    if role=='tracker' and not sample['tracker_running']:reasons.append('tracker_stopped')
    return reasons
