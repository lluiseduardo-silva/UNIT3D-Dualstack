#!/usr/bin/env python3
"""Reproduz a sequência do incidente sem banco, rede ou mudança no laboratório."""
import ast
import json
from pathlib import Path
import re
import subprocess
import time

source = Path(__file__).with_name('archive-binlogs.py')
tree = ast.parse(source.read_text())
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('require', 'inventory')]
namespace = {'re': re, 'subprocess': subprocess, 'time': time}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
calls = []
responses = iter([
    [['binlog.000080', '1073741800', 'No']],
    [['binlog.000081']],
    [['binlog.000080', '1073741850', 'No'], ['binlog.000081', '180', 'No']],
    [['binlog.000081']],
])

def mysql(sql, *, timeout):
    assert 0 < timeout <= 5
    calls.append(sql)
    return next(responses)

namespace['mysql'] = mysql
stable = namespace['inventory']()
assert stable == [('binlog.000080', 1073741850), ('binlog.000081', 180)]
assert len(calls) == 4
print(json.dumps({'status': 'rotation_recovered_without_io', 'inventory_attempts': 2,
                  'queries': calls}, indent=2))
