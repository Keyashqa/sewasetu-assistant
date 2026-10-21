# AUDIT.md — Sewa Setu portal, pre-build audit

Audit date: **2026-10-21** (portal clock IST; all containers run UTC).
Stack brought up with `ADMIN_PASSWORD=audit123 docker compose up -d --build`, left running.
Everything below comes from reading the code, exercising the live portal over HTTP, and
read-only SQL. No code was modified. Anything I could not confirm is marked **UNVERIFIED**.

---

## EXECUTIVE SUMMARY (10 lines)

1. **The officer's queue is empty.** The seed's 700 PENDING rows were submitted 2026-09-16…09-30; the scheduler runs `deemed_approval.py` *at container boot*, so any first `docker compose up` after ~2026-10-15 deems all of them approved. Post-boot: **`PENDING = 0`** of 100,001 rows.
2. **The one-active-application rule is not race-safe.** Three concurrent `/declaration` POSTs for one mobile committed **two PENDING applications** (ids 100015 + 100016, mobile 9000000012). Two assistants — or one that retries — will breach the rule.
3. **Anyone can read anyone's OTP.** `/__gateway/api/messages?to=<mobile>` is unauthenticated on the public port, so any 10-digit number can be signed in as that citizen. I minted a real `citizen:9000000001` token for a mobile that has no application at all.
4. **OAuth consent is not bound to a browser session.** A second HTTP client with *no cookies* POSTed `/oauth/consent?rid=…` and got a code that exchanged for a full **officer** token. No CSRF token exists on any form in the portal.
5. **16,576 live rows (16.6%) fail the portal's own IFSC regex** (`UTBI0PUR2819` is 12 chars; the validator demands 11). **100,000 of 100,001 rows have an empty `doc_path`** though age proof is mandatory. 2,585 approvals were under 60 at submission; 593 are still under 60 today.
6. **Timestamps lie by 5h30m.** Validation and the deadline use `now_ist()`; every stored `submitted_at` / `decided_at` / audit `at` uses `datetime.now()` = UTC. A 10:05 IST submission displays as `04:35`.
7. **9,000 of 9,700 deemed approvals were granted before 15 days elapsed** (14d 08:01 – 14d 17:00) — the seed is one cron-day early relative to what the job would actually do.
8. **No officer identity, no jurisdiction.** One `admin` account from `$ADMIN_PASSWORD`; `sub` is always `officer:admin`; every officer sees all six blocks; there is **no district column anywhere**.
9. **No API surface to build on.** `verify_token()` (`oauth.py:124`) is never called; no route accepts a Bearer token; there is no RFC 9728 protected-resource metadata and no mention of MCP in app code. Program tokens are 365-day officer JWTs that **cannot be revoked**.
10. **Nothing tells a citizen their decision.** Approve/reject send no SMS (verified: 9 messages before, 9 after). The acknowledgment PDF prints `?` instead of the name for the 300 Assamese-script applicants.

---

## 0. DIRECTOR'S NOTE

`DIRECTOR-NOTE.mp3` exists (3,115,049 bytes, 194.5 s of speech).

Transcribed locally with **faster-whisper, `small` model, int8 on CPU**, language forced to `en`.
The first attempt failed on an environment problem, not on the audio: the installed PyAV rejects
the `metadata_errors` keyword that `faster_whisper.audio.decode_audio` passes
(`TypeError: open() got an unexpected keyword argument 'metadata_errors'`). I decoded the MP3 to
16 kHz mono with PyAV directly and handed the array to the model. There is no `ffmpeg` on this
machine.

Full transcript with the model's timings. Three clear ASR slips are flagged inline; the rest is
verbatim.

> [0:00] Welcome. You are the new Bharat Digital Fellow assigned to my department.
> [0:04] Sit. Have some tea. Let me tell you why you are here.
> [0:07] The old age pension is Rs. 250 a month for any resident of Gurbanchal *[= Purvanchal]* aged 60 or above.
> [0:14] For a lot of people, it is a lifeline. Seva Setu *[= Sewa Setu]* is its portal. A citizen verifies her
> [0:19] mobile with an OTP, fills in her details and bank account, uploads an age proof
> [0:24] and gets an application number. The block officer sees the queue and approves or rejects.
> [0:29] If nobody decides within 15 days, the law approves it automatically through the system.
> [0:34] My team has given you the code and data. Last month in Sonari block, a woman of 70 came to
> [0:40] the counter with her grandson. On the bus, he had asked an AI assistant on his phone,
> [0:44] chat GPT or Claude to apply for her pension. It could not. It even gave outdated information
> [0:50] on the scheme. It had no way to talk to our portal and make an application in a way that
> [0:55] works for AI agents. And here is the thing, they were okay to use the AI agent but found
> [1:00] our website not so easy. I have heard the story with small variations from four blocks,
> [1:06] grandsons, daughters, CSC operators themselves. If these assistants can book flights and manage
> [1:12] calendars, why can they not help a widow apply for what the law already gives her?
> [1:16] Fellows from your last cohort built an MCP servers or *[probably "an MCP server so"]* AI assistants could use
> [1:21] Ministry of Statistics official data. Do the same but not for reading data, for applying for
> [1:26] something and getting an answer. So this is the job. Make it possible for any AI assistant
> [1:31] to help a citizen apply for the pension and follow it up. Build on open standards. The
> [1:36] assistant talks to the portal through an official channel for agents. The portal remains
> [1:41] the system of record. My IT team says AI will hallucinate, raise privacy concerns,
> [1:47] skip validations. There must be a way to do this reasonably well. Let's make the agent only
> [1:52] work for a subset of blocks of the portal. By properly, I mean this. An AI assistant is just
> [1:58] another way to apply following the same rules and validations as the portal or that such a form
> [2:04] naturally should have. The assistant must never get anyone a pension, the counter or paper form
> [2:09] would not. An application made from either place must be visible in both. Our applicants are
> [2:14] old. They share phones. They sit at kiosks. The assistant must work for them, not for an engineer
> [2:20] in a demo. Some of the worry inside my office may ease if the approving officers get an AI
> [2:25] assistant too. How can it make their life easier and help them do the job well? She should see
> [2:30] what is waiting for her, look at a case and approve or reject it for the reason recorded
> [2:35] against her name. That is a different design. I will test it by pointing my own AI assistant
> [2:41] at what you build and trying to get an application made for an old woman, plus other scenarios
> [2:46] I invent. Then I will connect my officer's assistant and try to approve it. Afterwards,
> [2:51] I will look at my own portal to see what is actually there. Before you build,
> [2:55] sit at a counter for an hour in your head. Inven *[Invent]* these people in detail, test with them
> [3:00] and set up evals. Come and see me when it is up. Send me a loom video, no more than three
> [3:05] minutes, showing what you achieved. The design decisions across the two MCPs, your personas
> [3:11] and evals and what you learnt from them. All the best.

### Things the note asks for that the code cannot currently support

- **"approve or reject it for the reason recorded against her name"** — there is exactly one
  officer identity (`admin`), and `admin_reject` accepts an **empty** reason (§5-C, §9-B4).
- **"make the agent only work for a subset of blocks of the portal"** (1:52) — ambiguous and
  not implementable as stated: no per-officer block assignment exists in the schema or code.
  See §10-Q1.
- **"It even gave outdated information on the scheme"** — scheme facts live in
  `app/config/app.ini` and `templates/index.html` / `about.html`. Nothing serves Rs. 250 /
  age 60 / 15-day SLA / the deadline as machine-readable data.
- **"An application made from either place must be visible in both"** — free if a server writes
  through `create_application()`; see §7 for the import hazards that make that non-trivial.

---

## 1. REPO MAP

```
.
├── .env                      ADMIN_PASSWORD=12345. NOT in git (.gitignore:2); created locally.
│                             docker compose auto-loads it, so a bare `docker compose up`
│                             yields admin password 12345. A shell-level ADMIN_PASSWORD wins.
├── .gitignore                54 lines; standard Python/IDE + .env, uploads/, applogs/
├── BRIEF.md                  Submission logistics (what to build, how it will be tested)
├── DIRECTOR-NOTE.mp3         3,115,049 B / 194.5 s — the actual task statement (§0)
├── README.md                 Operator docs: running, deploying, rules, OAuth overview
├── docker-compose.yml        4 services, 3 named volumes
├── plan.md                   235 lines. NOT part of the handout — an implementation plan
│                             written by this repo's owner, committed in the same single
│                             "first commit" (019eb6f). Out of scope for this audit.
├── app/
│   ├── Dockerfile            python:3.11-slim; apt cron; pip -r requirements.txt;
│   │                         mkdir /var/sewasetu/uploads /var/log/sewasetu; installs
│   │                         deploy/crontab; EXPOSE 8000; CMD gunicorn --workers 4
│   │                         --timeout 30 app:app
│   ├── requirements.txt      Flask 2.2.5, psycopg2-binary 2.9.9, requests 2.28.2,
│   │                         fpdf2 2.7.4, gunicorn 20.1.0, PyJWT[crypto] 2.9.0
│   ├── app.py                678 lines. The portal: helpers, the scheme-rule block
│   │                         (validate/create), citizen wizard, status portal, admin,
│   │                         ack PDF. Registers the oauth blueprint at line 673-674.
│   ├── oauth.py              622 lines. OAuth 2.1 AS as a Flask Blueprint: keys, discovery,
│   │                         DCR + CIMD, authorize/login/consent, token, revoke,
│   │                         /status/connections, /admin/tokens.
│   ├── schema.sql            111 lines of DDL. Mounted as 01-schema.sql (runs first).
│   ├── config/app.ini        20 lines. DB creds, secret_key, sms url, otp ttl, upload dir,
│   │                         min_age=60, sla_days=15, scheme_deadline=2026-10-31 23:59
│   ├── deploy/crontab        3 lines. `0 2 * * * python /app/scripts/deemed_approval.py
│   │                         >> /var/log/sewasetu/cron.log 2>&1`  (02:00 UTC = 07:30 IST)
│   ├── scripts/
│   │   └── deemed_approval.py  71 lines. The RTPS 15-day sweep (§3-E).
│   └── templates/            25 Jinja templates, all extending base.html
│       ├── base.html             layout + all CSS; renders get_flashed_messages()
│       ├── index.html            landing; "Rs. 250", "60 years and above", hours_left
│       ├── about.html            scheme facts: eligibility, 15-day SLA, deemed approval,
│       │                         accepted age-proof documents
│       ├── apply.html            step 1/6: mobile + arithmetic captcha
│       ├── verify.html           step 1/6: OTP entry
│       ├── form_step1.html       step 2/6: name, dob, gender, marital_status, husband_name
│       ├── form_step2.html       step 3/6: village, block (<select> from BLOCKS)
│       ├── form_step3.html       step 4/6: bank_account, ifsc
│       ├── upload.html           step 5/6: file input name="document"
│       ├── declaration.html      step 6/6: preview + error list + declaration checkbox
│       ├── confirmation.html     application number + ack PDF link
│       ├── status_login.html     mobile + password
│       ├── application.html      citizen's own application; withdraw form if PENDING
│       ├── connections.html      active OAuth sign-ins, "End now" / "End all"
│       ├── reset.html            password reset by mobile
│       ├── admin_login.html      username + password
│       ├── admin_dashboard.html  by-status counts, overdue count, pending-by-block
│       ├── admin_list.html       50-row table, mobile search, prev/next
│       ├── admin_view.html       one application + approve/reject forms + audit trail
│       ├── admin_tokens.html     issue program token; list tokens / grants / clients
│       ├── oauth_login.html      citizen OTP form OR officer password form
│       ├── oauth_consent.html    the consent screen (§6-D)
│       └── oauth_error.html      error title + detail
├── seed/
│   └── seed.sql              35,866,764 B / 399,314 lines. Three COPY blocks:
│                             applications (100,000 rows, ids 1–100000),
│                             portal_users (100,000), audit_log (199,300);
│                             then setval('applications_id_seq', 100010) and
│                             setval('audit_log_id_seq', max(id)).
│                             Header: "pg_dump 15.4, sewasetu@dbprod01, 2026-09-30".
└── smsgw/
    ├── Dockerfile            python:3.11-slim; pip Flask 2.2.5; CMD python app.py
    └── app.py                94 lines. In-memory list MESSAGES, 1–4 s fake carrier
                              latency, HTML console at /, JSON /api/send + /api/messages
```

### docker-compose services

| service | image / build | host port | container port | depends_on | volumes |
|---|---|---|---|---|---|
| `db` | `postgres:15` | *none* | 5432 (compose net only) | — | `pgdata:/var/lib/postgresql/data`; bind `./app/schema.sql` → `/docker-entrypoint-initdb.d/01-schema.sql`; bind `./seed/seed.sql` → `…/02-seed.sql` |
| `app` | `build: ./app` | **8000** | 8000 | `db`, `smsgw` | `uploads:/var/sewasetu/uploads`, `applogs:/var/log/sewasetu` |
| `scheduler` | `build: ./app` (same image) | *none* | 8000 exposed, unused | `db` **only** | `applogs:/var/log/sewasetu` |
| `smsgw` | `build: ./smsgw` | *none* | `expose: 8025` | — | — |

Env vars (`docker-compose.yml:14-20`):

- `app`: `ADMIN_USERNAME` (default `admin`), `ADMIN_PASSWORD` (default
  `change-me-before-deploying`), `PUBLIC_BASE_URL` (default `http://localhost:8000`).
- `db`: `POSTGRES_DB=sewasetu`, `POSTGRES_USER=sewasetu`, `POSTGRES_PASSWORD=sewasetu123`.
- `scheduler` and `smsgw`: **no env vars at all**. The scheduler never sees `PUBLIC_BASE_URL`
  and does not need it (it reads `app.ini` directly).

Named volumes: `pgdata`, `uploads`, `applogs`. Note `uploads` is mounted **only on `app`** —
the scheduler cannot read age-proof files, and nothing outside that container can either.

### Scheduler / cron setup

`docker-compose.yml:34-37`:

```yaml
command: ["sh", "-c", "until python /app/scripts/deemed_approval.py; do sleep 5; done; exec cron -f"]
```

Verified live: PID 1 in the scheduler container is `cron -f`; `crontab -l` returns
`deploy/crontab` verbatim. So:

- The job runs **once immediately at container start**, retried every 5 s until it exits 0
  (i.e. until Postgres accepts connections). My boot logged
  `2026-10-21 04:26:24 deemed approval: 0 applications approved` — 0 only because a previous
  run on 2026-10-20 had already swept the queue (§2-F).
- Then cron takes over at **02:00 container-local time, which is UTC** (`date -u` inside the
  container returns UTC; there is no `/etc/timezone`). 02:00 UTC = **07:30 IST**, not the
  02:00 IST the docstring claims (`scripts/deemed_approval.py:9`).
- `app`'s image has the same crontab baked in, but its CMD is gunicorn, so cron is not running
  there (verified: only a gunicorn master + 4 workers in `/proc`). No double-run.
- The scheduler does **not** `depends_on: smsgw`, so on a cold `up` the boot run can fire its
  SMS before the gateway is listening; the failure is swallowed
  (`scripts/deemed_approval.py:62-63`).

---

## 2. DATA MODEL

Source of truth: `app/schema.sql` (111 lines). There are **no migrations** — one DDL file,
every statement `CREATE TABLE IF NOT EXISTS`. Verified against `information_schema.columns`
and `pg_constraint` on the running database; the live schema matches the file exactly.

### A. Tables, columns, types

**`applications`** — `schema.sql:5-24`

| # | column | type | nullable | default | notes |
|---|---|---|---|---|---|
| 1 | `id` | `serial` → `integer` | NO | `nextval('applications_id_seq')` | PK |
| 2 | `application_no` | `varchar(20)` | YES | — | **no UNIQUE constraint** (§9-B1) |
| 3 | `applicant_name` | `varchar(100)` | YES | — | truncated to 100 chars by `sanitize()` |
| 4 | `mobile` | `varchar(15)` | YES | — | always 10 digits in practice |
| 5 | `dob` | `date` | YES | — | |
| 6 | `gender` | `varchar(10)` | YES | — | **never validated** (§3-B) |
| 7 | `marital_status` | `varchar(20)` | YES | — | **never validated** |
| 8 | `husband_name` | `varchar(100)` | YES | — | **never length-capped** (§9-B5) |
| 9 | `husband_employer` | `varchar(100)` | YES | — | dead column; code always writes `''` (`app.py:148`) |
| 10 | `village` | `varchar(100)` | YES | — | **never length-capped or value-checked** |
| 11 | `block` | `varchar(50)` | YES | — | checked against `BLOCKS` |
| 12 | `bank_account` | `varchar(30)` | YES | — | regex-capped at 18 digits |
| 13 | `ifsc` | `varchar(15)` | YES | — | regex-capped at 11 chars |
| 14 | `doc_path` | `varchar(200)` | YES | — | server-side absolute path; **no download route exists** |
| 15 | `status` | `varchar(20)` | YES | `'PENDING'` | free text; no enum, no CHECK |
| 16 | `submitted_at` | `timestamp without time zone` | YES | — | written with `datetime.now()` = **UTC** |
| 17 | `decided_at` | `timestamp without time zone` | YES | — | likewise UTC |
| 18 | `decided_by` | `varchar(50)` | YES | — | `admin` \| `APPLICANT` \| `RTPS-AUTO` |

**`portal_users`** — `schema.sql:27-30`. `mobile varchar(15) PRIMARY KEY`,
`password_hash varchar(80)`. The hash is an **unsalted SHA-256 of the DOB as `DDMMYYYY`** —
verified by recomputing five rows by hand, all MATCH.

**`otps`** — `schema.sql:32-37`. `id serial PK`, `mobile varchar(15)`, `code varchar(6)`,
`created_at timestamp`. **Plaintext codes, never deleted, no index on `mobile`.**

**`audit_log`** — `schema.sql:43-50`. `id serial PK`, `application_id integer` (**no FK**),
`action varchar(20)`, `actor varchar(50)`, `note varchar(500)`, `at timestamp`.

**OAuth tables** — `schema.sql:55-111`:

- `oauth_keys(kid varchar(32) PK, private_pem text, created_at timestamp)` — the RSA private
  key is stored **unencrypted** in the database.
- `oauth_clients(id serial PK, client_id varchar(300) UNIQUE, client_name varchar(100), redirect_uris jsonb, secret_hash varchar(64), kind varchar(10) /* dcr | cimd */, created_at, fetched_at)`
- `oauth_requests(id varchar(64) PK, params jsonb, subject varchar(80), role varchar(10), pending_mobile varchar(15), created_at)` — an authorization in flight.
- `oauth_codes(code_hash varchar(64) PK, client_id, redirect_uri varchar(500), scope varchar(20), code_challenge varchar(128), resource varchar(300), subject varchar(80), role varchar(10), created_at)`
- `oauth_refresh_tokens(token_hash varchar(64) PK, client_id, client_name, subject, role, scope, resource, created_at, expires_at, revoked_at)` — one row per sign-in; `expires_at` **is** the session's absolute end.
- `oauth_program_tokens(id serial PK, jti varchar(32) UNIQUE, label varchar(100), subject varchar(80), audience varchar(300), issued_by varchar(50), created_at, expires_at, revoked_at)` — `revoked_at` is **never written by any code path** (§5-E).

### B. Constraints and indexes actually present

```sql
SELECT conrelid::regclass AS tbl, conname, pg_get_constraintdef(oid)
FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY 1,2;
```

| table | constraint |
|---|---|
| `applications` | `PRIMARY KEY (id)` — **and nothing else** |
| `portal_users` | `PRIMARY KEY (mobile)` |
| `otps` | `PRIMARY KEY (id)` |
| `audit_log` | `PRIMARY KEY (id)` |
| `oauth_keys` | `PRIMARY KEY (kid)` |
| `oauth_clients` | `PRIMARY KEY (id)`, `UNIQUE (client_id)` |
| `oauth_requests` | `PRIMARY KEY (id)` |
| `oauth_codes` | `PRIMARY KEY (code_hash)` |
| `oauth_refresh_tokens` | `PRIMARY KEY (token_hash)` |
| `oauth_program_tokens` | `PRIMARY KEY (id)`, `UNIQUE (jti)` |

**No foreign keys, no CHECK constraints, no NOT NULL beyond the primary keys, and no unique
index on `applications.application_no` or on `(mobile, status)`.** Every business rule is
enforced in Python only. `portal_users_pkey` is the one constraint that accidentally
serialises concurrent submissions — §9-A2 explains why that protection is partial.

Indexes (`schema.sql:39-40, 51-52`):

```
applications : applications_pkey (id)
               idx_app_mobile (mobile)
               idx_app_status (status)
               idx_app_status_submitted (status, submitted_at)
audit_log    : audit_log_pkey (id)
               idx_audit_app (application_id)
```

`idx_app_status_submitted (status, submitted_at)` serves both the officer queue
(`WHERE status = ? ORDER BY submitted_at ASC`) and the deemed-approval sweep exactly. `otps`
has **no index on `mobile`**, so every OTP check is a sequential scan — fine at 13 rows,
a problem at scale.

### C. Every status value, and every transition

Status values are string literals in code; there is no enum. The complete set:

`PENDING`, `APPROVED`, `DEEMED_APPROVED`, `REJECTED`, `WITHDRAWN`.

`ACTIVE_STATUSES = ("PENDING", "APPROVED", "DEEMED_APPROVED")` (`app.py:47`) — the three that
block a fresh application. `WITHDRAWN` and `REJECTED` do not.

| from | to | trigger | code | `decided_by` | audit `action` | audit `actor` | note |
|---|---|---|---|---|---|---|---|
| — | `PENDING` | citizen submits the wizard | `create_application` `app.py:188-214`; literal `'PENDING'` in the INSERT at `app.py:197` | `NULL` | `SUBMIT` | `applicant:<mobile>` | `''` |
| `PENDING` | `APPROVED` | officer clicks Approve | `/admin/approve/<id>` `app.py:663-665` → `_admin_decide` `app.py:642-661` | `admin` | `APPROVED` | `admin:admin` | free text, optional |
| `PENDING` | `REJECTED` | officer clicks Reject | `/admin/reject/<id>` `app.py:668-670` → same helper | `admin` | `REJECTED` | `admin:admin` | free text, **optional** |
| `PENDING` | `WITHDRAWN` | citizen withdraws | `/application/<id>/withdraw` `app.py:489-511` | `APPLICANT` | **`WITHDRAW`** | `applicant:<mobile>` | `''` |
| `PENDING` | `DEEMED_APPROVED` | nightly RTPS sweep | `scripts/deemed_approval.py:41-54` | `RTPS-AUTO` | `DEEMED_APPROVED` | `system:rtps-cron` | `not processed within SLA` |

