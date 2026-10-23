# Phase 0 test log — final record

Phase 0 of the Sewa Setu assistant (IMPLEMENTATION_PLAN.md): two MCP servers over streamable
HTTP — `/mcp/citizen` (scope `citizen`) and `/mcp/officer` (scope `officer`) — on a shared
service layer, behind one origin (Caddy on :8000), with the portal as the system of record.
Run locally with `docker compose`, 2026-10-21.

**Outcome:** every build step's check passed. The automated replay of the §7 scenarios
passed 44/44 checks, plus the pre-flight, S9, S11 (web form), S14 and the §6-F2 exploit
blocks. All six standing invariants are 0. Manual runs in Claude Code with Haiku found two
defects in how the assistant behaves; both are fixed and re-tested (see *Manual runs*).

---

## 1. Build steps

| step | commit | "done when" result |
|---|---|---|
| 0 | `7ab2571` | `down -v`; fresh seed: 100000 applications, 700 PENDING, 0 with id > 100000 |
| 1 | `5f572c4` | portal served through Caddy; admin login works; `secret_key` from env; `/mcp/*` 502 until step 7 |
| 2 | `db41278` | migration run twice: 8 created, then 0 created / 8 present; schema fingerprint identical |
| 3 | `1f2f37f` | `deemed_date` equals the S7 SQL for all 700 seeded PENDING rows |
| 4 | `e43626f` | web flow files end to end; 3 concurrent declaration POSTs → 1 row; empty-reason web reject refused; approve/reject SMS delivered |
| 5 | `ccb273f` | document route serves bytes identical to disk; 404 for no document, unknown id, paths outside `UPLOAD_DIR` |
| 6 | `2ad6603` | `curl -F` upload (HTML + JSON) accepted; `.txt` and 6 MB refused with no partial file; distinct filenames; `document_uploads` sha256/size match disk and host |
| — | `9d91e37` | villages outside the known 19 accepted once a valid block is given (warning to assistant and officer) |
| 7 | `2f9ff77`, `93a58f3` | §7.1 pre-flight passes; Claude Code completes OAuth for both servers as a CIMD client; tokens carry the right aud/scope/role |
| 8 | `461e6cb` | 2 citizen tools; S2; S9 (window closed) |
| 9 | `ba08a4e` | S1, S3, S4, S5 (+ race), S9 submit |
| 10 | `1cc99bd` | S6, S7 |
| — | `13f489e` | helper-applicant fix (finding 1) |
| 11 | `1d0d54d` | §6-F2 exploit refused; full browser flow works; S14. Clean Claude Code re-auth verified 22:06–22:07 IST |
| 12 | `ed47e98` | officer instructions; S10 read half; `page=0`, `status=pending` behave |
| 13 | `5d2bf46` | image and PDF render; hash/size match disk; no-document and no-provenance messages |
| 14 | `6006ad6` | S10–S13; SMS gateway down → `citizen_notified:false` |
| — | `7110034`, `d99938c` | decision-ownership fixes (finding 2): reason must be the officer's; `officer_reason_quote` required |
| 15 | `eee9d60` | 8 demo applications through services, watermarked `SAMPLE - DEMO DATA`, `source=demo_seed`; non-localhost refused |
| 16 | (this commit) | full §7 replay, invariants, corrected S7 SQL — below |

Steps 8–16 were checked by calling the tools over real JSON-RPC through Caddy, with tokens
minted by the portal's own signer; the conversational runs in Claude Code are in §3.

## 2. Step 16 — full §7 replay (JSON-RPC, fresh mobiles 90000090xx)

**44/44 checks passed:**

