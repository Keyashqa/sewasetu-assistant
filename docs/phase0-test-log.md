# Phase 0 test log

Running record of each build step's "done when" check (IMPLEMENTATION_PLAN.md §8). The full
§7 scenario run and the invariant SQL are written up here at step 16.

| step | commit | result |
|---|---|---|
| 0 | `7ab2571` | `down -v`; fresh seed: 100000 applications, 700 PENDING, 0 rows with id > 100000 |
| 1 | `5f572c4` | portal served through Caddy; admin login works; `secret_key` from env; `/mcp/*` 502 until step 7 |
| 2 | `db41278` | migration run twice: 8 created, then 0 created / 8 present; schema fingerprint identical |
| 3 | `1f2f37f` | `deemed_date` equals the S7 SQL for all 700 seeded PENDING rows (see note on S7 below) |
| 4 | `e43626f` | web flow files end to end; 3 concurrent declaration POSTs → 1 row; empty-reason web reject refused; approve/reject SMS delivered |
| 5 | `ccb273f` | document route serves bytes identical to disk (sha256); 404 for no document, unknown id, paths outside `UPLOAD_DIR` |
| 6 | `2ad6603` | `curl -F` upload (HTML + JSON) accepted; `.txt` and 6 MB refused, no partial file; distinct filenames; `document_uploads` sha256/size match disk and host. Browser upload: emulated form POST only; a real-browser attempt did not reach the portal (no request in the proxy log) |
| — | `9d91e37` | villages outside the known 19 accepted once a valid block is given (warning to assistant and officer); unknown village with no block is the only problem case |
| 7 | `2f9ff77` | §7.1 curl pre-flight passes in full (see below); Claude Code OAuth completed for both servers |
| 8 | `461e6cb` | tools/list = 2 citizen tools (readOnlyHint). S2: age 58, eligible on 03/08/2028, nothing written. S9 (closed window): `open:false`, not eligible |
| 9 | `ba08a4e` | S1: PENDING, Dhemaji Pathar auto-filled, has_doc, one SUBMIT/applicant row, draft cleared, provenance stamped with the application id, sha256 = host file, SMS sent. S3: 1957-04-10 → 10/04/1957; 32/13/1957 refused, draft unchanged. S4: `no_document`, nothing written. S5: duplicate explained with no other person's details; 3 concurrent submits → 1 row. S9 submit: refused, window closed |
| 10 | (this commit) | S6: withdraw (confirm required; another mobile's number refused without detail), reapply → WITHDRAWN/APPLICANT then PENDING; audit SUBMIT, WITHDRAW, SUBMIT. S7: PENDING, submitted 21:17 IST = `submitted_at` + 5:30, auto-approval 06/11/2026 07:30 IST = cron-rule SQL |

| 11 | `1d0d54d` | cookie-less `POST /oauth/consent?rid=…` → "Request expired", no code (cookie-less login refused too); full browser flow still completes (token aud/scope/role officer, tools/list 200). S14: program token works → Revoke → `revoked_at` set → 401 "revoked". Clean Claude Code re-auth: to run by hand |
| 12 | `ed47e98` | officer instructions served. S10 read half: queue (703 pending, 700 overdue), Dhemaji Pathar list, oldest case. `page=0`/`'abc'`/`-3` → page 1; `status=pending` → 703 rows; bad status/block list valid values |
| 13 | `5d2bf46` | photo.png, JPEG fixture (2400×1600 → 1600×1067) and PDF fixture (page 1 of 2, 150 dpi) render; hash and size equal `sha256sum`/`stat` and `document_uploads`; seeded row → no-document text; web-form row → provenance-not-recorded text |
| 14 | (this commit) | S10: approve → APPROVED / admin / `officer:admin via assistant`, SMS sent, web view shows it and the document link works. S11: no reason / free text / `other` without note refused; "age proof document illegible" → REJECTED with that note. S12: age 59 + no document → blocked, unchanged. S13: id/number mismatch → refused, unchanged. smsgw stopped → `citizen_notified:false`, "has NOT been notified". Invariants 0/0/0/0 |

Steps 8–14 were checked at the tool level over JSON-RPC through Caddy, with tokens minted by
the portal's own signer; the conversational runs in Claude Code follow.

## Manual runs in Claude Code

**S1 with Haiku — FAILED (2026-10-21).** Signed in as the grandson's mobile (`9445816403`),
the assistant refused to file for his grandmother even after he said she was beside him and
consented: it claimed the application would "become his" and the declaration would be
untrue. Stricter than the portal, and it breaks the Director's core scenario (grandson,
daughter or CSC operator applying for her). Cause: every tool description said "the
applicant", and a small model read the signed-in mobile as the applicant. Fix: citizen
server `instructions` now state that a helper may apply with consent, that the mobile is
only the contact number, that the helper may confirm the declaration, and that the only
mobile rule is one active application per number; the four tool descriptions and the
shared-phone message were reworded to match (`13f489e`).

**Citizen re-run with Haiku after the fix — S2, S3, S4, S1, S7, S5, S6 all PASS (2026-10-21).**
Signed in as `9445816403` (the grandson), filing for Sewali Gogoi. Final database state,
confirmed by SQL:

| id | application_no | name | block | status | decided_by | audit | documents |
|---|---|---|---|---|---|---|---|
| 100017 | SSP26116432 | Sewali Gogoi | Dhemaji Pathar | WITHDRAWN | APPLICANT | SUBMIT, WITHDRAW | 1 |
| 100018 | SSP26779717 | Sewali Gogoi | Dhemaji Pathar | PENDING | — | SUBMIT | 1 |