**All four terminal states are final.** Every UPDATE carries `AND status = 'PENDING'`
(`app.py:501`, `app.py:647`, `deemed_approval.py:44`), so there is no un-withdraw, no
un-reject, no re-open and no admin override. Verified live: approving an already-APPROVED
application returns the flash `Only a pending application can be decided.`

Two naming inconsistencies between the seed and the code, both confirmed by query (Q47):

- Withdrawal writes action **`WITHDRAW`** in code (`app.py:504`) but the seed's 400 historical
  withdrawals carry action **`WITHDRAWN`**.
- Withdrawal writes actor **`applicant:<mobile>`** in code but the seed uses
  **`admin:APPLICANT`**.

An officer-side "audit trail" tool must match on both spellings or it will show gaps.

### D. How the queries were run

```
ADMIN_PASSWORD=audit123 docker compose up -d --build
docker compose exec -T db psql -U sewasetu -d sewasetu -f /dev/stdin < queries.sql
```

Every statement is a `SELECT` (plus `\echo` / `\pset`). Postgres 15.19,
`current_setting('TIMEZONE') = Etc/UTC`, `now()` at audit start = `2026-10-21 04:27:02+00`.

### E. One caveat on the numbers

The `pgdata` volume was **18 hours old when I started** — this database had already been
booted by the repo owner on 2026-10-20 and lightly used. Two measured consequences:

1. The boot-time deemed-approval job had **already run at 2026-10-20 10:10:47** and swept the
   seed's 700 PENDING rows. My own boot therefore reported `0 applications approved`.
2. One extra application pre-existed (id 100011, mobile 9887656430, REJECTED), plus one
   program token and 2 stale OTP rows from that session.

Where it matters I give **both** the raw-seed figure (computed from `seed/seed.sql` with awk,
so it is the true pristine state) and the live figure. My own probes added 4 more rows;
§2-H is a full inventory of what this audit created.

### F. Query results

#### Q1 — row counts per table

```sql
SELECT 'applications' t, count(*) FROM applications
UNION ALL SELECT 'portal_users', count(*) FROM portal_users
UNION ALL SELECT 'otps', count(*) FROM otps
UNION ALL SELECT 'audit_log', count(*) FROM audit_log
UNION ALL SELECT 'oauth_keys', count(*) FROM oauth_keys
UNION ALL SELECT 'oauth_clients', count(*) FROM oauth_clients
UNION ALL SELECT 'oauth_requests', count(*) FROM oauth_requests
UNION ALL SELECT 'oauth_codes', count(*) FROM oauth_codes
UNION ALL SELECT 'oauth_refresh_tokens', count(*) FROM oauth_refresh_tokens
UNION ALL SELECT 'oauth_program_tokens', count(*) FROM oauth_program_tokens
ORDER BY 1;
```

| table | rows at audit start | in pristine `seed.sql` |
|---|---|---|
| `applications` | 100,001 | 100,000 |
| `audit_log` | 200,002 | 199,300 |
| `portal_users` | 100,001 | 100,000 |
| `otps` | 2 | 0 |
| `oauth_keys` | 1 | 0 (generated on first use) |
| `oauth_program_tokens` | 1 | 0 |
| `oauth_clients` | 0 | 0 |
| `oauth_codes` | 0 | 0 |
| `oauth_refresh_tokens` | 0 | 0 |
| `oauth_requests` | 0 | 0 |

#### Q2 — applications by status

```sql
SELECT status, count(*), round(100.0*count(*)/sum(count(*)) OVER (),2) pct
FROM applications GROUP BY status ORDER BY 2 DESC;
```

| status | live at audit start | pct | **pristine `seed.sql`** |
|---|---|---|---|
| `APPROVED` | 82,900 | 82.90 | 82,900 |
| `DEEMED_APPROVED` | 9,700 | 9.70 | **9,000** |
| `REJECTED` | 7,001 | 7.00 | 7,000 |
| `WITHDRAWN` | 400 | 0.40 | 400 |
| **`PENDING`** | **0** | **0.00** | **700** |

The pristine figures come from the seed file itself:

```bash
awk 'NR>4 && /^\\\.$/{exit} {print}' seed/seed.sql | awk -F'\t' '{print $15}' | sort | uniq -c | sort -rn
#  82900 APPROVED / 9000 DEEMED_APPROVED / 7000 REJECTED / 700 PENDING / 400 WITHDRAWN
```

**This is the single most important finding in the dataset.** The 700 PENDING rows are gone,
converted to `DEEMED_APPROVED` by the boot-time sweep. See §3-E and §9-A1.

#### Q3 — by block × status (there is no district)

```sql
SELECT block, count(*) total,
  count(*) FILTER (WHERE status='PENDING')         pending,
  count(*) FILTER (WHERE status='APPROVED')        approved,
  count(*) FILTER (WHERE status='DEEMED_APPROVED') deemed,
  count(*) FILTER (WHERE status='REJECTED')        rejected,
  count(*) FILTER (WHERE status='WITHDRAWN')       withdrawn
FROM applications GROUP BY block ORDER BY 2 DESC;
```

| block | total | pending | approved | deemed | rejected | withdrawn |
|---|---|---|---|---|---|---|
| Khelua | 16,761 | 0 | 13,937 | 1,621 | 1,138 | 65 |
| Rajapara | 16,751 | 0 | 13,846 | 1,664 | 1,165 | 76 |
| Borgaon | 16,715 | 0 | 13,903 | 1,581 | 1,156 | 75 |
| Dhemaji Pathar | 16,656 | 0 | 13,800 | 1,616 | 1,181 | 59 |
| Sonari | 16,596 | 0 | 13,761 | 1,585 | 1,187 | 63 |
| Namti | 16,522 | 0 | 13,653 | 1,633 | 1,174 | 62 |

**There is no `district` column anywhere in the schema** — confirmed against
`information_schema.columns` (75 columns across 10 tables, none named `district`). The only
geography is `block` (6 values) and `village` (19 values). "By district" cannot be answered;
block is the finest and only administrative grain available.

#### Q4 — the pre-boot PENDING queue, reconstructed from the audit log

The 700 swept rows are identifiable because the job stamps a distinctive audit row:

```sql
SELECT count(*) AS swept_at_boot, min(at), max(at)
FROM audit_log WHERE actor='system:rtps-cron' AND at >= date '2026-10-20';
-- 700 | 2026-10-20 10:10:47.086678 | 2026-10-20 10:10:47.227862
```

```sql
SELECT a.block, count(*), min(a.submitted_at) oldest, max(a.submitted_at) newest,
       min(a.decided_at - a.submitted_at) min_elapsed, max(a.decided_at - a.submitted_at) max_elapsed
FROM applications a JOIN audit_log l ON l.application_id = a.id
WHERE l.actor='system:rtps-cron' AND l.at >= date '2026-10-20'
GROUP BY 1 ORDER BY 2 DESC;
```

| block | count | oldest submitted | newest submitted | min elapsed | max elapsed |
|---|---|---|---|---|---|
| Sonari | 125 | 2026-09-16 09:44 | 2026-09-30 17:26 | 19d 16:44 | 34d 00:26 |
| Dhemaji Pathar | 124 | 2026-09-16 10:55 | 2026-09-30 16:43 | 19d 17:27 | 33d 23:15 |
| Khelua | 123 | 2026-09-16 09:52 | 2026-09-30 16:26 | 19d 17:44 | 34d 00:18 |
| Rajapara | 123 | 2026-09-16 12:07 | 2026-09-30 17:38 | 19d 16:32 | 33d 22:03 |
| Namti | 111 | 2026-09-16 09:02 | 2026-09-30 17:57 | 19d 16:13 | 34d 01:08 |
| Borgaon | 94 | 2026-09-16 10:04 | 2026-09-30 17:15 | 19d 16:55 | 34d 01:08 |

The whole pending queue sat in a 15-day window ending exactly on the snapshot date
(2026-09-30). The data was built for "today ≈ 2026-09-30"; it is now 21 days stale.

#### Q5 — age at submission: min / max / median

```sql
SELECT min(age_yrs) min_age, max(age_yrs) max_age, round(avg(age_yrs),2) avg_age,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY age_yrs) median_age,
       percentile_cont(0.25) WITHIN GROUP (ORDER BY age_yrs) p25,
       percentile_cont(0.75) WITHIN GROUP (ORDER BY age_yrs) p75,
       count(*) n, count(*) FILTER (WHERE age_yrs IS NULL) null_age
FROM (SELECT (date_part('year', age(submitted_at::date, dob)))::int AS age_yrs FROM applications) s;
```

| min | max | avg | **median** | p25 | p75 | n | null |
|---|---|---|---|---|---|---|---|
| **58** | **88** | 73.05 | **73** | 66 | 80 | 100,001 | 0 |

The distribution is identical across all statuses (min 58, max 88, median 73 for each of
APPROVED / DEEMED_APPROVED / REJECTED / WITHDRAWN) — there is no age signal in the decisions.

DOB range: `1938-01-01` … `1966-12-28`. **The latest DOB is 59 years old today**, so the seed
contains people who are still under the minimum age.

#### Q6 — applicants under 60: the eligibility violations

```sql
-- under 60 AT SUBMISSION, by status
SELECT status, count(*) FROM (
  SELECT status, (date_part('year', age(submitted_at::date, dob)))::int a FROM applications
) s WHERE a < 60 GROUP BY status ORDER BY 2 DESC;
```

| status | under 60 at submission |
|---|---|
| `APPROVED` | **2,585** |
| `DEEMED_APPROVED` | **273** |
| `REJECTED` | 215 |
| `WITHDRAWN` | 10 |

```sql
-- still under 60 TODAY and not rejected/withdrawn
SELECT status, count(*) FROM applications
WHERE (date_part('year', age(date '2026-10-21', dob)))::int < 60
  AND status NOT IN ('REJECTED','WITHDRAWN')
GROUP BY status ORDER BY 2 DESC;
```

| status | still under 60 today |
|---|---|
| `APPROVED` | **529** |
| `DEEMED_APPROVED` | **64** |

**2,858 applications that the portal's own `validate_application()` would refuse today are
sitting in a pension-granting state**, and 593 of those beneficiaries have not yet reached 60.
`_admin_decide` and the deemed-approval job both re-check nothing (§3-F).

Sample of the youngest:

```sql
SELECT id, application_no, applicant_name, mobile, dob,
       (date_part('year', age(submitted_at::date, dob)))::int age_at_submit,
       block, status, submitted_at, decided_by
FROM applications WHERE status IN ('APPROVED','DEEMED_APPROVED') ORDER BY dob DESC LIMIT 5;
```

```
 90815 | SSP25078367 | Jatin Phukan   | 9487720038 | 1966-12-28 | 58 | Rajapara | DEEMED_APPROVED | 2025-07-16 17:11 | RTPS-AUTO
 60597 | SSP26999798 | Abdul Gogoi    | 9450194678 | 1966-12-28 | 59 | Rajapara | APPROVED        | 2026-07-22 12:44 | admin
 89120 | SSP25929174 | Haren Talukdar | 8776031231 | 1966-12-28 | 58 | Rajapara | DEEMED_APPROVED | 2025-07-07 17:28 | RTPS-AUTO
 99036 | SSP25256408 | প্ৰণৱ কুমাৰ দাস | 6625182968 | 1966-12-28 | 58 | Rajapara | APPROVED        | 2025-07-01 09:27 | admin
 55192 | SSP25527987 | Anima Kalita   | 9751028108 | 1966-12-28 | 58 | Khelua   | APPROVED        | 2025-09-30 15:54 | admin
```

#### Q7 — pending past the 15-day SLA

```sql
SELECT count(*) AS pending_total,
       count(*) FILTER (WHERE submitted_at < now()::timestamp - interval '15 days') AS pending_overdue
FROM applications WHERE status='PENDING';
-- 0 | 0
```

Zero, because the queue is empty. **In the pristine seed all 700 PENDING rows were overdue**:
they were submitted 2026-09-16 … 2026-09-30, and 15 days before today (2026-10-21) is
2026-10-06, so every one of them is past the SLA. The portal's own dashboard counter
(`app.py:585-588`, `WHERE status='PENDING' AND submitted_at < now() - 15 days`) would read
**700** on a database that had not been swept, and reads **0** now.

#### Q8 — duplicate mobiles with more than one active application

```sql
SELECT count(*) AS mobiles_with_multiple_active, coalesce(sum(n),0) AS rows_involved FROM (
  SELECT mobile, count(*) n FROM applications
  WHERE status IN ('PENDING','APPROVED','DEEMED_APPROVED')
  GROUP BY mobile HAVING count(*) > 1) s;
-- 0 | 0
```

```sql
SELECT n AS apps_per_mobile, count(*) AS mobiles FROM (
  SELECT mobile, count(*) n FROM applications GROUP BY mobile) s GROUP BY n ORDER BY n;
-- 1 | 100001
```

**The seed is perfectly clean: exactly one application per mobile, no duplicates of any kind.**
The one-active-application rule is therefore not *violated* in the shipped data — but it is not
*enforced* by the database either, and I broke it on purpose in under a second (§9-A2). After
my race test the same query returns `9000000012 | 2`.

#### Q9 — applications with no age-proof document

```sql
SELECT count(*) AS no_doc_total,
       count(*) FILTER (WHERE doc_path IS NULL) AS doc_null,
       count(*) FILTER (WHERE doc_path = '')    AS doc_empty
FROM applications WHERE doc_path IS NULL OR btrim(doc_path) = '';
-- 100000 | 0 | 100000

SELECT status, count(*) FROM applications
WHERE doc_path IS NULL OR btrim(doc_path)='' GROUP BY status ORDER BY 2 DESC;
```

| status | rows with empty `doc_path` |
|---|---|
| `APPROVED` | 82,900 |
| `DEEMED_APPROVED` | 9,700 |
| `REJECTED` | 7,000 |
| `WITHDRAWN` | 400 |

```sql
SELECT count(*) AS with_doc, min(length(doc_path)), max(length(doc_path))
FROM applications WHERE coalesce(btrim(doc_path),'') <> '';
-- 1 | 81 | 81
```

**Every single one of the 100,000 seeded applications has an empty `doc_path`** — the only row
with a document is the one the repo owner created through the real form. Yet
`validate_application` hard-fails with `age proof document is required` when `doc_path` is
empty (`app.py:170-171`). So 100% of the production corpus would be rejected by the portal's
own current validator, and an officer tool that surfaces "has the age proof been uploaded?"
will answer "no" for the entire historical dataset. There is also **no route that serves a
`doc_path` file**, so even the one real document cannot be viewed by an officer (§5-B).

#### Q10 — bad IFSC: 16.6% of live rows fail the portal's own regex

The validator demands `^[A-Z]{4}0[A-Z0-9]{6}$`, i.e. exactly 11 characters (`app.py:163-164`).

```sql
SELECT count(*) AS bad_ifsc FROM applications
WHERE coalesce(ifsc,'') <> '' AND ifsc !~ '^[A-Z]{4}0[A-Z0-9]{6}$';
-- 16576

SELECT ifsc, count(*), (ifsc ~ '^[A-Z]{4}0[A-Z0-9]{6}$') AS passes_app_regex, length(ifsc) len
FROM applications GROUP BY ifsc, length(ifsc) ORDER BY 2 DESC;
```

| ifsc | count | passes app regex | length |
|---|---|---|---|
| `UCBA0001522` | 16,836 | t | 11 |
| `PUNB0556610` | 16,728 | t | 11 |
| `SBIN0003077` | 16,708 | t | 11 |
| `CNRB0004417` | 16,579 | t | 11 |
| **`UTBI0PUR2819`** | **16,576** | **f** | **12** |
| `IDIB000S118` | 16,574 | t | 11 |

Only six distinct IFSC codes exist, evenly distributed, and **one of them is 12 characters
long and fails validation** — 13,732 of those 16,576 rows are already APPROVED. Confirmed
in-process: `validate_application(..., ifsc='UTBI0PUR2819')` returns
`['IFSC must be 11 characters, e.g. SBIN0003077']`. This looks deliberately planted: a citizen
re-applying who reads their own IFSC off an existing approved application will be refused.

#### Q11 — bank accounts, mobiles, NULLs: all clean

```sql
SELECT count(*) AS bad_bank FROM applications
WHERE coalesce(bank_account,'')='' OR bank_account !~ '^[0-9]{9,18}$';
-- 0
SELECT length(bank_account) len, count(*) FROM applications GROUP BY 1 ORDER BY 1;
-- 11 | 915   /   12 | 8931   /   13 | 90155
```

```sql
SELECT count(*) FILTER (WHERE mobile !~ '^[0-9]{10}$') AS not_10_digits,
       count(*) FILTER (WHERE mobile ~ '^[0-9]{10}$'
                          AND left(mobile,1) NOT IN ('6','7','8','9')) AS bad_prefix
FROM applications;
-- 0 | 0
SELECT left(mobile,1) first_digit, count(*) FROM applications GROUP BY 1 ORDER BY 1;
-- 6 | 24833   7 | 25325   8 | 24864   9 | 24979
```

All mobiles are valid 10-digit Indian numbers starting 6–9, evenly spread. No odd mobiles.

```sql
SELECT
  count(*) FILTER (WHERE application_no IS NULL OR application_no='')     AS no_appno,
  count(*) FILTER (WHERE applicant_name IS NULL OR btrim(applicant_name)='') AS no_name,
  count(*) FILTER (WHERE mobile IS NULL OR mobile='')                     AS no_mobile,
  count(*) FILTER (WHERE dob IS NULL)                                      AS no_dob,
  count(*) FILTER (WHERE gender IS NULL OR gender='')                     AS no_gender,
  count(*) FILTER (WHERE marital_status IS NULL OR marital_status='')      AS no_marital,
  count(*) FILTER (WHERE village IS NULL OR btrim(village)='')            AS no_village,
  count(*) FILTER (WHERE block IS NULL OR block='')                       AS no_block,
  count(*) FILTER (WHERE bank_account IS NULL OR bank_account='')         AS no_bank,
  count(*) FILTER (WHERE ifsc IS NULL OR ifsc='')                         AS no_ifsc,
  count(*) FILTER (WHERE submitted_at IS NULL)                            AS no_submitted
FROM applications;
```

**All eleven counts are 0.** Apart from `doc_path`, no field is ever null or blank.

#### Q12 — duplicate application numbers, and the collision risk ahead

```sql
SELECT count(*) AS distinct_app_nos_reused, sum(n) AS rows_affected FROM (
  SELECT application_no, count(*) n FROM applications GROUP BY application_no HAVING count(*)>1) s;
-- 0 | NULL
```

No duplicates today. But the generator is
`"SSP" + datetime.now().strftime("%y") + str(random.randint(100000, 999999))`
(`app.py:108-109`) — a random draw from 900,000 values, with **no UNIQUE constraint and no
retry loop**:

```sql
SELECT left(application_no,5) prefix, count(*), count(DISTINCT application_no) distinct_nos
FROM applications GROUP BY 1 ORDER BY 1;
-- SSP25 | 41439 | 41439
-- SSP26 | 58562 | 58562

SELECT count(*) AS existing_ssp26, round(100.0*count(*)/900000.0, 3) AS pct_collision_per_new_app
FROM applications WHERE application_no LIKE 'SSP26%';
-- 58562 | 6.507
```

**Every new application has a 6.5% chance of being issued an application number that already
belongs to someone else**, and the column has no unique index to stop it. See §9-B1.

#### Q13 — deemed approvals that look wrong

```sql
SELECT CASE WHEN decided_at - submitted_at < interval '15 days' THEN 'a: granted EARLY (<15 days)'
            WHEN decided_at - submitted_at < interval '16 days' THEN 'b: 15-16 days (correct window)'
            ELSE 'c: later than 16 days (job had not run)' END AS bucket,
       count(*), min(decided_at-submitted_at) min_elapsed, max(decided_at-submitted_at) max_elapsed
FROM applications WHERE status='DEEMED_APPROVED' GROUP BY 1 ORDER BY 1;
```

| bucket | count | min elapsed | max elapsed |
|---|---|---|---|
| **a: granted EARLY (< 15 days)** | **9,000** | 14d 08:01 | 14d 17:00 |
| b: 15–16 days (correct window) | 0 | — | — |
| c: later than 16 days | 700 | 19d 16:13 | 34d 01:08 |

```sql
SELECT to_char(decided_at,'HH24:MI') AS decided_at_clock, count(*)
FROM applications WHERE status='DEEMED_APPROVED' GROUP BY 1 ORDER BY 2 DESC LIMIT 6;
-- 02:00 | 9000
-- 10:10 | 700
```

Two distinct problems:

- **All 9,000 seeded deemed approvals were granted before the statutory 15 days had elapsed.**
  They are stamped at exactly `02:00`, as a real cron run would be, but one cron-day too early.
  Worked example (id 86551): submitted `2026-08-19 17:59`, deemed `2026-09-03 02:00` = 14d 08:01.
  The job's cutoff is `now() - 15 days`, so the 02:00 run on 2026-09-03 uses cutoff
  `2026-08-19 02:00`; `17:59 > 02:00`, so that row would **not** have been swept until
  `2026-09-04 02:00` (15d 08:01). Every one of the 9,000 is a day early.
- The 700 rows stamped `10:10` are the ones the boot-time job swept 4–19 days late, because no
  scheduler had been running between the snapshot and the first `docker compose up`. Their
  `decided_at` (2026-10-20) bears no relation to when the SLA actually expired.

So "deemed approved" in this dataset does **not** mean "exactly 15 days elapsed". A tool that
tells a citizen "your application will be auto-approved on *date X*" must compute X itself
rather than infer the rule from history. The arithmetic the job actually performs:

```sql
SELECT id, application_no, submitted_at,
       submitted_at + interval '15 days' AS fifteen_days_after_submit,
       (date_trunc('day', submitted_at + interval '16 days') + interval '2 hours') AS first_cron_utc,
       (date_trunc('day', submitted_at + interval '16 days') + interval '2 hours')
         + interval '5 hours 30 minutes' AS first_cron_in_ist
FROM applications WHERE status='PENDING';
```

