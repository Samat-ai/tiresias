"""Deploy the web slice to the owner's Vultr VM over pinned-key SSH.

Only allowlisted source and web credentials leave this computer. Run from the
repository root. The source archive contains no environment files or runtime data.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from tiresias.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def source_paths():
    for folder, suffixes in [('src/tiresias', {'.py', '.html', '.css', '.js'}),
                             ('migrations', {'.sql'}), ('deploy', {'.sh', '.service', '.md', ''})]:
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file() and path.suffix in suffixes and '__pycache__' not in path.parts:
                yield path
    yield ROOT/'pyproject.toml'


def web_environment(settings, hostname):
    if not settings.database_url or not settings.elevenlabs_key():
        raise SystemExit('Configure the Tiger Data URL and ElevenLabs key locally first.')
    values = {
        'APP_ENV': 'production', 'APP_BASE_URL': f'https://{hostname}',
        'DATABASE_URL': settings.database_url, 'ELEVENLABS_API_KEY': settings.elevenlabs_key(),
        'ELEVENLABS_TTS_MODEL': settings.elevenlabs_tts_model,
        'ALLOW_REGISTRATION': 'true', 'PRIVATE_SNAPSHOT_DIR': '/var/lib/tiresias/snapshots',
    }
    if settings.caller_link_secret:
        values['CALLER_LINK_SECRET']=settings.caller_link_secret
    lines=[]
    for key, value in values.items():
        if any(c in value for c in '\n\r\0'):
            raise SystemExit(f'Unexpected control character in {key}.')
        escaped=value.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(f'{key}="{escaped}"')
    return ('\n'.join(lines)+'\n').encode()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--alias', action='append', default=[], help='Additional HTTPS hostname; repeat as needed.')
    parser.add_argument('--key', default='data/deploy/tiresias_ed25519')
    args=parser.parse_args()
    for value in [args.host, args.hostname, *args.alias]:
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,252}', value):
            parser.error('Host and hostname must be ordinary IPv4/DNS names.')
    settings=Settings()
    environment=web_environment(settings,args.hostname)
    release=datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%Sz').lower()
    target=f'root@{args.host}'
    ssh=['ssh','-i',str(ROOT/args.key),'-o','BatchMode=yes','-o','ConnectTimeout=15',
         '-o','StrictHostKeyChecking=yes','-o',f'UserKnownHostsFile={ROOT / "data/deploy/known_hosts"}',target]

    archive=ROOT/'data/deploy'/f'source-{release}.tar.gz'
    archive.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive,'w:gz') as bundle:
        for path in source_paths():
            bundle.add(path,arcname=path.relative_to(ROOT).as_posix())
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    remote=f'/opt/tiresias/releases/{release}'
    subprocess.run(ssh+[f'install -d -m 0755 {remote}; install -d -m 0750 /etc/tiresias'],check=True)
    with archive.open('rb') as source:
        subprocess.run(ssh+[f'tar -xzf - -C {remote}'],stdin=source,check=True)
    # Pass secrets via encrypted stdin only, never argv, logs or the archive.
    subprocess.run(ssh+['umask 077; cat > /etc/tiresias/tiresias.env'],input=environment,check=True)
    hostnames=' '.join([args.hostname,*args.alias])
    subprocess.run(ssh+[f'sh {remote}/deploy/provision.sh {release} {hostnames}'],check=True)
    print(f'Release: {release}\nSource SHA256: {digest}\nURL: https://{args.hostname}')


if __name__=='__main__':
    main()
