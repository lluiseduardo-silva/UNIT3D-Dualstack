#!/usr/bin/env python3
import gzip
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from soak_metrics import Histogram, Samples, RECORD
from soak_guard import failures,GIB
from soak_diagnostics import ResponseFailure,record_drain


class SoakTests(unittest.TestCase):
    def test_response_diagnostics_never_export_arbitrary_body(self):
        secret=b'passkey-private-example'
        for status in (200,503):
            error=ResponseFailure(status,secret,{b'failure reason':secret})
            self.assertNotIn(secret.decode(),json.dumps(error.public))
            self.assertEqual(error.public['code'],'tracker_response_unknown')
            self.assertEqual(error.public['body_bytes'],len(secret))
            self.assertEqual(len(error.public['body_sha256']),64)
        error=ResponseFailure(200,b'body',{b'failure reason':b'Tracker temporarily unavailable. Please retry later.'})
        self.assertEqual(error.public['code'],'tracker_unavailable')
        self.assertEqual(ResponseFailure(500,secret).public['code'],'http_status')

    def test_drain_failure_preserves_primary_reason(self):
        status={'reason':'load_errors','cleanup':[]}
        record_drain(status,TimeoutError('private-message'))
        self.assertEqual(status['reason'],'load_errors')
        self.assertEqual(status['tracker_drain'],{'status':'failed','error_type':'TimeoutError'})
        self.assertNotIn('private-message',json.dumps(status))
        self.assertEqual(status['cleanup'][-1]['status'],'failed')
        record_drain(status)
        self.assertEqual(status['tracker_drain']['status'],'passed')

    def test_percentile_bounds(self):
        values=[i/321 for i in range(10000)] + [100,1000,10000]
        histogram=Histogram()
        for value in values:histogram.add(value)
        report=histogram.summary()
        for name,q in [('p50',.5),('p95',.95),('p99',.99)]:
            exact=values[math.ceil(len(values)*q)-1]
            self.assertGreaterEqual(report[name],exact)
            self.assertLessEqual(report[name],exact*1.001+.001)
        self.assertEqual(report['max'],10000)

    def test_segments_roundtrip_and_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'samples';s=Samples(path)
            row=(99,6,0,100,0.,.1,.2,.3,240,True)
            for _ in range(5000):s.add(*row)
            s.segment()
            for _ in range(1000):s.add(*row)
            s.close()
            files=sorted(path.glob('*.gz'))
            self.assertEqual(len(files),2)
            count=0
            for p in files:
                records=list(RECORD.iter_unpack(gzip.decompress(p.read_bytes())))
                count+=len(records)
                self.assertTrue(all(record==row for record in records))
            self.assertEqual(count,6000)
            self.assertLessEqual(s.peak_queue,16)
            self.assertFalse(list(path.glob('*.partial')))
            self.assertEqual(sum(json.loads(l)['records'] for l in (path/'manifest.jsonl').read_text().splitlines()),6000)

    def test_writer_failure_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Samples(Path(tmp)/'samples')
            with patch('soak_metrics.gzip.GzipFile',side_effect=OSError('space')):
                s.add(1,4,0,1,0.,0.,0.,0.,0,True)
                with self.assertRaises(RuntimeError):s.segment()
            self.assertIsNotNone(s.error)

    def test_guards(self):
        good={'role':'data','ssd_free':20*GIB,'archive_free':200*GIB,'memory_available':4*GIB,
              'archive_timer_active':True,'archive_failed':False,'archive_age':10,'closed_binlog_bytes':0,
              'mysql_restarts':0,'owner_live':True}
        self.assertEqual(failures(good),[])
        legacy=dict(good,owner_live=False,owner_lease_required=False)
        self.assertEqual(failures(legacy),[])
        self.assertIn('ssd_low',failures(dict(legacy,ssd_free=7*GIB)))
        self.assertIn('archiver_stale',failures(dict(legacy,archive_age=241)))
        for key,value,reason in [('ssd_free',7*GIB,'ssd_low'),('archive_free',19*GIB,'archive_low'),
             ('memory_available',400*1024**2,'memory_low'),('archive_age',241,'archiver_stale'),
             ('closed_binlog_bytes',5*GIB,'binlog_backlog'),('owner_live',False,'owner_lease_lost'),
             ('archive_failed',True,'archiver_unhealthy'),('mysql_restarts',1,'mysql_restarted')]:
            self.assertIn(reason,failures(dict(good,**{key:value})))


if __name__=='__main__':unittest.main(verbosity=2)