**For Phase 1 evals (no fix now):** before the helper fix, Haiku offered a month-first
reading of a date and speculated about future application windows. The server instructions
now forbid both; re-check them in the evals.

**Officer run with Haiku — FINDING (2026-10-21): the assistant chose the rejection reason.**
On S11's "Reject it." (no reason given) for `SSP26896862`, Haiku picked "age proof does not
match stated date of birth" from its own review of the document and rejected at once:

```
SSP26896862 | REJECTED | admin | officer:admin via assistant |
age proof does not match stated date of birth — Age proof shows name Test Jpeg Applicant and
date of birth 02/02/1955; application records Test Reject Applicant and 05/05/1952. ...
```

The mismatch was real (the fixture reused another fixture's document), so the review was
accurate; the defect is that the decision and its reason were the assistant's, not the
officer's. Fix: officer server instructions gain a "Decisions belong to the officer" section
(approve only on an explicit instruction for that application; a rejection reason must be
stated or confirmed by the officer — suggest one with the evidence, then ask; keep surfacing
mismatches), and the approve/reject descriptions and the reason-required message say the
same (`7110034`). `SSP26896862` is used up, so S11's "reject without a reason" check is
re-tested on a fresh fixture, `SSP26306140` (Test Reason Applicant, document matches the record).

**S11 re-test on `SSP26306140` — FAILED (2026-10-21, 22:01 IST).** On "Reject it." the
assistant did ask for the reason, and the officer answered "bank account not in her name". But
the rejection it recorded (and sent to the citizen by SMS) was its own observation, not the
officer's reason:

```
SSP26306140 | REJECTED | admin | officer:admin via assistant |
Age proof image is marked "TEST DOCUMENT - NOT REAL" and is titled "Birth certificate (fixture)".
It is not a genuine birth certificate.
```

Fix (Option B): `reject_application` takes a required `officer_reason_quote` — the officer's
own words giving or confirming the reason, verbatim — and stores it in the audit note as
`<reason> — Officer: "<quote>"`. Instructions and description: map the officer's stated reason
to the matching canonical reason, use "other" only when none fits, never substitute your own
observation. Checked over JSON-RPC: no quote → refused, nothing written; with a quote →
`bank account not in applicant's name — Officer: "reject it, the bank account isn't in her name"`,
SMS carries only the canonical reason. Re-test fixture: `SSP26288550`.

**S11 re-test on `SSP26288550` with Haiku — PASS (2026-10-21).** On "Reject it." it asked for
the officer's reason, offering options with evidence, and changed nothing. On "The bank
account isn't in his name." it rejected with the canonical reason and the officer's verbatim
words, and kept its own TEST DOCUMENT observation out of the record:

```
REJECTED | admin | officer:admin via assistant |
bank account not in applicant's name — Officer: "The bank account isn't in his name."
SMS: ... has been rejected. Reason: bank account not in applicant's name. ...
```

**S12 and S13 with Haiku — PASS.** `SSP26558440` (age 59, no document) blocked; id 99325 with
number `SSP26361385` refused. Both still PENDING with no decision rows.

**S10 approval of `SSP26779717` (Sewali Gogoi) — done in the officer session (21:57 IST),**
audit `APPROVED | officer:admin via assistant`. `citizen_notified` **was not captured**: the
session is gone and the SMS gateway's in-memory inbox was wiped by a rebuild that restarted
it as a dependency. Rebuilds now use `--no-deps`; re-checked with a fresh approval in step 16.

**Step 11 clean re-authentication — VERIFIED (22:06–22:07 IST)**, after removing and
re-adding both servers in Claude Code. An earlier "re-auth" at 21:59 had only refreshed the
existing tokens (two `POST /oauth/token`, no authorize/consent). The proxy log now shows a full
`authorize → login → consent → token` for each server, and `oauth_refresh_tokens` has new rows
with full sessions: citizen 1:59:59.96, officer 7:59:59.99.

## Step 7 — OAuth with Claude Code

Claude Code registers as a **client ID metadata document (CIMD)** client, not via DCR:

```
client_id  = https://claude.ai/oauth/claude-code-client-metadata   (oauth_clients.kind = cimd)
redirects  = http://localhost/callback, http://127.0.0.1/callback
```

Tokens decoded on the client, and the matching `oauth_refresh_tokens` rows:

| server | sub | aud = resource | scope / role | session |
|---|---|---|---|---|
| citizen | `citizen:9445816403` | `http://localhost:8000/mcp/citizen` | citizen / citizen | 2 h (15:36:51 → 17:36:51 UTC) |
| officer | `officer:admin` | `http://localhost:8000/mcp/officer` | officer / officer | 8 h (15:37:17 → 23:37:17 UTC) |

Pre-flight: 401 with `error`, `error_description`, `scope`, `resource_metadata`; correct
`scope` per server; POST/GET/DELETE on both canonical paths → 401, never 307/308; `-L`
→ `redirects=0`; all PRM forms served. Cross-role tokens → 403 naming the right server;
expired → 401 "Your sign-in has ended".

## Notes for step 16

- **S7 SQL** is wrong for submissions between 00:00 and 02:00 UTC. Use the cron rule (first
  02:00 UTC strictly after `submitted_at + 15 days`):
  ```sql
  date_trunc('day', submitted_at + interval '15 days') + interval '2 hours'
    + CASE WHEN submitted_at + interval '15 days'
                >= date_trunc('day', submitted_at + interval '15 days') + interval '2 hours'
           THEN interval '1 day' ELSE interval '0' END
    + interval '5 hours 30 minutes'   AS expected_deemed_ist
  ```
- **Invariants:** use `id > 100000`, not `id > 100016` (new rows started at 100011).
