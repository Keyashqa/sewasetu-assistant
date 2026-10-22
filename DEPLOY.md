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
- **Sized for the GCP Always Free tier** (e2-micro, 1 GB RAM): a 2 GB swapfile, per-service
  `mem_limit` summing to 880 MB, gunicorn 2 workers, uvicorn 1 worker, at most 5 pooled
  connections per process (`DB_POOL_MAX`), and Postgres tuned down (§1.6).

Current deployment: GCP project `build4b`, zone `us-central1-a`, VM `sewasetu`
(e2-micro, Ubuntu 24.04 LTS, 30 GB pd-standard) on network `sewasetu-net` / subnet
`sewasetu-subnet-usc1`, static IP `sewasetu-ip` (136.116.6.93), hostname
`136-116-6-93.sslip.io`. Repo on the VM: `/opt/sewasetu-assistant`.

Free-tier limits that matter (check the current GCP Free Tier terms): one e2-micro in
us-west1, us-central1 or us-east1; 30 GB-months of **standard** persistent disk (pd-balanced
and SSD are billed); 1 GB/month of egress from North America. A reserved static IP that is
**not attached** to a running VM is billed: release it if the VM is deleted or stopped for long.

Shorthand used below, on the VM, in `/opt/sewasetu-assistant`:

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
```

## 1. First deploy

### 1.1 Infrastructure (from a workstation with gcloud)

```bash
gcloud config set project build4b

# dedicated network: the project's `default` network allows RDP/ICMP to every VM on it
gcloud compute networks create sewasetu-net --subnet-mode=custom
gcloud compute networks subnets create sewasetu-subnet-usc1 \
  --network=sewasetu-net --region=us-central1 --range=10.10.1.0/24

# the only ingress rule on sewasetu-net: 22, 80, 443
gcloud compute firewall-rules create sewasetu-allow-web \
  --network=sewasetu-net --direction=INGRESS --action=allow \
  --rules=tcp:22,tcp:80,tcp:443 --source-ranges=0.0.0.0/0 --target-tags=sewasetu-web

gcloud compute addresses create sewasetu-ip --region=us-central1
gcloud compute addresses describe sewasetu-ip --region=us-central1 --format='value(address)'

# Always Free: e2-micro, us-central1, pd-standard (NOT pd-balanced), 30 GB
gcloud compute instances create sewasetu \
  --zone=us-central1-a --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --subnet=sewasetu-subnet-usc1 --address=sewasetu-ip --tags=sewasetu-web
```

`sewasetu-net` has no rule other than `sewasetu-allow-web`, so 22/80/443 are the only ports
open to the VM. Check with
`gcloud compute firewall-rules list --filter="network=sewasetu-net"`.

### 1.2 VM setup (`gcloud compute ssh sewasetu --zone=us-central1-a`)

A persistent 2 GB swapfile first (1 GB of RAM is not enough to build the images or to load
the seed without it):

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swappiness.conf && sudo sysctl --system
```

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

### 1.6 Memory budget (e2-micro, 1 GB RAM + 2 GB swap)

| service | `mem_limit` | tuning |
|---|---|---|
| db | 320 MB | `shared_buffers=64MB`, `work_mem=2MB`, `max_connections=30`, `effective_cache_size=256MB` |
| app | 200 MB | gunicorn `--workers 2`, `DB_POOL_MAX=5` |
| mcp | 200 MB | uvicorn `--workers 1`, `DB_POOL_MAX=5` |
| scheduler | 60 MB | cron + the nightly job |
| proxy | 50 MB | Caddy |
| smsgw | 50 MB | in-memory inbox |
| **total** | **880 MB** | |

Connections at peak: 2 × 5 (gunicorn) + 5 (mcp) + the portal's per-request connections + the
scheduler + `pg_dump`, well under 30. Watch with `free -m` and `docker stats --no-stream`;
a service that hits its limit is OOM-killed and restarted (`dc ps` shows the restarts).

Building on the VM (`dc build`) relies on the swapfile and is slow. If it is too slow, build
on a workstation and ship the images:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker save sewasetu-app sewasetu-mcp sewasetu-scheduler sewasetu-smsgw | gzip \
  | gcloud compute ssh sewasetu --zone=us-central1-a --command='gunzip | sudo docker load'
# then on the VM: dc up -d   (no --build)
```

## 2. Update

```bash
cd /opt/sewasetu-assistant
sudo /usr/local/bin/sewasetu-backup          # always take a dump first
git rev-parse HEAD                           # note the current commit for rollback
sudo git pull --ff-only
dc up -d --build                             # rebuilds app/mcp/scheduler, recreates changed services
dc ps && dc logs --tail=50 mcp app
# self-checks (read-only, or self-cleaning on a reserved test mobile)
dc exec -T app python /app/scripts/check_document_flow.py
dc exec -T app python /app/scripts/check_officer_documents.py
```

For a change to `app/` only, rebuild and restart just those two services so the SMS
gateway's in-memory inbox survives: `dc build app mcp && dc up -d --no-deps app mcp`.

The `mcp` container applies new migrations (`app/migrations/*.sql`, idempotent) before it
starts. Never `dc down -v` on the VM: `-v` deletes the database and the uploads.

## 3. Back up and restore

```bash
sudo /usr/local/bin/sewasetu-backup                       # on-demand dump
ls -lh /var/backups/sewasetu/

# uploads (age proofs), when needed
sudo tar -C /var/lib/docker/volumes/sewasetu_uploads/_data -czf /var/backups/sewasetu/uploads-$(date -u +%F).tgz .

# copy off the VM
gcloud compute scp sewasetu:/var/backups/sewasetu/<file> . --zone=us-central1-a

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
(`gcloud compute instances stop sewasetu --zone=us-central1-a`) without losing the disk or
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
