"""Diagnósticos públicos: códigos conhecidos, metadados e nenhum corpo arbitrário."""
import hashlib

KNOWN_REASONS = {
    b'Tracker temporarily unavailable. Please retry later.': 'tracker_unavailable',
    b'Internal tracker error.': 'tracker_internal_error',
    b'Invalid announce origin.': 'invalid_origin',
    b'Maximum number of endpoint families reached.': 'endpoint_limit',
}


class ResponseFailure(AssertionError):
    def __init__(self, status, body, result=None):
        result = result if isinstance(result, dict) else {}
        reason = result.get(b'failure reason', result.get(b'warning message'))
        code = KNOWN_REASONS.get(reason, 'tracker_response_unknown') if isinstance(reason, bytes) else ('http_status' if status!=200 else 'invalid_tracker_response')
        self.public = dict(code=code, http_status=status, body_bytes=len(body),
                           body_sha256=hashlib.sha256(body).hexdigest())
        super().__init__(code)


def record_drain(status, error=None):
    """A falha de drenagem permanece visível mesmo com motivo principal anterior."""
    status['tracker_drain'] = {'status': 'failed' if error else 'passed'}
    if error:
        status['tracker_drain']['error_type'] = type(error).__name__
    status.setdefault('cleanup', []).append({'vm': 120, 'action': 'tracker_drain',
        'status': status['tracker_drain']['status']})