```
100015 | SSP26801643 | 2026-10-21 04:37:33 | 2026-11-05 04:37:33 | 2026-11-06 02:00 | 2026-11-06 07:30
```

i.e. **submitted_at + 15 days, then round up to the next 02:00 UTC (07:30 IST)** — between 15
and 16 days, never exactly 15.

#### Q14 — human decisions never breached the SLA

```sql
SELECT status, count(*),
  percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM decided_at-submitted_at)/86400)::numeric(8,2) median_days,
  min(EXTRACT(epoch FROM decided_at-submitted_at)/86400)::numeric(8,2) min_days,
  max(EXTRACT(epoch FROM decided_at-submitted_at)/86400)::numeric(8,2) max_days,
  count(*) FILTER (WHERE decided_at - submitted_at > interval '15 days') AS over_sla
FROM applications WHERE decided_at IS NOT NULL GROUP BY status ORDER BY 2 DESC;
```

| status | count | median days | min | max | over SLA |
|---|---|---|---|---|---|
| `APPROVED` | 82,900 | 8.01 | 1.68 | **14.33** | 0 |
| `DEEMED_APPROVED` | 9,700 | 14.54 | 14.33 | 34.05 | 700 |
| `REJECTED` | 7,001 | 8.00 | 0.23 | **14.31** | 0 |
| `WITHDRAWN` | 400 | 5.11 | **-0.26** | 10.28 | 0 |

No APPROVED or REJECTED row ever exceeded 15 days — the seed is internally consistent on that
point (the sweep would have taken it first). Officer decisions cluster at a median of 8 days.

#### Q15 — other anomalies found

```sql
SELECT count(*) FILTER (WHERE submitted_at > now())  AS submitted_in_future,
       count(*) FILTER (WHERE decided_at  > now())   AS decided_in_future,
       count(*) FILTER (WHERE decided_at IS NOT NULL AND decided_at < submitted_at) AS decided_before_submit,
       count(*) FILTER (WHERE dob > current_date)    AS dob_in_future,
       count(*) FILTER (WHERE dob < date '1900-01-01') AS dob_before_1900,
       min(submitted_at), max(submitted_at), min(dob), max(dob)
FROM applications;
```

| check | result |
|---|---|
| submitted in the future | 0 |
| decided in the future | 0 |
| **decided before submitted** | **14** |
| DOB in the future | 0 |
| DOB before 1900 | 0 |
| submitted_at range | `2025-07-01 09:00` → `2026-10-20 10:15` |
| dob range | `1938-01-01` → `1966-12-28` |

The 14 time-travelling rows are all withdrawals, by up to 6h20m:

```sql
SELECT id, application_no, status, submitted_at, decided_at, decided_by, decided_at-submitted_at delta
FROM applications WHERE decided_at < submitted_at ORDER BY (decided_at-submitted_at) LIMIT 5;
```

```
 98795 | SSP25604075 | WITHDRAWN | 2025-08-13 17:53 | 2025-08-13 11:33 | APPLICANT | -06:20:00
 98886 | SSP25948089 | WITHDRAWN | 2025-12-11 17:33 | 2025-12-11 11:27 | APPLICANT | -06:06:00
 98626 | SSP26789730 | WITHDRAWN | 2026-08-18 17:20 | 2026-08-18 11:18 | APPLICANT | -06:02:00
 98629 | SSP26659540 | WITHDRAWN | 2026-02-26 14:52 | 2026-02-26 12:28 | APPLICANT | -02:24:00
 98913 | SSP26540804 | WITHDRAWN | 2026-03-02 13:11 | 2026-03-02 10:54 | APPLICANT | -02:17:00
```

Anything computing "time to decision" must clamp at zero.

**Village → block is a clean 1:1 map, but it is not validated anywhere:**

```sql
SELECT village, count(DISTINCT block) nblocks FROM applications
GROUP BY 1 HAVING count(DISTINCT block)>1;
-- (0 rows)

SELECT block, count(DISTINCT village) villages, string_agg(DISTINCT village, ', ')
FROM applications GROUP BY 1 ORDER BY 1;
```

| block | villages |
|---|---|
| Borgaon | Borgaon Centre, Milanpur, Udaypur |
| Dhemaji Pathar | Bordoloni, Kathoni, Nalbari Gaon, *purvanchal* |
| Khelua | Chengelimara, Khelua Gaon, Sialmari |
| Namti | Hatipara, Namti Chariali, Panidihing |
| Rajapara | Dighaljan, Rajapara Gaon, Teliagaon |
| Sonari | Bhekulajan, Kakotibari, Lakhipur, Namdang |

19 real villages, 3–4 per block, and no village ever straddles a block. The lower-case
`purvanchal` (1 row) is the repo owner's test row — proof that `village` is accepted as
arbitrary free text (§3-B). **Nothing in the code knows this mapping**, so an assistant can
legally file "Kathoni / Sonari" and nobody will notice.

**Other distributions:**

```sql
SELECT 'gender' col, gender val, count(*) FROM applications GROUP BY 2
UNION ALL SELECT 'marital_status', marital_status, count(*) FROM applications GROUP BY 2;
```

| field | values present |
|---|---|
| `gender` | Female 51,982 / Male 48,019 — **no `Other`, though the form offers it** |
| `marital_status` | Widowed 40,609 / Married 39,651 / Unmarried 19,741 |

```sql
SELECT gender, marital_status, count(*) FROM applications GROUP BY 1,2 ORDER BY 1,2;
-- Female Married 15589 | Female Unmarried 7726 | Female Widowed 28667
-- Male   Married 24062 | Male   Unmarried 12015 | Male   Widowed 11942
```

**11,942 male widowers** exist, but the only spouse field is labelled *"Late Husband's Name
(only if widowed; optional)"* (`form_step1.html:24`) and the preview only shows it when
`marital_status == 'Widowed'` (`declaration.html:10`). There is nowhere to record a late wife.

```sql
SELECT marital_status, count(*) total,
       count(*) FILTER (WHERE btrim(coalesce(husband_name,''))<>'') with_husband_name
FROM applications GROUP BY 1;
-- Widowed 40609 / 14175 ;  Married 39651 / 1 ;  Unmarried 19741 / 0
SELECT count(*) FILTER (WHERE btrim(coalesce(husband_employer,''))<>'') FROM applications;
-- 0
```

Only 35% of widows have a husband name; one married applicant has one. `husband_employer` is
empty in all 100,001 rows — a genuinely dead column.

```sql
SELECT count(*) FILTER (WHERE applicant_name ~ '[^\x01-\x7F]') AS non_ascii_names,
       count(*) FILTER (WHERE applicant_name <> btrim(applicant_name)) AS untrimmed,
       max(length(applicant_name)) AS longest
FROM applications;
-- 300 | 0 | 20
```

**300 applicants have Assamese/Bengali-script names** (e.g. `খগেন ডেকা`, `প্ৰণৱ কুমাৰ দাস`).
These are the rows whose acknowledgment PDF breaks (§9-B6).

```sql
SELECT extract(hour FROM submitted_at)::int hr, count(*) FROM applications GROUP BY 1 ORDER BY 1;
-- 9:11075 10:11165 11:11135 12:11115 13:11108 14:11077 15:11216 16:11044 17:11066
```

Every submission falls in 09:00–17:59 **UTC** — which is 14:30–23:29 IST. Either the generator
treated these as office hours in the wrong zone, or it wrote IST values into UTC columns. The
same ambiguity affects every timestamp in the system (§9-C1).

```sql
SELECT date_trunc('month', submitted_at)::date mon, count(*),
       count(*) FILTER (WHERE status='DEEMED_APPROVED') deemed
FROM applications GROUP BY 1 ORDER BY 1;
```

~6,800–7,100 per month from 2025-07 to 2026-08, then **3,784 in 2026-09** (the month was cut
short by the snapshot) and **1 row in 2026-10** (the owner's test). There is a **21-day hole in
the data between 2026-09-30 and today.** Nothing was submitted after the configured deadline
(`2026-10-31 23:59`): that query returns 0.

#### Q16 — audit-log integrity: clean

```sql
SELECT count(*) AS apps_without_any_audit FROM applications a
WHERE NOT EXISTS (SELECT 1 FROM audit_log l WHERE l.application_id = a.id);
-- 0
SELECT a.status, count(*) FROM applications a WHERE a.status <> 'PENDING'
  AND NOT EXISTS (SELECT 1 FROM audit_log l WHERE l.application_id=a.id AND l.action=a.status)
GROUP BY 1;
-- (0 rows)
SELECT count(*) FROM audit_log l
WHERE NOT EXISTS (SELECT 1 FROM applications a WHERE a.id=l.application_id);
-- 0
```

Every application has a `SUBMIT` row and a matching terminal row; there are no orphans. Note
the second query passes only because `WITHDRAWN` rows have a `WITHDRAWN` audit action in the
seed — the code would write `WITHDRAW` and break this invariant going forward.

```sql
SELECT action, CASE WHEN actor LIKE 'applicant:%' THEN 'applicant:<mobile>' ELSE actor END AS actor_format,
       count(*) FROM audit_log GROUP BY 1,2 ORDER BY 1,3 DESC;
```

| action | actor format | count |
|---|---|---|
| `APPROVED` | `admin:admin` | 82,902 |
| `DEEMED_APPROVED` | `system:rtps-cron` | 9,700 |
| `REJECTED` | `admin:admin` | 7,001 |
| `SUBMIT` | `applicant:<mobile>` | 100,005 |
| **`WITHDRAW`** | `applicant:<mobile>` | 1 *(written by live code)* |
| **`WITHDRAWN`** | `admin:APPLICANT` | 400 *(from the seed)* |

```sql
SELECT action, count(*) total, count(*) FILTER (WHERE coalesce(btrim(note),'')='') AS empty_note,
       count(DISTINCT note) AS distinct_notes FROM audit_log GROUP BY 1 ORDER BY 2 DESC;
SELECT note, count(*) FROM audit_log WHERE coalesce(btrim(note),'')<>'' GROUP BY 1 ORDER BY 2 DESC;
```

| note | count |
|---|---|
| `not processed within SLA` | 9,700 |
| `bank account not in applicant's name` | 1,814 |
| `duplicate of an earlier beneficiary record` | 1,739 |
| `age proof document illegible` | 1,738 |
| `age proof does not match stated date of birth` | 1,709 |

Every one of the 7,000 seeded rejections carries one of exactly **four** canonical reasons —
a useful enum for an officer tool to offer. But `APPROVED` notes are empty 82,900/82,902 times,
and **the code does not require a reason to reject** (§5-C). The three odd notes
(`csrf`, `audit probe: approve`, `no name`) are from this audit and the owner's session.

#### Q17 — `portal_users` is perfectly aligned

```sql
SELECT (SELECT count(*) FROM portal_users) users,
       (SELECT count(DISTINCT mobile) FROM applications) app_mobiles,
       (SELECT count(*) FROM applications a
          WHERE NOT EXISTS (SELECT 1 FROM portal_users p WHERE p.mobile=a.mobile)) apps_without_account,
       (SELECT count(*) FROM portal_users p
          WHERE NOT EXISTS (SELECT 1 FROM applications a WHERE a.mobile=p.mobile)) accounts_without_app;
-- 100001 | 100001 | 0 | 0
```

`pgcrypto` is not installed, so I verified the password rule outside SQL instead: dumped five
`(mobile, dob, password_hash)` rows and recomputed `sha256(to_char(dob,'DDMMYYYY'))` with
`sha256sum`. **All five MATCH.** Example: mobile `9217729489`, dob `1957-04-10`, password
`10041957`, hash `a75f96b3…4127`.

Because every applicant's password is their own DOB and DOB is printed on the status page and
in the acknowledgment PDF, **any party who can see one application can log in as that citizen**.

### G. State the audit left behind

Four applications and some OAuth rows were created by exercising the portal's own flows (the
brief asked me to bring the stack up and mint a real token). Nothing was written with raw SQL.

```sql
SELECT id, application_no, applicant_name, mobile, block, status, submitted_at, decided_by
FROM applications WHERE id > 100011 ORDER BY id;
```

| id | application_no | name | mobile | status | why it exists |
|---|---|---|---|---|---|
| 100012 | SSP26540132 | Audit Test Aaji | 9000000011 | APPROVED | §4 end-to-end wizard walk-through; approved by the §5 CSRF probe |
| 100013 | SSP26759556 | Race Probe B | 9000000012 | WITHDRAWN | §9-A2 first race attempt, then withdrawn to test withdrawal |
| 100015 | SSP26801643 | Race2 C | 9000000012 | PENDING | §9-A2 decisive race — **duplicate active** |
| 100016 | SSP26184691 | Race2 A | 9000000012 | APPROVED | §9-A2 decisive race — **duplicate active**, then approved in §5 |

Also created: 6 `oauth_clients` rows (dynamic registration probes), 5 `oauth_refresh_tokens`
(2 revoked), 1 extra `oauth_program_tokens` row, 11 extra `otps` rows, 7 `audit_log` rows.
Pre-existing from the owner's session: application 100011, 1 program token, 2 OTPs.

`docker compose down -v` followed by `ADMIN_PASSWORD=… docker compose up -d --build` restores
the pristine 100,000-row seed — **but note that doing so will immediately deem-approve all 700
PENDING rows again** (§9-A1). To get a usable officer queue you must either stop the scheduler
before first boot or shift `submitted_at` forward.

---

## 3. BUSINESS RULES

### A. `validate_application()` in full — `app.py:136-178`

The file flags this block as the contract every channel must honour (`app.py:118-123`):

> *"Scheme rules: the single source of truth for what an application must satisfy. Every channel
> that creates an application (the web form, any API, any batch import) MUST go through
> `validate_application()` and `create_application()` so that no channel admits an application
> another channel would refuse."*

Signature: `validate_application(data, doc_path) -> (errors, cleaned)`. `errors` is a list of
plain-language strings (empty when valid); `cleaned` is the normalised dict for
`create_application()`. **It never raises and never touches the database** — so the
one-active-application rule is *not* part of it (see §A-4).

**Normalisation first** (`app.py:138-152`), before any check:

| key | transform | source line |
|---|---|---|
| `applicant_name` | `sanitize()` → `.strip()[:100]` | 139 |
| `village` | `.strip()` only — **no length cap** | 140 |
| `block` | `.strip()` | 141 |
| `gender` | passed through verbatim | 142 |
| `marital_status` | passed through verbatim | 143 |
| `husband_name` | `.strip()` — **no length cap** | 144 |
| `husband_employer` | forced to `""` — *"no longer collected (not a scheme requirement)"* | 145 |
| `bank_account` | `re.sub(r"[\s-]", "", ...)` — spaces and hyphens stripped | 146 |
| `ifsc` | `re.sub(r"[\s-]", "", ...).upper()` — stripped **and upper-cased** | 147 |
| `doc_path` | `doc_path or ""` | 148 |
| `dob` | parsed separately | 149 |

**The seven rules, in evaluation order:**

| # | rule | exact condition | message | line |
|---|---|---|---|---|
| 1 | required fields | `applicant_name`, `village`, `block`, `bank_account` must be non-empty after normalising. **`dob` is checked separately; `ifsc` and `gender`/`marital_status` are NOT required at all** | `"<label> is required"` | 153-156 |
| 2 | block membership | if non-empty, `block in BLOCKS` | `"block must be one of: Sonari, Rajapara, Dhemaji Pathar, Borgaon, Namti, Khelua"` | 157-158 |
| 3 | bank account | if non-empty, `re.fullmatch(r"\d{9,18}")` | `"bank account number must be 9 to 18 digits"` | 159-160 |
| 4 | IFSC | **if non-empty**, `re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}")` — exactly 11 chars | `"IFSC must be 11 characters, e.g. SBIN0003077"` | 161-162 |
| 5 | DOB parses | `parse_dob()` must return a date | `"date of birth must be given as DD/MM/YYYY"` | 163-166 |
| 6 | minimum age | `age_on(dob, now_ist().date()) >= MIN_AGE` (60) | `"applicant must be 60 years of age or above"` | 167-169 |
| 7 | age proof | `cleaned["doc_path"]` must be non-empty | `"age proof document is required"` | 170-171 |
| 8 | scheme window | `now_ist() <= SCHEME_DEADLINE` | `"the application window has closed"` | 172-173 |

Verified in-process against the live container (`validate_application` called directly):

| input | result |
|---|---|
| valid baseline | `OK (no errors)` |
| no doc | `['age proof document is required']` |
| dob `22/10/1967` (age 59) | `['applicant must be 60 years of age or above']` |
| dob `21/10/1966` (exactly 60 today) | `OK` |
| dob `1950-01-01` (ISO) | `['date of birth must be given as DD/MM/YYYY']` |
| dob `01/01/2030` (future) | `['applicant must be 60 years of age or above']` ← **misleading message** |
| block `Guwahati` | `['block must be one of: …']` |
| block `''` | `['block is required']` |
| **ifsc `UTBI0PUR2819`** (16,576 live rows) | `['IFSC must be 11 characters, e.g. SBIN0003077']` |
| ifsc `' sbin0003077 '` | `OK` (stripped + upper-cased) |
| bank `12345678` (8 digits) | `['bank account number must be 9 to 18 digits']` |
| bank `1234567890123456789` (19) | `['bank account number must be 9 to 18 digits']` |
| bank `'1234 5678-9012'` | `OK` → stored as `123456789012` |
| bank `SB12345678901` | `['bank account number must be 9 to 18 digits']` |
| **gender `Yes`** | **`OK`** |
| **gender `''`** | **`OK`** |
| **marital_status `Divorced`** | **`OK`** |
| **marital_status `''`** | **`OK`** |
| village `''` | `['village is required']` |
| **village `'; DROP TABLE applications;--`** | **`OK`** (stored literally; all SQL is parameterised, so no injection — just junk) |
| name `''` | `['full name is required']` |
| **name × 300 chars** | **`OK`** → silently truncated to 100 by `sanitize()` |
| **name `<script>alert(1)</script>`** | **`OK`** (Jinja autoescapes on output) |
| **`husband_name` on an Unmarried applicant** | **`OK`** |
| **an `annual_income` field supplied** | **`OK` — silently ignored** |

#### A-1. How age is computed

```python
# app.py:125-133
def parse_dob(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None

def age_on(dob, on):
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))
```

- **As of which date:** `now_ist().date()` (`app.py:168`) — **today in Asia/Kolkata**, not the
  submission timestamp, not UTC. `now_ist()` (`app.py:22-24`) is
  `datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)` — a *naive* datetime carrying
  IST wall-clock values.
- **DOB parsing:** `%d/%m/%Y` **only**. Verified:
  `10/04/1957` → ok · `1/4/1957` → ok (single digits accepted) · `  10/04/1957  ` → ok
  (stripped) · `1957-04-10` → **None** · `10-04-1957` → **None** · `10/04/57` → **None** ·
  `31/02/1960` → **None** (real calendar check) · `10/04/1957extra` → **None** · `''`/`None` → **None**.
  **An AI assistant that emits ISO dates — the obvious default — gets a flat rejection.**
- **Boundary:** correct and inclusive. On 2026-10-21, dob `1966-10-21` → age 60, eligible;
  `1966-10-22` → 59, refused; `1966-10-20` → 60, eligible. Somebody turning 60 *tomorrow* is
  refused today and eligible tomorrow, which matters because the scheme closes 2026-10-31.
- **Timezone trap:** because the age clock is IST but `submitted_at` is UTC, an application
  accepted at 00:30 IST on someone's 60th birthday is stored with yesterday's date. Recomputing
  "age at submission" from the stored row can give 59 for an application that validated at 60.
  This is almost certainly how the 2,585 under-60 approvals in §2-F-Q6 were manufactured.

#### A-2. The "scheme window"

A **single end date, no start date**:

```ini
# app/config/app.ini:20
scheme_deadline = 2026-10-31 23:59
```

Parsed once at import (`app.py:52-53`) with `datetime.strptime(..., "%Y-%m-%d %H:%M")` into a
naive datetime compared against `now_ist()`. **Changing `app.ini` requires an app restart.**

Three places use it, inconsistently:

| place | behaviour |
|---|---|
| `deadline_remaining()` `app.py:101-105` | returns whole **hours** left, or `None` once past. Live: **253** hours |
| `index()` `app.py:222` → `index.html:6-11` | shows *"Application window closes in approximately 253 hours (midnight, 31 October)"* — note the template hard-codes "31 October" independently of the config |
| `apply()` `app.py:252-255` | if `deadline_remaining() is None`, flash + redirect to `/` — the wizard cannot even be started |
| `validate_application` rule 8 `app.py:172-173` | the real gate at submission |

There is **no opening date**, so "is the window open?" is purely "is now ≤ 2026-10-31 23:59 IST".
Applications in the seed start 2025-07-01, well before any plausible single-season window.

#### A-3. What counts as "active"

```python
# app.py:45-47
# An applicant may hold at most one application in these states at a time.
# WITHDRAWN and REJECTED applications do not block a fresh application.
ACTIVE_STATUSES = ("PENDING", "APPROVED", "DEEMED_APPROVED")
```

```python
# app.py:180-186
def active_application(cur, mobile):
    cur.execute("SELECT id, application_no, status FROM applications "
                "WHERE mobile = %s AND status IN %s "
                "ORDER BY submitted_at DESC LIMIT 1", (mobile, ACTIVE_STATUSES))
    return cur.fetchone()
```

Keyed on **`mobile` only** — not on name, not on DOB, not on bank account. Consequences:

- A shared phone (which the Director explicitly calls out at 2:14) means **one household can
  file only one application**, because the second person's mobile already holds an active one.
  There is no way to express "a different person at the same number".
- Conversely, one person with two SIMs can hold two pensions, and nothing detects it: there is
  no duplicate check on `(applicant_name, dob)` or on `bank_account`. The seed's rejection
  reason *"duplicate of an earlier beneficiary record"* (1,739 rows) shows officers do this
  work by eye.
- `ORDER BY submitted_at DESC LIMIT 1` returns only **one** row, so if duplicates already
  exist (as my race test created) the check reports just the newest.

#### A-4. The gap between the rule block and reality

`validate_application()` does **not** check for an active application — that happens separately
in `handle_submission()` (`app.py:382-390`), *after* validation and in a different transaction
scope. So the comment's promise ("no channel admits an application another channel would
refuse") holds only if a caller remembers to call `active_application()` too. Any MCP server
must replicate that pairing, and must do it atomically (§9-A2).

### B. Every list of allowed values, and where it lives