| scenario | checks |
|---|---|
| S1 happy path | eligible; village normalised, block auto-filled Dhemaji Pathar; bank/IFSC normalised; curl upload hash = host file; submit refused without declaration; filed with it; row PENDING / Dhemaji Pathar / has_doc / decided_by NULL; one SUBMIT `applicant:<mobile>` row; draft cleared; provenance stamped with the application id; confirmation SMS delivered |
| S2 under 60 | age 58 refused, eligible on 03/08/2028; nothing written |
| S3 DOB formats | 1957-04-10 → 10/04/1957; 32/13/1957 refused, draft unchanged |
| S4 no document | refused, names `get_document_upload_link`; nothing written |
| S5 duplicate | existing number shown with no other person's details; re-submit → duplicate; 3 concurrent submits → 1 row |
| S6 withdraw + reapply | confirm required; another mobile's number refused without saying whose; withdrawn; WITHDRAWN/APPLICANT then PENDING; audit SUBMIT, WITHDRAW |
| S7 status | plain words; submitted = `submitted_at` + 5:30 IST; auto-approval date = corrected S7 SQL |
| S8 isolation | citizen server lists exactly the 7 citizen tools; citizen token on officer → 403; officer token on citizen → 403 |
| S10 officer | queue total matches the DB; demo_seed provenance shown; `view_age_proof` returns text + image; **fresh approval: `citizen_notified: true`**, APPROVED / admin / `officer:admin via assistant`, approval SMS in the gateway |
| S11 reject | no reason → refused; no officer quote → refused; still PENDING; then recorded as `age proof document illegible — Officer: "reject it, the scan is unreadable"` |
| S12 ineligible | approving the youngest pending (59) blocked; unchanged |
| S13 mismatch | id/number mismatch refused; both unchanged |

One check first showed FAIL: my test harness decoded psql's UTF-8 output as Windows-1252 and
saw `â€”` instead of `—`. The stored note was checked byte-for-byte (`position(U&'\2014' …)`)
and is exact; re-checked with UTF-8 decoding → PASS.

**Further blocks, run separately:**

- **§7.1 pre-flight:** 401 with `error`, `error_description`, `scope="citizen"`/`"officer"`,
  `resource_metadata`; POST/GET/DELETE on both canonical paths → 401, never 307/308;
  `-L` → `redirects=0`; PRM `scopes_supported` correct; AS `issuer` = `http://localhost:8000`.
- **S9 closed window** (`SCHEME_DEADLINE="2026-10-01 00:00"`, app + mcp recreated with
  `--no-deps`): `get_scheme_info.window.open = false`; `check_eligibility` not eligible;
  `submit_application` refused "The application window has closed"; 0 rows; deadline restored.
- **S11 web form:** `POST /admin/reject/<id>` with an empty note → "A reason is required to
  reject an application."; still PENDING.
- **S14 + §6-F2:** cookie-less `POST /oauth/login` and `/oauth/consent?rid=…` → "Request
  expired", no code; the browser flow completes (token aud/scope/role officer, tools/list
  200); program token works → Revoke → `revoked_at` set → 401 "This program token has been
  revoked".

**Standing invariants (`id > 100000`):**

| duplicate numbers | mobiles with two live applications | rows without SUBMIT | new rows without audit | decided without a decision row | agent documents without provenance |
|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 | 0 |

34 applications were created in Phase 0 (10 pending, 5 approved, 7 rejected, 12 withdrawn),
all local test, fixture or demo data.

**Corrected S7 SQL** — the deemed date is the first 02:00 UTC strictly after
`submitted_at + 15 days`:

```sql
date_trunc('day', submitted_at + interval '15 days') + interval '2 hours'
  + CASE WHEN submitted_at + interval '15 days'
              >= date_trunc('day', submitted_at + interval '15 days') + interval '2 hours'
         THEN interval '1 day' ELSE interval '0' END
  + interval '5 hours 30 minutes'   AS expected_deemed_ist
```

It equals `services.deemed_date` for all 710 PENDING rows. At the edges the plan's original
SQL was a day late for submissions between 00:00 and 02:00 UTC (05:30–07:30 IST):

| submitted (UTC) | `deemed_date` = corrected SQL | original plan SQL |
|---|---|---|
| 21/10 00:30:00 | 05/11 07:30 IST | 06/11 07:30 IST (wrong) |
| 21/10 01:59:59 | 05/11 07:30 IST | 06/11 07:30 IST (wrong) |
| 21/10 02:00:00 | 06/11 07:30 IST | 06/11 07:30 IST |

## 3. Manual runs in Claude Code (Haiku)

Claude Code signs in as a **CIMD** client (`https://claude.ai/oauth/claude-code-client-metadata`),
not by DCR, and sends `resource` = the canonical server URL.

### Finding 1 — the assistant refused helpers (citizen) — FIXED

