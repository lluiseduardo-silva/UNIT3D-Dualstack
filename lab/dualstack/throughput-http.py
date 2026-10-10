#!/usr/bin/env python3
"""Reusar as verificacoes e amostras da densidade; ampliar somente a taxa."""
import argparse
import asyncio
from pathlib import Path

path=Path(__file__).with_name('density-http.py')
source=path.read_text()
assert source.count("cfg['rate'] <= 2000")==1
assert source.count("for g in groups.values()) <= 2000")==1
source=source.replace("cfg['rate'] <= 2000", "cfg['rate'] <= 12000")
source=source.replace("for g in groups.values()) <= 2000", "for g in groups.values()) <= 12000")
needle="        assert slots and 0 < cfg['rate'] <= 12000"
assert source.count(needle)==1
source=source.replace(needle,'''        if spec.get('shuffle', False):
            import random
            peers = {id(p): p for p, _ in slots}
            ordered = list(peers.values())
            random.Random(9137).shuffle(ordered)
            slots = [(p, f) for p in ordered for f in [4, 6]]
'''+needle)
start="            query = urllib.parse.urlencode("
end="            await writer.drain()"
a=source.index(start); b=source.index(end,a)
original=source[a:b]
source=source.replace('        connections = {}', '        connections = {}\n        verified_wires = set()')
# Mesmos bytes HTTP; campos constantes calculados antes da janela de carga.
prepare=original[:original.index("            writer.write(")]
prepare=prepare.replace('            ','        ').replace('uploaded=counter','uploaded=0')
cache='''    if spec.get('fast', False):
        for p in lanes:
'''+''.join('    '+line+'\n' for line in prepare.splitlines())+'''            wire=('GET '+path+' HTTP/1.1\\r\\nHost: tracker.lab\\r\\nUser-Agent: libtorrent/2.0.10\\r\\nConnection: keep-alive\\r\\n\\r\\n').encode()
            assert wire.count(b'uploaded=0&') == 1
            p['wire']=wire.split(b'uploaded=0&')
'''
source=source.replace('    start = time.monotonic()+.2',cache+'    start = time.monotonic()+.2')
parity=''.join('        '+line+'\n' for line in original[:original.index('            writer.write(')].splitlines())
expression=original.splitlines()[-1].strip()[len('writer.write('):-1]
source=source.replace(original,'''            if spec.get('fast', False):
                wire=p['wire'][0]+b'uploaded='+str(counter).encode()+b'&'+p['wire'][1]
                if family not in verified_wires:
'''+parity+'                    assert wire == '+expression+'''\n                    verified_wires.add(family)
                writer.write(wire)
            else:
'''+''.join('    '+line+'\n' for line in original.splitlines()))
scope={'__name__':'throughput_load','__file__':str(path)}
exec(compile(source,str(path),'exec'),scope)
parser=argparse.ArgumentParser()
parser.add_argument('plan')
asyncio.run(scope['main'](parser.parse_args()))
