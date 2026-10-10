#!/usr/bin/env python3
"""RPC local dentro do namespace. Entrada sensivel por stdin, nunca argumentos."""
import base64
import http.client
import json
import sys
import urllib.parse


def main(request):
    client = request['client']
    if client == 'qbit':
        conn = http.client.HTTPConnection('127.0.0.1', 8088, timeout=3)
        data = request.get('data')
        headers = {}
        if 'torrent' in request:
            boundary = 'unit3d-dualstack-rpc'
            body = b''
            for name, value in data.items():
                body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="torrents"; filename="lab.torrent"\r\nContent-Type: application/x-bittorrent\r\n\r\n'.encode()
            body += base64.b64decode(request['torrent']) + f'\r\n--{boundary}--\r\n'.encode()
            headers['Content-Type'] = 'multipart/form-data; boundary='+boundary
        elif data is not None:
            body = urllib.parse.urlencode(data)
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            body = None
        conn.request('GET' if body is None else 'POST', '/api/v2/'+request['method'], body, headers)
        response = conn.getresponse()
        payload = response.read()
        if response.status != 200:
            raise RuntimeError('qBittorrent RPC HTTP '+str(response.status))
        try:
            return json.loads(payload)
        except ValueError:
            return {'text': payload.decode()}
    conn = http.client.HTTPConnection(request.get('rpc_host', '127.0.0.1'), 9091, timeout=3)
    body = json.dumps({'method': request['method'], 'arguments': request.get('data', {})})
    headers = {'Content-Type': 'application/json'}
    for _ in range(2):
        conn.request('POST', '/transmission/rpc', body, headers)
        response = conn.getresponse()
        payload = response.read()
        if response.status == 409:
            headers['X-Transmission-Session-Id'] = response.getheader('X-Transmission-Session-Id')
            continue
        result = json.loads(payload)
        if response.status != 200 or result['result'] != 'success':
            raise RuntimeError('Transmission RPC recusado')
        return result['arguments']
    raise RuntimeError('Transmission RPC sessao indisponivel')


if __name__ == '__main__':
    try:
        print(json.dumps(main(json.load(sys.stdin))))
    except Exception as error:
        print(json.dumps({'rpc_error': type(error).__name__}))
        raise SystemExit(1)
