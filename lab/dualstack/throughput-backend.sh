#!/usr/bin/env bash
set -euo pipefail
test "$(hostname)" = unit3d-ds-tracker
base=/opt/unit3d-dualstack
action=${1:?}
case "$action" in start|stop) ;; *) exit 2 ;; esac
mode=${2:?}
batch=${3:-200}
case "$mode:$batch" in reference:200|instrumented:200|unobserved:200|drain:200|drain:500|writer-cadence:200|writer-cadence:500|writer-endpoints:200|writer-endpoints:500) ;; *) exit 2 ;; esac
if test "$mode" = reference || test "$action" = stop; then
    exec bash "$base/lab/benchmark-backend.sh" "$action" rust candidate
fi
# Gerar a partir do runner validado: a politica HTTP e o banco sao identicos.
python3 - "$mode" "$batch" <<'PY'
from pathlib import Path
import sys
base=Path('/opt/unit3d-dualstack')
mode,batch=sys.argv[1:]
text=(base/'lab/benchmark-backend.sh').read_text()
experiment=mode if mode.startswith('writer-') else 'throughput-rust'
assert (base/'experiments'/experiment/'lab-source.json').is_file()
text=text.replace('$source_dir/UNIT3D-Announce', '$base/experiments/'+experiment)
if mode.startswith('writer-'):
    needle="values.pop('LISTENING_UNIX_SOCKET', None)"
    assert text.count(needle)==1
    text=text.replace(needle,f"values['DUALSTACK_BATCH_SIZE'] = '{batch}'\n"+needle)
needle='docker run -d --name unit3d-ds-rust --network host'
assert text.count(needle)==1
flags=' -e DS_LAB_METRICS=1' if mode.startswith('writer-') else f' -e DS_LAB_DRAIN={int(mode=="drain")} -e DS_LAB_METRICS={int(mode!="unobserved")} -e DS_LAB_BATCH={batch}'
text=text.replace(needle,needle+flags)
(base/'lab/throughput-backend-generated.sh').write_text(text)
PY
exec bash "$base/lab/throughput-backend-generated.sh" start rust candidate
