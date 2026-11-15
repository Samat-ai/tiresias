# Persistent cloud calling

The existing Ubuntu 24.04 Vultr VM (`45.76.239.245`) can run both the Python
LiveKit agent and the Chert connector. Chert's Mac remains remotely hosted by
Chert; Linux needs no FaceTime application, camera, desktop, or inbound media
port. The HTTPS website and Caddy continue running independently.

Both new units use the dedicated `tiresias-call` account. Its state lives in
`/var/lib/tiresias-call`, separate from the website's `tiresias` account. Both
services restart after a crash or VM reboot. The media worker health endpoint
must bind only `127.0.0.1:8081`; no firewall or Caddy change is needed.

## Stage software without transferring secrets

First deploy the current application source using the existing web deployment
workflow. The new worker expects `AgentServer` to honor `AGENT_HOST`,
`AGENT_PORT`, and `AGENT_NUM_IDLE_PROCESSES` (the unit sets loopback, 8081, and
zero idle processes). The one CPU VM should also limit ONNX/Torch runtime
threads in application code where supported; its BLAS/OpenMP environment is
already bounded to one thread in the service.

From the repository root, using the existing pinned SSH identity:

```powershell
.venv/Scripts/python.exe scripts/deploy_call_services.py prepare
```

This installs Python media extras into `/opt/tiresias/runtime/call-venv`, official Node 22
(Linux x64, TLS download with the official SHA256 manifest), and pinned
`@trychert/facetime@0.1.0-beta.21`. Node 18 from Ubuntu's default repository
does not satisfy this CLI's Node version requirement. The script installs the
two unit files and verifies their systemd syntax. It does not start them,
replace application source, read local credentials, or change the website.

The stable call virtualenv survives web deployments. The worker unit uses
`PYTHONPATH=/opt/tiresias/current/src` so a restart loads the current release's
application code with those stable dependencies. Repeat preparation when the
media dependency list changes. Plan worker restarts between calls.

## Credential decision required before handoff

The earlier website deployment authorization covers its database and ElevenLabs
credentials. Cloud calling additionally requires authorization to transfer the
LiveKit key and secret, the Chert login credential, and a Google ADC credential
to this particular VM. The helper requires a separate explicit flag and paths;
staging software never implies permission for these transfers.

Prefer a dedicated Google identity limited to the required Vertex AI project.
Creating that identity or changing IAM is outside this script. Reusing an
existing user ADC file exports that user's refresh credential and existing
access scope; it is a separate authorization decision. No IAM is changed.

After approval, select the exact credential paths locally and run:

```powershell
.venv/Scripts/python.exe scripts/deploy_call_services.py install-secrets `
  --authorize-secret-transfer `
  --adc-file <approved-google-adc-json-path> `
  --chert-credentials-file <approved-chert-credentials-json-path>
```

Only allowlisted Settings become `/etc/tiresias-call/media.env`. The separate
`/etc/tiresias-call/chert.env` contains the three LiveKit settings only. Google ADC
lives at `/etc/tiresias-call/vertex-adc.json`, owned `root:tiresias-call`, mode 0640.
Chert's login is `/var/lib/tiresias-call/.chert/credentials.json`, owned by the
call account, mode 0600. Environment files are owned `root:tiresias-call`, mode
0640. Their parent `/etc/tiresias-call` is owned `root:tiresias-call`, mode 0750,
so the call account can traverse it and the website account cannot. File writes use encrypted SSH stdin and atomic installation; secret
values never go in a source archive, command arguments, or deployment output.

`CHERT_HOME=/var/lib/tiresias-call/.chert` controls the CLI credential and journal
directory. `CHERT_CREDENTIALS_FILE` in `media.env` points the caller identity
resolver at the same credential. The `dev` command does not accept a
`--credentials-file` flag. Its browser login expires after approximately 30
days; persistent systemd restart does not renew an expired login. Renew that
login using the approved operational credential process when needed.

## Controlled handoff

1. Check the owned Chert line and LiveKit rooms for an active call. Wait until
   it ends before stopping either local process. Chert also refuses
   `line_in_call` even when takeover is requested.
2. Start the cloud worker while the local connector remains available:

   ```powershell
   .venv/Scripts/python.exe scripts/deploy_call_services.py start-agent
   ```

   This checks the loopback health endpoint, which requires a healthy LiveKit
   connection. Confirm the cloud worker registered in its journal. Avoid test
   calls during the short overlap: both local and cloud workers register under
   the same agent name and either could receive a dispatch.
3. Stop the local connector gracefully (Ctrl+C releases its lease), then stop
   the local media worker. Do not stop unrelated Python or Node processes.
4. Start the cloud connector:

   ```powershell
   .venv/Scripts/python.exe scripts/deploy_call_services.py start-chert
   ```

   If replacing the still-connected owned session is explicitly authorized,
   add `--takeover`. This sets a temporary systemd override for the initial
   start and removes it afterward; ordinary future restarts do not steal a
   different live holder's lease. Never use `--force`.
5. Verify `dev_connected` and `agent_warm` in
   `journalctl -u tiresias-chert --since '5 minutes ago'`. Verify the media
   registration in `journalctl -u tiresias-agent --since '5 minutes ago'`.
   These journals can contain call identifiers; inspect them privately and
   avoid copying raw call records into public diagnostics.
6. Run `scripts/deploy_call_services.py check`, confirm HTTPS health, and place
   one real FaceTime call. Confirm actual speech and a visual task with the
   laptop processes stopped. This real call is required before declaring the
   laptop-independent flow verified.

`systemctl is-active` alone proves only that a process is running. Repeated
restarts, `dev_error`, or a missing `dev_connected` mean the handoff is not yet
healthy. `chert doctor --agent tiresias-agent --project
8fdd4e9f-a087-4269-89d1-8ee7fbfe6ba2 --env-file /etc/tiresias-call/chert.env --json`
can provide diagnostics under the call account with `CHERT_HOME` set, but it
creates and removes a short-lived LiveKit test room.

## Rollback without touching HTTPS

Wait for any active call to finish, then run:

```powershell
.venv/Scripts/python.exe scripts/deploy_call_services.py stop
```

This disables and gracefully stops only `tiresias-chert` and `tiresias-agent`.
Start the known local worker and connector again, in that order, with the same
agent/project configuration. Verify the local connector's `dev_connected`
before calling. If a previous cloud start was interrupted while using takeover,
remove `/run/systemd/system/tiresias-chert.service.d/handoff.conf` and run
`systemctl daemon-reload` before any subsequent cloud start. Retain installed
credentials only while cloud calling remains authorized.

The website unit and Caddy are unaffected. A source rollback is a separate
release operation; ensure its media dependencies match the stable call virtualenv
before restarting its worker. The VM has one CPU and 2 GB RAM, so this configuration targets one
FaceTime call at a time, with zero idle job processes and bounded service
memory. Observe swap pressure during the real call before increasing capacity.