| thing | allowed values | defined at | enforced? |
|---|---|---|---|
| **blocks** | `Sonari`, `Rajapara`, `Dhemaji Pathar`, `Borgaon`, `Namti`, `Khelua` | `app.py:57` (`BLOCKS`) | **Yes** — `validate_application` rule 2. Also populates the `<select>` via `form_step(…, blocks=BLOCKS)` `app.py:330-331` |
| **districts** | — | *nowhere* | n/a — **the concept does not exist in this system** |
| **villages** | 19 real values, 3–4 per block (§2-F-Q15) | *nowhere in code* — only implicit in the data | **No.** Free text, any value accepted, no length cap |
| **gender** | `Male`, `Female`, `Other` | `templates/form_step1.html:13-15` only | **No.** `Yes`, `''`, 40 chars all pass validation. (`Other` never appears in the data) |
| **marital_status** | `Married`, `Unmarried`, `Widowed` | `templates/form_step1.html:20-22` only | **No.** `Divorced` and `''` both pass |
| **statuses** | `PENDING`, `APPROVED`, `DEEMED_APPROVED`, `REJECTED`, `WITHDRAWN` | string literals scattered across `app.py` + `deemed_approval.py`; the active subset at `app.py:47` | partially — transitions are guarded by `AND status='PENDING'`, but the column is free text with no CHECK |
| **document types** | *"Birth certificate, School leaving certificate, Voter ID"* | `templates/upload.html:5-6` and `about.html:12-13` — **prose only** | **No.** Only the file *extension* is checked; the document *type* is never recorded, so there is no column for it and no way for an officer to know which kind was uploaded |
| **document formats** | `pdf`, `jpg`, `jpeg`, `png` | `app.py:343` | **Yes** (extension only, after `.lower()`) |
| **audit actions** | `SUBMIT`, `APPROVED`, `REJECTED`, `WITHDRAW`/`WITHDRAWN`, `DEEMED_APPROVED` | literals at `app.py:213`, `app.py:654`, `app.py:504`, `deemed_approval.py:53` | no constraint |
| **rejection reasons** | 4 canonical strings exist in the data (§2-F-Q16) | *nowhere in code* | **No** — free text, and may be empty |
| **OAuth scopes** | `citizen`, `officer` | `oauth.py:54-60` (`SCOPES`) | **Yes** — exactly one required at `/oauth/authorize` |
| **roles** | `citizen`, `officer` | `oauth.py:49-52` (`SESSION`) | **Yes** — derived from the scope |

Three notes for anyone building tools on top:

- **`gender` and `marital_status` are unvalidated free text with tight column widths**
  (`varchar(10)` / `varchar(20)`). A 40-character gender passes `validate_application` and then
  **crashes the INSERT** with `StringDataRightTruncation` — verified in §9-B5.
- The block list is **case- and spelling-exact**. `"dhemaji pathar"` or `"Dhemaji  Pathar"` is
  rejected with the full list in the message, which is at least recoverable for an assistant.
- `village` is the opposite failure: anything is accepted, so an assistant that invents a
  village name will silently file an unlocatable application.

### C. Is income — or any other eligibility criterion — checked anywhere?

**No.** `grep -rn -i "income\|district\|aadhaar\|aadhar\|caste\|bpl\|ration\|disab" app/` returns
nothing but incidental substring matches (`declaration`, `registration`). There is:

- no income column, no income field on any form, no income check in `validate_application`;
- no residency/domicile check, despite `index.html:4-5` and `about.html:6` both promising
  *"residents of Purvanchal"*;
- no Aadhaar, no caste/BPL/ration-card criterion, no existing-pension cross-check;
- no verification that the **bank account is in the applicant's name**, although
  `form_step3.html:10-11` instructs *"Ensure the account is in the name of the applicant"* and
  1,814 seeded rejections cite exactly that.

Passing an extra `annual_income` key to `validate_application` is silently discarded (verified
above). **The complete, enforced eligibility test is: age ≥ 60 as of today IST, the five
required fields present, a block from the list, a valid-shaped bank account and IFSC, an
age-proof file present, the window open, and no active application on that mobile.** Everything
else in the README, the templates and the Director's note is advisory.

### D. Withdrawal rules — `app.py:489-511`

```python
cur.execute("UPDATE applications SET status = 'WITHDRAWN', decided_at = %s, "
            "decided_by = 'APPLICANT' WHERE id = %s AND mobile = %s "
            "AND status = 'PENDING' RETURNING application_no",
            (datetime.now(), app_id, mobile))
```

- **Who:** only the citizen, from the status portal. Requires `session["logged_in"]` **and**
  `session["portal_mobile"]`; the UPDATE additionally scopes on `mobile = <session mobile>`, so
  one citizen cannot withdraw another's application.
- **There is no officer withdrawal** and no admin override of any kind.
- **Only `PENDING`.** An APPROVED, DEEMED_APPROVED, REJECTED or already-WITHDRAWN application
  returns the flash `Only a pending application can be withdrawn.` Verified live: the second
  withdrawal of the same row produced exactly that.
- `decided_by` becomes the literal `'APPLICANT'`; `decided_at` is `datetime.now()` (**UTC**).
- Audit row: action **`WITHDRAW`**, actor `applicant:<mobile>`, empty note (`app.py:504`).
- **Effect:** `WITHDRAWN` is not in `ACTIVE_STATUSES`, so the mobile may apply afresh
  immediately. Verified end-to-end: withdraw → reapply → new PENDING row.
- **Method is POST-only** with a JS `confirm()` in the template (`application.html:23-24`) and
  **no CSRF token** — so a cross-site POST can withdraw a logged-in citizen's application.
- No SMS is sent on withdrawal.
- The redirect target is `view_application(app_id)` (`app.py:511`), which still works because
  the row is only status-changed, never deleted.

### E. The deemed-approval job — `scripts/deemed_approval.py`

**Exactly what it does** (71 lines, no CLI arguments, no dry-run, no logging beyond one
`print`):

1. Reads `app/config/app.ini` at import (`:22-28`) for `sla_days` (15) and `sms_gateway_url`.
   `SLA_DAYS` and `SMS_GATEWAY_URL` are module-level, so the file must exist at import time.
2. Opens its own `psycopg2` connection from the same `[database]` section (`:32-38`) — it does
   **not** import `app.py` and shares no code with the portal.
3. Computes `cutoff = datetime.now() - timedelta(days=SLA_DAYS)` (`:40`).
4. One bulk UPDATE (`:41-46`):

```sql
UPDATE applications
   SET status = 'DEEMED_APPROVED', decided_at = %s, decided_by = 'RTPS-AUTO'
 WHERE status = 'PENDING' AND submitted_at < %s
 RETURNING application_no, mobile
```

5. Then — and this is the fragile part — re-finds the rows it just changed **by time window**
   rather than by the ids it had in hand (`:48-54`):

```sql
SELECT id FROM applications WHERE status = 'DEEMED_APPROVED'
  AND decided_by = 'RTPS-AUTO' AND decided_at >= %s   -- datetime.now() - 1 minute
```

   and inserts one `audit_log` row per id (action `DEEMED_APPROVED`, actor `system:rtps-cron`,
   note `not processed within SLA`).
6. `conn.commit()` (`:55`), then loops the `RETURNING` rows sending one SMS each
   (`:56-63`), 5 s timeout, all exceptions swallowed.
7. Prints `<timestamp> deemed approval: N applications approved` and exits 0.

**How it counts 15 days:**

- **Calendar days, not working days.** `timedelta(days=15)` — weekends and holidays included.
- **From `submitted_at`**, the stored UTC timestamp.
- **Against `datetime.now()` = container UTC**, *not* `now_ist()`. The portal's own docstring
  says the clock is IST (`app.py:23`) and `validate_application` uses IST, but this job does
  not. Both `submitted_at` and `now()` are UTC here, so the comparison is **internally
  consistent** — the 5h30m skew does not corrupt the SLA arithmetic. It only corrupts what a
  human or an assistant reads off the row (§9-C1).
- **Strict `<`**, so an application is swept only once it is *more* than 15 days old.
- **Effective grant date = `submitted_at + 15 days`, rounded up to the next 02:00 UTC
  (07:30 IST)** — i.e. always between 15 and 16 days, never exactly 15. Confirmed arithmetically
  in §2-F-Q13.

**Bugs and edge cases:**

**E1 — it runs at container boot and detonates the whole queue.** The compose `command`
(`docker-compose.yml:34-37`) runs the job once before handing over to cron, with the stated
intent *"so a freshly restored database is brought up to date"*. Because the snapshot is
2026-09-30 and today is 2026-10-21, "up to date" means **every pending application is past the
SLA**, so all 700 are auto-approved within seconds of a first `docker compose up`. Measured:
700 rows, all in the same 141 ms (`2026-10-20 10:10:47.086` → `.227`). **The officer-facing
MCP server has nothing to work on out of the box, and neither does the Director's own test.**

**E2 — the audit backfill can miss or duplicate rows.** The `RETURNING` clause yields
`application_no, mobile` but *not* `id`, so step 5 re-queries by a 1-minute window:

- If the UPDATE takes longer than 60 s (plausible on 100k rows with a cold cache), the
  earliest-updated rows fall outside `decided_at >= now() - 1 minute` and get **no audit row**,
  silently breaking the §2-F-Q16 invariant.
- If the job runs twice inside a minute (the compose `until … do sleep 5; done` loop retries
  every 5 s, and a transient DB error after the UPDATE but before the commit would re-run it),
  the second pass re-selects the first pass's rows and writes **duplicate audit rows**.
- The two `datetime.now()` calls at `:46` and `:50` are separate wall-clock reads, so the
  window is not anchored to the UPDATE at all.

**E3 — no eligibility re-check.** The UPDATE conditions on `status` and `submitted_at` only. An
application from a 55-year-old, with no document, with a malformed IFSC, in a non-existent
village, is deemed approved just the same. 273 of the 9,700 deemed approvals were under 60 at
submission; 64 are still under 60 today. There is no exclusion list and no "hold" state.

**E4 — SMS after commit, serially, un-retried.** The notification loop runs after
`conn.commit()`, so a crash mid-loop leaves applications approved and citizens un-notified
with no record of which ones were sent. Each `requests.post` has a 5 s timeout; 700 rows is up
to ~58 minutes worst case. The scheduler container has no `depends_on: smsgw`, so on a cold
boot the gateway may not be listening at all (failures swallowed at `:62-63`). And the gateway
stores messages **in memory only** — a restart loses them.

**E5 — cron fires at 02:00 UTC = 07:30 IST.** Harmless, but the docstring (`:9`) says
*"Scheduled via cron, 02:00 daily"*, which a reader will take as IST. `/var/log/sewasetu/cron.log`
is currently empty (no 02:00 boundary has passed since boot), so cron execution itself is
**UNVERIFIED** — only the crontab's installation and `cron -f` running as PID 1 are confirmed.

**E6 — no transaction isolation against an officer deciding simultaneously.** Both the job's
UPDATE and `_admin_decide`'s UPDATE carry `AND status='PENDING'`, so row locking makes one of
them a no-op — this one is genuinely safe. The officer simply gets
`Only a pending application can be decided.` if the sweep won the race.

### F. Stated in the docs but not enforced in code (or enforced differently)

| claim | where it is stated | what the code actually does |
|---|---|---|
| *"residents of Purvanchal"* | `index.html:4-5`, `about.html:6` | **Not checked at all.** No residency, domicile or address-proof field exists |
| *"One application per eligible citizen"* | `about.html:6-7` | Enforced per **mobile number**, not per citizen (§A-3). Shared phones under-count; two SIMs over-count |
| *"Applications are processed within 15 days"* | `about.html:7-8` | True of the seed (max human latency 14.33 d) but nothing *enforces* it; the deemed-approval job is the only consequence |
| *"applications not processed within the statutory period stand approved"* | `about.html:8-9`, `README` | Implemented, but grants at 15–16 days, and 9,000 historical rows were granted **early** (§2-F-Q13) |
| *"an age proof document (birth certificate, school leaving certificate or Voter ID)"* | `about.html:11-13`, `upload.html:5-6` | Only the **extension** is checked. The document *type* is never recorded, never verified, and **100,000 of 100,001 rows have no document at all** |
| *"JPG, PNG or PDF up to 5 MB"* | `about.html:13`, `upload.html:6` | Correct — but `index.html:21` says only *"JPG or PDF"* and `upload.html:6` bolds *"JPG or PDF"* while the code also accepts PNG and `jpeg` |
| *"Ensure the account is in the name of the applicant"* | `form_step3.html:10-11` | Not checkable; 1,814 seeded rejections cite it |
| *"Pension amount: Rs. 250 per month, credited by DBT"* | `index.html:4`, `about.html:10` | Nothing in the schema or code concerns disbursement. Approval is the end of the pipeline |
| *"Name, date of birth, village, block and bank account are mandatory"* | `form_step1.html:26` | Accurate. Note **IFSC is *not* mandatory** — an application with a blank IFSC validates fine (rule 4 is conditional) |
| README: *"the mobile number holds no other active (pending / approved / deemed-approved) application"* | `README` | Accurate as a description, but it is **not race-safe** (§9-A2) |
| README: *"A pending application can be withdrawn from the status portal, after which the same mobile may apply again"* | `README` | Accurate and verified |
| `deemed_approval.py:9` *"Scheduled via cron, 02:00 daily"* | docstring | 02:00 **UTC** = 07:30 IST (§E5) |
| `app.py:23` *"The portal's clock is Indian Standard Time regardless of where the server runs"* | docstring | True only for `now_ist()` callers — validation and the deadline. **Every database write uses `datetime.now()` = UTC** (§9-C1) |
| `app.py:81-83` *"capped at the column width, counting characters … so Assamese/Bangla names are stored intact"* | comment | Only `applicant_name` goes through `sanitize()`. `village` and `husband_name` are uncapped and blow up the INSERT (§9-B5). And Assamese names are **not** rendered in the acknowledgment PDF (§9-B6) |
| `app.py:118-123` *"Every channel … MUST go through validate_application() and create_application()"* | comment | Good advice, but `validate_application` omits the active-application check, so following the comment literally is not sufficient (§A-4) |
| `admin_view.html:28` placeholder *"Reason for rejection"* | template | **Not required.** `admin_reject` reads `request.form.get("note", "")` and happily records an empty reason (§5-C) |

---

## 4. CITIZEN FLOW (end to end)

Walked end to end against the live portal with `requests`, test mobile `9000000011`. The result
is application `SSP26540132` / id 100012 (§2-G).

### A. The wizard, route by route

The templates label this *"Step N of 6"* but there are **7 HTTP steps** (`/apply` and `/verify`
share the label "Step 1 of 6").

| step | URL | methods | form fields | validation at this step | on success |
|---|---|---|---|---|---|
| 1 | `/apply` | GET, POST | `mobile`, `captcha` | captcha must equal `session["captcha_answer"]`; `len(mobile) == 10 and mobile.isdigit()` | inserts an `otps` row, sends SMS, sets `session["apply_mobile"]`, `session.permanent = True`, → `/verify` |
| 2 | `/verify` | GET, POST | `otp` | latest `otps` row for that mobile must match **exactly** and be ≤ 300 s old | sets `session["verified_mobile"]` → `/form/1` |
| 3 | `/form/1` | GET, POST | `applicant_name`, `dob`, `gender`, `marital_status`, `husband_name` | **none** | merges into `session["form_data"]` → `/form/2` |
| 4 | `/form/2` | GET, POST | `village`, `block` | **none** | merges → `/form/3` |
| 5 | `/form/3` | GET, POST | `bank_account`, `ifsc` | **none** | merges → `/upload` |
| 6 | `/upload` | GET, POST | `document` (file) | extension in `pdf/jpg/jpeg/png`; size ≤ 5 MB | writes the file, sets `session["doc_path"]` → `/declaration` |
| 7 | `/declaration` | GET, POST | *(a `required` checkbox, not read server-side)* | GET previews `validate_application` errors; POST runs the real submission | `confirmation.html` with the application number |

Verified transcript:

```
POST /apply   (mobile+captcha) -> 302 /verify
POST /verify  (otp 259461)     -> 302 /form/1
POST /form/1                   -> 302 /form/2
POST /form/2                   -> 302 /form/3
POST /form/3                   -> 302 /upload
POST /upload  (age.png)        -> 302 /declaration
POST /declaration              -> 200  application_no = SSP26540132
```

Details worth knowing:

- **`/apply`** (`app.py:250-280`). The captcha is `make_captcha()` (`app.py:282-286`) — a single
  `a + b` sum with `a, b ∈ 1..9` stored in the session. **A new captcha is generated on every
  GET and on every failed POST**, so it is a trivial two-request obstacle for a program (I solve
  it by regexing `What is (\d) \+ (\d)\?` out of the page). It is the only rate-limiting-ish
  control anywhere in the portal.
- **`/verify`** (`app.py:288-310`). Reads only the **newest** OTP for the mobile
  (`ORDER BY id DESC LIMIT 1`), compares with plain `==` (not constant-time; `oauth.py:375`
  uses `secrets.compare_digest` for the same job — an inconsistency), then checks
  `(datetime.now() - created_at) <= 300`. Both sides are UTC so the TTL is correct.
  **On expiry it redirects to `/apply`, losing nothing** (the form data is not yet in session).
  **There is no attempt limit** — verified: 15 wrong OTPs in a row all return 200, and the
  correct OTP still works afterwards (§9-D3).
- **`/form/<int:step>`** (`app.py:313-330`). Guarded only by `session["verified_mobile"]`;
  `step` must be 1, 2 or 3 or it `abort(404)`. The POST handler is completely generic:

```python
data = session.get("form_data", {})
for k, v in request.form.items():
    data[k] = v
session["form_data"] = data
```

  **It copies every submitted key verbatim into the session with no allow-list.** So any step
  can set any field — `POST /form/1` with `block=Namti&bank_account=…` works fine, and the
  three steps exist purely for presentation. It also means an assistant can fill the whole form
  in **one** POST to `/form/1` and then jump to `/upload`. Conversely there is **no per-step
  validation at all**: a citizen types a bad DOB on step 2 of 6 and only learns about it on
  step 6.
- **`/declaration` GET** (`app.py:360-371`) runs `validate_application` and renders the error
  list, so it is a true preview. The declaration **checkbox is `required` in HTML only**
  (`declaration.html:34`) — the POST handler never reads it, so a program submits with an empty
  body and no consent is recorded anywhere.
