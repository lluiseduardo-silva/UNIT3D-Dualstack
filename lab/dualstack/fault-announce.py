#!/usr/bin/env python3
"""Uma requisicao por socket real; exporta somente campos seguros do protocolo."""
import argparse
import http.client
import json
from pathlib import Path
import socket
import time
import urllib.parse

from baseline import bdecode


def main():
    if socket.gethostname() != 'unit3d-ds-clients':
        raise SystemExit('Exige a VM isolada de clientes.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--family', type=int, choices=[4, 6], required=True)
    parser.add_argument('--uploaded', type=int, required=True)
    parser.add_argument('--event', choices=['started', 'completed'], default='completed')
    args = parser.parse_args()
    fixture = json.loads(Path('/opt/unit3d-dualstack/fixture.json').read_text())
    peer = b'-DS9200-000000000091'
    params = {'info_hash': bytes.fromhex(fixture['torrents'][0]['info_hash_hex']), 'peer_id': peer,
              'port': 6881, 'uploaded': args.uploaded, 'downloaded': 0, 'left': 0,
              'event': args.event, 'compact': 1, 'numwant': 0}
    target = '172.29.92.10' if args.family == 4 else 'fd42:756e:6974:92::10'
    source = '172.29.92.30' if args.family == 4 else 'fd42:756e:6974:92::30'
    connection = http.client.HTTPConnection(target, 8080, timeout=12, source_address=(source, 0))
    result = {'user_id': fixture['users'][0]['id'], 'torrent_id': fixture['torrents'][0]['id'],
              'peer_id_hex': peer.hex(), 'source_family': args.family, 'event': args.event,
              'uploaded': str(args.uploaded), 'success': False}
    start = time.monotonic()
    try:
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        connection.request('GET', '/announce/'+fixture['users'][0]['passkey']+'?'+query,
                           headers={'User-Agent': 'libtorrent/2.0.10'})
        response = connection.getresponse()
        result['http_status'] = response.status
        body = response.read()
        try:
            decoded = bdecode(body)
            result['protocol_failure'] = b'failure reason' in decoded
            result['success'] = response.status == 200 and not result['protocol_failure']
            for field in [b'complete', b'incomplete', b'interval']:
                if isinstance(decoded.get(field), int):
                    result[field.decode('ascii')] = decoded[field]
        except (ValueError, IndexError, AttributeError, TypeError):
            result['invalid_bencode'] = True
    except Exception as error:
        # Nem mensagens de drivers nem corpo HTTP: podem conter URL/passkey.
        result['transport_error'] = type(error).__name__
    finally:
        connection.close()
    result['duration_seconds'] = round(time.monotonic() - start, 6)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
