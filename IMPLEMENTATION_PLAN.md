# IMPLEMENTATION_PLAN.md — Phase 0

Scope: two MCP servers (`/mcp/citizen`, `/mcp/officer`) over streamable HTTP, a shared
service layer, the minimal portal fixes listed in the brief, all running under
`docker compose up` behind one origin, manually tested with Claude Code.
Phases 1–2 are outlined in §10.

Ground truth for every claim about the existing system is `AUDIT.md`; section refs are cited
inline. Nothing in the locked decision list turned out to be technically impossible.

**Status: approved with amendments, 2026-10-21.** The defaults in R1–R10 (§9) are accepted as
written, so nothing in this plan is now blocked on a decision. The approved amendments are
folded into the sections they affect:

| # | amendment | where |
|---|---|---|
| 1 | the canonical `/mcp/citizen` and `/mcp/officer` paths are served exactly — POST/GET/DELETE, no 307 to a trailing slash; a no-slash curl check added | §5 (Mounting), §6.2, §7.1, step 7 |
| 1b | **correction to the amendment-1 sketch:** a `Route` does not strip the path prefix, so `streamable_http_app()` would 404. Each server gets a per-server ASGI wrapper that authenticates and then calls `session_manager.handle_request(scope, receive, send)`; both session managers are started in the lifespan. The wrapper is a class **instance**, because `Route` wraps a plain function in `request_response` | §5 (Mounting), §4.4 |
| 2 | `oauth.py` (a) loopback equivalence and (c) scope-from-resource move to **step 7**, before the first Claude Code OAuth test; the 401 challenge also carries `scope` | §2.2 header + (a)/(c), §4.2, §4.4, steps 7 and 11 |
| 3 | anti-fabrication: the two document-touching tool descriptions forbid creating or substituting a file; SHA-256, byte size, original filename and upload time are recorded for every agent-channel upload and shown to the officer | §2.3 (`document_uploads`), §3.3, §5 conventions, §5.1, §5.2 |
| 4 | the `Principal` is read from the `ContextVar` in the async tool body and the identity passed explicitly into `services`; never read in a worker thread | §4.4 (Identity rule), §5 conventions |
| 5 | `docker compose down -v` first, for a pristine database | step 0, §6.4 |
| 6 | demo-seeded age proofs are watermarked `SAMPLE – DEMO DATA`; local use only, documented and enforced | §6.5, step 15 |
| 7 | MCP tool annotations: `readOnlyHint` on reads, `destructiveHint` on approve/reject/withdraw | §5.3 |
| 8 | R1–R10 defaults accepted | §9 |
| 9 | **after Phase 0 (2026-10-22):** citizen document flow — the person uploads through a phone-friendly `/upload/<token>` page; the citizen assistant never verifies, judges or comments on the document; `curl_example` removed (local-file upload only on explicit request); one-line document rule | §5.1 (superseded in part) |
| 10 | **after Phase 0 (2026-10-22):** the officer assistant never sees documents. `view_age_proof` is replaced by `get_age_proof_link` (link + recorded provenance, no image); `get_application` carries the same link; `pypdfium2` removed; the portal's document route opens inline and login returns to it | §5.2 `view_age_proof`, §5.3, R3 (superseded) |
| 11 | **after Phase 0 (2026-10-23):** a helper files for several applicants in one sign-in. `/verify-number/<token>` (bound to the signed-in helper, 15 min, single-use): the helper enters the applicant's mobile, the portal sends the OTP to it, the helper types it on the page; 5-min OTP, 5 wrong tries lock the link, 60 s resend cooldown, 5 sends per link. The number stays verified for that helper until their sign-in ends. New tool `get_number_verification_link`; `check_eligibility`, `save_application_details`, `get_document_upload_link`, `submit_application` take an optional `applicant_mobile` (the signed-in number or one it verified; default the signed-in number). Drafts keyed by (owner, mobile); the application is filed on the applicant's mobile through the same locked path, audit actor `helper:<helper> for <applicant>`, recorded in `helper_filings`. `get_my_application` adds `filed_for_others`; `withdraw_application` stays own-number only. The assistant never asks for, sees or relays an OTP | §5.1, §5.3, `migrations/003_helper_numbers.sql` |
| 12 | **after Phase 0 (2026-10-23):** the officer assistant reports, it does not investigate. It relays the record and the tools' warnings (one line each), never cross-references applications, looks for patterns or speculates about fraud; with warnings it mentions them once and asks once, without warnings it acts on the officer's instruction directly (document-link reminder kept). Audit notes hold only the officer's words: approve `note` and reject `officer_reason_quote` verbatim, never the assistant's own. One new deterministic warning: `The same age-proof file (sha256) is also attached to application <no> (<name>).` (recorded hashes, plus the on-disk hash of an unrecorded file) | §5.2, `services._same_document_warnings`, `migrations/004_docup_sha.sql` |
| 13 | **after Phase 0 (2026-10-23):** the officer assistant assists, it does not investigate (supersedes the confirmation rules of 12). It does what the officer asks, relays the record and the tools' warnings one line each without commentary, never cross-references, analyses patterns, speculates about fraud or conflicts of interest, or second-guesses. No repeated confirmations: on the officer's word it calls the tool (approve: id + number; reject: the officer's reason and quote). The remind-to-open-the-link and restate-and-confirm rules are gone; the link is given when a case is opened or asked for. Hard blocks unchanged (under 60, no age proof); the blocked message carries only the portal's reason. Audit notes stay the officer's words only | §5.2 |
| 15 | **after Phase 0 (2026-10-23):** the same-document warning of 12 is removed, with its index (migration 004 now drops it); the "decision before submission date" warning goes too. Officer warnings are the portal's rule-based checks only: age under 60 / no date of birth, no age proof, invalid IFSC, village/block | §5.2 |
| 16 | **after Phase 0 (2026-10-23):** every citizen and officer tool result has a `reply`: a short pre-formatted markdown message the assistant shows almost verbatim (`mcp_server/replies.py`). Both servers' instructions gain the style rules: use `reply`, add nothing unless asked; at most 4 short lines plus a link; one action in bold; no repeated details except the declaration read-back; no rule explanations unless asked or blocked; no advice, no emojis; DD/MM/YYYY, 10:11 IST. Behaviour and the other result fields unchanged (the person-facing `instructions` field of the two link tools is replaced by `reply`) | §5.1, §5.2 |
| 14 | **after Phase 0 (2026-10-23):** `/upload/<token>` and `/verify-number/<token>` show a "Done – return to chat" button on success that calls `window.close()` (and tries once automatically after ~2 s); when the browser refuses, the person stays on the success page with "You can close this tab and return to your chat, then say done." No `history.back()`: in a normal tab it landed on the used OTP form. Citizen texts: on any reply after a link, check `document_attached` / `verified_numbers` before asking again | §5.1 |

---

## 1. File layout

### 1.1 New files

```
docker-compose.yml                  (modified — see §6)
proxy/Caddyfile                     single public entrypoint on :8000; /mcp/* + PRM -> mcp, rest -> Flask
app/services.py                     THE shared business layer. Flask routes and both MCP servers call it.
app/mcp_server/__init__.py          (empty)
app/mcp_server/main.py              ASGI entrypoint: Starlette app mounting both FastMCP servers + PRM routes
app/mcp_server/auth.py              RFC 9728 metadata, 401 challenge, JWT verification, token -> Principal
app/mcp_server/citizen.py           FastMCP instance + 7 citizen tools
app/mcp_server/officer.py           FastMCP instance + 6 officer tools
app/mcp_server/fmt.py               IST formatting, plain-language status text, compact row rendering
app/migrations/002_phase0.sql       additive DDL: agent_drafts + indexes (idempotent)
app/scripts/apply_migrations.py     applies migrations/*.sql in order at mcp container boot
app/scripts/seed_demo_queue.py      creates N pending applications THROUGH services.py (never raw SQL);
                                    LOCAL USE ONLY — its generated age proofs are watermarked (§6.5)
app/templates/upload_token.html     the /upload/<token> page (phone browser + curl)
```

### 1.2 Modified files

| file | why |
|---|---|
| `app/app.py` | import `services` at the bottom; route bodies delegate to it; 6 minimal fixes (§2.1) |
| `app/oauth.py` | rid↔session binding, loopback redirect equivalence, program-token revocation write, scope-from-resource fallback (§2.2) |
| `app/requirements.txt` | add `mcp`, `uvicorn[standard]`, `starlette`, `pypdfium2`, `python-multipart` |
| `app/Dockerfile` | no code change; only verify the new wheels install (all pure wheels, no apt packages) |
| `app/schema.sql` | **not touched.** New DDL lives in `migrations/002_phase0.sql`, applied at boot, so an existing `pgdata` volume does not have to be recreated |
| `app/templates/admin_view.html` | document path becomes a link to the new officer document route; reject input gets `required` |
| `app/templates/admin_tokens.html` | a Revoke button per program-token row (the existing one revokes the wrong table, §5-E) |
| `app/config/app.ini` | unchanged; `SCHEME_DEADLINE` gains an env override in `app.py` for the closed-window test (§7, S9) |

Everything else (templates, URLs, admin login, the deemed-approval job, the SMS gateway
exposure) is untouched, per the locked decisions.

---

## 2. Exact portal changes

### 2.1 `app/app.py`

**(a) Line 38 — SECRET_KEY.** No code change; `docker-compose.yml` now passes `SECRET_KEY`
(§9-D1). Keep the `os.environ.get("SECRET_KEY") or config.get(...)` fallback.

**(b) Line 52 — deadline override for a test stack.**
```python
SCHEME_DEADLINE = datetime.strptime(
    os.environ.get("SCHEME_DEADLINE") or config.get("pension", "scheme_deadline"),
    "%Y-%m-%d %H:%M")
```
Default behaviour is identical. It exists only so the closed-window scenario can be tested
without editing a tracked config file. The scheme deadline value itself is unchanged.

**(c) `new_application_no()` (line 108) — collision retry (§9-B1).** Change the signature to
take a cursor and loop:
```python
def new_application_no(cur):
    for _ in range(10):
        no = "SSP" + now_ist().strftime("%y") + str(random.randint(100000, 999999))
        cur.execute("SELECT 1 FROM applications WHERE application_no = %s", (no,))
        if not cur.fetchone():
            return no
    raise RuntimeError("could not allocate a unique application number")
```
`%y` now comes from `now_ist()` — UTC gave a year-behind prefix for 5½ h around New Year
(§4-D). The migration adds a unique index so the retry is backed by the database.

**(d) `validate_application()` (line 136) — length checks (§9-B5).** After the existing IFSC
rule, insert four length rules so an over-long value errors cleanly instead of crashing the
INSERT:
```python
for label, key, maxlen in (("gender", "gender", 10),
                           ("marital status", "marital_status", 20),
                           ("village", "village", 100),
                           ("late husband's name", "husband_name", 100)):
    if len(cleaned[key]) > maxlen:
        errors.append("%s must be %d characters or fewer" % (label, maxlen))
```
No other rule changes: age 60, the block list, the deadline, the document requirement, the
IFSC regex and the bank regex stay exactly as they are.

**(e) `create_application()` (line 188).** One line changes: `app_no = new_application_no(cur)`.
Everything else (portal_users creation, the SUBMIT audit row, no commit) is unchanged.

**(f) `handle_submission()` (line 373) — becomes a thin wrapper over services.**
```python
def handle_submission():
    mobile = session.get("verified_mobile")
    res = services.submit_web(mobile, session.get("form_data", {}), session.get("doc_path", ""))
    if res["status"] == "invalid":
        flash("Please correct the following before submitting: " + "; ".join(res["errors"]) + ".")
        return redirect(url_for("form_step", step=1))
    if res["status"] == "duplicate":
        flash("Application %s (%s) already exists for this mobile number. A pending "
              "application can be withdrawn from the status portal if you need to "
              "apply afresh." % (res["existing"]["application_no"], res["existing"]["status"]))
        return redirect(url_for("index"))
    session.pop("form_data", None); session.pop("doc_path", None)
    session.pop("verified_mobile", None)
    session["logged_in"] = True; session["portal_mobile"] = mobile
    return render_template("confirmation.html", app_no=res["application_no"], app_id=res["id"])
```
The advisory lock, the active-application check, `create_application` and the submission SMS
move inside `services.submit_web` → `services._submit_locked`. Flash strings are preserved
verbatim so the web flow looks unchanged.

**(g) `withdraw_application()` (line 489).** Body becomes
`res = services.withdraw(mobile, app_id=app_id, actor="applicant:%s" % mobile)` and the two
existing flashes keyed on `res["status"]` (`ok` / `not_pending`). Audit verb stays `WITHDRAW`.

**(h) `_admin_decide()` (line 642) — reason required on reject, SMS on both.**
```python
def _admin_decide(app_id, new_status, note):
    if not session.get("admin"):
        abort(403)
    officer = session.get("admin_user", ADMIN_USERNAME)
    res = services.decide(application_id=app_id, decision=new_status,
                          reason=note, note="", officer=officer, channel="web")
    if res["status"] == "reason_required":
        flash("A reason is required to reject an application.")
    elif res["status"] in ("not_pending", "not_found"):
        flash("Only a pending application can be decided.")
    else:
        flash("Application %s %s." % (res["application_no"], new_status.lower()))
    return redirect(url_for("admin_view", app_id=app_id))
```
`services.decide` sends the citizen SMS on approve and reject (§4-E), so the web form gains
it too. `admin_view.html`'s reject input gets `required`. The web channel is **not**
eligibility-blocked (see §3.3 `decide` step 4 and R10).

**(i) New route — officer document view (§4-C).**
```python
@app.route("/admin/application/<int:app_id>/document")
def admin_document(app_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    doc = services.application_document(app_id)        # (bytes, mimetype, filename) or None
    if not doc:
        abort(404)
    return send_file(io.BytesIO(doc[0]), mimetype=doc[1], download_name=doc[2])
```
`admin_view.html` line 15 becomes a link when `a[10]` is non-empty, plain `-` otherwise.

**(j) New route — token-protected draft upload.**
```python
@app.route("/upload/<token>", methods=["GET", "POST"])
def draft_upload(token):
    d = services.draft_for_upload_token(token)         # None if unknown/expired/used
    if not d:
        return render_template("upload_token.html", expired=True), 404
    if request.method == "POST":
        f = request.files.get("document")
        res = services.attach_draft_document(token, f.filename if f else "", f)
        if request.args.get("format") == "json":
            return jsonify(res), (200 if res["status"] == "ok" else 400)
        return render_template("upload_token.html", d=d, result=res)
    return render_template("upload_token.html", d=d)
```
`curl -F document=@age.jpg <url>` gets the HTML page with a success banner (200);
`...?format=json` gets JSON. Same file rules as `/upload` (pdf/jpg/jpeg/png, ≤5 MB) enforced
in `services.attach_draft_document`, which streams and aborts past 5 MB + 1 byte (so this
path does not inherit §9-B9) and writes a collision-proof filename (§9-B8).
`app.config["MAX_CONTENT_LENGTH"]` is **not** set globally — that would change the existing
`/upload` behaviour.

**(k) Bottom of file, before the oauth import.**
```python
import services                                  # noqa: E402  (same deferral trick as oauth)
from oauth import oauth as _oauth_blueprint      # noqa: E402
app.register_blueprint(_oauth_blueprint)
```
`services.py` does `import app as portal` at its top, so the §7-C hazard applies identically:
**`import app` first, always.** The MCP entrypoint does exactly that.

### 2.2 `app/oauth.py`

**Build order note:** (a) and (c) are interop prerequisites — they land in **build step 7**,
before the first Claude Code OAuth attempt, because a failure in either looks like a broken
MCP server rather than a portal bug. (b) and (d) land in **step 11**.

**(a) `redirect_allowed()` (line 182) — loopback host equivalence (§6-D). [step 7]** Today a client
that registers `http://localhost:PORT/callback` and calls back on `127.0.0.1` is rejected,
and vice versa; Claude Code may do either. Change the final loop's hostname test from
`rp.hostname == u.hostname` to "both are loopback":
```python
if rp.scheme == "http" and rp.hostname in LOOPBACK_HOSTS and rp.path == u.path \
        and rp.query == u.query:
    return True
```
Exact path and query matching are kept — RFC 8252 §7.3 exempts only the port. Also add
`"[::1]"` / `"::1"` to `register()`'s accept list (line 248) so registration and redirect
checking agree (§6-B inconsistency).

**(b) `authorize()` (line 311) — bind `rid` to the browser session (§6-F2). [step 11]** After the
`oauth_requests` INSERT:
```python
session["oauth_rids"] = (session.get("oauth_rids", []) + [rid])[-5:]
session.modified = True
```
and in `login()` and `consent()`, reject when `rid not in session.get("oauth_rids", [])`,
rendering the existing `oauth_error.html` ("Request expired / Please start again from your
application."). Keeping the last 5 rather than a single value avoids breaking a kiosk user
who starts two sign-ins.

**(c) `authorize()` — scope implied by `resource`. [step 7]** Claude Code may send no `scope`, or a
space-separated set; the portal demands exactly one and silently defaults to `citizen`
(§6-D), which would hand an officer client a citizen token. Insert before the scope check:
```python
RESOURCE_SCOPE = {ISSUER + "/mcp/citizen": "citizen", ISSUER + "/mcp/officer": "officer"}
resource = q.get("resource") or ISSUER
implied = RESOURCE_SCOPE.get(resource.rstrip("/"))
raw = [s for s in (q.get("scope") or "").split() if s]
if implied and (not raw or implied in raw):
    scopes = [implied]
else:
    scopes = raw or ["citizen"]
```
For any other resource the behaviour is byte-identical to today. This is the one change worth
your sanity check: it is the difference between "Claude Code signs in" and "Claude Code gets
the wrong role".

**(d) Program-token revocation (§5-E, locked decision 2). [step 11]**
- `admin_tokens()`: select `jti, label, subject, audience, issued_by, created_at, expires_at,
  revoked_at`, and handle a new POST field:
  ```python
  if request.form.get("revoke_jti"):
      cur.execute("UPDATE oauth_program_tokens SET revoked_at = %s "
                  "WHERE jti = %s AND revoked_at IS NULL",
                  (datetime.now(), request.form["revoke_jti"]))
      flash("Program token revoked.")
  ```
- `admin_tokens.html`: one `Revoked` / `Revoke` cell per row.
- New helper `verify_program_jti(jti) -> bool`, used by the officer MCP server: False when a
  row exists with `revoked_at IS NOT NULL`; True otherwise (tokens issued before this change
  keep working).

**(e) Deliberately not changed in Phase 0:** CORS wildcard (D13), `/oauth/revoke` client
auth (D8), the access-token revocation window (D7 — an access token carries no link to its
refresh row), CIMD SSRF (D10), `resource` validation (D9 — our servers do the exact `aud`
match the README prescribes), rate limiting (D3), CSRF on web forms (D4). Out of the locked
scope; D3/D4 belong in Phase 2.

### 2.3 DDL — `app/migrations/002_phase0.sql`

Applied by the `mcp` container at boot (`apply_migrations.py`, idempotent, before uvicorn
starts), so an existing `pgdata` volume picks it up without needing `down -v` — which matters
in Phase 2, where the data is real. Build step 0 still wipes the volume locally, for test
hygiene rather than because the migration requires it (§2-G left duplicate-active rows behind
that would mask the very regressions §7 checks for).

```sql
-- Phase 0. Additive only: no column dropped, no existing row modified.

CREATE TABLE IF NOT EXISTS agent_drafts (
    mobile        VARCHAR(15) PRIMARY KEY,
    data          JSONB     NOT NULL DEFAULT '{}'::jsonb,
    doc_path      VARCHAR(200),
    doc_name      VARCHAR(120),
    upload_token  VARCHAR(64),
    token_expires TIMESTAMP,
    created_at    TIMESTAMP NOT NULL,
    updated_at    TIMESTAMP NOT NULL,
    expires_at    TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_drafts_token
    ON agent_drafts(upload_token) WHERE upload_token IS NOT NULL;

-- Provenance of every document the agent channel accepted. Outlives the draft (which is
-- cleared on submit) so an officer can always see what arrived and when. Anti-fabrication:
-- the officer sees the hash, the size and the original filename, never a claim about them.
CREATE TABLE IF NOT EXISTS document_uploads (
    id             SERIAL PRIMARY KEY,
    mobile         VARCHAR(15) NOT NULL,
    application_id INTEGER,                      -- stamped by _submit_locked; NULL until submitted
    doc_path       VARCHAR(200) NOT NULL,
    original_name  VARCHAR(200) NOT NULL,        -- exactly what the uploader sent
    sha256         CHAR(64)     NOT NULL,
    byte_size      INTEGER      NOT NULL,
    content_type   VARCHAR(60),
    source         VARCHAR(20)  NOT NULL,        -- 'upload_token' | 'demo_seed'
    uploaded_at    TIMESTAMP    NOT NULL         -- UTC-naive, like every other timestamp
);
CREATE INDEX IF NOT EXISTS idx_docup_app ON document_uploads(application_id);
CREATE INDEX IF NOT EXISTS idx_docup_path ON document_uploads(doc_path);

-- §9-B1: back the retry loop with a constraint. Safe: Q12 proved 0 duplicates today.
-- Also the only index on application_no, which the officer lookup needs (100k seq scan today).
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_no_unique ON applications(application_no);

-- officer queue filter: status + block ((status, submitted_at) already exists)
CREATE INDEX IF NOT EXISTS idx_app_status_block ON applications(status, block);

-- §8/§9-D12 adjacency: every OTP check is a sequential scan today
CREATE INDEX IF NOT EXISTS idx_otps_mobile ON otps(mobile, id DESC);
```

Deliberately **not** added: the partial unique index on
`(mobile) WHERE status IN ('PENDING','APPROVED','DEEMED_APPROVED')` suggested in §9-A2. The
shipped seed is clean (Q8), but the audit's own race left ids 100015/100016 as a duplicate
active pair on mobile `9000000012` (§2-G), so the index fails to build on any database that
has been exercised. The advisory lock in `services` is the enforcement; the index is a
Phase 2 hardening step once the data is known clean.

All new timestamp columns are UTC-naive, matching every existing timestamp. No stored-time
semantics change anywhere (§9-A3).

---

## 3. `app/services.py` — the shared layer

Rules: every business mutation goes through here, and here calls the portal's own rule
functions — `portal.validate_application`, `portal.active_application`,
`portal.create_application`, `portal.write_audit`. It writes no raw SQL for a business
mutation. Reads use SQL directly (no portal function exists for them). No Flask
request/session/flash is touched, so it is callable from the MCP process with no app context
(§7-C confirms this is safe).

### 3.1 Module setup

```python
import app as portal                      # MUST be first; see the §7-C import hazard
from psycopg2 import pool
_POOL = None                              # ThreadedConnectionPool(1, 10, **portal dsn), lazy

@contextmanager
def db(commit=False):
    conn = _pool().getconn()
    try:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit() if commit else conn.rollback()   # never leave idle-in-transaction
        finally:
            cur.close()
    except Exception:
        conn.rollback(); raise
    finally:
        _pool().putconn(conn)
```
Every function uses `with db(...)`, so **every connection is returned on every path** — the
portal leaks one per exception today (§7-C). Flask keeps `get_db()` for its read routes; only
the paths in §2.1 move.

`class ServiceError(Exception)` carries `code` and `message`; both channels map the code.

### 3.2 Constants and pure helpers

| name | value / behaviour |
|---|---|
| `BLOCKS` | re-exported from `portal.BLOCKS` — never redefined |
| `VILLAGES` | the 19 real villages → block, from §2-F-Q15. Sonari: Bhekulajan, Kakotibari, Lakhipur, Namdang. Rajapara: Dighaljan, Rajapara Gaon, Teliagaon. Borgaon: Borgaon Centre, Milanpur, Udaypur. Dhemaji Pathar: Bordoloni, Kathoni, Nalbari Gaon. Namti: Hatipara, Namti Chariali, Panidihing. Khelua: Chengelimara, Khelua Gaon, Sialmari |
| `REJECTION_REASONS` | the 4 canonical strings from §2-F-Q16 + `"other"` (note required) |
| `DRAFT_TTL` / `UPLOAD_TOKEN_TTL` | 7 days / 24 hours |
| `to_ist(dt)` | `dt + 5:30` on a UTC-naive value → naive IST; `None` → `None` |
| `fmt_ist(dt)` | `"21/10/2026 10:05 IST"`; `None` → `"—"` |
| `deemed_date(submitted_at)` | `submitted_at + 15d`, rounded **up to the next 02:00 UTC**, returned as IST (= 07:30 IST). Exactly the arithmetic verified in §2-F-Q13; never inferred from history (§9-C6) |
| `window_status()` | `{open, deadline_ist, hours_left}` from `portal.SCHEME_DEADLINE` and `portal.deadline_remaining()` — config, not hardcoded |
| `normalise(fields)` | DOB from `DD/MM/YYYY`, `D/M/YYYY`, `YYYY-MM-DD`, `DD-MM-YYYY`, `DD.MM.YYYY` → canonical `DD/MM/YYYY`; IFSC strip + upper; bank account digits only; village matched case-insensitively against `VILLAGES`; block matched case-insensitively against `BLOCKS` and corrected to canonical spelling (§9-E5). Returns `(clean_fields, notes)` |
| `age_from_dob(raw)` | `portal.parse_dob` + `portal.age_on(dob, portal.now_ist().date())` — age on today IST (§3-A1) |

### 3.3 API

Every function returns a JSON-safe dict with `status` as the discriminator. Caller mistakes
raise `ServiceError`; expected business outcomes are returned, not raised.

**Drafts**

| function | in | out | tx |
|---|---|---|---|
| `get_draft(mobile)` | mobile | `{fields, doc_attached, doc_name, missing, errors, expires_at}` or `None` | read |
| `save_draft(mobile, fields)` | partial dict, any subset | `{status:"ok", saved, missing, problems, corrections, suggested_block}` | one tx, upsert |
| `issue_upload_token(mobile)` | mobile | `{url, token, expires_at_ist, doc_attached}` | one tx |
| `draft_for_upload_token(token)` | token | draft dict or `None` (unknown/expired) | read |
| `attach_draft_document(token, filename, stream)` | | `{status:"ok"\|"bad_type"\|"too_large"\|"no_file", doc_name, sha256, byte_size, uploaded_at_ist}` | one tx |
| `document_provenance(application_id=None, doc_path=None)` | | `{recorded:true, original_name, sha256, byte_size, content_type, source, uploaded_at_ist}` or `{recorded:false, reason:"uploaded through the web form or predates this release"}` | read |
| `clear_draft(mobile)` | mobile | `{status:"ok"}` | one tx |

`save_draft` merges, normalises, then calls `portal.validate_application(merged, doc_path)`
and reports its errors as `problems` — but **never blocks the save**: a half-filled draft is
legal. `missing` is derived from the required set (name, dob, village, block, bank_account)
plus the document. Errors raised: `ServiceError("bad_field")` only for a non-dict input.

`attach_draft_document` writes
`UPLOAD_DIR/draft_<mobile>_<yyyymmddHHMMSS>_<4 hex>.<ext>` — unique per upload, so no other
application's `doc_path` is ever overwritten (§9-B8) and no user-controlled path component
survives. It hashes the bytes as it streams them and inserts one `document_uploads` row
(`original_name` = exactly what the uploader sent, `sha256`, `byte_size`, `content_type`,
`source="upload_token"`, `uploaded_at = datetime.now()`). The MCP layer never produces
document bytes: the only writer of a document on the agent path is this function, called from
the Flask `/upload/<token>` route by whoever is holding the applicant's paper. `_submit_locked`
stamps `application_id` onto the row inside the same transaction as the INSERT, so provenance
survives the draft being cleared.

**Citizen**

| function | out | notes |
|---|---|---|
| `scheme_info()` | `{amount_inr, min_age, residency, documents_accepted, formats, sla_days, deemed_approval, window, blocks, villages_by_block}` | all from config/constants |
| `eligibility(mobile, dob_raw=None)` | `{age, age_ok, turns_60_on, window_open, has_active, eligible, reasons}` | age on today IST; no invented criteria |
| `submit(mobile, confirm_declaration, actor)` | `ok` / `incomplete` / `no_document` / `declaration_required` / `invalid`+errors / `duplicate`+existing | the agent path; reads the draft |
| `submit_web(mobile, form_data, doc_path)` | same discriminators | the web path; same `_submit_locked` core |
| `my_application(mobile)` | `{found, application_no, status, status_meaning, submitted_at_ist, decided_at_ist, decided_by, reason, deemed_date_ist, village, block, doc_attached}` | the token's mobile only |
| `withdraw(mobile, application_no=None, app_id=None, actor=...)` | `ok` / `not_pending` / `not_found` | own + PENDING only |

`_submit_locked(cur, mobile, cleaned)` is the single write path for both channels:
```sql
SELECT pg_advisory_xact_lock(hashtext(%s))     -- mobile
```
then `portal.active_application(cur, mobile)` → bail `duplicate`; then
`portal.create_application(cur, mobile, cleaned)` (which writes the SUBMIT audit row);
commit; **then** `portal.send_sms(...)` and `clear_draft(mobile)`. One transaction, lock held
to commit — this closes §9-A2 for the web form and the agent alike, and matches the pattern
§7-C prescribes.

**Officer**

| function | out | notes |
|---|---|---|
| `queue_summary()` | `{pending_total, by_block, overdue_15d, deemed_within_48h, oldest_pending_ist}` | overdue cutoff `datetime.now() - 15d`, consistent with the dashboard and the cron |
| `list_applications(status="PENDING", block=None, overdue_only=False, search=None, page=1)` | `{total, page, pages, rows:[{id, application_no, applicant_name, mobile, block, status, submitted_at_ist, days_pending}]}` | status/block matched case-insensitively against the known sets and **rejected** with the valid list if unknown (§9-B3); `page` coerced to ≥1 (§9-B2); `LIMIT 20`; `ORDER BY submitted_at ASC`; `search` = exact application_no, exact mobile, or name `ILIKE %…%`, always under the LIMIT (§9-E21) |
| `get_application(application_id=None, application_no=None)` | full row + `audit` + `warnings` | audit matches `action IN ('WITHDRAW','WITHDRAWN')` and both actor formats (§9-C3); `days_pending` / `time_to_decision` clamped at 0 (§9-B11) |
| `eligibility_warnings(row)` | list of strings | age today < 60; `doc_path` empty; IFSC non-empty and failing `^[A-Z]{4}0[A-Z0-9]{6}$`; village not in the 19; village/block mismatch; `decided_at < submitted_at` |
| `application_document(application_id)` | `(bytes, mimetype, filename)` or `None` | refuses any path outside `UPLOAD_DIR` (`os.path.realpath` prefix check), 10 MB read cap |
| `decide(application_id, decision, reason, note, officer, channel, expect_application_no=None)` | `ok` / `not_found` / `not_pending` / `no_match` / `reason_required` / `blocked`+warnings | below |

`decide`, in one transaction:
1. `SELECT … FOR UPDATE` the row → `not_found` / `not_pending`.
2. If `expect_application_no` is given and does not match → `no_match`, nothing written.
3. `decision == "REJECTED"` with no non-empty reason → `reason_required`.
4. Re-run `eligibility_warnings`. **On approve from `channel="mcp"`**, a hard warning (age
   today < 60, or no document) → `blocked` with the explanation, nothing written; soft
   warnings (IFSC shape, village/block mismatch) are returned but do not block. Rationale:
   Director 2:09 — the assistant must never get anyone a pension the counter would not
   (§9-E16). Reject is never blocked, and `channel="web"` is never blocked (the human officer
   at the keyboard keeps today's authority).
5. `UPDATE applications SET status, decided_at = datetime.now(), decided_by = %s
   WHERE id = %s AND status = 'PENDING' RETURNING application_no` — keeps the existing
   idempotency guard (§5-B).
6. `portal.write_audit(cur, id, decision, actor, note_text)` where
   `actor = ("officer:%s via assistant" % officer)[:50]` for `channel="mcp"` and
   `"admin:%s" % officer` for `channel="web"` (web unchanged), and `note_text = reason`
   (+ `" — " + note` when both are given), truncated to 500.
7. Commit, **then** SMS:
   - approve: `"Sewa Setu: your pension application <no> has been approved. Rs 250 per month will be credited to your bank account by DBT."`
   - reject: `"Sewa Setu: your pension application <no> has been rejected. Reason: <reason>. You may apply again at the Sewa Setu portal or at your block office."`

   `portal.send_sms` swallows errors, so `decide` POSTs to the gateway itself (5 s timeout)
   and reports the real result as `sms_sent`. The officer tool must never claim the citizen
   was notified when it was not (§9-E19).

`decided_by` is the officer username from the token (`varchar(50)`) — `admin` today (§5-D).
The audit actor carries the channel. Single-item only; no bulk tool exists anywhere.

---

## 4. Auth design

### 4.1 Canonical resource URLs

| server | canonical URL (= `resource` = `aud`) | PRM path |
|---|---|---|
| citizen | `${PUBLIC_BASE_URL}/mcp/citizen` | `/.well-known/oauth-protected-resource/mcp/citizen` |
| officer | `${PUBLIC_BASE_URL}/mcp/officer` | `/.well-known/oauth-protected-resource/mcp/officer` |

Locally `PUBLIC_BASE_URL=http://localhost:8000`; in Phase 2 only the scheme and host change.
Because the proxy puts Flask and the MCP servers on one origin, `iss` and both resource URLs
share a host — which is what makes discovery work with no extra configuration.

### 4.2 Request flow

```
Claude Code                      MCP (/mcp/officer)         Portal (AS, same origin)
  | POST /mcp/officer (no token)      |                              |
  |---------------------------------->|                              |
  | 401  WWW-Authenticate: Bearer error="invalid_token", scope="officer",          |
  |      resource_metadata=".../.well-known/oauth-protected-resource/mcp/officer"
  |<----------------------------------|                              |
  | GET that resource_metadata URL -->|                              |
  | {resource, authorization_servers:[PUBLIC_BASE_URL], jwks_uri, scopes_supported:["officer"]}
  |<----------------------------------|                              |
  | GET /.well-known/oauth-authorization-server -------------------->|
  | {authorization_endpoint, token_endpoint, registration_endpoint, jwks_uri} <--|
  | POST /oauth/register  (DCR; redirect_uri http://localhost:PORT/callback) --->|
  | browser: GET /oauth/authorize?response_type=code&code_challenge=…&S256
  |          &scope=officer&resource=http://localhost:8000/mcp/officer --------->|
  |          -> /oauth/login (departmental username + password)
  |          -> /oauth/consent  -> 302 http://localhost:PORT/callback?code=…&iss=…
  | POST /oauth/token (code + code_verifier + resource) ------------>|
  | {access_token RS256 aud=.../mcp/officer, refresh_token, session_ends}
  | POST /mcp/officer  Authorization: Bearer <jwt>   |               |
  |---------------------------------->| verify via /.well-known/jwks.json (PyJWKClient)
  | 200 tool result                   |                              |
```

Citizen is identical with `scope=citizen`, `resource=.../mcp/citizen`, and OTP login — the
tester reads the OTP from `/__gateway/` (left exposed on purpose, locked decision 3).

### 4.3 The metadata documents, verbatim

`GET /.well-known/oauth-protected-resource/mcp/citizen`
```json
{
  "resource": "http://localhost:8000/mcp/citizen",
  "authorization_servers": ["http://localhost:8000"],
  "jwks_uri": "http://localhost:8000/.well-known/jwks.json",
  "scopes_supported": ["citizen"],
  "bearer_methods_supported": ["header"],
  "resource_name": "Sewa Setu — Old Age Pension (citizen)",
  "resource_documentation": "http://localhost:8000/about"
}
```
`.../mcp/officer` is the same with `/mcp/officer`, `["officer"]`, and
`"resource_name": "Sewa Setu — Old Age Pension (block officer)"`.

Also served, defensively, because clients differ on path construction: the same documents at
`/.well-known/oauth-protected-resource?resource=<url>` and at
`/mcp/citizen/.well-known/oauth-protected-resource`. `Access-Control-Allow-Origin: *` on the
PRM routes only.

### 4.4 Verification outline — `app/mcp_server/auth.py`

```python
JWKS = PyJWKClient(ISSUER + "/.well-known/jwks.json", cache_keys=True, lifespan=600)

@dataclass
class Principal:
    role: str            # "citizen" | "officer"
    subject: str         # "citizen:9876543210" | "officer:admin"
    mobile: str | None   # citizen only, parsed from sub — NEVER from tool input
    officer: str | None
    kind: str            # "access" | "program"
    session_ends: int | None

def authenticate(header, expected_role, canonical_url) -> Principal:
    if not header or not header.startswith("Bearer "):
        raise Unauthorized("sign in")                       # 401 + challenge
    token = header[7:]
    key = JWKS.get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], issuer=ISSUER,
                        options={"verify_aud": False,
                                 "require": ["iss", "sub", "aud", "exp", "iat"]})
    if str(claims["aud"]).rstrip("/") != canonical_url:      # D9: the AS does not validate resource
        raise Forbidden("this token was issued for a different service")
    if claims.get("role") != expected_role or claims.get("scope") != expected_role:
        raise Forbidden("this token is for the %s service" % claims.get("role"))
    if claims.get("kind") == "program":
        if expected_role != "officer":
            raise Forbidden("program tokens are officer-only")
        if not oauth.verify_program_jti(claims["jti"]):
            raise Unauthorized("this program token has been revoked")
    if claims.get("session_ends") and claims["session_ends"] <= time.time():
        raise Unauthorized("your sign-in has ended")
    sub = claims["sub"]
    return Principal(role=expected_role, subject=sub,
                     mobile=sub.split(":", 1)[1] if sub.startswith("citizen:") else None,
                     officer=sub.split(":", 1)[1] if sub.startswith("officer:") else None,
                     kind=claims.get("kind", "access"),
                     session_ends=claims.get("session_ends"))
```

Notes:
- `algorithms=["RS256"]` is pinned — no `none`, no HS confusion.
- `aud` is compared by exact string (trailing slash tolerated) because the AS accepts any
  `resource` verbatim (§6-F3 / D9). `verify_aud` is off precisely so the comparison is ours.
- Both `role` and `scope` are checked although they are redundant by construction (§6-E):
  cheap, and it catches a hand-rolled token.
- **A citizen token on the officer endpoint** fails the `aud` check first and the role check
  second → 403 with `"This token was issued for the citizen service. Reconnect with the
  officer MCP server."` The reverse is symmetric.
- **Every 401 carries the full challenge**, including the scope this server needs, so a
  client that honours `scope` in the challenge asks the AS for the right one even if it
  ignores the PRM document:
  ```
  WWW-Authenticate: Bearer error="invalid_token",
      error_description="<one sentence>",
      scope="officer",
      resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp/officer"
  ```
  (`scope="citizen"` on the citizen server.) This is the belt to R1's braces: PRM
  `scopes_supported`, the challenge `scope`, and the portal's resource→scope inference all
  point at the same value.
- **The absolute session end** (2 h citizen / 8 h officer, §6-E) arrives as
  `jwt.ExpiredSignatureError`, because `exp` is already `min()`-ed with `session_ends`.
  It becomes that same 401 with
  `error_description="Your sign-in has ended. Please sign in again."`, which makes Claude
  Code re-run the OAuth flow. A tool call that races the expiry returns the same sentence as
  text rather than raising.
- **Program tokens** must be issued with audience exactly
  `http://localhost:8000/mcp/officer`; anything else fails the `aud` check. Documented in the
  test script.
- Access tokens revoked mid-session stay valid ≤20/30 min (D7); accepted for Phase 0 and
  stated in the hand-over note, because an access token has no stored link to its refresh row.

Plumbing: the per-server ASGI endpoint (`MCPEndpoint.__call__`, §5) reads `Authorization`
straight off the raw scope, calls `authenticate(...)` with **that endpoint's** role and
canonical URL, stores the `Principal` in a `ContextVar`, and only then calls
`session_manager.handle_request`. Not a shared middleware: the role and canonical URL are
baked into each endpoint instance, so there is no path-sniffing to decide which server a
request belongs to and no way for the two to be confused. Unauthenticated requests get the
401 + challenge **before** the session manager sees them, so `initialize` and `tools/list`
are authenticated too — refusing early is what makes Claude Code start the OAuth flow
immediately. The `ContextVar` is reset in a `finally`, so a pooled task never inherits a
previous request's identity.

**Identity rule (non-negotiable, applies to every tool).** The `ContextVar` is read **in the
async tool body**, on the request's own task, and the identity is then passed **explicitly**
as an argument into the `services` call:

```python
@citizen.tool(annotations={"readOnlyHint": True})
async def get_my_application() -> dict:
    p = current_principal()                      # async body, request task — correct context
    return await anyio.to_thread.run_sync(services.my_application, p.mobile)
```

Never read the `ContextVar` inside a worker thread. `anyio.to_thread.run_sync` copies the
context in current anyio versions, but relying on that is how one tool call ends up acting
for another user's mobile under load — so `services` takes `mobile` / `officer` as plain
parameters and has no access to the context at all. A tool that needs identity and forgot to
pass it cannot compile into something that silently uses the wrong person's data: every
`services` entry point that touches one person's data takes the identity as its **first
positional argument**.

The mobile for a citizen tool always comes from `Principal.mobile` (parsed from the token's
`sub`), never from tool input — no citizen tool has a `mobile` parameter in its schema.

---

## 5. MCP tools

Transport: streamable HTTP, `stateless_http=True` on both FastMCP instances (not SSE; each
POST is self-contained, which keeps the proxy simple and a multi-worker deployment possible).
Tool bodies are sync `services` calls wrapped in `anyio.to_thread.run_sync`, so psycopg2 never
blocks the event loop.

**Mounting: the canonical path is served exactly, with no redirect, and no app does its own
path matching.** `aud` is `…/mcp/citizen` with no trailing slash, every client posts to that
exact URL, and a 307 to `…/mcp/citizen/` would at best cost a round trip and at worst drop the
POST body or the `Authorization` header on a redirect-following client.

Two mechanics have to be right here, and the obvious spelling of each is wrong:

1. **`streamable_http_app()` cannot be used as a `Route` endpoint.** A Starlette `Route` does
   **not** strip the path prefix (only `Mount` does), so the Starlette router inside
   `streamable_http_app()` would try to match `/mcp/citizen` against its own `"/"` route and
   return 404. The fix is to skip that wrapper entirely and hand the raw ASGI scope to the
   session manager, which dispatches on method and headers and never looks at the path.
2. **The endpoint must be a class instance, not a function.** `Route.__init__` applies
   `request_response(endpoint)` when `inspect.isfunction(endpoint) or inspect.ismethod(endpoint)`
   — so a plain `async def endpoint(scope, receive, send)` (or a closure returning one) gets
   called as `endpoint(request)` and breaks. An object with an `async __call__` is not a
   function, so Starlette assigns it as the ASGI app verbatim.

```python
class MCPEndpoint:
    """One ASGI app per MCP server: authenticate, then hand the raw scope straight to the
    session manager. No internal path matching, so the mount prefix is irrelevant.
    An instance (not a function) so Starlette treats it as an ASGI app, not a view."""

    def __init__(self, server, role, canonical_url):
        self.server, self.role, self.canonical = server, role, canonical_url

    async def __call__(self, scope, receive, send):
        header = _get_header(scope, b"authorization")        # raw scope, no Request needed
        try:
            principal = authenticate(header, self.role, self.canonical)
        except AuthError as e:
            # 401 + full challenge (error, error_description, scope, resource_metadata)
            await challenge_response(e, self.role, self.canonical)(scope, receive, send)
            return
        token = set_principal(principal)                     # ContextVar, on the request task
        try:
            await self.server.session_manager.handle_request(scope, receive, send)
        finally:
            reset_principal(token)


@asynccontextmanager
async def lifespan(app):
    # Each session manager may be entered exactly once per process; both live for the
    # lifetime of the app. Accessing .session_manager constructs it on first use, which is
    # why it happens here and not at import time.
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(citizen.session_manager.run())
        await stack.enter_async_context(officer.session_manager.run())
        yield


routes = [
    Route("/mcp/citizen", MCPEndpoint(citizen, "citizen", CITIZEN_URL),
          methods=["POST", "GET", "DELETE"]),
    Route("/mcp/officer", MCPEndpoint(officer, "officer", OFFICER_URL),
          methods=["POST", "GET", "DELETE"]),
    Route("/.well-known/oauth-protected-resource/mcp/citizen", prm_citizen, methods=["GET"]),
    Route("/.well-known/oauth-protected-resource/mcp/officer", prm_officer, methods=["GET"]),
    Route("/.well-known/oauth-protected-resource", prm_by_query, methods=["GET"]),
    Route("/mcp/citizen/.well-known/oauth-protected-resource", prm_citizen, methods=["GET"]),
    Route("/mcp/officer/.well-known/oauth-protected-resource", prm_officer, methods=["GET"]),
]
app = Starlette(routes=routes, lifespan=lifespan, redirect_slashes=False)
```

Consequences worth stating:

- Both FastMCP instances are still built with `stateless_http=True`; `streamable_http_path` is
  now irrelevant, since `streamable_http_app()` is never called. (It is left at its default
  rather than set to `"/"`, to avoid implying a route that does not exist.)
- `redirect_slashes=False` means neither `/mcp/citizen` nor `/mcp/citizen/` is ever answered
  with a 307: the canonical path is handled, the trailing-slash form is a plain 404.
- All three methods are served on the exact path — POST (JSON-RPC), GET (the server→client SSE
  stream the spec permits) and DELETE (session teardown). A fourth method gets Starlette's 405.
- Auth runs **inside** this endpoint, before `handle_request`, so an unauthenticated request
  never reaches the session manager and `initialize` / `tools/list` are covered too.
- Caddy matches `/mcp/citizen`, `/mcp/officer`, `/mcp` and `/mcp/*` with no rewrite and never
  adds a slash.
- Verified in build step 7 by a `curl -i` loop that must show `200`/`401` and **never** `307`
  on the no-trailing-slash URL, for all three methods.

Conventions for every tool:
- Output is a compact JSON object rendered as text (plus `ImageContent` for `view_age_proof`).
  Never more than 20 rows; never a raw dump.
- Every time value is a pre-formatted IST string ending in `IST`.
- Every error message ends with the next action.
- Descriptions are written for a small model: what it does, when to call it, exact input
  formats, one short example.
- Identity comes from the token via the rule in §4.4; no citizen tool takes a `mobile`
  parameter.
- **Annotations are declared on every tool** (§5.3), so a client can tell a read from a
  decision before calling it.
- **No tool fabricates evidence.** Nothing in either server creates, generates, edits,
  converts or substitutes a document, and no tool states a fact about a file it has not read.
  The two tools that touch documents say so in their own descriptions (§5.1), and the officer
  side shows the recorded hash, size, filename and upload time rather than any assertion about
  them (§5.2).

### 5.1 Citizen server — `/mcp/citizen`, scope `citizen`

**`get_scheme_info`**
> Facts about the Purvanchal Old Age Pension: the amount, who qualifies, which documents are
> needed, how long a decision takes, and whether the application window is open right now.
> Call this first when the person asks what the scheme is, who can get it, or what papers are
> needed. No input.

Output: `{amount:"Rs 250 per month", min_age:60, residency:"resident of Purvanchal",
documents_accepted:["Birth certificate","School leaving certificate","Voter ID"],
formats:"JPG, PNG or PDF up to 5 MB", decision_days:15,
deemed_approval:"If no officer decides within 15 days, the application stands approved
automatically.", window:{open:true, closes:"31/10/2026 23:59 IST", time_left:"10 days 6 hours"},
blocks:[6 names], villages_by_block:{…}}` — window from config (§3-A2), never hardcoded.
Errors: none.

**`check_eligibility`**
> Checks whether this person can apply: age 60 or above from their date of birth, the window
> still open, and whether this mobile number already has a live application. Call before
> collecting details. Input: date_of_birth as DD/MM/YYYY, for example 10/04/1957. Other
> formats are accepted and corrected.

Input `{date_of_birth: string}`. Output `{age:69, age_ok:true, turns_60_on:null,
window_open:true, existing_application:null, eligible:true,
next_step:"call save_application_details"}`.
Errors: unreadable date → `"I could not read that date. Give it as DD/MM/YYYY, for example
10/04/1957."`; future date → `"That date is in the future. Please check the year."`
(explicitly not the misleading age message of §9-E2); under 60 → `"Age is 58. The pension is
for people 60 and above. She becomes eligible on 14/03/2028."`; window closed → the closing
date and that nothing can be filed; active application → `"This mobile number already has
application SSP26540132 (PENDING). One application per mobile number is the portal's rule. If
it is your own, use get_my_application. If it belongs to someone else who shares this phone,
they must apply from their own number or at the block office."` — no name and no other
personal detail of the other person (§9-E7).

**`save_application_details`**
> Saves or updates the applicant's details on the server. Send any subset of fields — call it
> several times as the conversation goes. It tells you what is saved, what is still missing
> and what is wrong. Fields: full_name, date_of_birth (DD/MM/YYYY), gender
> (Male/Female/Other), marital_status (Married/Unmarried/Widowed), husband_name (only if
> widowed), village (one of the 19 from get_scheme_info), block (exact spelling),
> bank_account (9–18 digits), ifsc (11 characters, e.g. SBIN0003077).
> Example: {"full_name":"Sewali Gogoi","date_of_birth":"10/04/1957","village":"Kathoni"}

Output `{saved:{…}, missing:["bank_account","age proof document"], problems:[…],
corrections:["date of birth read as 10/04/1957","IFSC upper-cased"],
suggested_block:"Dhemaji Pathar", ready_to_submit:false}`.
Behaviour: normalises DOB / IFSC / bank; matches the village case-insensitively against the
19 and **suggests the block** (§2-F-Q15) instead of letting an invented village through;
corrects block spelling; applies the new length rules so nothing can 500 later (§9-B5);
reports `validate_application` errors as `problems` without blocking the save.
Errors: unknown village → `"I do not know the village 'Pratapgarh'. Villages in Sonari are
Bhekulajan, Kakotibari, Lakhipur and Namdang. Ask which one is nearest, or give the block."`;
bad IFSC → `"The portal accepts an 11-character IFSC like SBIN0003077. 'UTBI0PUR2819' is 12
characters, so it will be refused — please check the passbook, or leave IFSC blank, as it is
not mandatory."` (§9-C1: 16,576 live rows carry exactly that code; IFSC really is optional,
§3-F).

**`get_document_upload_link`**
> Gives a link for uploading the age proof (birth certificate, school leaving certificate or
> Voter ID). The person opens it on a phone, or whoever is helping them uploads it with curl.
> A document is required before the application can be submitted. No input.
>
> Only a real document provided by the applicant may be uploaded — a photo or scan of the
> actual certificate they hold. You must never create, generate, draw, edit, fill in,
> convert or substitute a document, and never upload a file from anywhere other than the
> applicant. If they do not have their age proof to hand, give them the link and stop: the
> application waits until they upload it. An invented document is a false government record.

Output `{upload_url:"http://localhost:8000/upload/<32 chars>",
expires:"22/10/2026 11:40 IST", document_attached:false,
curl_example:"curl -F document=@age-proof.jpg http://localhost:8000/upload/<token>",
instructions:"Open the link on the phone, choose the photo of the birth certificate or Voter
ID, and press Upload. JPG, PNG or PDF, up to 5 MB.",
recorded:"Every upload is recorded with its SHA-256 hash, size, original filename and time,
and the block officer sees all four."}`.
When one is attached: `document_attached:true, document_name:"age-proof.jpg",
sha256:"3b1f…", byte_size:421337, uploaded:"21/10/2026 11:02 IST"` plus `"A document is
already attached. Uploading again replaces it."` A draft is created on demand; the token is
bound to the mobile from the token's `sub` and to nothing the model can set.

Note on the mechanics: the MCP server cannot accept file bytes through this tool at all — it
only issues a URL. The upload is an HTTP request from the applicant's own browser or their
helper's shell to the Flask portal. That is a structural guarantee, not a policy one.

**`submit_application`**
> Files the application with the portal. Only call after the details are complete, the age
> proof is uploaded, and you have read the declaration back to the person and they said yes.
> Input: confirm_declaration must be true, meaning the applicant has confirmed the information
> is correct and consents to the department verifying it.
>
> Everything filed must have come from the applicant. Never invent, guess or fill in a detail
> they did not give you — not a name, not a date of birth, not a village, not a bank account,
> and above all not the age-proof document, which must be a file the applicant themselves
> uploaded and which you must never create, generate or substitute. If something is missing,
> ask for it. A guessed field becomes a sworn declaration on a government record.

Input `{confirm_declaration: boolean}`. Output
`{application_number:"SSP26540132", status:"PENDING", submitted:"21/10/2026 10:05 IST",
what_happens_next:"A block officer decides within 15 days. If nobody decides, it stands
approved automatically on 06/11/2026 07:30 IST.", how_to_check:"Ask me any time. On the portal:
mobile number plus password, and the password is the date of birth written as DDMMYYYY — for
10/04/1957 that is 10041957.", sms:"A confirmation SMS has been sent to this number."}`.
Errors: `declaration_required` → `"I cannot submit until the applicant confirms the
declaration. Read the details back and ask whether all of it is correct."`;
`incomplete` → the `missing` list; `no_document` → `"The age proof is not uploaded yet. Use
get_document_upload_link."`; `invalid` → the exact `validate_application` strings;
`duplicate` → the existing number, its status, and the withdraw route. Race-safe via the
advisory lock, so a retry after a timeout cannot create a second application (§9-A2, §9-E11).

**`get_my_application`**
> The status of this mobile number's application, in plain words. Use it whenever the person
> asks whether it has been approved or what is happening, and after submitting. No input — it
> only ever reads the application belonging to the signed-in mobile number.

Output `{found:true, application_number, status:"PENDING", means:"The block officer has not
decided yet. This is normal.", submitted:"21/10/2026 10:05 IST", decided:"—",
auto_approval_if_no_decision:"06/11/2026 07:30 IST", village, block, age_proof_attached:true}`.
Status meanings: PENDING as above; APPROVED → `"Approved. Rs 250 per month will be credited to
the bank account by DBT."`; DEEMED_APPROVED → `"Nobody decided within 15 days, so by law it is
approved."`; REJECTED → plus the reason recorded in the audit trail; WITHDRAWN → plus
`"you may apply again"`. `found:false` → `"No application on this mobile number yet. Call
check_eligibility to start one."`

**`withdraw_application`**
> Withdraws a pending application so the person can apply again. Only their own, only while it
> is still pending. Input: application_no (e.g. SSP26540132) and confirm must be true. Ask the
> person out loud before calling this.

Output `{status:"withdrawn", application_number, next:"You may submit a new application for
this mobile number now."}`.
Errors: `confirm` false → `"Not withdrawn. Ask the applicant to confirm first."`; wrong number
→ `"That application number does not belong to this mobile number."` (nothing about whose it
is); not pending → `"Only a pending application can be withdrawn. This one is APPROVED."`

**`get_number_verification_link`** and `applicant_mobile` — *added by amendment 11; the descriptions in `app/mcp_server/citizen.py` are the reference.*

### 5.2 Officer server — `/mcp/officer`, scope `officer`

**`get_queue_summary`**
> What is waiting in the queue: pending counts per block, how many are past the 15-day
> statutory deadline, and which ones will be deemed approved in the next two days. Call this
> first when the officer asks what is waiting or what is urgent. No input.

Output `{pending_total:12, by_block:[{block:"Sonari", pending:4}, …], overdue_15d:3,
deemed_within_48h:[{application_no, block, deemed_on:"23/10/2026 07:30 IST"}],
oldest_pending:"02/10/2026 14:30 IST", note:"Anything not decided within 15 days is approved
automatically by law."}`.

**`list_applications`**
> Lists applications oldest first, 20 per page. Call with no arguments for the pending queue.
> status: PENDING, APPROVED, DEEMED_APPROVED, REJECTED or WITHDRAWN (case does not matter).
> block: one of the six block names. overdue_only: true for those past 15 days. search: an
> application number, a mobile number, or part of a name. page starts at 1.
> Example: {"block":"Sonari","overdue_only":true}

Output `{total:37, page:1, pages:2, showing:20, rows:[{id, application_no, name, mobile,
block, status, submitted:"02/10/2026 14:30 IST", days_pending:19}]}`.
Errors: bad status → `"status must be one of PENDING, APPROVED, DEEMED_APPROVED, REJECTED,
WITHDRAWN."`; bad block → the six names; `page` ≤ 0 or non-numeric is coerced to 1 (§9-B2);
`page` past the end → `rows: []` plus `"Page 3 is past the end; there are 2 pages."`

**`get_application`**
> The full record of one application, its history, and any eligibility problems the officer
> should see before deciding. Identify it by application_id (the id the other tools return) or
> application_no (e.g. SSP26540132). Example: {"application_no":"SSP26540132"}

Output `{id, application_no, name, mobile, date_of_birth:"10/04/1957", age_today:69, gender,
marital_status, husband_name, village, block, bank_account, ifsc,
age_proof:"attached"|"none", status, submitted:"…IST", decided:"…IST"|"—", decided_by,
days_pending, deemed_on:"06/11/2026 07:30 IST"|null,
document:{recorded:true, original_name:"voter-id.jpg", sha256:"3b1f…9ac4", byte_size:421337,
          content_type:"image/jpeg", uploaded:"21/10/2026 11:02 IST", source:"upload_token"},
warnings:["Age today is 58 — below the 60-year minimum.","No age-proof document is attached."],
history:[{when:"02/10/2026 14:30 IST", action:"SUBMIT", by:"applicant:9876543210", note:""}]}`.
History matches both `WITHDRAW` and `WITHDRAWN` and both actor formats (§9-C3). Warnings are
computed, never guessed; an empty list is reported as `"No eligibility problems found."`
The `document` block is read from `document_uploads` — it is the record of what arrived, so
the officer can see the file's hash, true size, original filename and upload time rather than
anyone's description of them. For a web-form or historical application there is no row:
`document:{recorded:false, reason:"uploaded through the web form or predates this release"}`.
Errors: not found → `"No application with that id or number."`; both or neither argument →
`"Give exactly one of application_id or application_no."`

**`view_age_proof`** — *superseded by amendment 10: replaced by `get_age_proof_link`, which returns the officer's link to `/admin/application/<id>/document` and the recorded provenance, never the document.*
> Returns the uploaded age-proof document as an image so you can actually read it. PDFs are
> rendered as an image of the first page. Call this before approving or rejecting on document
> grounds. Input: application_id.

Output: `ImageContent` (PNG or JPEG, downscaled to ≤1600 px on the long side) plus one text
line carrying the provenance as recorded, not as described:
`"Age proof for SSP26540132 — original filename voter-id.jpg, 411.5 KB (421,337 bytes),
SHA-256 3b1f…9ac4, uploaded 21/10/2026 11:02 IST via the applicant's upload link. The date of
birth on record is 10/04/1957. What the image shows is for you to judge."`
PDFs are rendered at 150 dpi with `pypdfium2`; the text line then says
`"page 1 of N rendered at 150 dpi"` and the hash is of the **original PDF**, not the render.
If `document_uploads` has no row (web form or historical), the line says
`"provenance not recorded (uploaded through the web form or predates this release)"` and gives
the on-disk size only.
Errors: no document → `"No age-proof document is attached to this application. Almost every
application in the historical data has none, so this is common. Do not record a judgement
about a document you cannot see."` (§9-C2, §9-E15); file missing on disk → says so and names
the recorded path; render failure → `"This is a PDF I could not render. Open it in the portal
at /admin/application/<id>/document."`

**`approve_application`**
> Approves a pending application in the officer's name. Pass both application_id and
> application_no — they must refer to the same application; that is the confirmation step, so
> there is no second question. The optional note is recorded in the audit trail.
> Example: {"application_id":100021,"application_no":"SSP26540132"}

Output `{status:"approved", application_no, decided_by:"admin",
decided_at:"21/10/2026 16:20 IST", recorded_in_audit_as:"officer:admin via assistant",
citizen_notified:true, message:"Approved. An SMS has been sent to 9876543210."}`.
If the SMS fails: `citizen_notified:false` and `"Approved, but the SMS could not be sent — the
applicant has NOT been notified."` (§9-E19).
Errors: mismatch → `"application_id 100021 is SSP26184691, not SSP26540132. Nothing was
changed — check with get_application."`; not pending → `"Only a pending application can be
decided; this one is APPROVED."`; blocked → `"Not approved. The applicant's age today is 58,
below the 60-year minimum — the counter would refuse this application. If the date of birth on
the document differs from the record, reject with 'age proof does not match stated date of
birth' and ask the applicant to apply again with the correct date."`

**`reject_application`**
> Rejects a pending application with a reason recorded against the officer's name. reason must
> be one of: "bank account not in applicant's name", "duplicate of an earlier beneficiary
> record", "age proof document illegible", "age proof does not match stated date of birth", or
> "other" with an explanation in note. Pass application_id and application_no; they must match.
> Example: {"application_id":100021,"application_no":"SSP26540132","reason":"age proof document illegible"}

Output: as approve, with `status:"rejected"` and the reason echoed.
Errors: missing or blank reason → the four canonical reasons listed (§2-F-Q16, §9-E18);
`reason:"other"` with no note → `"Give the reason in note when reason is 'other'."`; mismatch
and not-pending as above. A rejection is never blocked by eligibility warnings.

No bulk tools, no list tool that can decide, and no tool that writes without an explicit
id + number pair.

### 5.3 Tool annotations

Declared on every tool, so a client can distinguish a lookup from an irreversible decision
before calling. Note that `destructiveHint` defaults to **true** for a non-read-only tool in
the MCP spec, so the additive writers set it to `false` explicitly rather than leaving it
implied.

| tool | `readOnlyHint` | `destructiveHint` | `idempotentHint` | title |
|---|---|---|---|---|
| `get_scheme_info` | **true** | — | — | Scheme information |
| `check_eligibility` | **true** | — | — | Check eligibility |
| `get_my_application` | **true** | — | — | My application status |
| `get_document_upload_link` | false | false | true | Get an upload link |
| `get_number_verification_link` (amendment 11) | false | false | true | Verify another mobile number |
| `save_application_details` | false | false | true | Save applicant details |
| `submit_application` | false | false | false | File the application |
| `withdraw_application` | false | **true** | false | Withdraw the application |
| `get_queue_summary` | **true** | — | — | Queue summary |
| `list_applications` | **true** | — | — | List applications |
| `get_application` | **true** | — | — | Open a case |
| `get_age_proof_link` (was `view_age_proof`, amendment 10) | **true** | — | — | Age-proof link |
| `approve_application` | false | **true** | false | Approve (final) |
| `reject_application` | false | **true** | false | Reject (final) |

Rationale for the three `destructiveHint: true` tools: all four application states are
terminal — there is no un-withdraw, no un-reject and no re-open anywhere in the portal
(§2-C), so each of these is a one-way door for the citizen's pension.
`openWorldHint` is left at its default on every tool; nothing here reaches outside the
portal. `save_application_details` and `get_document_upload_link` are idempotent in the sense
that repeating them converges on the same draft state; `submit_application` is not, which is
exactly why it holds the advisory lock.

---

## 6. docker-compose, proxy, env, running locally

### 6.1 `docker-compose.yml`

```yaml
services:
  db:        # unchanged

  app:
    build: ./app
    expose: ["8000"]                 # was ports: 8000:8000 — the proxy now owns the host port
    environment:
      ADMIN_USERNAME: ${ADMIN_USERNAME:-admin}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD:-change-me-before-deploying}
      PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-http://localhost:8000}
      SECRET_KEY: ${SECRET_KEY:?set SECRET_KEY in .env}      # §9-D1
      SCHEME_DEADLINE: ${SCHEME_DEADLINE:-}                  # empty = app.ini value
    depends_on: [db, smsgw]
    volumes: [uploads:/var/sewasetu/uploads, applogs:/var/log/sewasetu]

  mcp:
    build: ./app                     # same image
    command: ["sh","-c","python /app/scripts/apply_migrations.py && exec uvicorn mcp_server.main:app --host 0.0.0.0 --port 8080 --workers 1"]
    expose: ["8080"]
    environment:
      PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-http://localhost:8000}
      SECRET_KEY: ${SECRET_KEY:?}
      ADMIN_USERNAME: ${ADMIN_USERNAME:-admin}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD:-change-me-before-deploying}
      SCHEME_DEADLINE: ${SCHEME_DEADLINE:-}
    depends_on: [db, app, smsgw]
    volumes: [uploads:/var/sewasetu/uploads:ro, applogs:/var/log/sewasetu]

  proxy:
    image: caddy:2-alpine
    ports: ["8000:8000"]
    volumes: [./proxy/Caddyfile:/etc/caddy/Caddyfile:ro, caddydata:/data]
    depends_on: [app, mcp]

  scheduler: # unchanged
  smsgw:     # unchanged

volumes: {pgdata:, uploads:, applogs:, caddydata:}
```
The `uploads` volume is read-only on `mcp`: the MCP layer only ever reads documents (Flask
writes them), which also fixes the §1 note that nothing outside `app` could read an age proof.
`--workers 1` keeps `stateless_http` simple in Phase 0; it is not a scaling claim.
`mcp_server.main` does `import app as portal` before anything else, preserving the §7-C import
order.

### 6.2 `proxy/Caddyfile`

```
{
  auto_https off
}

:8000 {
  # exact paths first, then the subtree. No rewrite, no uri strip_suffix, no redir:
  # /mcp/citizen must reach the MCP server as /mcp/citizen, never as /mcp/citizen/.
  @mcp path /mcp/citizen /mcp/officer /mcp /mcp/* /.well-known/oauth-protected-resource*
  handle @mcp {
    reverse_proxy mcp:8080 {
      flush_interval -1          # stream responses, no buffering
    }
  }
  handle {
    reverse_proxy app:8000
  }
  log
}
```
Caddy does not add trailing slashes on its own (that would need an explicit `redir`), and
`Starlette(redirect_slashes=False)` makes sure the MCP app does not either — amendment 1 is
enforced at both hops and asserted by the §7.1 pre-flight.

`/.well-known/oauth-authorization-server` and `/.well-known/jwks.json` fall through to Flask,
which is the AS half. Phase 2 replaces `:8000` with the hostname and drops `auto_https off`;
nothing else changes.

### 6.3 `.env` (local)

```
ADMIN_PASSWORD=pick-something
SECRET_KEY=<openssl rand -hex 32>
PUBLIC_BASE_URL=http://localhost:8000
```

### 6.4 Running

```bash
# 0. CLEAN DATABASE FIRST. The current pgdata volume carries the audit's leftovers
#    (§2-G: ids 100012-100016, including the duplicate active pair on 9000000012, plus
#    stale OAuth clients and OTPs). Those would mask exactly the regressions we test for.
docker compose down -v

# 1. everything EXCEPT the scheduler, so the seed's 700 PENDING rows survive (§9-A1)
docker compose up -d --build db app mcp proxy smsgw
#    first boot reloads schema.sql + seed.sql (~36 MB, give it a minute) and
#    apply_migrations.py adds the Phase 0 DDL before uvicorn starts

# 2. put clean work in the officer queue, through the service layer (never SQL):
docker compose exec mcp python /app/scripts/seed_demo_queue.py --count 8
#    8 drafts + a generated age-proof PNG each + services.submit, on mobiles
#    9000001001..9000001008 using the 19 real villages. Prints the application numbers.

# 3. the deemed-approval sweep, only when you want it:
docker compose up -d scheduler        # deems approved anything pending > 15 days
```
A test stack with a closed window:
```bash
SCHEME_DEADLINE="2026-10-01 00:00" docker compose up -d --force-recreate app mcp
```

### 6.5 `seed_demo_queue.py` — local use only, and visibly so

The officer queue needs work to look at (§9-A1), and the honest way to create it is through
the service layer. Each synthetic applicant needs an age proof, so the script generates one —
and a generated document must never be mistakable for a citizen's real paper:

- Every generated page carries **`SAMPLE – DEMO DATA`** as large dark text across the middle
  of the image, plus a second line `not a real document — generated by seed_demo_queue.py`
  and the generation timestamp. The watermark is drawn first and the synthetic "certificate"
  fields over it, so it cannot be cropped out of the visible area.
- `document_uploads.source` is `"demo_seed"`, not `"upload_token"`, so `get_application` and
  `view_age_proof` show the officer where the file came from.
- Mobiles are confined to `9000001001`–`9000001099` and names are prefixed `Demo`, so the
  rows are trivially identifiable and deletable.
- The script refuses to run unless `PUBLIC_BASE_URL` points at `localhost`/`127.0.0.1`, and
  prints `LOCAL DEMO DATA — do not run against the deployment` on every invocation. It is
  **not** used in Phase 2, and the deployment's queue comes from real test conversations and
  the surviving seed rows.
- Documented in the same terms in `README`-adjacent notes and at the top of the script.

It writes nothing with raw SQL: it calls `services.save_draft`, `services.issue_upload_token`,
`services.attach_draft_document` and `services.submit`, i.e. exactly the path a citizen's
assistant takes.

---

## 7. Manual test script (Phase 0)

### 7.1 Register both servers with Claude Code

```bash
claude mcp add --transport http sewasetu-citizen http://localhost:8000/mcp/citizen
claude mcp add --transport http sewasetu-officer http://localhost:8000/mcp/officer
claude mcp list                      # both show "needs authentication"
```
Then, in Claude Code: `/mcp` → `sewasetu-citizen` → Authenticate. A browser opens at
`/oauth/login`.

**Citizen sign-in.** Enter the mobile (e.g. `9000002001`), then read the OTP:
```bash
curl -s "http://localhost:8000/__gateway/api/messages?to=9000002001" | python -m json.tool
# "text" is null until the carrier "delivers" — wait 1-4 s and read again (§8-C)
```
or watch `http://localhost:8000/__gateway/`. Enter the OTP, press **Allow**.

**Officer sign-in.** `/mcp` → `sewasetu-officer` → Authenticate → username `admin`, password
`$ADMIN_PASSWORD` → **Allow**.

**Program token (unattended officer).** `/admin` → `/admin/tokens`: label `eval-harness`,
**audience `http://localhost:8000/mcp/officer`** (exact), days 7 → copy the JWT.
```bash
curl -s -X POST http://localhost:8000/mcp/officer \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 400
```

Pre-flight:
```bash
# 401 with the full challenge: error, error_description, scope, resource_metadata
curl -i -X POST http://localhost:8000/mcp/citizen -d '{}' | sed -n '1p;/WWW-Authenticate/p'
curl -i -X POST http://localhost:8000/mcp/officer -d '{}' | grep -o 'scope="[a-z]*"'   # scope="officer"

# NO REDIRECT on the canonical path, for every method. Must print 401 or 200, never 307/308.
for m in POST GET DELETE; do
  printf '%s -> ' "$m"
  curl -s -o /dev/null -w '%{http_code}\n' -X "$m" http://localhost:8000/mcp/citizen
done
curl -s -o /dev/null -w 'redirects=%{num_redirects} final=%{url_effective}\n' \
     -L -X POST http://localhost:8000/mcp/citizen        # redirects=0

curl -s http://localhost:8000/.well-known/oauth-protected-resource/mcp/officer
curl -s http://localhost:8000/.well-known/oauth-authorization-server | grep issuer
```

Shorthand below: `psql` = `docker compose exec -T db psql -U sewasetu -d sewasetu -c`.

### 7.2 Scenarios

**S1 — happy path, citizen, document by curl.**
Say: *"My grandmother Sewali Gogoi, born 10/04/1957, lives in Kathoni. Help her apply.
Account 90155123456, IFSC SBIN0003077."* Expect `check_eligibility` → eligible;
`save_application_details` (block auto-suggested **Dhemaji Pathar**);
`get_document_upload_link`; the upload; `submit_application` after an explicit yes.
```bash
curl -F document=@age.jpg "http://localhost:8000/upload/<token>"
```
```sql
SELECT id, application_no, applicant_name, dob, village, block, ifsc, status,
       doc_path <> '' AS has_doc, decided_by
FROM applications WHERE mobile = '9000002001' ORDER BY id DESC LIMIT 1;
SELECT action, actor, note FROM audit_log
WHERE application_id = (SELECT max(id) FROM applications WHERE mobile = '9000002001');
SELECT count(*) FROM agent_drafts WHERE mobile = '9000002001';
-- provenance survived the submit and is stamped with the application id
SELECT application_id, original_name, sha256, byte_size, source, uploaded_at
FROM document_uploads WHERE mobile = '9000002001';
```
Expect: one row, `status=PENDING`, `has_doc=t`, `block=Dhemaji Pathar`, `decided_by` NULL;
exactly one `SUBMIT` / `applicant:9000002001` audit row; `agent_drafts` count **0** (cleared
on submit); one `document_uploads` row with `application_id` set, `source='upload_token'`,
`original_name='age.jpg'`, and `sha256` equal to `sha256sum age.jpg` on the host; and a
confirmation SMS in `/__gateway/api/messages?to=9000002001`.

**S2 — under 60.** *"My father is 58, born 03/08/1968."* Expect a refusal naming the age and
the date he becomes eligible; nothing is written.
```sql
SELECT count(*) FROM applications WHERE mobile = '9000002002';   -- 0
```

**S3 — bad DOB format.** *"She was born 1957-04-10."* Expect it accepted and normalised (the
tool normalises what the portal would reject, §9-E1).
```sql
SELECT data->>'date_of_birth' FROM agent_drafts WHERE mobile = '9000002003';  -- 10/04/1957
```
Then *"born 32/13/1957"* → a clear format error, draft unchanged.

**S4 — submit with no document.** Fill everything, then *"submit it"*. Expect a refusal that
names `get_document_upload_link`.
```sql
SELECT count(*) FROM applications WHERE mobile = '9000002004';   -- 0
```

**S5 — duplicate active application.** With S1's citizen signed in: *"apply again for my aunt
on this phone"*. Expect the kind explanation with the existing number and status, and no other
person's name.
```sql
SELECT count(*) FROM applications
WHERE mobile = '9000002001' AND status IN ('PENDING','APPROVED','DEEMED_APPROVED');  -- 1
```
Race regression test for §9-A2:
```bash
for i in 1 2 3; do curl -s -X POST http://localhost:8000/mcp/citizen \
  -H "Authorization: Bearer $CIT" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"submit_application","arguments":{"confirm_declaration":true}}}' & done; wait
```
```sql
SELECT mobile, count(*) FROM applications
WHERE status IN ('PENDING','APPROVED','DEEMED_APPROVED')
GROUP BY mobile HAVING count(*) > 1;        -- expect 0 rows
```

**S6 — withdraw, then reapply.** *"Cancel it"* → confirm → `withdraw_application`; then apply
again end to end.
```sql
SELECT id, application_no, status, decided_by FROM applications
WHERE mobile = '9000002001' ORDER BY id;
-- first row WITHDRAWN / APPLICANT, second row PENDING / NULL
SELECT action, actor FROM audit_log WHERE application_id = <first id> ORDER BY at;
-- SUBMIT, WITHDRAW
```

**S7 — status check.** *"Has it been approved yet?"* → `get_my_application`: PENDING, plain
meaning, submitted time in IST, auto-approval date.
```sql
SELECT submitted_at,
       date_trunc('day', submitted_at + interval '16 days') + interval '2 hours'
         + interval '5 hours 30 minutes' AS expected_deemed_ist
FROM applications WHERE mobile = '9000002001' AND status = 'PENDING';
```
`auto_approval_if_no_decision` must equal `expected_deemed_ist` (§2-F-Q13), and `submitted`
must equal `submitted_at + 5:30`, labelled IST.

**S8 — citizen token on the officer endpoint.**
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/mcp/officer \
  -H "Authorization: Bearer $CITIZEN_JWT" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'        # expect 403
```
And the reverse, `$OFFICER_JWT` against `/mcp/citizen` → 403. Also confirm that in the citizen
Claude Code session `/mcp` lists **only** the 7 citizen tools, with no officer tool visible.

**S9 — closed window.**
```bash
SCHEME_DEADLINE="2026-10-01 00:00" docker compose up -d --force-recreate app mcp
```
`get_scheme_info` → `window.open:false` with the closing date; `check_eligibility` → not
eligible, window closed; `submit_application` → refused with `"the application window has
closed"`.
```sql
SELECT count(*) FROM applications WHERE mobile = '9000002009';   -- 0
```
Restore with `docker compose up -d --force-recreate app mcp` (no override).

**S10 — officer: queue → case → document → approve.**
*"What is waiting in Dhemaji Pathar?"* → `get_queue_summary` / `list_applications`;
*"show me the oldest one"* → `get_application`; *"let me see the age proof"* →
`view_age_proof` renders the image; *"approve it"* → `approve_application` with id + number.
```sql
SELECT id, application_no, status, decided_by, decided_at FROM applications WHERE id = <id>;
-- APPROVED / admin / now (UTC)
SELECT action, actor, note FROM audit_log WHERE application_id = <id> ORDER BY at;
-- SUBMIT …; APPROVED | officer:admin via assistant | <note or ''>
```
```bash
curl -s "http://localhost:8000/__gateway/api/messages?to=<mobile>" | grep -c approved   # 1
```
Then check the web view the Director will look at:
`http://localhost:8000/admin/application/<id>` → status APPROVED, the audit row present, and
the document link works.

**S11 — officer: reject without a reason, then with one.** *"Reject it"* → the tool refuses
and lists the four canonical reasons.
```sql
SELECT status FROM applications WHERE id = <id>;                 -- still PENDING
```
*"Reject it — the age proof is illegible"* → rejected.
```sql
SELECT status, decided_by FROM applications WHERE id = <id>;     -- REJECTED / admin
SELECT action, note FROM audit_log WHERE application_id = <id> ORDER BY at DESC LIMIT 1;
-- REJECTED | age proof document illegible
```
And on the web form, POST `/admin/reject/<id>` with an empty note now flashes
`A reason is required to reject an application.` and changes nothing.

**S12 — officer: approve someone ineligible (the §9-E16 guard).**
```sql
SELECT id, application_no, dob,
       date_part('year', age(current_date, dob))::int AS age_today
FROM applications WHERE status = 'PENDING' ORDER BY dob DESC LIMIT 3;
```
Ask the assistant to approve the youngest. Expect `approve_application` → blocked, with the
age explained; status unchanged.

**S13 — mismatched id and number.** `approve_application(application_id=<A>,
application_no=<B of another row>)` → refused, nothing written.
```sql
SELECT id, status FROM applications WHERE id IN (<A>, <B>);       -- both unchanged
```

**S14 — revoked / ended session.** `/admin/tokens` → **Revoke** on the `eval-harness` row,
then repeat the curl from §7.1 → 401 with a `please sign in again` description.
```sql
SELECT label, revoked_at FROM oauth_program_tokens ORDER BY id DESC LIMIT 1;  -- revoked_at set
```
Also confirm the §6-F2 fix: a cookie-less `POST /oauth/consent?rid=<a live rid>` with
`decision=allow` now renders "Request expired" instead of issuing a code.

**Standing invariants, after the whole run:**
```sql
-- no duplicate application numbers
SELECT count(*) FROM (SELECT application_no FROM applications
                      GROUP BY 1 HAVING count(*) > 1) s;                                  -- 0
-- no mobile with two live applications
SELECT count(*) FROM (SELECT mobile FROM applications
   WHERE status IN ('PENDING','APPROVED','DEEMED_APPROVED')
   GROUP BY 1 HAVING count(*) > 1) s;                                                     -- 0
-- every application still has a SUBMIT row
SELECT count(*) FROM applications a WHERE NOT EXISTS
  (SELECT 1 FROM audit_log l WHERE l.application_id = a.id AND l.action = 'SUBMIT');      -- 0
-- nothing written in this phase lacks an audit row
SELECT count(*) FROM applications WHERE id > 100016 AND NOT EXISTS
  (SELECT 1 FROM audit_log l WHERE l.application_id = applications.id);                   -- 0
```

---

## 8. Build order

Each step leaves the stack working and has its own check. **I stop after each check and hand
back to you before starting the next step.**

| # | step | done when |
|---|---|---|
| 0 | `docker compose down -v` — discard the audit's leftover pgdata (§2-G) and start from the pristine seed | the volume is gone (`docker volume ls` shows no `*_pgdata`); after step 1's boot, `SELECT count(*) FROM applications;` = **100000**, `SELECT status, count(*) … GROUP BY status` shows **PENDING = 700**, and `SELECT count(*) FROM applications WHERE id > 100000;` = **0** |
| 1 | `proxy/Caddyfile`, compose changes (app un-published, proxy on 8000, `SECRET_KEY`) | `http://localhost:8000/` serves the portal through Caddy and `/admin` login works; `docker compose exec app python -c "import app; print(app.app.secret_key[:6])"` shows the env value |
| 2 | `migrations/002_phase0.sql` + `scripts/apply_migrations.py` | running it twice is a no-op; `\d agent_drafts` and `idx_app_no_unique` exist |
| 3 | `services.py` skeleton: pool, `db()`, constants, `to_ist`, `deemed_date`, `window_status`, `normalise` | `docker compose exec app python -c "import app, services; print(services.deemed_date(…), services.window_status())"` matches the S7 SQL |
| 4 | portal fixes (a)–(h): retry, length rules, `_submit_locked`, rewired `handle_submission` / `withdraw` / `_admin_decide` | the **web** flow files an application end to end; the S5 race loop yields one row; a web reject with an empty note is refused; approve and reject now send SMS |
| 5 | officer document route, `application_document`, `admin_view.html` link | `/admin/application/<id>/document` serves the one row that has a `doc_path`; 404 otherwise; a path outside `UPLOAD_DIR` is refused |
| 6 | draft service functions + `/upload/<token>` + `upload_token.html` + `document_uploads` provenance | a token issued from `python -c` accepts a phone-browser upload **and** `curl -F`; `.txt` and a 6 MB file are refused; two uploads produce two distinct filenames; `SELECT original_name, sha256, byte_size, source, uploaded_at FROM document_uploads` matches `sha256sum` of the file on disk |
| 7 | `mcp_server/main.py` + `auth.py`: per-server `MCPEndpoint` ASGI wrappers on the exact paths (auth → `session_manager.handle_request`), both session managers in the lifespan, PRM documents, full 401 challenge, **plus `oauth.py` (a) loopback equivalence and (c) scope-from-resource** — no tools yet | the §7.1 pre-flight block passes in full: 401 carries `error`, `error_description`, `scope` and `resource_metadata`; `scope="citizen"`/`"officer"` are correct per server; POST/GET/DELETE on `/mcp/citizen` return 401 or 200 and **never 307/308**, `-L` reports `redirects=0`; both PRM documents fetch; `claude mcp add` + `/mcp` completes OAuth for **both** servers and shows connected with 0 tools, with `scope`/`role` in the minted token matching the server signed into (decode the JWT to confirm) |
| 8 | citizen tools `get_scheme_info`, `check_eligibility` | `/mcp` lists 2 tools; S2 and S9 pass |
| 9 | citizen tools `save_application_details`, `get_document_upload_link`, `submit_application` | S1, S3, S4, S5 pass |
| 10 | citizen tools `get_my_application`, `withdraw_application` | S6, S7 pass |
| 11 | `oauth.py`: (b) rid↔session binding and (d) program-token revocation + template ((a) and (c) landed in step 7) | re-authenticating both servers from a clean Claude Code still works; the cookie-less `POST /oauth/consent?rid=…` exploit (§6-F2) is refused; S14 passes |
| 12 | officer tools `get_queue_summary`, `list_applications`, `get_application` | S10's read half passes; `page=0` and `status=pending` behave (no 500, no silently empty queue) |
| 13 | officer tool `view_age_proof` (+ `pypdfium2`) | an image and a PDF both render in Claude Code; the hash and byte size shown match `sha256sum` / `ls -l` on the file; the no-document and no-provenance messages appear for a seeded historical row |
| 14 | officer tools `approve_application`, `reject_application` | S10–S13 pass; audit actor and `decided_by` are as specified; stop `smsgw` and confirm `citizen_notified:false` is reported honestly |
| 15 | `scripts/seed_demo_queue.py` | 8 pending applications appear in `get_queue_summary`, each with a document, created with no raw SQL; the generated image visibly reads `SAMPLE – DEMO DATA` when opened through `view_age_proof`; `document_uploads.source = 'demo_seed'` for all 8; the script refuses to run with a non-localhost `PUBLIC_BASE_URL` |
| 16 | full §7 run + the invariant SQL, written up in `docs/phase0-test-log.md` | every scenario matches its expected database state |

---

## 9. Risks and open questions

**All defaults below were accepted on review (2026-10-21).** They are kept in the plan as the
record of what was decided and why, not as open questions. R1 and R2 are still the two things
to watch during step 7.

**R1 — How Claude Code requests scope (highest risk; mitigated).** The portal needs exactly
one scope and silently defaults to `citizen` (§6-D). If Claude Code sends no scope, or two,
the officer sign-in would return a citizen token that then fails the officer `aud`/role check
— a confusing dead end. Mitigation: §2.2(c) derives the scope from the `resource` when it is
one of our two canonical URLs, and each PRM document advertises exactly one scope.
**Verify this first at step 11.** If Claude Code also omits `resource`, the fallback is a
pair of signed-in entry URLs that pre-set the scope — more code, same outcome.

**Observed at step 7 (2026-10-21):** Claude Code signs in as a **CIMD** client, not by DCR:
`client_id = https://claude.ai/oauth/claude-code-client-metadata` (`oauth_clients.kind =
'cimd'`, redirect URIs `http://localhost/callback` and `http://127.0.0.1/callback`). It sent
`resource` = the canonical server URL, and the minted tokens carried the matching `aud`,
`scope` and `role` for both servers. The CIMD fetch path (`load_client`, §6-C / D10) is
therefore on the critical path for sign-in, and the deployed portal must be able to reach
`claude.ai` over HTTPS.

**R2 — Trailing slash and host spelling.** `resource=…/mcp/officer/` yields an `aud` with a
slash; handled by comparing `aud.rstrip("/")`. A different host spelling (`127.0.0.1` vs
`localhost`) is correctly rejected; the test script uses `localhost` throughout, and
`PUBLIC_BASE_URL` is the single source of the canonical strings.

**R3 — `pypdfium2` in the image.** *(Moot since amendment 10: removed.)* A pure wheel with a bundled binary; expected to install on
`python:3.11-slim` with no apt packages. If it does not, `view_age_proof` falls back to text
for PDFs and still returns images. Not a blocker.

**R4 — The historical corpus looks broken by design.** 100,000 of 100,001 rows have no
document and 16.6% carry an IFSC the portal's own validator rejects (§9-C1, §9-C2), so the
officer tools emit warnings on nearly every seeded case. That is honest and intended, but a
demo that browses history looks noisy; `seed_demo_queue.py` provides clean cases. Open
question: keep `view_age_proof`'s "no document" wording as blunt as drafted?

**R5 — One officer identity (§5-D, §10-Q1/Q2).** `decided_by` is always `admin` and
`audit_log.actor` is `varchar(50)`, so the only place the channel can be recorded is that
free-text actor. Locked: no officer accounts, no block scoping. **Default I will proceed
with:** `officer:admin via assistant`. Flagged because the Director's 2:30 line ("recorded
against her name") is not fully satisfiable without a portal change you have ruled out.

**R6 — The shared-phone rule (§10-Q7).** One active application per *mobile* stays.
`check_eligibility` explains it without naming the other person. Residual: the **web** form's
existing flash still names the other person's application number (`app.py:386`) — unchanged,
because the locked list says keep the pages as they are. Say the word and I will soften it.

**R7 — The deemed-approval sweep during the test window (§10-Q5).** The scheduler stays as-is
and the run instructions start the stack without it, so the seed's 700 PENDING rows survive
(§9-A1). Start `scheduler` and those 700 become `DEEMED_APPROVED` in seconds; the queue is
then whatever `seed_demo_queue.py` created. **Default:** scheduler off during manual testing,
on when you want to demonstrate deemed approval.

**R8 — Access tokens outlive revocation by ≤20/30 min** (D7). No fix in Phase 0; there is no
stored link from an access token to its refresh row. Program tokens *are* revocable now, by
`jti`.

**R9 — `/__gateway/` stays public** (locked; §9-D2, §10-Q9). Anyone who can reach the
deployment can read any OTP and so act as any citizen. It is required for testing. Phase 2
should at least put it behind the admin session or an IP allow-list on the public VM — your
decision.

**R10 — Could not resolve from the code.** (a) Whether the four rejection reasons are current
departmental policy or a seed artefact (§10-Q12) — I am treating them as the enum with
`"other" + note` as the escape hatch. (b) Whether an officer should ever be able to approve a
case today's `validate_application` would refuse (§10-Q6) — I am blocking hard failures (age,
missing document) on the **agent** channel only and warning on soft ones, which is my reading
of Director 2:09; the web form keeps today's authority. Both are one-line changes if you
decide otherwise.

---

## 10. Phases 1–2 (outline)

**Phase 1 — evals.** 8–12 invented citizens, each with a name, age, village, block, bank
details, a way of speaking, and a machine-checkable expected end state in the portal: exact
row count, status, block, document presence, audit actions, SMS count. The cast spans an
elderly applicant alone on a kiosk, a grandson on a bus, a CSC operator doing three in a row,
a widow with no IFSC, a 58-year-old, two people on one phone, and an officer clearing an
overdue queue. A harness (`evals/run.py`) drives a **real** MCP client — Claude Code headless
with `--mcp-config`, a small model and a turn cap — against a throwaway stack, minting each
persona's token through the real OAuth flow (OTP read from the gateway JSON), then asserts the
database with the SQL from §7 and stores the transcript. Results land in `eval_runs` /
`eval_assertions` and render at `/eval-dashboard` (a new Flask route): personas, transcripts,
per-assertion pass/fail, pass rate by persona and by scenario, and what changed in the tool
descriptions after each round. The point of the phase is that loop: every failure becomes
either a tool-description edit or a validation fix, and the dashboard shows which.

**Phase 2 — deployment.** One VM, the same compose files; Caddy's `:8000` block becomes
`sewasetu.<domain>` with automatic TLS, and `PUBLIC_BASE_URL=https://sewasetu.<domain>` so
`iss`, both canonical resource URLs and every discovery document rewrite themselves — nothing
else changes, which is the whole reason for the one-origin proxy in Phase 0. Add: real
`SECRET_KEY` and `ADMIN_PASSWORD` in an operator-only `.env`, `restart: unless-stopped`,
a Postgres dump cron, log rotation for `applogs`, an uptime check hitting `/` and both PRM
documents, and a decision on `/__gateway/` exposure (R9). Then re-run the §7 script against
the public URL with Claude Code pointed at `https://…/mcp/citizen` and `/mcp/officer`,
re-issue the officer program token with the HTTPS audience, and hand over the officer login,
the two endpoints, the `/eval-dashboard` URL and the one-page design note.
