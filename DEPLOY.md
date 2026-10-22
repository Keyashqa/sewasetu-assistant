# DEPLOY.md — running Sewa Setu on a VM

One VM, the same compose stack as local, plus `docker-compose.prod.yml`:

- **Caddy** serves the public hostname with automatic HTTPS on 80/443 (`proxy/Caddyfile.prod`);
  routing is identical to local (`/mcp/*` and the protected-resource metadata to the MCP
  servers, everything else to the portal).
- `restart: unless-stopped` and size-capped Docker logs on every service.
- The **scheduler runs** (deemed approval is the law). On a fresh database its boot run deems
  approved the seed's 700 overdue PENDING rows; that is correct.
- Only the proxy publishes ports. No demo data: `seed_demo_queue.py` is never run here (it
  refuses a non-localhost `PUBLIC_BASE_URL` anyway).

Current deployment: GCP project `build4b`, zone `asia-south1-a`, VM `sewasetu`
(e2-medium, Ubuntu 24.04 LTS, 30 GB), static IP `sewasetu-ip`, hostname
`<ip-with-dashes>.sslip.io`. Repo on the VM: `/opt/sewasetu-assistant`.

Shorthand used below, on the VM, in `/opt/sewasetu-assistant`:

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
```

## 1. First deploy

### 1.1 Infrastructure (from a workstation with gcloud)

```bash
gcloud config set project build4b
gcloud compute addresses create sewasetu-ip --region=asia-south1
gcloud compute addresses describe sewasetu-ip --region=asia-south1 --format='value(address)'

gcloud compute instances create sewasetu \
  --zone=asia-south1-a --machine-type=e2-medium \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-balanced \
  --address=sewasetu-ip --tags=sewasetu-web

gcloud compute firewall-rules create sewasetu-allow-web \
  --network=default --direction=INGRESS --action=allow \
  --rules=tcp:22,tcp:80,tcp:443 --target-tags=sewasetu-web --source-ranges=0.0.0.0/0
```

The VM gets only the `sewasetu-web` tag, so with the `default-allow-*` rules removed or
not matching, 22/80/443 are the only ports open to it. Check with
`gcloud compute firewall-rules list --filter="network=default"`.

### 1.2 VM setup (`gcloud compute ssh sewasetu --zone=asia-south1-a`)

Docker Engine and the compose plugin from Docker's apt repository
(https://docs.docker.com/engine/install/ubuntu/), then:

```bash
# read-only deploy key: add the .pub at GitHub → repo → Settings → Deploy keys (no write access)
sudo ssh-keygen -t ed25519 -N '' -C sewasetu-vm-deploy -f /root/.ssh/sewasetu_deploy
printf 'Host github.com\n  IdentityFile /root/.ssh/sewasetu_deploy\n  IdentitiesOnly yes\n' | sudo tee -a /root/.ssh/config
sudo ssh-keyscan github.com | sudo tee -a /root/.ssh/known_hosts
sudo git clone git@github.com:Keyashqa/sewasetu-assistant.git /opt/sewasetu-assistant
```

`.env` exists **only on the VM** (`/opt/sewasetu-assistant/.env`, mode 600, gitignored):

```
SITE_HOST=<ip-with-dashes>.sslip.io
PUBLIC_BASE_URL=https://<ip-with-dashes>.sslip.io
SECRET_KEY=<openssl rand -hex 32>
ADMIN_PASSWORD=<strong random>
```

`PUBLIC_BASE_URL` is stamped into token `iss`/`aud` and every discovery document; it must be
exactly `https://` + `SITE_HOST`, no trailing slash.

### 1.3 Start

```bash
dc up -d --build
dc logs -f scheduler     # "deemed approval: 700 applications approved" on a fresh volume
dc logs -f proxy         # certificate obtained for SITE_HOST
```

The first boot loads `seed/seed.sql` (~36 MB) into a fresh `sewasetu_pgdata` volume; give it
a minute. Services that start before Postgres is ready restart until it is.

### 1.4 Ops

```bash
sudo install -m 755 ops/backup.sh /usr/local/bin/sewasetu-backup
sudo install -m 644 ops/logrotate-sewasetu /etc/logrotate.d/sewasetu
echo '30 21 * * * root /usr/local/bin/sewasetu-backup >> /var/log/sewasetu-backup.log 2>&1' \
  | sudo tee /etc/cron.d/sewasetu-backup
```

- **Backups:** `pg_dump -Fc` at 21:30 UTC (03:00 IST) to `/var/backups/sewasetu/`, newest 7 kept.
  Uploaded age proofs live in the `sewasetu_uploads` volume and are not in the dump (§3).
