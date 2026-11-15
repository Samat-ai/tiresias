# Vultr web deployment

The Vultr VM runs FastAPI, Caddy and systemd. The separate call worker and Chert
connector also run on this VM; see [Persistent cloud calling](CALL-HOSTING.md).
All services use the same hosted Tiger Data database, so saved voices and
aggregate call telemetry are shared. This document covers the web deployment.

From the repository root, using a private SSH key registered on the VM and a
previously verified `data/deploy/known_hosts`:

```powershell
.\.venv\Scripts\python.exe scripts/deploy_vultr.py --host 45.76.239.245 --hostname tiresias.ink --alias www.tiresias.ink --alias 45.76.239.245.sslip.io
```

The script sends only source, the Tiger Data URL, ElevenLabs web-preview key
and the application-owned `CALLER_LINK_SECRET` when configured.
It does not upload ADC, LiveKit/Chert keys, snapshots, accounts, logs or the local
virtual environment. Secrets live in `/etc/tiresias/tiresias.env`, readable by
root and the service group. Releases are root-owned; the web service runs as a
dedicated unprivileged user and listens on loopback. Public ports are 80/443;
SSH remains open. Do not expose port 8000.

The database must already have the application migrations. After schema changes,
run `python -m tiresias.migrate` locally with the configured application URL
before deploying the compatible web release. Tests use an isolated test DB.

Verify `https://tiresias.ink/healthz`, register/sign in, save a voice,
reload, preview it and check `/performance`. Use your own account. During a call,
say “Use profile” followed by the eight digits on your settings page. This code
selects voice preferences only; it does not authenticate the caller.

Operations over the same pinned-key SSH connection:

```sh
systemctl status tiresias-web caddy
journalctl -u tiresias-web -n 50 --no-pager
systemctl restart tiresias-web
cat /opt/tiresias/previous-release
```

To roll back, verify the recorded path is a prior directory under
`/opt/tiresias/releases/`, repoint `/opt/tiresias/current` to that path and restart
`tiresias-web`. Keep the database schema compatible with that release. Credentials
are shared across releases and are not rolled back. Caddy renews HTTPS
automatically. The sslip.io hostname remains a fallback during DNS propagation.

For automatic caller settings, retain the same random `CALLER_LINK_SECRET`
(at least 32 characters) in the local worker environment and deployed web
environment. The local worker resolves caller handles through its existing
`~/.chert/credentials.json`; that credential is never uploaded to Vultr. Users
connect their phone/FaceTime email once under “Remember me next time”: request
setup, make an inbound call, and enter the four spoken digits on the site.
Later calls use the saved preferences automatically. Only masked handles and
keyed fingerprints are stored. This link does not authenticate web/private data.
Apply migration 004 before enabling caller setup.

In Porkbun DNS, replace the root/www parking records pointing to
`pixie.porkbun.com`: add an A record with blank Host and Answer `45.76.239.245`,
and a CNAME with Host `www` and Answer `tiresias.ink`. Keep default TTL,
nameservers, MX and TXT records. No AAAA record is needed for this IPv4 setup.
