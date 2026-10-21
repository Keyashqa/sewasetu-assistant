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

Steps 8–10 were checked at the tool level over JSON-RPC through Caddy, with citizen tokens
minted by the portal's own signer; the conversational runs in Claude Code follow.

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