**S1 FAILED.** Signed in as the grandson's mobile (`9445816403`), the assistant refused to file
for his grandmother even after he said she was beside him and consented: the application would
"become his" and the declaration would be "untrue". Stricter than the portal; it breaks the
Director's core scenario (grandson, daughter, CSC operator).
*Cause:* every tool description said "the applicant", and a small model read the signed-in
mobile as the applicant.
*Fix (`13f489e`):* citizen server instructions — the person talking may be the applicant or a
family member, helper or CSC operator acting with consent; the signed-in mobile is only the
contact number; a helper may confirm the declaration; the only mobile rule is one active
application per number; dates are DD/MM/YYYY; no speculation. Four tool descriptions and the
shared-phone message reworded; anti-fabrication kept ("only details and documents given by
the applicant or their helper").
*Re-test:* S2, S3, S4, S1, S7, S5, S6 all **PASS**. Final state for `9445816403`:
`SSP26116432` WITHDRAWN/APPLICANT (SUBMIT, WITHDRAW, 1 document) and `SSP26779717` PENDING
(SUBMIT, 1 document), later approved in S10.

### Finding 2 — the assistant decided rejection reasons itself (officer) — FIXED

**S11 FAILED (`SSP26896862`).** On "Reject it." with no reason, the assistant picked "age proof
does not match stated date of birth" from its own review of the document and rejected at once.
The mismatch it saw was real (the fixture reused another fixture's document), but the decision
and its reason were the assistant's, not the officer's.
*First fix (`7110034`):* a "Decisions belong to the officer" section in the officer
instructions — approve only on an explicit instruction for that application; a rejection reason
must be stated or confirmed by the officer; suggest one with the evidence, then ask.
**Re-test FAILED (`SSP26306140`).** It asked first, but after the officer answered "bank
account not in her name" it recorded its own observation ("Age proof image is marked TEST
DOCUMENT…") as the reason, which was also sent to the citizen by SMS.
*Second fix (`d99938c`):* `reject_application` requires `officer_reason_quote`, the officer's
own words verbatim, stored as `<reason> — Officer: "<quote>"`; map the officer's reason to a
canonical one, "other" only when none fits, never substitute your own observation.
*Re-test PASS (`SSP26288550`):* asked for the reason (offering options with evidence, changing
nothing), then recorded
`bank account not in applicant's name — Officer: "The bank account isn't in his name."`, with
its own TEST DOCUMENT observation kept out of the record; the SMS carries the canonical reason.

### Other manual results

- **S12 PASS** — `SSP26558440` (age 59, no document) blocked. **S13 PASS** — id 99325 with
  `SSP26361385` refused. Both still PENDING, no decision rows.
- **S10** — `SSP26779717` approved in the officer session at 21:57 IST
  (`officer:admin via assistant`). `citizen_notified` for that approval **was not captured**
  (the session is gone and a rebuild restarted the in-memory SMS gateway). Re-checked in
  step 16 with a fresh approval: `citizen_notified: true` and the SMS present.
- **Step 11 clean re-auth** — an earlier "re-auth" only refreshed tokens; after removing and
  re-adding both servers, the proxy log shows a full authorize → login → consent → token for
  each, with fresh sessions of 2 h (citizen) and 8 h (officer).

## 4. Where the build differs from the plan text

None changes a locked decision; each was reported when it came up.

- `mcp==1.30.0` pinned (2.x renamed FastMCP); `PyJWT` 2.9.0 → 2.10.1, which it requires.
- mcp 1.x builds a server's session manager only inside `streamable_http_app()`: called once
  at import, its app discarded. `redirect_slashes` is set on `app.router` (Starlette 1.9 has
  no constructor argument).
- The MCP container fetches the JWKS from `http://app:8000`; `iss` is still checked against
  `PUBLIC_BASE_URL`. DNS-rebinding protection allows the public host as well as loopback
  (`mcp_server/common.py`).
- Agent submissions report `sms_sent` from a checked send, not `portal.send_sms`.
- `save_draft` fills in the block for a known village; unreadable or unknown values are not
  stored; villages outside the 19 are accepted with a valid block (decided 2026-10-21).
- `deemed_on` in officer tools is the statutory date or the next nightly run, whichever is
  later.
- Officer reject takes a required `officer_reason_quote` (finding 2).
- Demo watermark uses an ASCII hyphen (`SAMPLE - DEMO DATA`): Pillow's built-in font has no
  en dash. The first batch, rendered with a missing glyph, was withdrawn via
  `services.withdraw` and re-seeded.
- S7 SQL corrected (above); invariants use `id > 100000` (new rows started at 100011).

## 5. Open items for Phase 1 (and 2)

**Evals (Phase 1)**
- Re-check the two pre-fix behaviours: month-first readings of dates and speculation about
  future windows.
- Keep helper-applicant and decision-ownership scenarios in the eval set, including "reject it"
  with no reason, and an officer reason that maps to "other".
- `SSP26779717` was approved although the assistant reported the photo showed no date of birth.
  It was the officer's call, but decide whether the assistant should suggest rejecting (age
  proof illegible / does not show the date of birth) in that case.
- Evals that read SMS must not restart `smsgw` (its inbox is in memory); rebuild with
  `--no-deps`.

**Not yet tested**
- A real phone-browser upload through `/upload/<token>`: the one attempt never reached the
  portal (a phone cannot reach `localhost`). Needs the public URL (Phase 2).

**Known limits carried from the plan**
- R5: one officer identity; `decided_by` is always `admin`.
- R8: access tokens stay valid up to 20/30 min after revocation.
- R9: `/__gateway/` is public, so anyone who can reach it can read OTPs. Decide before
  deployment.
- Rate limiting and CSRF on web forms (D3/D4); the partial unique index on live applications
  per mobile, once the data is known clean.
- R6: the web form's duplicate message still shows the other application's number.

**Deployment (Phase 2)**
- The portal must reach `claude.ai` over HTTPS for CIMD sign-in.
- Set `PUBLIC_BASE_URL`; confirm the MCP host check and the PRM/AS documents on the public
  host; re-issue program tokens with the HTTPS audience.
- Start from the pristine seed: the local database holds test, fixture (`Test …`) and demo
  (`Demo …`) rows; `seed_demo_queue.py` refuses non-localhost and must not be run there.
- Upgrading to `mcp` 2.x is a separate migration.

## 6. Changes after Phase 0 (2026-10-22)

Recorded here so the scenario results above are read against the right build.

- **Officer approval with a raised concern** (`d2396ce`): restate it and get confirmation
  before `approve_application`. Narrowed by the change below to tool warnings only.
- **Citizen document flow** (`441395c`): the person uploads through a phone-first
  `/upload/<token>` page (applicant name, masked mobile, `image/*`/PDF picker, plain-language
  errors, "Uploaded. Go back to your chat and say done."). The citizen assistant never
  verifies, judges or comments on the document; `curl_example` is gone, and a local file is
  uploaded only when the person gives its path and asks. `scripts/check_document_flow.py`:
  31/31 on the deployment.
- **The officer assistant never sees documents** (amendment 10): `view_age_proof` →
  `get_age_proof_link` (the officer's link to `/admin/application/<id>/document` plus the
  recorded provenance; no image content). `get_application` carries the same link.
  `pypdfium2` and the render code are removed. The document route opens inline and a signed-out
  officer returns to it after login. `scripts/check_officer_documents.py`: 23/23 locally
  (with a demo document). S10's "`view_age_proof` returns text + image" and the step-13 check
  no longer apply.
- **A helper files for several applicants in one sign-in** (amendment 11): the helper verifies
  another mobile on `/verify-number/<token>` (the OTP goes to that phone and is typed on the
  page, never in the chat), then passes it as `applicant_mobile`; filed on that mobile through
  the same locked path, audit `helper:<helper> for <applicant>`. `scripts/check_helper_numbers.py`
  (local only, self-cleaning): 73/73 — two verified numbers filed; unverified refused with
  nothing written; one active per mobile (and 3 concurrent submits → 1 row); the helper cannot
  withdraw a helper-filed application; no OTP in any of 38 tool outputs; the single-applicant
  flow unchanged. Over the real transport: 8 citizen tools; the link lasts 15 min and the
  verification until the sign-in ends. Regressions: `check_document_flow` 31/31 (now counts 8
  tools), `check_officer_documents` 23/23, the web form files as `applicant:<mobile>`.
