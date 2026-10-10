#!/usr/bin/env python3
"""Um announce real IPv4 contra a tag Rust; nao exporta passkey ou URL."""
import http.client
import json
from pathlib import Path
import urllib.parse

from baseline import safe_response

base = Path('/opt/unit3d-dualstack')
fixture = json.loads((base/'fixture.json').read_text())
params = {'info_hash': bytes.fromhex(fixture['torrents'][0]['info_hash_hex']),
          'peer_id': b'-DS9200-000000000092', 'port': 6881, 'uploaded': 1400,
          'downloaded': 0, 'left': 0, 'numwant': 0, 'compact': 1}
connection = http.client.HTTPConnection('172.29.92.10', 8080, timeout=3, source_address=('172.29.92.30', 0))
try:
    connection.request('GET', '/announce/'+fixture['users'][0]['passkey']+'?'+urllib.parse.urlencode(params, quote_via=urllib.parse.quote),
                       headers={'User-Agent': 'libtorrent/2.0.10'})
    response = connection.getresponse()
    body = safe_response(response.read())
    if response.status != 200 or 'failure reason' in body:
        raise AssertionError('Announce original recusado: '+json.dumps(body))
    print(json.dumps({'status': 'passed', 'backend': 'Rust 0.3.1 original', 'family': 4, 'uploaded': 1400, 'response': body}))
finally:
    connection.close()
