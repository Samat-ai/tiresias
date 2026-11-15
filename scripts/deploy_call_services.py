"""Stage persistent cloud call services over pinned SSH; secret transfer is opt-in.

This leaves the existing HTTPS service running. Deploy current application source
with deploy_vultr.py first. No credentials are accessed by prepare/check/start/stop.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CALL_HOME = '/var/lib/tiresias-call'
PROJECT = '8fdd4e9f-a087-4269-89d1-8ee7fbfe6ba2'

PREPARE = r'''
set -eu
test -x /opt/tiresias/current/.venv/bin/python
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -o DPkg::Lock::Timeout=180 install -y -qq ca-certificates python3-venv libgomp1 xz-utils
if ! id tiresias-call >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/tiresias-call --create-home --shell /usr/sbin/nologin tiresias-call
fi
install -d -o tiresias-call -g tiresias-call -m 0700 /var/lib/tiresias-call /var/lib/tiresias-call/.chert /var/lib/tiresias-call/snapshots
install -d -o root -g tiresias-call -m 0750 /etc/tiresias-call
install -d -m 0755 /opt/tiresias/runtime /opt/tiresias/chert
python3 - <<'PY'
import hashlib, pathlib, re, tarfile, tempfile, urllib.request
base = 'https://nodejs.org/dist/latest-v22.x/'
checksums = urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=30).read().decode()
entry = next((line.split() for line in checksums.splitlines()
              if re.fullmatch(r'[0-9a-f]{64}\s+node-v22\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz', line)), None)
if not entry:
    raise SystemExit('No supported Node22 Linux x64 archive in official manifest')
digest, name = entry
root = pathlib.Path('/opt/tiresias/runtime')
destination = root / name.removesuffix('.tar.xz')
if not destination.exists():
    with tempfile.TemporaryDirectory(prefix='tiresias-node-') as work:
        archive = pathlib.Path(work) / name
        urllib.request.urlretrieve(base + name, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise SystemExit('Node archive checksum mismatch')
        with tarfile.open(archive) as bundle:
            bundle.extractall(root, filter='data')
link = root / 'node'
if link.is_symlink():
    link.unlink()
elif link.exists():
    raise SystemExit('Refusing to replace unexpected Node runtime directory')
link.symlink_to(destination, target_is_directory=True)
print('Node runtime:', name.removesuffix('-linux-x64.tar.xz'))
PY
export PATH=/opt/tiresias/runtime/node/bin:/usr/sbin:/usr/bin:/sbin:/bin
npm install --prefix /opt/tiresias/chert --omit=dev --no-audit --no-fund --ignore-scripts @trychert/facetime@0.1.0-beta.21
python3 -m venv /opt/tiresias/runtime/call-venv
/opt/tiresias/runtime/call-venv/bin/pip install --disable-pip-version-check --quiet '/opt/tiresias/current[media]'
runuser -u tiresias-call -- env HOME=/var/lib/tiresias-call OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /opt/tiresias/runtime/call-venv/bin/python -c 'from livekit import rtc; from livekit.agents import AgentServer; from livekit.plugins import elevenlabs, silero; silero.VAD.load(); print("Native media imports and Silero model load passed")'
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/tiresias-agent.service /etc/systemd/system/tiresias-chert.service
echo 'Call dependencies and units staged; no call service started and no secrets copied.'
'''

START_CHERT = r'''
python3 - <<'PY'
import json, subprocess, time
since = str(int(time.time()))
subprocess.run(['systemctl', 'enable', 'tiresias-chert'], check=True)
subprocess.run(['systemctl', 'restart', 'tiresias-chert'], check=True)
for attempt in range(30):
    logs = subprocess.run(['journalctl', '-u', 'tiresias-chert', '--since', '@' + since,
                           '--output=cat', '--no-pager'], capture_output=True, text=True, check=True)
    codes = set()
    for line in logs.stdout.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            codes.add(record.get('code'))
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'tiresias-chert']).returncode == 0
    if active and {'dev_connected', 'agent_warm'} <= codes:
        print('Cloud connector connected and agent warm; make one real FaceTime test call.')
        break
    time.sleep(2)
else:
    raise SystemExit('Connector did not report dev_connected and agent_warm; inspect its private journal.')
PY
'''


def env_bytes(values: dict[str, str]) -> bytes:
    lines = []
    for key, raw in values.items():
        value = str(raw)
        if any(c in value for c in '\r\n\0'):
            raise ValueError(f'Control character in {key}')
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(f'{key}="{escaped}"')
    return ('\n'.join(lines) + '\n').encode()


def media_environment(settings) -> bytes:
    values = {
        'APP_ENV': 'production', 'APP_BASE_URL': 'https://tiresias.ink',
        'DATABASE_URL': settings.database_url,
        'LIVEKIT_URL': settings.livekit_url, 'LIVEKIT_API_KEY': settings.livekit_api_key,
        'LIVEKIT_API_SECRET': settings.livekit_api_secret,
        'AGENT_NAME': 'tiresias-agent', 'ELEVENLABS_API_KEY': settings.elevenlabs_key(),
        'ELEVENLABS_STT_MODEL': settings.elevenlabs_stt_model,
        'ELEVENLABS_TTS_MODEL': settings.elevenlabs_tts_model,
        'ELEVENLABS_VOICE_ID': settings.elevenlabs_voice_id,
        'GEMINI_MODEL': settings.gemini_model,
        'GOOGLE_GENAI_USE_VERTEXAI': 'true',
        'GOOGLE_CLOUD_PROJECT': settings.google_cloud_project,
        'GOOGLE_CLOUD_LOCATION': settings.google_cloud_location,
        'GOOGLE_APPLICATION_CREDENTIALS': '/etc/tiresias-call/vertex-adc.json',
        'CHERT_PROJECT_ID': PROJECT, 'CHERT_LINE_ID': settings.chert_line_id,
        'CHERT_INTEGRATION_MODE': 'cli',
        'CHERT_CREDENTIALS_FILE': CALL_HOME + '/.chert/credentials.json',
        'CALLER_LINK_SECRET': settings.caller_link_secret,
        'PRIVATE_SNAPSHOT_DIR': CALL_HOME + '/snapshots',
        'USE_MOCK_PROVIDERS': 'false',
    }
    for key in ('DATABASE_URL', 'LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET',
                'ELEVENLABS_API_KEY', 'GOOGLE_CLOUD_PROJECT', 'CALLER_LINK_SECRET'):
        if not values[key]:
            raise SystemExit(f'Missing required local setting: {key}')
    return env_bytes(values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'install-secrets', 'start-agent', 'start-chert', 'check', 'stop'])
    parser.add_argument('--host', default='45.76.239.245')
    parser.add_argument('--key', default='data/deploy/tiresias_ed25519')
    parser.add_argument('--authorize-secret-transfer', action='store_true',
                        help='Use only after authorization to export LiveKit, Chert, and Google ADC to this VM.')
    parser.add_argument('--adc-file', type=Path)
    parser.add_argument('--chert-credentials-file', type=Path)
    parser.add_argument('--takeover', action='store_true', help='Initial handoff only; explicitly authorized owned line.')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{1,252}', args.host):
        parser.error('Host must be a DNS name or IPv4 address')
    if args.takeover and args.action != 'start-chert':
        parser.error('--takeover only applies to start-chert')
    if args.action == 'install-secrets' and not (
        args.authorize_secret_transfer and args.adc_file and args.chert_credentials_file
    ):
        parser.error('install-secrets needs explicit --authorize-secret-transfer, --adc-file and --chert-credentials-file')
    ssh = ['ssh', '-i', str(ROOT / args.key), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
           '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={ROOT / "data/deploy/known_hosts"}',
           f'root@{args.host}']

    def run(command: str, payload: bytes | None = None, *, capture: bool = False):
        return subprocess.run(ssh + [command], input=payload, check=True, capture_output=capture)

    def put(path: str, payload: bytes, *, owner: str = 'root:tiresias-call', mode: str = '0640'):
        # Secret bytes travel only over encrypted stdin. Never use an archive/argv.
        dest = shlex.quote(path)
        command = (f'set -eu; umask 077; t=$(mktemp {dest}.XXXXXX); '
                   f'trap \'rm -f "$t"\' EXIT; cat > "$t"; '
                   f'chown {owner} "$t"; chmod {mode} "$t"; mv -f "$t" {dest}')
        run(command, payload)

    if args.action == 'prepare':
        for unit in ('tiresias-agent.service', 'tiresias-chert.service'):
            put('/etc/systemd/system/' + unit, (ROOT / 'deploy' / unit).read_bytes(), owner='root:root', mode='0644')
        run('sh -s', PREPARE.encode())
    elif args.action == 'install-secrets':
        from tiresias.config import Settings
        settings = Settings()
        media = media_environment(settings)
        # Read only the two files explicitly selected after transfer authorization.
        adc = args.adc_file.read_bytes()
        chert = args.chert_credentials_file.read_bytes()
        for label, content in [('ADC', adc), ('Chert', chert)]:
            if not isinstance(json.loads(content), dict):
                raise SystemExit(f'{label} credential must be a JSON object')
        chert_env = env_bytes({'LIVEKIT_URL': settings.livekit_url,
                               'LIVEKIT_API_KEY': settings.livekit_api_key,
                               'LIVEKIT_API_SECRET': settings.livekit_api_secret})
        put('/etc/tiresias-call/media.env', media)
        put('/etc/tiresias-call/chert.env', chert_env)
        put('/etc/tiresias-call/vertex-adc.json', adc)
        put(CALL_HOME + '/.chert/credentials.json', chert, owner='tiresias-call:tiresias-call', mode='0600')
        print('Scoped call credentials installed; services remain stopped.')
    elif args.action == 'start-agent':
        run('set -eu; systemctl enable tiresias-agent; systemctl restart tiresias-agent; '
            'attempt=0; until curl --fail --silent http://127.0.0.1:8081/ >/dev/null; do '
            'attempt=$((attempt + 1)); test "$attempt" -lt 30; sleep 2; done; '
            'systemctl is-active --quiet tiresias-agent; '
            'echo "Agent connected to LiveKit; inspect registration before stopping the local worker."')
    elif args.action == 'start-chert':
        # Check active calls with Chert on the laptop before stopping its connector.
        # Chert itself refuses line_in_call even when --takeover is supplied.
        if args.takeover:
            run('install -d /run/systemd/system/tiresias-chert.service.d; '
                'printf \'[Service]\\nEnvironment=CHERT_TAKEOVER=--takeover\\n\' '
                '> /run/systemd/system/tiresias-chert.service.d/handoff.conf; systemctl daemon-reload')
        try:
            run('sh -s', START_CHERT.encode())
        finally:
            if args.takeover:
                run('rm -f /run/systemd/system/tiresias-chert.service.d/handoff.conf; systemctl daemon-reload')
    elif args.action == 'check':
        run("systemctl show tiresias-web tiresias-agent tiresias-chert "
            "--property=Id,ActiveState,SubState,NRestarts,MemoryCurrent; "
            "curl --silent --fail http://127.0.0.1:8000/healthz; "
            "printf '\\n'; ss -ltn")
    elif args.action == 'stop':
        run('systemctl disable --now tiresias-chert tiresias-agent')


if __name__ == '__main__':
    main()
