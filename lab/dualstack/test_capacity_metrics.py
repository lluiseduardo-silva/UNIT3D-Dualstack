"""Verifica defasagem de observação e detecção de fila crescente."""
import json
from pathlib import Path
import unittest
from capacity_metrics import lag_trend


def synthetic(rate,seconds,growth):
    progress=[{'at':i+.17,'accepted':rate*(i+.17)} for i in range(seconds+3)]
    observations=[]
    for t in range(2,seconds,2):
        at=t+.63
        observations.append({'sql_start':at-.02,'sql_end':at+.02,
            'mysql':['persisted\t'+str(round(rate*at-100-growth*at))+'\t0']})
    return lag_trend(progress,observations,0,seconds,rate)


class CapacityMetricsTests(unittest.TestCase):
    def test_stable_with_different_collection_phases(self):
        result=synthetic(8000,60,0)
        self.assertTrue(result['sufficient_samples'])
        self.assertFalse(result['growing'])
        self.assertAlmostEqual(result['slope_per_second'],0,places=5)

    def test_ramp_detects_growing_backlog(self):
        result=synthetic(8000,60,125)
        self.assertTrue(result['growing'])
        self.assertAlmostEqual(result['slope_per_second'],125,places=5)

    def test_long_confirmation_detects_smaller_growth(self):
        result=synthetic(8000,300,20)
        self.assertTrue(result['growing'])

    def test_missing_samples_do_not_establish_stability(self):
        result=lag_trend([],[],0,60,1000)
        self.assertFalse(result['sufficient_samples'])
        self.assertIsNone(result['growing'])

    def test_real_false_saturation_regression(self):
        name='capacity-cpu-ram-v1-reference-1000'
        root=Path(__file__).parent/'results/capacity/capacity-cpu-ram-v1'
        progress=[json.loads(line) for line in (root/'clients/results/capacity'/name/'progress.jsonl').read_text().splitlines()]
        observations=[json.loads(line) for line in (root/'data/results/capacity'/name/'data-observer.jsonl').read_text().splitlines()]
        original=json.loads((root/'supervisor/capacity/capacity-cpu-ram-v1'/(name+'-result.json')).read_text())
        result=lag_trend(progress,observations,original['measured_at'],original['finish_epoch'],original['rate'])
        self.assertTrue(original['accounting_passed'])
        self.assertGreater(original['observed_lag_slope_per_second'],30)
        self.assertTrue(result['sufficient_samples'])
        self.assertLess(abs(result['slope_per_second']),1)
        self.assertFalse(result['growing'])


if __name__=='__main__':unittest.main()