- **Logs:** Docker logs are capped at 5 × 10 MB per container (compose `logging`). The
  portal's own logs in `sewasetu_applogs` (`sewasetu-app.log`, `cron.log`) rotate daily via
  logrotate, 14 kept, compressed.

### 1.5 Verify

From anywhere:

```bash
H=https://<ip-with-dashes>.sslip.io
curl -sv $H/ -o /dev/null 2>&1 | grep -E 'subject:|issuer:|expire|HTTP/'
curl -si -X POST $H/mcp/citizen -d '{}' | grep -i www-authenticate
for p in citizen officer; do for m in POST GET DELETE; do
  printf '%s %s -> ' $p $m; curl -s -o /dev/null -w '%{http_code}\n' -X $m $H/mcp/$p; done; done
curl -s $H/.well-known/oauth-protected-resource/mcp/citizen
curl -s $H/.well-known/oauth-authorization-server
```

Every 401 must carry `scope` and `resource_metadata`; no 307/308; every URL in the PRM and AS
documents must start with `$H`, and the AS `issuer` must equal `$H`.

## 2. Update

```bash
cd /opt/sewasetu-assistant
sudo /usr/local/bin/sewasetu-backup          # always take a dump first
git rev-parse HEAD                           # note the current commit for rollback
sudo git pull --ff-only
dc up -d --build                             # rebuilds app/mcp/scheduler, recreates changed services
dc ps && dc logs --tail=50 mcp app
```

The `mcp` container applies new migrations (`app/migrations/*.sql`, idempotent) before it
starts. Never `dc down -v` on the VM: `-v` deletes the database and the uploads.

## 3. Back up and restore

```bash
sudo /usr/local/bin/sewasetu-backup                       # on-demand dump
ls -lh /var/backups/sewasetu/

# uploads (age proofs), when needed
sudo tar -C /var/lib/docker/volumes/sewasetu_uploads/_data -czf /var/backups/sewasetu/uploads-$(date -u +%F).tgz .

# copy off the VM
gcloud compute scp sewasetu:/var/backups/sewasetu/<file> . --zone=asia-south1-a

# restore a dump (stops writers first)
dc stop app mcp scheduler
dc exec -T db pg_restore -U sewasetu -d sewasetu --clean --if-exists < /var/backups/sewasetu/<file>.dump
dc start app mcp scheduler
```

## 4. Roll back

Code:

```bash
cd /opt/sewasetu-assistant
sudo git checkout <previous-commit>      # detached HEAD; `git checkout main` to return
dc up -d --build
```

If the bad release changed data, restore the dump taken before the update (§3) after the
code rollback. Migrations are additive, so older code runs against a newer schema.

Infrastructure: everything is named `sewasetu*` in project `build4b`; the VM can be stopped
(`gcloud compute instances stop sewasetu --zone=asia-south1-a`) without losing the disk or
the static IP.

## 5. Known risks (accepted for the test window)

- **`/__gateway/` is public.** The simulated SMS gateway's console and
  `/__gateway/api/messages?to=<mobile>` are reachable by anyone, so anyone can read any OTP
  and sign in as any citizen (IMPLEMENTATION_PLAN R9, AUDIT §9-D2). Kept on purpose: the
  testers sign citizens in by reading the OTP there. A real deployment uses a real SMS
  provider and removes the route.
- One officer identity (`admin`); every decision is `decided_by = admin`,
  `officer:admin via assistant` in the audit (R5).
- Access tokens stay valid up to 20/30 min after revocation (R8).
- No rate limiting or CSRF tokens on the portal's web forms.
- The SMS gateway's inbox is in memory: restarting `smsgw` loses it.

## 6. Rotate before real production

- **Postgres password** `sewasetu123` is in `docker-compose.yml` (and `app/config/app.ini`).
  The database is not published outside the compose network, but the value is in the repo.
- **`secret_key` in `app/config/app.ini`** is a committed placeholder. It is overridden by
  `SECRET_KEY` from `.env` (required by compose), so it is not used, but remove it.
- `ADMIN_PASSWORD` and `SECRET_KEY` in the VM's `.env`: rotating `SECRET_KEY` signs everyone
  out of the portal's web sessions; rotating `ADMIN_PASSWORD` needs `dc up -d app mcp`.
- The OAuth RSA signing key (`oauth.signing_key()`) is generated once and stored in the
  database, so it is also in every dump; rotating it invalidates every issued token,
  including program tokens.
