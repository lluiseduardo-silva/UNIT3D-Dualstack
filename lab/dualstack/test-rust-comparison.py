#!/usr/bin/env python3
"""Executar na VM de clientes; rejeitar respostas incompatíveis antes da carga."""
import importlib.util
import ipaddress
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('comparison',Path(__file__).with_name('rust-comparison-load.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.load=object.__new__(m.Comparison)
        self.load.fixture={'sizes':[250]}
        self.load.plan={'comparison_variant':'original'}
        self.p={'torrent_slot':0,'sent':3}
        self.endpoint=b'\xac\x1d\x5c\x64\x27\x10'
        self.load.eligible={(0,4,self.endpoint):20000}
        self.response={b'complete':200,b'incomplete':50,b'peers':self.endpoint}

    def test_same_single_family_credit_in_both_variants(self):
        for variant in ('original','candidate'):
            self.load.plan={'comparison_variant':variant}
            self.assertEqual(self.load.counter(self.p),300)
            self.load.validate_response(self.p,self.response,1,None)
        self.assertEqual(m.soak.Load.counter(self.load,self.p),200)

    def test_wrong_counts_and_family_rejected(self):
        for update in ({b'complete':10},{b'incomplete':0},{b'peers6':b'x'*18},{b'peers':b''}):
            with self.assertRaises(AssertionError):
                self.load.validate_response(self.p,dict(self.response,**{})|update,1,None)

    def test_original_mapped_storage_does_not_relax_candidate(self):
        mapped=ipaddress.ip_address('::ffff:172.29.92.100').packed
        self.load.plan={'comparison_variant':'original'}
        self.assertEqual(self.load.stored_address(mapped),ipaddress.ip_address('172.29.92.100'))
        native=ipaddress.ip_address('fd42::100').packed
        self.assertEqual(self.load.stored_address(native),ipaddress.ip_address('fd42::100'))
        self.load.plan={'comparison_variant':'candidate'}
        self.assertNotEqual(self.load.stored_address(mapped),ipaddress.ip_address('172.29.92.100'))

    def test_original_mapped_response_preserves_identity_and_bound(self):
        compact=ipaddress.ip_address('::ffff:172.29.92.100').packed+self.endpoint[-2:]
        response=self.response|{b'peers':b'',b'peers6':compact}
        self.load.validate_response(self.p,response,1,None)
        self.assertEqual(self.load.mapped_ipv4_responses,1)
        for changed,wanted in ((response|{b'peers':self.endpoint},2),
                (response|{b'peers6':ipaddress.ip_address('fd42::100').packed+compact[-2:]},1),
                (response,0)):
            with self.assertRaises(AssertionError):self.load.validate_response(self.p,changed,wanted,None)
        wrong=response|{b'peers6':ipaddress.ip_address('::ffff:172.29.92.101').packed+compact[-2:]}
        with self.assertRaises(KeyError):self.load.validate_response(self.p,wrong,1,None)
        self.load.plan={'comparison_variant':'candidate'}
        with self.assertRaises(AssertionError):self.load.validate_response(self.p,response,1,None)

    def test_other_swarm_and_duplicates_rejected(self):
        with self.assertRaises(KeyError):
            self.load.validate_response(self.p,self.response|{b'peers':b'\x00'*6},1,None)
        with self.assertRaises(AssertionError):
            self.load.validate_response(self.p,self.response|{b'peers':self.endpoint*2},2,None)
        self.load.validate_response(self.p,self.response|{b'peers':b''},0,None)

    def test_six_hours_are_measured_in_full_and_short_profile_unchanged(self):
        plan=dict(warmup=300,measurement=21600,seconds=21900,prolonged=True,window_seconds=300)
        phases=m.Comparison.phases(plan)
        self.assertEqual(len(phases),73)
        self.assertEqual(sum(s for label,s in phases if label=='measurement'),21600)
        self.assertEqual(sum(s for label,s in phases if label=='warmup'),300)
        self.assertEqual(m.Comparison.phases(dict(warmup=300,measurement=900,seconds=1200)),
                         [('warmup',300),('measurement',900)])
        for update in (dict(seconds=21600),dict(measurement=21601,seconds=21901),dict(window_seconds=7200)):
            with self.assertRaises(AssertionError):m.Comparison.phases(plan|update)

    def test_replay_separates_refresh_from_credit(self):
        self.load.plan={'prolonged':True}
        self.load.lanes=[dict(index=0,seeder=True,observed=0,accepted=0),dict(index=1,seeder=False,observed=0,accepted=0)]
        self.load.replay_sample(0,4,0,100,True)
        self.load.replay_sample(1,4,3,0,True)
        self.load.replay_sample(1,4,3,0,True)
        self.assertEqual([p['accepted'] for p in self.load.lanes],[1,2])
        self.assertEqual(sum(p['observed'] for p in self.load.lanes),100)
        for row in ((0,4,0,100,True),(0,4,3,0,True),(1,4,3,100,True),
                    (1,6,3,0,True),(1,4,1,0,True),(1,4,3,0,False)):
            with self.assertRaises(AssertionError):self.load.replay_sample(*row)
        self.load.plan={}
        with self.assertRaises(AssertionError):self.load.replay_sample(1,4,3,0,True)


if __name__=='__main__':unittest.main(verbosity=2)
