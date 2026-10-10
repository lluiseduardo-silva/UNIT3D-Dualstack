"""Alinha contadores assíncronos antes de estimar crescimento da fila."""
import bisect
import statistics


def lag_trend(progress, observations, begin, end, rate, batch_size=500):
    progress=sorted(progress,key=lambda x:x['at'])
    times=[x['at'] for x in progress]
    rows=[]
    for sample in observations:
        if 'sql_start' not in sample or 'sql_end' not in sample:continue
        at=(sample['sql_start']+sample['sql_end'])/2
        if not begin<=at<=end:continue
        index=bisect.bisect_right(times,at)
        if not 0<index<len(progress):continue
        left,right=progress[index-1],progress[index]
        span=right['at']-left['at']
        if not 0<span<=3:continue
        persisted=next((int(line.split('\t')[1]) for line in sample.get('mysql',[]) if line.startswith('persisted\t')),None)
        if persisted is None:continue
        accepted=left['accepted']+(right['accepted']-left['accepted'])*(at-left['at'])/span
        rows.append({'at':at,'lag':max(0,accepted-persisted),'sql_span':sample['sql_end']-sample['sql_start'],'progress_span':span})
    rows.sort(key=lambda x:x['at'])
    tail=rows[len(rows)//2:]
    if len(tail)<6:return {'sufficient_samples':False,'samples':len(rows),'growing':None}
    n=max(2,len(tail)//3);early,late=tail[:n],tail[-n:]
    elapsed=statistics.median(x['at'] for x in late)-statistics.median(x['at'] for x in early)
    growth=statistics.median(x['lag'] for x in late)-statistics.median(x['lag'] for x in early)
    # Até dois lotes de oscilação e a incerteza da consulta. É resolução de
    # detecção, não evidência de que uma tendência menor é rigorosamente zero.
    tolerance=2*batch_size+rate*max(x['sql_span'] for x in tail)
    return {'sufficient_samples':True,'samples':len(rows),'slope_per_second':growth/elapsed,
            'growth':growth,'comparison_seconds':elapsed,'growth_tolerance':tolerance,
            'growing':growth>tolerance,'minimum_lag':min(x['lag'] for x in rows),
            'maximum_lag':max(x['lag'] for x in rows),
            'max_sql_span_seconds':max(x['sql_span'] for x in rows),
            'max_progress_span_seconds':max(x['progress_span'] for x in rows)}
