"""Reuso do contrato HTTP/SQL do laboratorio, sem dependencias no produto."""
import importlib.util
from pathlib import Path

BASE = Path('/opt/unit3d-dualstack')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


fixture = module('fixture', BASE/'benchmark-fixture.py')
benchmark = module('benchmark', BASE/'benchmark-http.py')
connect = fixture.connect
insert = fixture.insert
snapshot = benchmark.snapshot
percentiles = benchmark.percentiles
bdecode = benchmark.bdecode