- **`/declaration` POST → `handle_submission()`** (`app.py:373-405`): re-validate → check
  `active_application` → `create_application` → commit → clear `form_data` / `doc_path` /
  `verified_mobile` from the session → **set `session["logged_in"]` and
  `session["portal_mobile"]`** so the citizen lands on the status portal without a second login
  (`app.py:398-400`, verified: the confirmation page's ack-PDF link works immediately) → send
  SMS → render `confirmation.html`.
  On validation failure it flashes all errors joined with `;` and redirects to `/form/1`
  (`app.py:377-379`) — **the session data survives**, so nothing is lost.
  On an existing active application it flashes the number and status and redirects to `/`.
  Verified: `Application SSP26540132 (PENDING) already exists for this mobile number. A pending
  application can be withdrawn from the status portal if you need to apply afresh.`

### B. Where data lives between steps

**Entirely in the Flask session cookie. There is no draft table and no draft row.**

| session key | set at | holds |
|---|---|---|
| `captcha_answer` | `make_captcha()` | the expected sum |
| `apply_mobile` | `/apply` POST | the number an OTP was sent to |
| `verified_mobile` | `/verify` POST | the gate for every later step |
| `form_data` | `/form/<step>` POST | a dict of **every** posted key |
| `doc_path` | `/upload` POST | the server path of the saved file |
| `logged_in`, `portal_mobile` | submission, or `/status` login | status-portal identity |
| `admin`, `admin_user` | `/admin` login | officer identity |

Consequences:

- `PERMANENT_SESSION_LIFETIME = 7200` (`app.py:40`) with the comment *"elderly applicants fill
  the form slowly; the draft lives in the session"*. `session.permanent = True` is set at
  `/apply` (`app.py:277`). **After 2 hours the whole draft evaporates** and the citizen restarts
  from the OTP.
- The cookie is signed with
  `secret_key = "ssp-prod-key-2023-donotshare"` (`app/config/app.ini:12`, used at `app.py:38`
  unless `$SECRET_KEY` is set — and `docker-compose.yml` does **not** set it). **A committed,
  publicly readable signing key means anyone can forge a session cookie, including
  `{"admin": True}`.** This is the most severe single defect in the portal (§9-D1).
- An abandoned wizard leaves **no trace in the database** except the `otps` row. There is no
  "resume my half-finished application" to build a tool around, and no way for an officer to
  see drop-off.
- The flow is **not idempotent and not resumable across clients**: an MCP server cannot hand a
  half-filled draft to another process, because the state is in a cookie it holds.

### C. The age-proof upload — `app.py:332-357`

```python
f = request.files.get("document")
if f is None or f.filename == "":
    flash("Please choose a file to upload (JPG, PNG or PDF, up to 5 MB)."); return render_template("upload.html")
filename = f.filename.lower()
content = f.read()
if not filename.rsplit(".", 1)[-1] in ("pdf", "jpg", "jpeg", "png"):
    flash("Please upload a JPG, PNG or PDF file."); return render_template("upload.html")
if len(content) > 5 * 1024 * 1024:
    flash("File is larger than 5 MB. Please upload a smaller file."); return render_template("upload.html")
os.makedirs(UPLOAD_DIR, exist_ok=True)
path = os.path.join(UPLOAD_DIR, "%s_%s" % (session["verified_mobile"], filename))
with open(path, "wb") as out:
    out.write(content)
session["doc_path"] = path
```

| property | value |
|---|---|
| **field name** | `document` (`upload.html:9`), `enctype="multipart/form-data"` |
| **accepted** | extension `pdf`, `jpg`, `jpeg`, `png` after `.lower()` — **extension only, no magic-byte or MIME check** |
| **size limit** | 5 MB, checked **after** `f.read()` loads the whole body into memory. `MAX_CONTENT_LENGTH` is not set, so a 500 MB upload is read into RAM before being rejected — a trivial memory-exhaustion vector across 4 gunicorn workers |
| **storage** | `/var/sewasetu/uploads/<mobile>_<lowercased original filename>`, on the `uploads` named volume, mounted **only on the `app` container** |
| **link to the application** | the absolute server path is copied into `session["doc_path"]`, then into `applications.doc_path` by `create_application` (`app.py:201`). There is **no uploads table, no FK, no content hash, and no `document_type`** |

Verified probe results:

| upload | outcome |
|---|---|
| `age.txt` | `Please upload a JPG, PNG or PDF file.` |
| 6 MB `age.png` | `File is larger than 5 MB. Please upload a smaller file.` |
| `age.PNG` | **accepted**, stored as `9000000011_age.png` (lower-cased) |
| `../traversal-probe.png` | **HTTP 500** — `FileNotFoundError: /var/sewasetu/uploads/9000000011_../traversal-probe.png` |
| `age.png` (good) | accepted → `/declaration` |

Three real problems:

- **No `secure_filename()`.** The filename is user-controlled and only lower-cased. Because the
  `<mobile>_` prefix is glued on, a leading `../` cannot actually escape the directory (it would
  need a directory literally named `9000000011_..`), so **I could not achieve traversal** — but
  any filename containing `/` produces an **unhandled 500**. A deployment where `UPLOAD_DIR`
  already contains subdirectories would be exploitable; here it is a crash, not an escape.
- **Silent overwrite.** The path is `<mobile>_<filename>`, so re-uploading `age.png` overwrites
  the previous file — including one still referenced by an *earlier* application's `doc_path`.
  I observed exactly this: my first `age.PNG` and second `age.png` collapsed onto one file.
  Case-folding makes `AGE.PNG` and `age.png` collide too.
- **No download route.** `grep` confirms nothing serves `doc_path`; `admin_view.html:15` prints
  the raw server path as text. **An officer — human or AI — literally cannot look at the age
  proof.** For a scheme whose top two rejection reasons are *"age proof document illegible"* and
  *"age proof does not match stated date of birth"* (3,447 seeded rejections), this is the
  single biggest functional hole in the officer workflow.

### D. How the application number is generated — `app.py:108-109`

```python
def new_application_no():
    return "SSP" + datetime.now().strftime("%y") + str(random.randint(100000, 999999))
```

- Format `SSP` + 2-digit year + a 6-digit random integer → e.g. `SSP26540132`. Always 11 chars
  in a `varchar(20)`.
- The year comes from `datetime.now()` (**UTC**), not `now_ist()` — so for 5½ hours around each
  New Year the prefix is a year behind the portal's own clock.
- **`random`, not `secrets`** — seeded per worker process, so numbers are predictable in
  principle.
- **No uniqueness check, no retry, no DB constraint** → a 6.5% collision chance per new
  application against the existing `SSP26*` population (§2-F-Q12). Live samples:
  `SSP26180638, SSP26363931, SSP26803272, SSP26331343, SSP26202093`.
- It is generated **inside** `create_application` (`app.py:189`), so a caller cannot supply or
  pre-reserve one.

### E. SMS messages: what is sent, and when

`send_sms(mobile, text)` (`app.py:93-99`) POSTs `{"to", "text"}` to
`http://smsgw:8025/api/send` with a 5 s timeout and logs-and-swallows any exception.

| trigger | code | message |
|---|---|---|
| OTP requested at `/apply` | `app.py:275` | `Your Sewa Setu OTP is 123456. Valid for 5 minutes.` |
| OTP requested in the **OAuth** citizen login | `oauth.py:389` | *identical text* |
| application submitted | `app.py:401-403` | `Sewa Setu: application SSP26540132 received. Track at the status portal with mobile no. and password (DOB as DDMMYYYY).` |
| password reset | `app.py:559-560` | `Sewa Setu: your password has been reset to your date of birth (DDMMYYYY).` |
| deemed approval | `deemed_approval.py:58-61` | `Sewa Setu: your pension application SSP26540132 stands approved under the RTPS Act.` |

**That is the complete list — five messages.** Notably absent:

- **no SMS on approve**, **no SMS on reject**, **no SMS on withdrawal**. Verified empirically:
  9 messages in the inbox before approving + rejecting applications for `9000000012`, 9 after.
  A citizen who does not log back in never learns the outcome.
- The submission SMS **tells the citizen their password is their DOB** in plain text — and the
  gateway inbox is world-readable (§9-D2).

### F. The status portal

**Login — `/status`, GET + POST (`app.py:443-468`).** Fields `mobile`, `password`. Looks up
`portal_users.password_hash` and compares `== hash_password(password)` i.e. unsalted SHA-256.
On success sets `session["logged_in"]`, `session["portal_mobile"]`, then redirects to the
**most recent** application (`ORDER BY submitted_at DESC LIMIT 1`, `app.py:454-456`). If the
mobile has a portal account but no application: `No application found for this mobile number.`
On failure the flash **states the password rule**: `Mobile number or password is incorrect. The
password is your date of birth as DDMMYYYY.`

Problems: the password *is* the DOB (8-digit, ~36,500 realistic values for a 60-90-year-old),
unsalted, **with no lockout and no rate limit** — 12 wrong attempts in 0.2 s all returned 200
(§9-D3). `portal_users` rows are created only when absent (`app.py:209-212` checks
`count(*) == 0`), so a citizen whose second application has a different DOB keeps their **old**
password forever.

**`/status/reset`, GET + POST (`app.py:537-562`).** Takes only `mobile`, resets the hash to
`sha256(dob as DDMMYYYY)` and SMSes a notice. Always flashes the same neutral message —
verified: a known mobile and `9999999999` return identical text, so no account enumeration.
Two flaws: it needs **no proof of ownership whatsoever** (anyone can trigger a reset for any
number), and it picks the DOB with `SELECT dob FROM applications WHERE mobile = %s LIMIT 1`
(`app.py:546`) — **no `ORDER BY`**, so for a mobile with several applications it may reset to
an older application's DOB, which the login hint then contradicts.

**View — `/application/<int:app_id>` GET (`app.py:471-487`).** Requires
`session["logged_in"]`; the query is scoped `WHERE id = %s AND mobile = %s` against
`session["portal_mobile"]`, so cross-tenant reads `abort(404)` — verified: `GET /application/1`
as `9000000011` → **404**. Shows: application number, name, mobile, DOB, village, block, bank
account, IFSC, **status**, submitted, decided. Note it shows the full bank account and the DOB
(= the password) in clear.

**Withdraw** — see §3-D. The button renders only when `status == 'PENDING'`
(`application.html:19`); for `WITHDRAWN`/`REJECTED` the page instead offers a link to apply
again (`application.html:27-29`); for `APPROVED`/`DEEMED_APPROVED` it offers nothing at all.

**Acknowledgment PDF — `/ack/<int:app_id>.pdf` GET (`app.py:513-535`).** Auth: if
`session["admin"]` is set, no further check; otherwise it must match
`WHERE id = %s AND mobile = <session portal_mobile>` or `abort(403)`. Verified: `/ack/1.pdf`
as `9000000011` → **403**; as admin → 200. It looks for a cached
`$UPLOAD_DIR/ack/<id>.pdf`, which **nothing ever writes**, so every request regenerates with
`generate_acknowledgment` (`app.py:407-436`) — a 10-row fpdf2 table, ~1.8 kB. Note it does not
require `logged_in`, only a matching `portal_mobile`.

**"Connected applications" — `/status/connections`, GET + POST (`oauth.py:570-586`).** Requires
`logged_in` + `portal_mobile`; subject is `"citizen:" + session["portal_mobile"]`. GET lists
active grants from `oauth_refresh_tokens` where `revoked_at IS NULL AND expires_at > now()`,
showing client name (falling back to client id), signed-in time and session end. POST with a
`token_hash` ends that one sign-in; POST with none ends **all** of them
(`_revoke_grants(subject, None)`), flashing `N sign-in(s) ended.` Verified live: the page renders
`No application is currently signed in for you.` when empty, and lists/revokes correctly
otherwise.

**It only ever revokes refresh tokens.** Access tokens are stateless JWTs with no revocation
check, so **ending a sign-in leaves the current access token valid for up to 20 minutes**
(30 for officers). And program tokens never appear here at all (§5-E).

---

## 5. OFFICER FLOW

### A. Admin routes

| URL | methods | guard | what it does |
|---|---|---|---|
| `/admin` | GET, POST | — | login form; `app.py:565-576` |
| `/admin/dashboard` | GET | `session["admin"]` | counts; `app.py:578-595` |
| `/admin/applications` | GET | `session["admin"]` | list + filter; `app.py:597-619` |
| `/admin/application/<int:id>` | GET | `session["admin"]` | one case + audit trail; `app.py:621-640` |
| `/admin/approve/<int:id>` | **POST** | `session["admin"]` else `abort(403)` | `app.py:663-665` |
| `/admin/reject/<int:id>` | **POST** | `session["admin"]` else `abort(403)` | `app.py:668-670` |
| `/admin/tokens` | GET, POST | `session["admin"]` | program tokens; `oauth.py:589-622` |

**Login** (`app.py:566-576`): a plain string comparison against the two env vars, requiring
`ADMIN_PASSWORD` to be non-empty:

```python
if (ADMIN_PASSWORD and request.form.get("username") == ADMIN_USERNAME and
        request.form.get("password") == ADMIN_PASSWORD):
    session["logged_in"] = True
    session["admin"] = True
    session["admin_user"] = ADMIN_USERNAME
```

Not constant-time, no lockout, no rate limit, no audit record of logins or failures. Note it
also sets `logged_in`, the **same key the citizen status portal uses** — so an admin session
satisfies `view_application`'s guard, though the `mobile = portal_mobile` scope then 404s. There
is **no `/admin/logout` route anywhere.**

**Dashboard** (`app.py:579-595`) runs three queries and nothing else:

```sql
SELECT status, count(*) FROM applications GROUP BY status;
SELECT count(*) FROM applications WHERE status = 'PENDING' AND submitted_at < %s;  -- now()-15d
SELECT block, count(*) FROM applications WHERE status = 'PENDING' GROUP BY block ORDER BY count(*) DESC;
```

Live output: `APPROVED 82900 / DEEMED_APPROVED 9700 / PENDING 3 / REJECTED 7001 /
WITHDRAWN 401`, `Pending beyond 15-day SLA: 0`, `Pending by Block: Dhemaji Pathar 3` (the 3 are
my test rows). On a pristine, unswept database this would read `PENDING 700` and
`Pending beyond 15-day SLA: 700`. The overdue cutoff uses `datetime.now()` (UTC), consistent
with the job.

**List / filter** (`app.py:598-619`) has exactly **two** modes:

```python
if mobile:
    "... WHERE mobile = %s ORDER BY submitted_at ASC"          # no LIMIT, ignores `status`
else:
    "... WHERE status = %s ORDER BY submitted_at ASC LIMIT 50 OFFSET %s"
```

- Default `status = "PENDING"`; page size 50; `page` from the query string.
- **Oldest first** — correct for a queue.
- Columns returned: `id, application_no, applicant_name, mobile, block, status, submitted_at`.

Probe results:

| query string | result |
|---|---|
| *(default)* | 200, 3 rows |
| `?status=PENDING` | 200, 3 rows |
| `?status=PENDING&page=2` | 200, 0 rows |
| **`?status=PENDING&page=0`** | **500** (negative `OFFSET`) |
| **`?status=PENDING&page=-1`** | **500** |
| **`?status=PENDING&page=abc`** | **500** (`int()` raises; `app.py:601` is unguarded) |
| **`?page=1.5`** | **500** |
| `?status=NONSENSE` | 200, 0 rows — no validation, silently empty |
| **`?status=pending`** | **200, 0 rows** — status matching is case-**sensitive** |
| `?mobile=9000000012` | 200, 3 rows (all statuses, no pagination) |
| `?mobile=' OR 1=1--` | 200, 0 rows — parameterised, no injection |

Four traps for an assistant here: a lower-case status silently returns an empty queue; an
invalid status silently returns an empty queue; `page=0` (the natural 0-indexed guess) is a
**500**; and the mobile search is **unbounded**, ignoring the status filter entirely.

There is also **no way to filter by block, by date range, or by overdue-ness**, and no total
count — the template's "Next »" link (`admin_list.html:22`) is unconditional, so you cannot
tell you have reached the end without clicking into an empty page.

**Case view** (`app.py:622-640`) selects 15 columns plus the audit trail
(`ORDER BY at ASC`) and renders approve/reject forms **only when `status == 'PENDING'`**
(`admin_view.html:20-31`). It shows `doc_path` as plain text (`admin_view.html:15`) — again,
there is no link and no route to fetch the file. Unknown ids `abort(404)`.

### B. Approve / reject — `_admin_decide`, `app.py:642-661`

```python
def _admin_decide(app_id, new_status, note):
    if not session.get("admin"):
        abort(403)
    actor = session.get("admin_user", ADMIN_USERNAME)
    cur.execute("UPDATE applications SET status = %s, decided_at = %s, decided_by = %s "
                "WHERE id = %s AND status = 'PENDING' RETURNING application_no",
                (new_status, datetime.now(), actor, app_id))
    row = cur.fetchone()
    if row:
        write_audit(cur, app_id, new_status, "admin:%s" % actor, note)
        conn.commit()
        flash("Application %s %s." % (row[0], new_status.lower()))
    else:
        flash("Only a pending application can be decided.")
```

- `AND status = 'PENDING'` makes it idempotent and race-safe against the cron job and against a
  double-click. Verified: approve → `Application SSP26184691 approved.`; approve again →
  `Only a pending application can be decided.`; reject an approved row → same refusal.
- `decided_at` is `datetime.now()` = **UTC**.
- **No eligibility re-check.** An officer can approve a 55-year-old with no document and a
  malformed IFSC; nothing warns them. The seed shows 2,585 such approvals already (§2-F-Q6).
- **No SMS.** Verified: the applicant's inbox is unchanged across an approve and a reject.
- **No CSRF protection.** Verified: a bare cross-site POST carrying only the session cookie,
  with no `Referer`, no `Origin` and no token, **approved application 100012** and recorded the
  note `csrf` in the audit log. Every state-changing route in the portal has this property.
- `note` is `request.form.get("note", "")` — see §5-C.

### C. Is a rejection reason required?

**No.** `admin_reject` (`app.py:668-670`) passes `request.form.get("note", "")` straight
through, and `write_audit` stores whatever it gets. The template merely *suggests* one with a
placeholder (`admin_view.html:28`: `placeholder="Reason for rejection"`). There is no
server-side check, no minimum length, and no enum.

The seed, by contrast, has a reason on **all 7,000** rejections, drawn from exactly four
strings (§2-F-Q16) — so the historical data sets an expectation the code does not enforce.
This directly contradicts the Director at 2:30 (*"approve or reject it for the reason recorded
against her name"*). An officer-side MCP tool should require the reason itself.

### D. Officers, identities and jurisdiction

**There is exactly one officer.**

- Credentials come from two environment variables, `ADMIN_USERNAME` (default `admin`) and
  `ADMIN_PASSWORD` (`app.py:42-43`), read **once at import**. There is **no officers table, no
  user management, no password change, and no second account.** Adding an officer means
  restarting the container with different env vars — which replaces the only account rather
  than adding one.
- `session["admin_user"]` is always `ADMIN_USERNAME`, so `decided_by` is always `admin` and the
  audit actor is always `admin:admin` — confirmed across all 89,903 decision rows in the data.
- The OAuth officer login (`oauth.py:376-381`) checks the **same two env vars**, so every
  officer token has `sub = "officer:admin"`. There is no way to tell two officers apart in a
  token, in `decided_by`, or in the audit log.
- **There is no jurisdiction of any kind.** No block or district is associated with the officer
  anywhere in the schema, the session, the token claims or the routes. Verified: one page of
  the APPROVED list shows applications from **all six blocks**
  (`['Borgaon', 'Dhemaji Pathar', 'Khelua', 'Namti', 'Rajapara', 'Sonari']`), and there is no
  block filter to narrow it. The dashboard's "Pending by Block" is informational only.

This is the hardest constraint on the officer MCP server. The Director asks for a *block*
officer whose decisions are recorded *against her name* (2:30) and for the agent to work on
"a subset of blocks" (1:52) — **none of which the portal can currently express.** Any
per-officer identity or block scoping has to be invented in the MCP layer, and it will not be
reflected in `decided_by` or the audit log unless that layer writes a richer actor string
itself. See §10-Q1 and §10-Q2.

### E. Program tokens — `/admin/tokens`, `oauth.py:589-622`

**Creation.** A POST without a `revoke_subject` field mints one (`oauth.py:594-608`):

```python
label    = (request.form.get("label") or "program").strip()[:100]
audience = (request.form.get("audience") or "").strip() or ISSUER
days     = max(1, min(int(request.form.get("days") or 90), 365))
subject  = "officer:" + session.get("admin_user", portal.ADMIN_USERNAME)
issued, claims = mint_access_token(subject, "officer", "officer", audience,
                                   "admin-issued", ttl=days * 86400, kind="program")
```

then inserts `(jti, label, subject, audience, issued_by, created_at, expires_at)` into
`oauth_program_tokens` and renders the JWT once in a `<pre>` (`admin_tokens.html:8-11`).

**Claims.** Minted live with `days=400`:

```json
{
  "iss": "http://localhost:8000",
  "sub": "officer:admin",
  "aud": "http://mcp.example.test/officer",
  "scope": "officer",
  "role": "officer",
  "client_id": "admin-issued",
  "iat": 1792557169,
  "exp": 1824093169,
  "jti": "d6346f4fdf6829c9197dfc3f",
  "kind": "program"
}
```

Same shape as a user token with two differences: `client_id` is the literal `"admin-issued"`,
`kind` is `"program"` instead of `"access"`, and **there is no `session_ends` claim** (because
`_issue` is bypassed and `session_ends=None`).

**Lifetime.** `days` is clamped to `[1, 365]`. Verified: requesting 400 days yielded exactly
**365.0 days**. `int()` is unguarded, so `days=abc` is a **500**. There is no default expiry
policy beyond the form's `value="90"`.

**Revocation: there is none.** This is a real defect, not an oversight in my reading:

- `oauth_program_tokens.revoked_at` exists in the schema (`schema.sql:110`) and is **never
  written by any code path** — `grep` for `revoked_at` finds writes only against
  `oauth_refresh_tokens` (`oauth.py:508`, `:534`, `:548`, `:551`).
- The "End now" button on `/admin/tokens` (`admin_tokens.html:34-36`) posts `revoke_subject` +
  `token_hash` into `_revoke_grants` (`oauth.py:544-557`), which only ever updates
  **`oauth_refresh_tokens`**. It governs the officer's *interactive* OAuth sign-ins, listed
  under a separate heading — not the program tokens listed above them.
- Nothing anywhere checks a presented token's `jti` against `oauth_program_tokens`, so even
  setting `revoked_at` by hand would have no effect.

**Net: a leaked program token is a full officer credential, valid for up to a year, that cannot
be withdrawn without rotating the signing key in `oauth_keys` (which invalidates every other
token too).** The page offers no delete, and the token is displayed once with no fingerprint
recorded beyond the `jti`, so an operator cannot even tell which of two leaked tokens to worry
about.

**What the page also shows** (`oauth.py:609-622`): the last 20 program tokens (label, subject,
audience, issued_by, created, expires), the admin's own active interactive grants with an "End
now" button each, and the last 20 registered OAuth clients (name, `dcr`/`cimd`, created). Note
it lists **every** program token ever issued regardless of who issued it, and shows no
revoked/expired distinction.

### F. The audit trail, exactly

`write_audit(cur, app_id, action, actor, note="")` (`app.py:112-115`):

```sql
INSERT INTO audit_log (application_id, action, actor, note, at) VALUES (%s, %s, %s, %s, %s)
```

with `at = datetime.now()` (**UTC**). It takes the caller's cursor and **does not commit** — the
caller's `conn.commit()` makes the audit row and the status change atomic. That is the one place
the design is genuinely careful, and any MCP server must preserve it by passing its own cursor.

| column | written as |
|---|---|
| `application_id` | the integer `applications.id` — **no FK, so a bad id is accepted silently** |
| `action` | `SUBMIT` \| `APPROVED` \| `REJECTED` \| `WITHDRAW` \| `DEEMED_APPROVED` |
| `actor` | `applicant:<mobile>` \| `admin:<admin_user>` \| `system:rtps-cron` (`varchar(50)`) |
| `note` | free text ≤ 500 chars; `''` for SUBMIT and WITHDRAW; optional for decisions; fixed `not processed within SLA` for the cron |
| `at` | UTC timestamp |

Actor formats actually present in the database are tabulated in §2-F-Q16. The two seed-vs-code
mismatches (`WITHDRAWN`/`WITHDRAW`, `admin:APPLICANT`/`applicant:<mobile>`) mean an officer
tool that reconstructs history must accept both.

What is **not** audited anywhere: admin logins and failures, OAuth consent grants, token
issuance, token revocation, password resets, OTP requests, document uploads, and any read
access. `admin_view.html:41` even anticipates gaps — *"No audit entries (application predates
audit logging)"* — though in practice every row has one.

---

## 6. OAUTH / AUTH SERVER

`app/oauth.py`, a Flask Blueprint registered at `app.py:673-674`. `ISSUER` is
`$PUBLIC_BASE_URL` with trailing slashes stripped, defaulting to `http://localhost:8000`
(`oauth.py:46`) — read **once at import**, so changing it needs a restart.

### A. Every endpoint, with verified behaviour

| endpoint | method | auth | behaviour |
|---|---|---|---|
| `/.well-known/oauth-authorization-server` | GET | none | RFC 8414 metadata; `oauth.py:139-158` |
| `/.well-known/jwks.json` | GET | none | one RSA public key; `oauth.py:160-162` |
| `/oauth/register` | POST | none | RFC 7591 dynamic registration; `oauth.py:239-273` |
| `/oauth/authorize` | **GET only** | none | validates, stores an `oauth_requests` row, redirects to `/oauth/login`; `oauth.py:311-346` |
| `/oauth/login` | GET, POST | none | citizen OTP **or** officer password; `oauth.py:349-396` |
| `/oauth/consent` | GET, POST | none *(see §6-F2)* | shows the consent screen, issues the code; `oauth.py:399-434` |
| `/oauth/token` | POST | client auth if a secret was issued | `authorization_code` + `refresh_token`; `oauth.py:468-526` |
| `/oauth/revoke` | POST | **none at all** | RFC 7009 refresh-token revocation; `oauth.py:529-541` |
| `/status/connections` | GET, POST | citizen session cookie | §4-F |
| `/admin/tokens` | GET, POST | admin session cookie | §5-E |

**`/.well-known/oauth-authorization-server`** — fetched live:

```json
{
  "issuer": "http://localhost:8000",
  "authorization_endpoint": "http://localhost:8000/oauth/authorize",
  "token_endpoint": "http://localhost:8000/oauth/token",
  "registration_endpoint": "http://localhost:8000/oauth/register",
  "jwks_uri": "http://localhost:8000/.well-known/jwks.json",
  "revocation_endpoint": "http://localhost:8000/oauth/revoke",
  "scopes_supported": ["citizen", "officer"],
  "response_types_supported": ["code"],
  "response_modes_supported": ["query"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"],
  "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
  "authorization_response_iss_parameter_supported": true,
  "client_id_metadata_document_supported": true,
  "service_documentation": "http://localhost:8000/about"
}
```

Everything advertised is implemented. `/.well-known/openid-configuration` → **404** (this is
not an OIDC provider: no `id_token`, no `userinfo`, no `nonce`).

**`/.well-known/jwks.json`** — one key, `RS256`, `use: sig`,
`kid: a9a33aab5d44d068`, 2048-bit RSA, with `key_ops: ["verify"]` added by PyJWT. The private
key is generated on first use and stored as plaintext PEM in `oauth_keys`
(`oauth.py:73-96`), then cached per-process in `_KEY_CACHE`. `ON CONFLICT DO NOTHING` plus a
re-SELECT makes the 4-worker race benign — all workers converge on `ORDER BY created_at ASC
LIMIT 1`. **There is no key rotation and no second key**, so rotating is a hard cutover that
invalidates every live token.

**CORS** (`oauth.py:165-172`) is an `after_app_request` hook that stamps
`Access-Control-Allow-Origin: *`, `Allow-Headers: *`, `Allow-Methods: GET, POST, OPTIONS` on
**every** path starting `/.well-known/` or `/oauth/`. That includes `/oauth/token` and
`/oauth/revoke`. Credentials are not allowed, so it is not directly exploitable, but it does
mean any web page can drive the token and revoke endpoints.

### B. Dynamic client registration — `oauth.py:239-273`

Validation, in order:

1. `redirect_uris` must be a **non-empty list of strings** (`:242-245`).
2. Every URI's scheme must be `https`, **or** `http` with hostname in
   `("localhost", "127.0.0.1")` (`:246-250`). Note `[::1]` is **not** accepted here, though
   `redirect_allowed` accepts it later — an inconsistency.
3. `token_endpoint_auth_method` must be `none` or `client_secret_post` (`:251-254`).
4. `client_name` is truncated to 100 chars, defaulting to `"Unnamed application"`.

`client_id` is `"ssc_" + secrets.token_urlsafe(16)`; a `client_secret` is minted only for
`client_secret_post` and stored as a bare SHA-256 (`:255-265`). Response is `201` with
`client_secret_expires_at: 0` (never expires).

**No authentication, no rate limit, no quota** — anyone can register unlimited clients, and
`oauth_clients` grows unbounded. There is no `GET`/`PUT`/`DELETE` on a registration (no
`registration_access_token`, no `registration_client_uri`), so clients cannot be updated or
removed.

Verified probes:

| body | result |
|---|---|
| `{"redirect_uris": ["http://evil.example.com/cb"]}` | **400** `invalid_redirect_uri` — "must be https, or http on localhost" |
| `{"redirect_uris": ["https://ok.example.com/cb"]}` | **201** |
| `{"redirect_uris": ["http://127.0.0.1:1/cb"]}` | **201** |
| `{"redirect_uris": []}` | **400** "must be a non-empty list" |
| `{"redirect_uris": ["ftp://x/y"]}` | **400** |
| `…"token_endpoint_auth_method": "client_secret_basic"` | **400** `invalid_client_metadata` |
| `…"token_endpoint_auth_method": "client_secret_post"` | **201**, with a `client_secret` |

A real registration I used for the rest of this section:

```json
{ "client_id": "ssc_CuEri90WrMnmq2zsOxiWAw", "client_name": "Audit Probe",
  "redirect_uris": ["http://localhost:9999/callback"],
  "token_endpoint_auth_method": "none",
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"], "client_id_issued_at": 1792557107 }
```

### C. Client-ID-Metadata-Document support — `oauth.py:201-236`

`_is_url_client(client_id)` is true when the id starts `https://` or `http://localhost`
(`:201-202`). `load_client` then GETs that URL with a 5 s timeout and
`Accept: application/json`, and requires **two** things of the document (`:221-223`):

- `doc["client_id"] == client_id` (it must be self-referential), and
- `doc["redirect_uris"]` must be a `list`.

On success it upserts a row with `kind='cimd'` and `fetched_at = now()`, then **caches it for
one hour** — `load_client` only re-fetches when `(now - fetched_at) >= 3600` (`:210`).
`client_name` defaults to the URL itself.

Verified by serving documents from a throwaway HTTP server inside the app container and calling
`oauth.load_client` directly:

| `client_id` | `_is_url_client` | `load_client` |
|---|---|---|
| `http://localhost:7777/cimd.json` (self-referential, valid) | True | **loaded** → `{'client_name': 'CIMD Probe Client', 'redirect_uris': ['http://localhost:9999/cb'], 'kind': 'cimd', 'secret_hash': None}` |
| `http://localhost:7777/mismatch.json` (`client_id` points elsewhere) | True | `None` |
| `http://localhost:7777/nouris.json` (no `redirect_uris`) | True | `None` |
| `https://example.com/x.json` (404) | True | `None` |
| `ssc_nonexistent` | False | `None` |

And over HTTP at `/oauth/authorize`, all three of
`https://example.com/not-a-client.json`, `http://localhost:8000/about` (HTML, so `.json()`
raises) and `http://not-localhost.test/c.json` return **400 "Unknown application"**.

**What is *not* validated:** the document's redirect URIs are never put through the
`register()` scheme checks, so **a CIMD client may declare any redirect URI at all** —
`http://evil.example.com/cb` would be rejected at `/oauth/register` but accepted via CIMD.
There is also no size limit on the fetched body, no redirect-count limit, and no SSRF
protection: `load_client` will fetch any `https://` URL, or any `http://localhost` URL, **from
inside the app container**. `http://localhost:…` resolves to the app itself, which is a
same-host SSRF primitive against anything listening in that container.

### D. The authorize flow

**Step 1 — `/oauth/authorize` (GET)**, `oauth.py:311-346`. In order:

1. `load_client(client_id)`; unknown → **400** `oauth_error.html` "Unknown application".
2. `redirect_allowed(client["redirect_uris"], redirect_uri)`; bad → **400** "Bad redirect URI".
   Both of these render an error **page** rather than redirecting, which is correct (RFC 6749
   §4.1.2.1).
3. `response_type` must be `code`, else an error **redirect** `unsupported_response_type`.
4. `code_challenge` must be present and `code_challenge_method` must be `S256` (defaulting to
   `S256` if absent), else `invalid_request` "PKCE with S256 is required".
5. **Exactly one** scope, from `{citizen, officer}`, else `invalid_scope`
   "request exactly one of: citizen, officer".
6. `resource = q.get("resource") or ISSUER`.
7. Insert an `oauth_requests` row keyed by `rid = secrets.token_urlsafe(24)` holding
   `params` (client_id, client_name, redirect_uri, state, code_challenge, scope, resource) and
   `role = scopes[0]`; redirect to `/oauth/login?rid=…`.

Verified enforcement:

| variation | result |
|---|---|
| registered `http://localhost:9999/cb`, request `http://localhost:31337/cb` | **302** accepted (loopback any-port, RFC 8252 §7.3) |
| request `http://127.0.0.1:9999/cb` | **400** — `127.0.0.1` does **not** match a registered `localhost` |
| request `http://[::1]:9999/cb` | **400** |
| request `https://localhost:9999/cb` | **400** (scheme must match) |
| request `http://localhost:9999/other` | **400** (path must match) |
| **request `http://localhost:9999/cb?x=1`** | **400** (query must match exactly) |
| request `https://evil.test/cb` | **400** |
| no `code_challenge` | 302 `error=invalid_request` |
| `code_challenge_method=plain` | 302 `error=invalid_request` |
| `scope=citizen officer` | 302 `error=invalid_scope` |
| `scope=admin` | 302 `error=invalid_scope` |
| `response_type=token` | 302 `error=unsupported_response_type` |
| registered `https://claude.ai/api/mcp/auth_callback`, request with `?x=1` appended | **False** |

`redirect_allowed` (`oauth.py:182-199`) is exact-match, plus a loopback exemption that compares
scheme, hostname, path **and query** but ignores the port. Two interop footguns for MCP clients:
a client that registers `localhost` and calls back on `127.0.0.1` (or vice versa) **fails**,
and any client that appends a parameter to its callback **fails**.

**Step 2a — citizen login (OTP)**, `oauth.py:352-374`. `/oauth/login?rid=…`:

- POST without an `otp` field and with a 10-digit `mobile` → inserts an `otps` row with
  `secrets.randbelow(1000000)`, sends the same OTP SMS as the web form, stores
  `pending_mobile` on the request row, re-renders with the OTP input.
- POST with `otp` → compares the newest OTP for `pending_mobile` using
  **`secrets.compare_digest`** and a `<= OTP_VALIDITY_SECONDS` age check, then sets
  `subject = "citizen:" + mobile` and redirects to `/oauth/consent`.

**There is no check that the mobile belongs to an existing applicant.** Verified: I obtained a
valid token for `citizen:9000000001`, a number with **no application and no `portal_users`
row**. That is necessary (a first-time applicant must be able to sign in) but it means the
`sub` claim asserts only "someone could read an SMS to this number" — and the OTP inbox is
world-readable (§9-D2). There is also no attempt limit on this OTP path either.

**Step 2b — officer login (password)**, `oauth.py:375-381`. Compares `username`/`password`
against `portal.ADMIN_USERNAME` / `portal.ADMIN_PASSWORD` — **the same single departmental
account** — and sets `subject = "officer:" + ADMIN_USERNAME`.

**How the scope is chosen: entirely by the client.** `role` is just `scopes[0]` from the
authorize request (`oauth.py:342`), and it decides which login form the person sees. There is
no server-side notion of who is allowed to ask for `officer` — a public client with no secret
can request `scope=officer` and will be shown the departmental password form. Security rests
solely on knowing `ADMIN_PASSWORD`. Equally, nothing stops a *citizen* client from requesting
`officer`, or an officer-facing client from requesting `citizen`.

**Step 3 — consent**, `oauth.py:399-434`. GET requires the request row to exist **and** have a
`subject`. The screen shows exactly five rows — captured live for the officer flow:

```
Allow this application?
  Application        Audit Probe
  Signed in as       admin (officer)
  It will be able to act as a block officer: see applications in the queue,
                     verify them, record approve/reject decisions
  Valid for          http://mcp.example.test/officer
  Signed in until    8 hours from now, then the application must ask you to sign in again

You can end this earlier at any time from the status portal under Connected applications
(officers: from the admin dashboard). If you did not start this from an application you are
using right now, choose Deny.
                                                          [ Allow ]   [ Deny ]
```

and for a citizen:

```
  Signed in as       9217729489 (citizen)
  It will be able to act for you on the Old Age Pension portal: check eligibility, apply,
                     see and manage your own application
  Valid for          http://mcp.example.test/citizen
  Signed in until    2 hours from now, …
```

Scope descriptions come from `SCOPES` (`oauth.py:54-60`). Note the **`resource` string is shown
raw to the citizen** as "Valid for" — an attacker-chosen value (§6-F3), and meaningless to an
elderly applicant.

`decision != "allow"` → clears `subject` and error-redirects `access_denied`; the request row
is **not deleted**, so the flow can be retried. `decision == "allow"` → inserts an
`oauth_codes` row (code hashed SHA-256, 32 random bytes), **deletes** the `oauth_requests` row,
and redirects with `code`, `iss` and `state`.

The whole authorize→consent flow is driven **only by `rid` in the URL**. See §6-F2 — this is
the most serious OAuth defect.

### E. The token endpoint and the real token I minted

**Client authentication** (`oauth.py:441-446`): if the client has a `secret_hash`, compare
`sha256(form["client_secret"])` with `secrets.compare_digest`; otherwise **allow**. Public
clients are therefore unauthenticated, which is correct for PKCE.

**`authorization_code`** (`oauth.py:478-505`), in order:
`DELETE … RETURNING` makes the code strictly single-use at the database level (good) → client
must match → `redirect_uri` must match **if supplied** (RFC 6749 wants it required when it was
in the authorize request) → age ≤ `CODE_TTL` 300 s → `b64url(sha256(verifier)) == code_challenge`
→ `resource` must match if supplied.

**`refresh_token`** (`oauth.py:506-522`): a single atomic
`UPDATE … SET revoked_at = now() WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > now() RETURNING …`
— rotation and consumption in one statement, so concurrent reuse cannot both succeed. Then
`_issue(..., session_ends=<the original expires_at>)`, so **rotation never extends the session**.

**A real citizen token, end to end.** Registered a client, drove `/oauth/authorize`, read the
OTP from `/__gateway/api/messages?to=9217729489`, consented, exchanged the code with the PKCE
verifier:

```
AUTHORIZE -> 302 /oauth/login?rid=SUIOlCW9Qjkajpyn6h3FPVWdpH_RJpM3
gateway inbox: 'Your Sewa Setu OTP is 317278. Valid for 5 minutes.'
LOGIN     -> 302 /oauth/consent?rid=SUIOlCW9…
CONSENT   -> 302 http://localhost:9999/callback?code=LdfmG0myF_v087qbL-5Js6OS_oFqf5OBpOmIsg217XE
                 &iss=http%3A%2F%2Flocalhost%3A8000&state=st123
TOKEN     -> 200
```

Token response:

```json
{ "access_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6ImE5YTMzYWFi…",
  "token_type": "Bearer",
  "expires_in": 1200,
  "refresh_token": "mwiZvGJFRCWUFaDcw4zFK4QIdCImeSUU29Q8DLYbBgU",
  "scope": "citizen",
  "session_ends": "2026-10-21T06:31:58" }
```

Decoded JWT header and claims:

```json
{ "alg": "RS256", "kid": "a9a33aab5d44d068", "typ": "JWT" }
```

```json
{
  "iss": "http://localhost:8000",
  "sub": "citizen:9217729489",
  "aud": "http://mcp.example.test/citizen",
  "scope": "citizen",
  "role": "citizen",
  "client_id": "ssc_CuEri90WrMnmq2zsOxiWAw",
  "iat": 1792557118,
  "exp": 1792558318,
  "jti": "71137ace11320e0d9a0bda87",
  "kind": "access",
  "session_ends": 1792564318
}
```

`exp - iat = 1200 s` (20 min); `session_ends - iat = 7200 s` (2 h). And the officer token from
the same client:

```json
{
  "iss": "http://localhost:8000",
  "sub": "officer:admin",
  "aud": "http://mcp.example.test/officer",
  "scope": "officer",
  "role": "officer",
  "client_id": "ssc_CuEri90WrMnmq2zsOxiWAw",
  "iat": 1792557118, "exp": 1792558918,
  "jti": "3dd04459656af60e596c194b",
  "kind": "access",
  "session_ends": 1792585918
}
```

`exp - iat = 1800 s` (30 min); `session_ends - iat = 28800 s` (8 h).

**The complete claim set** (`mint_access_token`, `oauth.py:105-121`) is therefore
`iss, sub, aud, scope, role, client_id, iat, exp, jti, kind` plus `session_ends` when a session
applies. **There is no `nbf`, no `typ` beyond the header, no `azp`, no `auth_time`, and
`aud` is a plain string, not an array.**

| claim | value / meaning |
|---|---|
| `iss` | `$PUBLIC_BASE_URL`, trailing slash stripped |
| `sub` | `citizen:<10-digit mobile>` or `officer:<username>` — always `officer:admin` in practice |
| `aud` | **the `resource` parameter verbatim**, or `ISSUER` if none was sent |
| `scope` | `citizen` or `officer` (single value, never a space-separated list) |
| `role` | identical to `scope` — redundant by construction |
| `client_id` | the requesting client, or the literal `admin-issued` for program tokens |
| `exp` | `iat + 1200` (citizen) / `iat + 1800` (officer), **then `min()`-ed with `session_ends`** (`oauth.py:111-112`) — so the last access token of a session is short |
| `jti` | 24 hex chars; **not recorded for access tokens**, so not checkable |
| `kind` | `access` or `program` |
| `session_ends` | absolute session end as a Unix timestamp; **absent on program tokens** |

**Session caps** (`oauth.py:49-52`):

```python
SESSION = {
    "citizen": {"access": 20 * 60, "session": 2 * 3600},   # 2-hour session
    "officer": {"access": 30 * 60, "session": 8 * 3600},   # one working day
}
CODE_TTL = 300
```

`session_ends` is computed **once**, at `_issue` time from the authorization-code grant
(`oauth.py:449-450`), stored as `oauth_refresh_tokens.expires_at`, and passed forward unchanged
on every rotation. Counted from the token exchange, not literally from the consent click
(a negligible difference).

Verified behaviours:

| probe | result |
|---|---|
| refresh once | **200**, new access + new refresh, `session_ends` unchanged (`2026-10-21T06:31:58`) |
| reuse the **old** refresh token | **400** `invalid_grant` "refresh token is invalid, expired or revoked; the person must sign in again" |
| refresh with a **different** `resource` | **400** `invalid_target` "resource differs from the original grant" |
| `POST /oauth/revoke` with the refresh token | **200**, empty body |
| refresh after revoke | **400** `invalid_grant` |
| `POST /oauth/revoke` with `token=total-garbage`, no client auth | **200** |

Rotation is correct and reuse fails. But note the **reuse of a rotated token is not treated as
a breach signal** — RFC 9700 recommends invalidating the whole family; here only that one token
fails, and the attacker's freshly rotated token stays live.

**Revocation gaps, consolidated:**

- `/oauth/revoke` performs **no client authentication whatsoever** (`oauth.py:529-541`) — it
  does not even read `client_id`. Anyone who learns a refresh-token value can revoke it, and
  the endpoint always returns 200 (so it is also a blind oracle-free DoS primitive). RFC 7009
  §2.1 requires client authentication.
- **Access tokens cannot be revoked at all.** Nothing verifies against a denylist, and
  `verify_token` (`oauth.py:124-131`) checks only signature, `aud` and `iss`. So revoking a
  sign-in — or a citizen clicking "End all" — leaves the current access token usable for up to
  20/30 more minutes.
- **Program tokens cannot be revoked at any horizon** (§5-E).
- There is **no introspection endpoint** (RFC 7662), so a resource server has no way to ask.

### F. Defects in the OAuth server

**F1 — `verify_token()` is dead code.** `oauth.py:124-131` is defined, documented as
*"the in-process shortcut"*, and **never called from anywhere**. `grep -rn "verify_token" app/`
returns exactly the one definition. **No route in the portal accepts a Bearer token.** The
entire OAuth server issues credentials that nothing in this codebase consumes — it exists
purely for the resource servers you are about to build.

**F2 — the authorization request is not bound to the browser session.** `_load_request(rid)`
(`oauth.py:289-300`) looks up `oauth_requests` by `rid` alone, with a 900 s age check and **no
reference to the Flask session, no cookie, and no CSRF token**. `/oauth/login` and
`/oauth/consent` both take `rid` from the query string.

Verified exploit: session A (cookies) authenticated as the officer; **session B, a brand-new
`requests.Session` with no cookies at all**, POSTed `/oauth/consent?rid=<A's rid>` with
`decision=allow`:

```
session A logged in, rid = 0MMwtLPK7DArFsWduaKK_U1mqP3z6R1L
session B (no cookies) POSTs consent -> 302 http://localhost:9999/cb?code=8lwVpp-Uaq…&iss=…&state=s
>>> session B obtained an OFFICER token:
{ "iss": "http://localhost:8000", "sub": "officer:admin", "aud": "http://localhost:8000",
  "scope": "officer", "role": "officer", "client_id": "ssc_KWqHfFYGi9hXR25IcajHZA",
  "iat": 1792557169, "exp": 1792558969, "jti": "e588528e21a301d4475e4dc0",
  "kind": "access", "session_ends": 1792585969 }
```

Two attacks follow. **(a) Consent CSRF:** the consent form has no token, so any page a
signed-in person visits can POST `allow` for an attacker's `rid` and `redirect_uri`. **(b) rid
leakage:** the `rid` travels in a URL (Referer headers, browser history, shared kiosk screens,
shoulder-surfing — exactly the Director's "shared phones and kiosks" at 2:14), and anyone who
reads it within 15 minutes can complete the grant. PKCE does not help: the attacker chose the
`code_challenge` in their own authorize request.

The fix is one line of the kind this codebase already knows how to write — stash `rid` in the
Flask session at `/oauth/authorize` and compare — but it is not there.

**F3 — `resource` is completely unvalidated and lands in `aud` verbatim.** `oauth.py:338` is
`resource = q.get("resource") or ISSUER`. Verified: every one of these was accepted and would
become the `aud` claim:

| `resource` | authorize result |
|---|---|
| `not-a-url` | 302 (accepted) |
| `javascript:alert(1)` | 302 (accepted) |
| `http://attacker.test/` | 302 (accepted) |
| 400 × `x` | 302 (accepted) |

RFC 8707 requires an absolute URI with no fragment, and an AS is expected to reject resources
it does not know. Here there is **no allow-list of known resource servers**. The practical
consequences: a resource server **must** compare `aud` to its own canonical URL with an exact
string match (as the README correctly instructs) because the AS offers no guarantee; the value
is echoed unescaped-but-autoescaped into the consent screen's "Valid for" row; and
`varchar(300)` on `oauth_codes.resource` means a longer value will blow up the INSERT with
`StringDataRightTruncation` (**UNVERIFIED** — I stopped at the authorize redirect and did not
complete consent with the 400-char value).

**F4 — no RFC 9728 protected-resource metadata, anywhere.** Probed live:

| path | status |
|---|---|
| `/.well-known/oauth-authorization-server` | **200** |
| `/.well-known/jwks.json` | **200** |
| `/.well-known/openid-configuration` | 404 |
| `/.well-known/oauth-protected-resource` | **404** |
| `/.well-known/oauth-protected-resource/mcp` | **404** |

`grep -rn -i "mcp\|protected.resource\|9728\|resource_server\|bearer" app/` finds **one** hit:
the literal `"token_type": "Bearer"` in the token response (`oauth.py:462`). **The portal does
not expect resource servers to serve RFC 9728 metadata, and contains no reference to MCP at
all** — the only MCP mentions in the repo are in `BRIEF.md` (and in the owner's `plan.md`).

This matters concretely: the MCP authorization spec expects a resource server to return
`WWW-Authenticate: Bearer resource_metadata="…"` on a 401 and to serve
`/.well-known/oauth-protected-resource`, pointing at this AS. **You must write that yourself on
each MCP server** — the portal gives you the AS half only. The good news is that the AS half is
complete: discovery, DCR, CIMD, PKCE S256, `iss` in the response (RFC 9207) and resource
indicators are all present and working, which is most of what an MCP client needs.

**F5 — smaller things.**

- `/oauth/authorize` is **GET-only**; a client that POSTs the authorization request gets 405.
- `state` is optional and never required; `nonce` is unsupported.
- The authorize endpoint accepts a `client_secret_post` client with **no secret**, because
  secrets are only checked at the token endpoint.
- `oauth_requests`, `oauth_codes` and expired `oauth_refresh_tokens` rows are **never garbage
  collected** — expiry is enforced by comparison at read time, so all three tables grow
  forever.
- `_update_request` (`oauth.py:302-309`) builds SQL by interpolating **column names** from
  `**cols` keys: `", ".join("%s = %%s" % k for k in cols)`. Every call site passes literals
  (`subject`, `pending_mobile`), so it is not reachable by an attacker today, but it is an
  injection waiting for a careless caller.
- `_cors` is an `after_app_request` hook, so it applies to the **whole app**, not just the
  blueprint — an easy thing to trip over when adding routes.

---

## 7. EXISTING APIs

### A. The complete route table

Enumerated from the live app with `app.url_map.iter_rules()`:

```
/                                            GET          index
/.well-known/jwks.json                       GET          oauth.jwks
/.well-known/oauth-authorization-server      GET          oauth.as_metadata
/__gateway/                                  GET          gateway_proxy
/__gateway/<path:subpath>                    GET          gateway_proxy
/about                                       GET          about
/ack/<int:app_id>.pdf                        GET          ack_pdf
/admin                                       GET,POST     admin_login
/admin/application/<int:app_id>              GET          admin_view
/admin/applications                          GET          admin_list
/admin/approve/<int:app_id>                  POST         admin_approve
/admin/dashboard                             GET          admin_dashboard
/admin/reject/<int:app_id>                   POST         admin_reject
/admin/tokens                                GET,POST     oauth.admin_tokens
/application/<int:app_id>                    GET          view_application
/application/<int:app_id>/withdraw           POST         withdraw_application
/apply                                       GET,POST     apply
/declaration                                 GET,POST     declaration
/form/<int:step>                             GET,POST     form_step
/oauth/authorize                             GET          oauth.authorize
/oauth/consent                               GET,POST     oauth.consent
/oauth/login                                 GET,POST     oauth.login
/oauth/register                              POST         oauth.register
/oauth/revoke                                POST         oauth.revoke
/oauth/token                                 POST         oauth.token
/static/<path:filename>                      GET          static
/status                                      GET,POST     status_login
/status/connections                          GET,POST     oauth.citizen_connections
/status/reset                                GET,POST     reset_password
/upload                                      GET,POST     upload
/verify                                      GET,POST     verify
```

31 rules. **Nothing is missing from this list** — there is no hidden API blueprint.

### B. JSON routes an MCP server could call

**Short answer: there are four, and only one of them returns application data — none at all.**

| route | returns | auth required | usable? |
|---|---|---|---|
| `/.well-known/oauth-authorization-server` | AS metadata JSON | **none** | yes, for OAuth discovery |
| `/.well-known/jwks.json` | JWKS JSON | **none** | **yes — this is how your MCP servers verify tokens** |
| `/oauth/register`, `/oauth/token`, `/oauth/revoke` | OAuth JSON | public-client: none | yes, for the auth flow |
| `/__gateway/api/messages?to=<mobile>` | the SMS inbox as JSON (proxied) | **none** | yes, but it is a test fixture and a security hole (§9-D2) |
| `/__gateway/api/send` | — | — | **no** — `gateway_proxy` is `GET`-only (`app.py:231-232`) and forwards with `requests.get`, so the send API is not reachable through the portal |
| `/ack/<id>.pdf` | `application/pdf` | session cookie (`admin`, or matching `portal_mobile`) | binary, cookie-auth only |
| everything else | HTML | session cookie | no |

So:

- **No route accepts an `Authorization: Bearer` header.** `verify_token` is never called
  (§6-F1). The tokens the portal mints are useless against the portal itself.
- **No JSON endpoint exposes applications, statuses, the officer queue, or the audit log.**
  Every piece of business data is reachable only as server-rendered HTML behind a session
  cookie.
- **There is no document-fetch route**, so no API — present or future — can serve the age proof
  without one being written.

The practical conclusion: **you are not wrapping an existing API, you are writing the API.**
Your two MCP servers must talk to Postgres (ideally through the portal's own Python functions,
see §7-C) and verify the portal's JWTs out-of-band via JWKS. Scraping the HTML with a session
cookie is the only alternative and would bypass `validate_application` on write paths, which
the Director's 1:58 instruction rules out.

### C. Functions reusable as a service layer

All in `app/app.py`, all pure-Python with an explicit cursor passed in — the module is
noticeably better factored for reuse than the routes suggest.

| function | line | signature | commits? | notes |
|---|---|---|---|---|
| `validate_application` | 136 | `(data: dict, doc_path: str) -> (errors: list[str], cleaned: dict)` | no DB at all | **the rule engine.** Pure, no I/O, never raises. Safe to call from anywhere |
| `create_application` | 188 | `(cur, mobile, cleaned) -> (id, application_no)` | **no — caller commits** | inserts the application, creates the `portal_users` row if absent, writes the `SUBMIT` audit row |
| `active_application` | 180 | `(cur, mobile) -> (id, application_no, status) \| None` | read-only | the one-active-application check. **Must be paired with `create_application` atomically** (§9-A2) |
| `write_audit` | 112 | `(cur, app_id, action, actor, note="")` | **no — caller commits** | the audit insert. `actor` is a free-text 50-char field, so an MCP layer can write a richer actor than `admin:admin` |
| `parse_dob` | 125 | `(raw) -> date \| None` | — | `%d/%m/%Y` only |
| `age_on` | 132 | `(dob, on) -> int` | — | pure |
| `now_ist` | 22 | `() -> naive datetime` | — | IST wall clock |
| `deadline_remaining` | 101 | `() -> int \| None` | — | whole hours to the deadline |
| `new_application_no` | 108 | `() -> str` | — | the colliding generator (§4-D) |
| `sanitize` | 81 | `(value, maxlen=100) -> str` | — | strip + truncate |
| `hash_password` | 89 | `(p) -> str` | — | bare SHA-256 |
| `send_sms` | 93 | `(mobile, text)` | — | fire-and-forget POST, swallows errors |
| `get_db` | 71 | `() -> psycopg2 connection` | — | a **fresh connection every call**, no pool |
| `generate_acknowledgment` | 407 | `(cur, app_id) -> bytes` | read-only | the PDF; breaks on non-latin-1 names (§9-B6) |
| `oauth.verify_token` | 124 | `(token, audience) -> claims \| None` | reads `oauth_keys` once | **the in-process token check you want** — but see the import hazard below |
| `oauth.mint_access_token` | 105 | `(subject, role, scope, audience, client_id, ttl=None, kind="access", session_ends=None)` | reads/writes `oauth_keys` on first call | |
| `oauth.public_jwks` | 98 | `() -> dict` | reads `oauth_keys` | |

**The deemed-approval job shares nothing.** `scripts/deemed_approval.py` does not import
`app.py`; it re-reads `app.ini` and opens its own connection. So its SLA arithmetic is a second,
independent implementation — if you change `sla_days` semantics in one place you must change both.

#### Importability: three real hazards

**1. Import order matters — `import oauth` alone crashes.** `app.py:673` imports `oauth`, and
`oauth.py:42` does `import app as portal`. Verified inside the container:

```
>>> import oauth
ImportError: cannot import name 'oauth' from partially initialized module 'oauth'
             (most likely due to a circular import) (/app/oauth.py)
```

```
>>> import app as p      # OK
>>> import oauth         # OK, now that app is in sys.modules
```

**You must `import app` first.** It works that way round only because `app.py` defers the
blueprint import to the very bottom of the file.

**2. Side effects at import time** (verified by introspection after `import app`):

| effect | detail |
|---|---|
| `configparser` reads `app/config/app.ini` | `app.py:34-35`. **Silent if the file is missing** — `config.read()` does not raise, so the next `config.get` raises `NoSectionError` instead. The path is relative to `app.py`, so the module must be importable from its own directory |
| a `Flask` app object is constructed | `app.py:37`. Harmless but means `import app` costs you a Flask instance |
| `SCHEME_DEADLINE`, `MIN_AGE`, `SLA_DAYS`, `UPLOAD_DIR`, `OTP_VALIDITY_SECONDS`, `SMS_GATEWAY_URL` are frozen | `app.py:49-55`. **Config changes need a process restart** |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` are frozen from the environment | `app.py:42-43` |
| a log directory and file handler are created | `app.py:59-67` — `os.makedirs("/var/log/sewasetu")` plus a `FileHandler`. Wrapped in `try/except Exception: pass`, so it degrades quietly if the path is unwritable |
| **no database connection is opened** | confirmed: `get_db` is lazy. Importing `app` does *not* require Postgres to be up |

**3. No Flask app context is needed for the service layer.** `validate_application`,
`create_application`, `active_application`, `write_audit`, `parse_dob`, `age_on` and
`generate_acknowledgment` touch neither `request`, `session`, `flash` nor `url_for`. Verified: I
called all of them directly from a bare `python -` inside the container with no request context
and no errors. The route functions obviously do need one. `send_sms` uses `app.logger` only in
its exception path, so it is safe outside a context too.

`oauth.signing_key()` **does** hit the database on first call and then caches in
`oauth._KEY_CACHE` per process — verified: `_KEY_CACHE` goes from `[]` to `['kid', 'priv']`.
`verify_token` calls it, so your first token verification needs DB connectivity; after that it
is pure crypto. **Better practice for a separate MCP process: fetch `/.well-known/jwks.json`
over HTTP and verify with PyJWT's `PyJWKClient`,** so the MCP server never needs the portal's
private key or its database credentials for auth.

#### Connection handling

`get_db()` opens a brand-new `psycopg2` connection per call with no pooling, and the routes
follow a rigid `conn = get_db(); cur = conn.cursor(); …; cur.close(); conn.close()` shape — often
**twice in one request** (e.g. `status_login` at `app.py:447-461`). There is no
`try/finally`, so **any exception leaks the connection** until garbage collection. With 4
gunicorn workers against a default `max_connections = 100` this is survivable; a long-lived
MCP server doing the same per tool call is not. Use a pool (`psycopg2.pool`) or a single
long-lived connection with explicit transactions, and wrap everything in `try/finally`.

Also note: psycopg2 opens transactions implicitly, and several read-only routes never commit or
roll back — they just `close()`. That is fine for reads but means **an idle-in-transaction
connection is easy to create** if you hold connections open.

#### The pattern to copy for a write

This is what the web form does, and what an MCP write tool must do — with the one fix noted:

```python
errors, cleaned = validate_application(data, doc_path)
if errors:
    return {"ok": False, "errors": errors}

conn = get_db(); cur = conn.cursor()
try:
    # FIX: the portal does not do this, and that is the race in §9-A2.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (mobile,))
    existing = active_application(cur, mobile)
    if existing:
        return {"ok": False, "existing": {"application_no": existing[1], "status": existing[2]}}
    new_id, app_no = create_application(cur, mobile, cleaned)   # writes the SUBMIT audit row
    conn.commit()
finally:
    cur.close(); conn.close()

send_sms(mobile, "...")        # after the commit, as the portal does
```

---

## 8. SMS GATEWAY

`smsgw/app.py`, 94 lines, `Flask 2.2.5`, run as `python app.py` (the **development** server) on
port 8025, `expose`d on the compose network only. The portal reaches it at
`http://smsgw:8025` (`app/config/app.ini:13`).

### A. How the portal sends

`send_sms(mobile, text)` (`app.py:93-99`):

```python
requests.post(SMS_GATEWAY_URL + "/api/send", json={"to": mobile, "text": text}, timeout=5)
```

Synchronous, inside the request, 5 s timeout, **all exceptions logged and swallowed** — so a
dead gateway never fails a submission, and the citizen simply never gets their message.
`deemed_approval.py:58-61` does the same thing inline with its own `requests.post`.

### B. The JSON API

**`POST /api/send`** (`smsgw/app.py:42-58`). Accepts JSON (`force=True, silent=True`) or form
data; requires non-empty `to` and `text`.

```
→ {"to": "9000000011", "text": "Your Sewa Setu OTP is 259461. Valid for 5 minutes."}
← 200 {"status": "queued", "id": 7}
← 400 {"status": "error", "reason": "to and text required"}
```

**`GET /api/messages?to=<mobile>`** (`smsgw/app.py:61-76`). Omitting `to` returns **every**
message ever sent. Verified live:

```json
{"messages": [
  {"id": 2, "to": "9217729489",
   "text": "Your Sewa Setu OTP is 317278. Valid for 5 minutes.",
   "delivered": true, "sent_at": 1792557112.985, "delivery_at": 1792557113.985}
]}
```

`text` is **`null` until the message is "delivered"**, with `delivered: false` and the
`delivery_at` epoch telling you when to look again. That is the one piece of real API
behaviour to code against: *poll until `delivered`*, do not assume the first read has the OTP.

**`GET /`** (`smsgw/app.py:79-90`) is an HTML console listing the **last 100** messages newest
first, auto-refreshing every 5 s via `<meta http-equiv="refresh" content="5">`, showing
`(in transit)` for undelivered ones.

Both are reachable through the portal at `/__gateway/…` via `gateway_proxy`
(`app.py:231-244`), which forwards query strings and the upstream `Content-Type` with a 5 s
timeout and returns `502 "SMS gateway unreachable: …"` on failure. **The proxy is GET-only**, so
`/api/send` is not reachable from outside the compose network.

### C. Latency

```python
DELAY_MIN, DELAY_MAX = 1, 4          # smsgw/app.py:16-17
"delivery_at": now + random.randint(DELAY_MIN, DELAY_MAX)
```

`/api/send` returns **immediately** with `queued`; the message becomes readable
`random.randint(1, 4)` seconds later — an integer, so 1, 2, 3 or 4 s. Delivery is purely
computed at read time (`now >= m["delivery_at"]`); there is no background worker and no
possibility of failure or reordering. **In my probes a 5 s sleep was always sufficient.**

For an assistant this is the single most important timing fact in the system: after requesting
an OTP you must **wait and poll for up to ~4 s**, and an eager read returns `text: null` rather
than an error. A naive single-shot read will look like "the OTP never arrived".

### D. Limitations that will bite

- **`MESSAGES` is a plain in-process Python list** (`smsgw/app.py:13`) with no persistence. A
  container restart loses every message — including an OTP a citizen is mid-way through using.
- The list grows **without bound**; only the console truncates (to 100), not the API.
- `python app.py` is Flask's dev server — single process. Fine here, and in fact necessary:
  under gunicorn with multiple workers the in-memory list would be per-worker and OTP reads
  would intermittently miss.
- **No authentication on either API, and no sender identity** — see §9-D2. Omitting `to`
  dumps the entire message history of every citizen.
- No delivery failures, no DLRs, no rate limits, no per-number throttling, no unicode/length
  handling — so nothing in the portal is tested against a real carrier's behaviour.
- `/api/messages` has no ordering guarantee beyond insertion order and no pagination.

---

## 9. RISKS, BUGS AND TRAPS

Severity is my judgement for *this* project: **[BLOCKER]** will break the Director's test,
**[HIGH]** will produce wrong data or a security incident, **[MED]** will confuse an assistant,
**[LOW]** is cosmetic or latent.

### A. Things that will break the demo

**A1 [BLOCKER] — the boot-time deemed-approval job empties the officer queue.**
`docker-compose.yml:34-37` runs `deemed_approval.py` before cron. The seed's 700 PENDING rows
were submitted 2026-09-16…09-30; today is 2026-10-21, so **all of them are past the 15-day
SLA** and are auto-approved within ~141 ms of first boot. Measured: `PENDING = 0` out of
100,001 rows; 700 audit rows written at `2026-10-20 10:10:47`.

The Director's test is *"connect my officer's assistant and try to approve it"* (2:46). With an
empty queue, an officer tool has nothing to list. Worse, `docker compose down -v && up` —
the obvious reset — reproduces the wipe every time.

Mitigations, in order of preference: (a) have the MCP/eval harness create its own pending
applications through `create_application`, so the demo never depends on the seed; (b) shift
`submitted_at` forward on a subset of rows before first boot; (c) start the stack with
`docker compose up -d db app smsgw` and omit `scheduler` until you want a sweep. Do **not**
rely on there being a pending queue.

**A2 [BLOCKER] — the one-active-application rule is not race-safe, and I broke it.**
`handle_submission` (`app.py:382-392`) is check-then-act with no lock, no unique index and no
`SELECT … FOR UPDATE`:

```python
existing = active_application(cur, mobile)     # app.py:383
if existing: ... return                        # app.py:384-390
new_id, app_no = create_application(cur, mobile, cleaned)   # app.py:391
conn.commit()
```

Four gunicorn workers make this trivially reachable. Two measured outcomes:

*First attempt* — mobile with **no** `portal_users` row, 2 concurrent POSTs:

```
thread 0 -> 500  (psycopg2.errors.UniqueViolation: duplicate key value violates
                  constraint "portal_users_pkey", Key (mobile)=(9000000012) already exists)
thread 1 -> 200  app_no=SSP26759556
```

`portal_users_pkey` accidentally serialises them — but the loser gets a **raw HTTP 500**, not
"you already have an application". An assistant will read that as a transient failure and retry.

*Decisive attempt* — same mobile, now **with** a `portal_users` row (i.e. anyone re-applying
after a withdrawal or rejection, which is the documented happy path), 3 concurrent POSTs:

```
thread 0 -> 200 app_no=SSP26184691
thread 1 -> 200 flash='Application SSP26184691 (PENDING) already exists…'
thread 2 -> 200 app_no=SSP26801643
```

```sql
SELECT mobile, count(*) n FROM applications
WHERE status IN ('PENDING','APPROVED','DEEMED_APPROVED') GROUP BY mobile HAVING count(*)>1;
-- 9000000012 | 2
```

**Two committed PENDING applications for one mobile.** `create_application` skips the
`portal_users` INSERT when `count(*) != 0` (`app.py:209-212`), so the one accidental guard
disappears exactly when re-applying — the case the README advertises. Ids 100015 and 100016 are
still in the database as evidence.

For the MCP build this is the highest-value fix: take a lock before the check. A
`pg_advisory_xact_lock(hashtext(mobile))` in the same transaction (see §7-C) costs one line; a
partial unique index would be better but requires DDL:

```sql
CREATE UNIQUE INDEX CONCURRENTLY idx_one_active_per_mobile
  ON applications (mobile) WHERE status IN ('PENDING','APPROVED','DEEMED_APPROVED');
```

**A3 [HIGH] — `datetime.now()` vs `now_ist()`: a 5h30m split brain.** Measured in the container:

```
now_ist()      = 2026-10-21 10:04:17
datetime.now() = 2026-10-21 04:34:17     <-- skew 5:29:59.999997
```

`now_ist()` (`app.py:22-24`) governs the age check (`app.py:168`), the scheme deadline
(`app.py:103`, `:172`) and `deadline_remaining()`. **Every database write uses
`datetime.now()`** — `submitted_at` and the SUBMIT audit (`app.py:204`, `:114`), `decided_at`
(`app.py:502`, `:648`), `otps.created_at` (`app.py:272`), every OAuth timestamp, and the whole
of `deemed_approval.py`. The SLA arithmetic stays correct because both sides of that comparison
are UTC, but:

- Every timestamp shown to a citizen or an officer is **5h30m earlier** than the IST time the
  portal claims to keep. My 10:05 IST submission displays as `2026-10-21 04:35` on
  `application.html:14` and in the acknowledgment PDF.
- "Age at submission" recomputed from `(submitted_at, dob)` can come out 59 for an application
  that legitimately validated at 60 — the likely origin of §2-F-Q6's 2,585 under-60 approvals.
- `new_application_no()` takes its year prefix from `datetime.now()` (`app.py:109`), so for
  5½ hours either side of New Year the prefix is a year behind the portal's own clock.

Any tool that reports a date must decide, once, whether it is speaking UTC or IST and say so.
See §10-Q4.

### B. Correctness bugs

**B1 [HIGH] — application numbers collide, by design.**
`"SSP" + %y + random.randint(100000, 999999)` (`app.py:108-109`) with **no unique constraint and
no retry**. 58,562 `SSP26*` numbers already exist in a 900,000 space:

```sql
SELECT count(*), round(100.0*count(*)/900000.0,3) FROM applications WHERE application_no LIKE 'SSP26%';
-- 58562 | 6.507
```

**6.5% of new applications will be issued someone else's application number.** Nothing detects
it: `application_no` has no index at all, so a lookup by number is also a 100k-row sequential
scan and would return two rows. If an MCP tool lets a citizen quote their application number,
this *will* surface. Generate the number yourself with a collision check, or add a unique index.

**B2 [HIGH] — `?page=0` and `?page=abc` are 500s.** `app.py:601` is
`page = int(request.args.get("page", 1))`, unguarded, feeding
`OFFSET (page - 1) * 50` (`app.py:615`). Verified: `page=0` → 500 (negative OFFSET), `page=-1`
→ 500, `page=abc` → 500, `page=1.5` → 500. A 0-indexed guess — the natural one for a program —
crashes the officer list.

**B3 [MED] — status filtering is silently case-sensitive and unvalidated.**
`?status=pending` → 200 with **0 rows**; `?status=NONSENSE` → 200 with 0 rows. An assistant that
lower-cases a status, or invents one, is told the queue is empty rather than that it asked
wrongly. The mobile search additionally **ignores `status` entirely and has no `LIMIT`**
(`app.py:607-610`).

**B4 [MED] — a rejection needs no reason.** `request.form.get("note", "")` (`app.py:669`), no
check. The template only hints at one (`admin_view.html:28`). All 7,000 seeded rejections carry
one of four canonical reasons, so the data sets an expectation the code does not. This
contradicts the Director at 2:30 directly.

**B5 [MED] — unvalidated fields with tight columns crash the INSERT.** `gender` (`varchar(10)`),
`marital_status` (`varchar(20)`), `village` (`varchar(100)`) and `husband_name` (`varchar(100)`)
pass `validate_application` at **any** length — only `applicant_name` goes through `sanitize()`.
Verified in-process:

```
village 300 chars   -> validate: NONE  -> INSERT RAISED StringDataRightTruncation:
                       value too long for type character varying(100)
gender  40 chars    -> validate: NONE  -> INSERT RAISED StringDataRightTruncation:
                       value too long for type character varying(10)
```

`handle_submission` has no `try/except`, so this is an **unhandled 500 after the citizen has
filled in the entire form**. An MCP server must length-check these itself.

**B6 [MED] — the acknowledgment PDF cannot print Assamese names.**
`generate_acknowledgment` uses core Helvetica (latin-1 only) and swallows per-cell failures
(`app.py:425-431`). Verified by decompressing the PDF text streams:

```
ack for id 1     -> ['Applicant Name', 'Sewali Gogoi', 'Mobile', '9217729489']
ack for id 99001 -> ['Applicant Name', '?',            'Mobile', '9080623760']
                     (actual name: খগেন ডেকা)
```

**300 applicants** get a `?` where their name should be. The fix is a TTF with
`pdf.add_font(..., uni=True)`. Note the `except` writes `?` into the *value* cell only, so the
layout survives — it fails quietly, which is worse.

**B7 [MED] — `/status/reset` picks an arbitrary DOB.**
`SELECT dob FROM applications WHERE mobile = %s LIMIT 1` (`app.py:546`) with **no `ORDER BY`**.
For a mobile with several applications Postgres may return any of them, so the password can be
reset to an *older* application's DOB while the login hint says "your date of birth". Also:
`portal_users` rows are created only when absent (`app.py:209-212`), so a second application
with a corrected DOB never updates the password.

**B8 [LOW] — any filename containing `/` is a 500.** No `secure_filename()`; the name is only
lower-cased (`app.py:342`). Verified: `../traversal-probe.png` →
`FileNotFoundError: /var/sewasetu/uploads/9000000011_../traversal-probe.png`. The `<mobile>_`
prefix means a leading `../` cannot actually escape (it would need a directory named
`9000000011_..`), so **I could not achieve traversal here** — but it is a crash, and in a
deployment where `UPLOAD_DIR` has subdirectories it would be an escape. Related: the path is
`<mobile>_<filename>`, so **re-uploading silently overwrites a file an older application still
references**, and `AGE.PNG` collides with `age.png`.

**B9 [LOW] — the 5 MB limit is checked after reading the body.** `content = f.read()` precedes
the size check (`app.py:341-347`) and `MAX_CONTENT_LENGTH` is unset, so an arbitrarily large
upload is buffered in memory first. Four workers; easy memory exhaustion.

**B10 [LOW] — the deemed-approval audit backfill is time-windowed, not id-based.** §3-E2:
`RETURNING` yields `application_no, mobile` but not `id`, so the audit rows are found with
`decided_at >= now() - 1 minute`. An UPDATE slower than 60 s loses audit rows; a re-run inside
60 s duplicates them. The two `datetime.now()` calls (`:46`, `:50`) are independent reads.

**B11 [LOW] — 14 applications were decided before they were submitted** (§2-F-Q15), all
withdrawals, by up to 6h20m. Clamp any "time to decision" at zero.

**B12 [LOW] — `_update_request` interpolates column names into SQL.**
`oauth.py:302-309`: `", ".join("%s = %%s" % k for k in cols)`. Not reachable today (all call
sites pass literals) but an injection waiting for a careless caller.

**B13 [LOW] — no `/admin/logout`, and `logged_in` is shared.** `admin_login` sets both
`session["admin"]` and `session["logged_in"]` (`app.py:571-573`), the same key the citizen
portal uses. There is no route to clear either. An admin who then logs into the status portal
holds both identities at once.

### C. Inconsistencies between code, docs and data

**C1 [HIGH] — the IFSC `UTBI0PUR2819`.** 16,576 live rows (16.6%), 13,732 already APPROVED,
**fail the portal's own validator** (12 chars vs the required 11). Verified both in SQL and by
calling `validate_application` directly. A citizen re-applying who copies the IFSC off their own
approved application is refused. This looks deliberately planted.

**C2 [HIGH] — every seeded application has an empty `doc_path`** (100,000 of 100,001), yet
`validate_application` requires one. 100% of the historical corpus would be rejected today, and
an officer tool asking "is the age proof attached?" answers "no" for the entire dataset.

**C3 [HIGH] — the audit log uses two different verbs and two different actor formats for
withdrawal.** Code writes `WITHDRAW` / `applicant:<mobile>` (`app.py:504`); the seed's 400 rows
say `WITHDRAWN` / `admin:APPLICANT`. Verified in §2-F-Q16. Match on both or show gaps.

**C4 [MED] — `about.html` promises things nothing checks**: *"residents of Purvanchal"* (no
residency field at all), *"One application per eligible citizen"* (enforced per mobile, so
shared phones under-count and two SIMs over-count), and a document type (never recorded).
`index.html:21` says *"JPG or PDF"* while the code also accepts PNG and `jpeg`.

**C5 [MED] — `deemed_approval.py:9` says "cron, 02:00 daily"**; the container is UTC, so it is
**07:30 IST**. And `app.py:23` claims the portal's clock is IST, which is true only of
`now_ist()` callers (§A3).

**C6 [MED] — deemed approval does not mean "15 days elapsed".** 9,000 of 9,700 seeded rows were
granted at 14d 08:01–14d 17:00 — a cron-day early (§2-F-Q13). The 700 swept at boot are 19–34
days. **Never infer the rule from the data; compute `submitted_at + 15d`, rounded up to the
next 02:00 UTC.**

**C7 [MED] — `app.py:118-123` tells you to go through `validate_application` and
`create_application`, but `validate_application` omits the active-application check.** Following
the comment literally is insufficient (§3-A4).

**C8 [LOW] — `husband_employer` is a dead column** (0 of 100,001 rows set; forced to `""` at
`app.py:145`), and **11,942 male widowers** have nowhere to record a late spouse because the
only field is labelled "Late Husband's Name" and is shown only for `Widowed`.

**C9 [LOW] — `gender` offers `Other` in the form** (`form_step1.html:15`) but **no row in the
data uses it**, and the value is unvalidated anyway.

**C10 [LOW] — every seed submission falls in 09:00–17:59 UTC** = 14:30–23:29 IST (§2-F-Q15).
Either the generator wrote IST values into UTC columns, or it had the wrong idea of office
hours. Symptomatic of C/A3 either way.

### D. Security holes

**D1 [HIGH] — the Flask signing key is committed in cleartext.**
`secret_key = ssp-prod-key-2023-donotshare` (`app/config/app.ini:12`), used at `app.py:38`
unless `$SECRET_KEY` is set — and `docker-compose.yml` **does not set it**. Verified live:
`app.secret_key == 'ssp-prod-key-2023-donotshare'`. Anyone with the repo can forge a session
cookie, including `{"admin": True, "admin_user": "admin"}`, and approve applications without
ever knowing `ADMIN_PASSWORD`. **Set `SECRET_KEY` in the environment before you deploy
anything.** (`app/config/app.ini:9` also commits `sewasetu123` as the DB password.)

**D2 [HIGH] — the OTP inbox is world-readable on the public port.**
`/__gateway/api/messages?to=<mobile>` has **no authentication**, and `gateway_proxy`
(`app.py:231-244`) publishes it on port 8000. Verified:

```
GET /__gateway/api/messages?to=9217729489
200 {"messages":[{"delivered":true,"text":"Your Sewa Setu OTP is 317278. …","to":"9217729489"}]}
GET /__gateway/      ->  200, the console HTML contains OTP text
```

Omitting `to` returns **every message ever sent**. Combined with the fact that the OAuth citizen
login accepts **any** 10-digit number (§6-D), this is complete citizen impersonation: request an
OTP for any mobile, read it from the public inbox, consent, and hold a `citizen:<that mobile>`
token. I did exactly this for `9000000001` (no application) and `9217729489` (a real applicant).

It is documented as a simulation convenience in the README, and in a sealed demo it is
harmless. On a **public VM for the Director's test** it is not: anyone who finds the URL can act
as any citizen. Put `/__gateway/` behind the admin session or an IP allow-list before deploying.

**D3 [HIGH] — no rate limiting or lockout anywhere.** Verified:

| probe | result |
|---|---|
| 12 wrong status-portal passwords | all **200**, 0.2 s total, **no lockout** |
| 15 wrong OTPs in a row | all **200**; the **correct OTP still worked afterwards** |
| admin login | no lockout, non-constant-time comparison |
| `/oauth/register` | unauthenticated, unlimited |
| `/status/reset` | no proof of ownership; resets any mobile's password |

A 6-digit OTP with unlimited attempts is ~10⁶ guesses with no cost. The status-portal password
is an 8-digit DOB — for a 60-to-90-year-old, ~11,000 plausible values — unsalted SHA-256, with
the rule printed in the failure message and in the submission SMS. The only brute-force control
in the whole portal is the single-sum captcha on `/apply`, which a program solves by reading it.

**D4 [HIGH] — no CSRF protection on any state-changing route.** There is no CSRF token in any
template and no `SameSite`/`Referer`/`Origin` check. Verified: a bare cross-site POST carrying
only the session cookie **approved application 100012** and logged the note `csrf`. The same
applies to `/admin/reject`, `/application/<id>/withdraw`, `/oauth/consent` and
`/admin/tokens` (which would mint an officer token).

**D5 [HIGH] — the OAuth authorization request is not session-bound** (§6-F2). A cookie-less
client completed another session's consent and received a full **officer** token. Both a consent
CSRF and a `rid`-leakage attack — and `rid` travels in a URL, on the shared phones and kiosks
the Director specifically calls out.

**D6 [HIGH] — program tokens are unrevocable** (§5-E). 365-day officer JWTs; the schema's
`revoked_at` is never written, the "End now" button on that page touches a different table, and
nothing checks `jti`. A leak can only be contained by rotating `oauth_keys`, which kills every
other token too.

**D7 [MED] — access tokens survive revocation.** `verify_token` checks signature, `aud` and
`iss` only. Ending a sign-in — or a citizen pressing "End all" — leaves the live access token
valid for up to 20 min (citizen) or 30 min (officer). Your resource servers should additionally
check `oauth_refresh_tokens.revoked_at` for the subject, or accept the window.

**D8 [MED] — `/oauth/revoke` has no client authentication** (`oauth.py:529-541`); it does not
even read `client_id`, and always returns 200. Contrary to RFC 7009 §2.1.

**D9 [MED] — `resource` is unvalidated and becomes `aud` verbatim** (§6-F3), including
`javascript:alert(1)` and 400-char strings. **Your MCP servers must compare `aud` to their own
canonical URL with an exact string match** — the AS provides no guarantee at all. The raw value
is also shown to the citizen on the consent screen as "Valid for".

**D10 [MED] — CIMD bypasses the redirect-URI scheme checks and is an SSRF primitive**
(§6-C). A metadata document may declare `http://evil.example.com/cb`, which `/oauth/register`
would refuse. And `load_client` will fetch any `https://` or `http://localhost` URL from inside
the app container, with no size or redirect limit.

**D11 [MED] — the RSA private key is stored unencrypted in Postgres** (`oauth_keys.private_pem`),
with no rotation path and exactly one key. Anyone with DB read access can mint officer tokens.

**D12 [LOW] — plaintext OTPs accumulate forever.** `otps` is never pruned and has no index on
`mobile` (13 rows now; 2 were 18 hours old when I started). Live secrets at rest.

**D13 [LOW] — `Access-Control-Allow-Origin: *` on `/oauth/*` and `/.well-known/*`**
(`oauth.py:165-172`), including `/oauth/token` and `/oauth/revoke`, applied app-wide via
`after_app_request`. Credentials are not allowed so it is not directly exploitable, but any web
page can drive those endpoints.

**D14 [LOW] — PII on display.** `application.html` and the acknowledgment PDF both show the full
bank account and the DOB — and the DOB **is** the status-portal password. Any party who sees one
application can log in as that citizen.

### E. Specifically what will trip up an AI assistant

**For a citizen-facing assistant:**

1. **ISO dates are rejected outright.** `parse_dob` accepts `%d/%m/%Y` only. `1950-03-15` →
   `None` → *"date of birth must be given as DD/MM/YYYY"*. A model's default date format fails.
   Normalise in your tool schema; never pass the user's string through.
2. **A future DOB gets the wrong error.** `01/01/2030` → *"applicant must be 60 years of age or
   above"*, not "that date is in the future". An assistant will loop trying to explain the age
   rule for a typo.
3. **An age-proof file is mandatory and there is no way to produce one in conversation.** A
   chat-only assistant literally cannot satisfy rule 7. This is the hardest product question in
   the brief — see §10-Q3.
4. **The IFSC a citizen reads off their own approved application may be rejected** (C1,
   16,576 rows). Expect it, and say something better than "invalid IFSC".
5. **`block` is spelling-exact; `village` accepts anything.** One rejects helpfully with the
   full list; the other silently files an unlocatable application. Validate `village` against
   the 19 known values and their block (§2-F-Q15) yourself.
6. **Nothing tells the citizen the outcome.** No SMS on approve or reject (§4-E). A follow-up
   tool must poll; the citizen cannot be notified by the portal.
7. **One active application per *mobile*, not per person.** On a shared phone the second person
   in a household cannot apply at all, and the error names the *first* person's application
   number — a privacy leak between family members and a confusing dead end.
8. **Timestamps are UTC while the portal claims IST** (A3). "Submitted at 04:35" for a 10:05 IST
   submission; "your 15 days are up on…" needs the §2-F-Q13 arithmetic, not naive addition.
9. **OTP delivery takes 1–4 s and an early read returns `text: null`, not an error** (§8-C).
   Poll; do not single-shot.
10. **A 2-hour cookie session holds the whole draft** (§4-B). There is no draft row, so a
    conversation that outlives it loses everything with no server-side trace. Keep your own
    state and submit in one shot.
11. **Retrying a submission can create a duplicate** (A2), and the loser of the race can be a
    bare 500. Make writes idempotent on your side with a lock plus an existence re-check.
12. **`gender`/`marital_status`/`village` over-long values produce a 500 after the whole form**
    (B5). Length-check before calling.

**For an officer-facing assistant:**

13. **The queue is empty on a fresh stack** (A1). Build the demo so it creates its own work.
14. **`page=0` is a 500 and a lower-case status silently returns nothing** (B2, B3).
15. **The age proof cannot be viewed.** No route serves `doc_path` (§4-C), yet the two most
    common rejection reasons are about the document. An officer tool must not claim the officer
    "reviewed" it, and should not invent a verdict about a file it cannot read.
16. **Approving does not re-check eligibility** (§3-E3, §5-B). The assistant is the last line of
    defence: 2,585 under-60 approvals already exist. The Director's hard line at 2:09 —
    *"The assistant must never get anyone a pension the counter or paper form would not"* —
    means your officer tool should surface eligibility warnings, not silently approve.
17. **There is one officer identity and no jurisdiction** (§5-D). `decided_by` is always
    `admin`; `sub` is always `officer:admin`. "Recorded against her name" (2:30) and "a subset
    of blocks" (1:52) cannot be expressed in the portal — only in your layer, and only in the
    free-text `audit_log.actor` field. See §10-Q1/Q2.
18. **A rejection with no reason is accepted** (B4). Require one in the tool; offer the four
    canonical strings from §2-F-Q16.
19. **No SMS on decision** (§4-E) — an officer assistant that says "the applicant has been
    notified" is lying.
20. **The audit trail uses two verbs for withdrawal** (C3). Match `WITHDRAW` and `WITHDRAWN`.
21. **`/admin/applications?mobile=…` is unbounded and ignores the status filter** (B3). Do not
    hand its output straight to a small model.

### F. Things that look deliberately planted

Judgement, not fact — but each is too neat to be accidental:

- **`UTBI0PUR2819`** — exactly one of six IFSC codes, exactly one character too long, on
  exactly 16.6% of rows, 13,732 of them already approved (C1).
- **Every seeded `doc_path` is empty** while the validator makes the document mandatory (C2).
- **The pending queue sits exactly in the 15 days before the snapshot date**, so any boot after
  ~2026-10-15 destroys it (A1).
- **`secret_key = ssp-prod-key-2023-donotshare`** committed, with `$SECRET_KEY` supported but
  deliberately absent from `docker-compose.yml` (D1).
- **The 9,000 historical deemed approvals are uniformly one cron-day early** (C6) — a precise,
  consistent off-by-one rather than noise.
- **`verify_token()` written, documented and never called** (§6-F1) — the hook you are meant to
  find.
- **`oauth_program_tokens.revoked_at` in the schema with no writer** (D6).
- **The `app.py:118-123` comment insisting every channel use the rule functions**, immediately
  above a `validate_application` that omits the duplicate check (C7).
- **`app.py:81-83` promising Assamese names are "stored intact"**, with 300 such names in the
  data and a PDF that prints `?` for all of them (B6).
- `husband_employer`, a dead column kept with the comment *"no longer collected"* (C8).

---

## 10. OPEN QUESTIONS

Things the code cannot answer and a human must decide.

**Q1 — What does "make the agent only work for a subset of blocks" (Director, 1:52) mean?**
Three readings, materially different: (a) the officer MCP server is scoped to the blocks its
officer is responsible for; (b) the whole pilot is limited to a few blocks while the rest stay
paper/web; (c) a rate/risk limit on how much of the caseload an agent may touch. The portal
supports **none** of them — there is no officer-to-block mapping anywhere. Whichever is meant,
the mapping has to be invented in the MCP layer, and it will not be visible in `decided_by` or
the audit log. The transcription is also shaky at that timestamp, so this may be worth
re-listening to. **Needs a decision before the officer server is designed.**

**Q2 — Who are the officers, and how do they authenticate as themselves?** There is one shared
`admin` account from `$ADMIN_PASSWORD`, and OAuth `sub` is always `officer:admin`. The Director
wants decisions *"recorded against her name"* (2:30) and the brief requires handing over *"an
officer login for us"*. Options: add an officers table (changes the portal, which the brief
discourages); keep one portal account and carry the real officer identity in the MCP layer,
writing a richer `audit_log.actor` such as `officer:sunita@sonari via mcp`; or issue one
program token per officer and map `jti` → person. Each has a different audit story. **The audit
log's `actor` is `varchar(50)`, so plan the format against that limit.**

**Q3 — How does a citizen supply an age proof through a conversation?** Rule 7 is mandatory and
there is no way to produce a file in chat. Options: the MCP server exposes an upload URL the
citizen opens on their phone; the assistant files the application without a document and
something attaches it later (impossible — validation blocks the insert); a CSC operator or
family member uploads on their behalf; or the age proof is deferred to an in-person counter
visit recorded in the audit note. This is the single biggest product gap between the brief and
the portal. **Nothing in the code hints at an intended answer.**

**Q4 — UTC or IST, and who fixes it?** Dates stored are UTC; dates validated are IST (§A3).
Either the MCP layer converts on the way out and states the zone explicitly, or the portal is
fixed to store IST consistently. Mixing them has already produced 2,585 under-60 approvals in
the seed. Changing the portal is out of scope per the brief; converting in the MCP layer leaves
the portal's own HTML pages still 5h30m wrong, which the Director will see when he *"look[s] at
my own portal"* (2:51).

**Q5 — Should the officer queue be repopulated, and how?** The demo needs pending work (A1).
Repopulating by shifting `submitted_at` falsifies the historical record; having the eval harness
create applications is honest but means the Director's first look at the queue shows only
synthetic citizens. Also: should the scheduler run at all during the test window? If it does,
anything pending for 15 days during the demo will auto-approve itself.

**Q6 — Is it acceptable for an assistant to approve an application the portal would now refuse?**
2,858 existing applications in pension-granting states fail today's `validate_application`
(§2-F-Q6) — mostly on age, computed differently than at submission. If an officer asks the
assistant to "approve everything in Sonari", should it refuse the ineligible ones (and override
an officer), flag them (and slow the officer down), or approve them (and contradict the
Director's 2:09 line)? **A policy decision, not a technical one.**

**Q7 — What is the real rule for "one application per citizen"?** The portal keys on mobile; the
docs say "per eligible citizen"; shared phones are explicitly expected (2:14). Should the
assistant be able to file for a second person on the same number? If so, the portal must change.
If not, what does an assistant tell the second person — and how, without leaking the first
person's application number as the current flash message does?

**Q8 — What is the deployment's `PUBLIC_BASE_URL`, and will it be HTTPS?** It is stamped into
`iss` and all discovery URLs at import. README warns *"some applications refuse to sign in over
plain HTTP"* — which is true of MCP clients. Also unresolved: the canonical `resource` URL for
each MCP server, since that becomes `aud` and your servers must match it exactly (D9).

**Q9 — Is `/__gateway/` to stay publicly readable on the deployed VM?** It is how the Director
will read an OTP during his own test, so removing it breaks the demo; leaving it exposed means
anyone can impersonate any citizen (D2). An admin-session gate would satisfy both if the
Director logs in first — but that needs confirming with him.

**Q10 — How much of the portal may be changed?** The brief says *"The portal stays the system of
record"* and the Director says the assistant must follow *"the same rules and validations as the
portal"* (1:58) — neither forbids fixing the portal. The race in A2, the `SECRET_KEY` in D1 and
the missing document-fetch route are all portal-side and cannot be fully fixed from outside.
**Needs an explicit yes or no**, since the answer changes the architecture.

**Q11 — What should a citizen see about a 6.5%-likely duplicate application number** (B1)? Fixing
the generator is a portal change; working around it in the MCP layer means the number your tool
reports may not uniquely identify the application the Director then looks up by hand.

**Q12 — Do rejections need the four canonical reasons as an enum?** All 7,000 seeded rejections
use exactly four strings, but the code accepts anything including empty (B4). If the officer
assistant should offer a fixed list, someone must confirm these four are current departmental
policy and not just a seed artefact.
