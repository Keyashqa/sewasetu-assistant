# Sewa Setu AI Assistant — Master Implementation Plan

This document outlines the complete architectural blueprint, technical specifications, and step-by-step roadmap for building the **Sewa Setu AI Assistant** project as defined in `BRIEF.md` and `README.md`.

---

## 1. Project Goal & Core Requirements

The objective is to build **two separate Model Context Protocol (MCP) servers** over streamable HTTP that allow an AI client (such as Claude Code) to act for citizens and block officers, backed by an **automated evaluation suite** and an **`/eval-dashboard`** web page.

### Non-Negotiable Requirements:
1. **The Portal Remains the System of Record:** As specified in `BRIEF.md` (*"Whatever APIs you need behind them. The portal stays the system of record"*), all mutations and validations must go through the portal's official business logic (`validate_application()`, `create_application()`, `write_audit()`). The MCP servers must **not** bypass portal rules with unvalidated raw SQL.
2. **Strict Security Boundaries:** A citizen's assistant must **never** see or execute officer tools. Citizen and Officer tools must live on completely separate MCP endpoints.
3. **Streamable HTTP Transport:** MCP servers must use HTTP/SSE (Server-Sent Events) rather than local `stdio`, enabling remote clients over the internet to connect.
4. **OAuth 2.1 & JWKS Authentication:** Third-party clients authenticate via the portal’s built-in OAuth 2.1 server. MCP servers verify tokens against `http://<portal>/.well-known/jwks.json`.
5. **Evaluation Suite with Invented Personas:** Invented citizen personas tested against real clients with database assertions, displayed on `/eval-dashboard`.
6. **Deployability:** Hosted on a public VM with HTTPS, running continuously until the evaluation window closes.

---

## 2. System Architecture & Communication Flow

```
                                  [Claude Code / AI Client]
                                        |             |
                 +----------------------+             +----------------------+
                 | (OAuth 2.1 Bearer)                        | (OAuth 2.1 Bearer)
                 v                                           v
      +------------------------+                  +------------------------+
      |   Citizen MCP Server   |                  |   Officer MCP Server   |
      |   Path: /mcp/citizen   |                  |   Path: /mcp/officer   |
      +-----------+------------+                  +-----------+------------+
                  |                                           |
                  |     Internal API Calls / Service Layer    |
                  |  (validate_application, write_audit, etc)|
                  v                                           v
      +--------------------------------------------------------------------+
      |                       Sewa Setu Portal App                         |
      |                     (The System of Record)                         |
      +----------------------------------+---------------------------------+
                                         |
                 +-----------------------+-----------------------+
                 |                       |                       |
                 v                       v                       v
        [PostgreSQL DB]          [Simulated SMS GW]       [Eval Dashboard]
        (~100k records)           (:8025 / __gateway)    (/eval-dashboard)
```

### How the MCP Servers Talk to the Portal:
In accordance with `BRIEF.md` (*"Whatever APIs you need behind them. The portal stays the system of record"*), the communication between the MCP server and the Portal follows the **Service/API Layer pattern**:
* **Do NOT execute unvalidated raw SQL in MCP:** Directly doing `INSERT INTO applications` from MCP risks bypassing statutory age calculation ($\ge 60$), the 6-block whitelist, duplicate application checks, and mandatory audit logging.
* **The Correct Pattern:**
  * Add internal API endpoints to the Flask portal (e.g. `POST /api/applications`, `POST /api/applications/<id>/decide`, `GET /api/applications/pending`) protected by Bearer JWT tokens, **OR**
  * Import and call `validate_application()`, `create_application()`, and `write_audit()` directly from `app.py` as a shared Python library.
* Every application creation and officer decision generates an immutable entry in the `audit_log` table with timestamp and actor identity (`applicant:<mobile>` or `officer:<username>`).

---

## 3. Component Breakdown & Specifications

### Component A: Citizen MCP Server (`/mcp/citizen`)
* **Target Audience:** Elderly citizens seeking pensions or checking status.
* **Authentication:** Verify Bearer JWT via JWKS; require `scope == "citizen"` and extract mobile from `sub` (`citizen:<mobile>`).
* **Tools to Implement:**
  1. `check_eligibility(dob, block, annual_income)`
     * Verifies age $\ge 60$ as of today.
     * Verifies block belongs to allowed list: `['Sonari', 'Rajapara', 'Dhemaji Pathar', 'Borgaon', 'Namti', 'Khelua']`.
     * Checks if an active application (`PENDING`, `APPROVED`, `DEEMED_APPROVED`) already exists for this mobile number.
  2. `get_application_status()`
     * Retrieves current status for the authenticated citizen's mobile.
     * Returns application number, submission date, decision date, and acknowledgment download link.
  3. `submit_application(applicant_name, village, block, dob, gender, marital_status, bank_account, ifsc, document_b64)`
     * Validates fields according to `validate_application()`.
     * Inserts into `applications` table with status `PENDING`.
     * Creates `portal_users` account with DOB as initial password (`DDMMYYYY`).
     * Writes to `audit_log` (`action: SUBMIT`, `actor: applicant:<mobile>`).
     * Dispatches SMS confirmation via SMS Gateway.
  4. `withdraw_application(application_id)`
     * Only permitted if status is `PENDING` and belongs to this citizen.
     * Updates status to `WITHDRAWN`, records `decided_by = 'APPLICANT'`, and logs audit event.
     * Frees the mobile number to submit a fresh application.
  5. `get_scheme_info()`
     * Returns scheme guidelines, required documents, deadline countdown, and FAQs.

---

### Component B: Officer MCP Server (`/mcp/officer`)
* **Target Audience:** Block Development Officers (BDOs) and Social Welfare Department staff.

#### Officer Authentication & Identity Verification:
* **Token Verification:** Verify incoming Bearer JWT against Sewa Setu's JWKS (`http://<portal>/.well-known/jwks.json`).
* **Scope Check:** Must contain `claims["role"] == "officer"` and `claims["scope"] == "officer"`. If a citizen's token (`role == "citizen"`) or an unauthenticated call arrives, the server immediately rejects the call with `403 Forbidden`.
* **Actor Extraction:** Extracts officer identity from `claims["sub"]` (e.g. `officer:admin`). This identity is stamped into every audit log record (`decided_by`).
* **Dual Auth Support:** Accepts both interactive OAuth session JWTs and long-lived **Program Tokens** generated at `/admin/tokens`.

#### AI Safety & Officer Guardrails (Preventing Accidental Mass Decisions):
To prevent an AI bot from hallucinating or executing accidental bulk rejections:
1. **Strictly Single-Item Tools:** No batch or wildcard tools (e.g. NO `bulk_approve()` or `reject_all()`). Tools require explicit, individual `application_id`.
2. **Mandatory Officer Justification Note:** The `officer_note` argument is mandatory. The bot cannot decide a case with empty remarks.
3. **Strict State Enforement:** Operations only succeed if the application is currently in `PENDING` state. Deciding an already approved/rejected case is blocked.
4. **Immutable Audit Accountability:** Every decision records the actor, decision timestamp, and note to the `audit_log` table.

#### Tools to Implement:
1. `list_applications(status, block, search_mobile, page, limit)`
   * Paginated search over applications with status and block filters.
2. `get_sla_breaches()`
   * Returns pending applications older than statutory 15-day SLA (`submitted_at < NOW() - 15 days`).
3. `get_application_details(application_id)`
   * Returns full application details, bank IFSC, village/block, and audit trail history.
4. `approve_application(application_id, officer_note)`
   * Verifies current status is `PENDING`.
   * Updates status to `APPROVED`, records `decided_at` and `decided_by`.
   * Writes entry to `audit_log` with the officer's remarks.
5. `reject_application(application_id, rejection_reason)`
   * Verifies current status is `PENDING`.
   * Updates status to `REJECTED`, records `decided_at` and `decided_by`.
   * Writes entry to `audit_log` with the rejection reason.
6. `get_dashboard_metrics()`
   * Returns counts by status, overdue applications count, and block distribution.

---

### Component C: Evaluation Suite & `/eval-dashboard`
* **Purpose:** Prove your assistants work reliably with diverse human behavior and verify post-conversation database assertions.
* **Citizen Personas to Implement:**
  1. **Elderly Rural Citizen (Happy Path):** Age 64, Borgaon block, dialect-heavy query $\rightarrow$ Assistant guides step-by-step $\rightarrow$ DB assertion: New `PENDING` application created.
  2. **Underage Applicant (Rejection Path):** Age 58 $\rightarrow$ Assistant politely explains 60-year threshold $\rightarrow$ DB assertion: No record inserted.
  3. **Invalid Block Applicant:** Mentions village in non-scheme block $\rightarrow$ Assistant explains scheme coverage and lists valid blocks $\rightarrow$ DB assertion: No invalid block submitted.
  4. **Duplicate Applicant (Conflict Path):** Mobile number already holds a `PENDING` application $\rightarrow$ Assistant explains duplicate rule and offers withdrawal option.
  5. **Withdrawing Applicant:** Asks to correct a mistake on existing pending application $\rightarrow$ Assistant withdraws old application $\rightarrow$ DB assertion: Status is `WITHDRAWN`.
  6. **Status Checker:** Citizen checks progress of application $\rightarrow$ Assistant reads exact database status and returns acknowledgment details.
  7. **Officer SLA Triage:** Officer asks for overdue cases $\rightarrow$ Assistant lists >15 day cases $\rightarrow$ Officer approves case $\rightarrow$ DB assertion: Status is `APPROVED`, audit entry created.

* **`/eval-dashboard` Features:**
  * Clean UI accessible on the public domain (`/eval-dashboard`).
  * List of all personas with brief bios and intents.
  * Interactive or expandable conversation traces showing turns between persona and assistant.
  * Direct database assertions (Expected vs Actual DB state).
  * Overall pass/fail summary rate.

---

## 4. Technical Stack Recommendation

* **Language:** Python 3.11 (matching the handout runtime).
* **Framework:**
  * FastMCP (`from mcp.server.fastmcp import FastMCP`) with SSE transport, OR
  * FastAPI + standard `mcp` Python SDK over SSE.
* **Database Access:** Portal Service Layer / REST endpoints, or direct `psycopg2` using imported `validate_application()` logic.
* **Token Verification:** `PyJWT` with `cryptography` fetching keys from `http://app:8000/.well-known/jwks.json`.
* **Reverse Proxy:** **Caddy** (recommended for automatic Let's Encrypt HTTPS certificates) or **Nginx**.

---

## 5. Step-by-Step Implementation Roadmap

### Phase 1: Environment & Foundational Setup
- [ ] Listen to `DIRECTOR-NOTE.mp3` and note key domain nuances.
- [ ] Initialize git repository `sewasetu-assistant` with full history.
- [ ] Create folder structure:
  ```
  sewasetu-assistant/
  ├── app/                  # Existing portal files
  │   └── api.py            # Backend REST endpoints for MCP servers
  ├── mcp_servers/
  │   ├── citizen_mcp.py    # Citizen MCP server
  │   ├── officer_mcp.py    # Officer MCP server
  │   ├── auth_utils.py     # JWKS validation & scope enforcement
  │   └── guardrails.py     # Safety rules & single-item enforcement
  ├── evals/
  │   ├── personas/         # Persona definitions
  │   ├── runner.py         # Automated test runner with DB assertions
  │   └── dashboard/        # Eval dashboard (FastAPI/Flask)
  ├── docker-compose.yml    # Orchestrates portal, DB, SMSGW, MCP servers, Caddy
  ├── Caddyfile             # HTTPS reverse proxy configuration
  └── README.md
  ```

### Phase 2: Building Backend APIs & MCP Servers
- [ ] Build Portal API endpoints in `app/` (or shared service layer):
  - Expose application submission, status, withdrawal, queue listing, and approval/rejection endpoints invoking `validate_application()` and `write_audit()`.
- [ ] Build `auth_utils.py`:
  - Fetch JWKS from `http://app:8000/.well-known/jwks.json`.
  * Validate RS256 JWT, verify audience and issuer.
  * Enforce role/scope checks (`citizen` vs `officer`).
- [ ] Build `citizen_mcp.py`:
  - Implement eligibility, submit, status, withdraw tools.
  - Test tools using simulated citizen OAuth tokens.
- [ ] Build `officer_mcp.py`:
  - Implement list, SLA breaches, view details, approve, reject tools.
  - Implement safety guardrails (no bulk actions, mandatory notes).
  - Test tools with Program Tokens minted at `/admin/tokens`.

### Phase 3: Building Evaluation Suite & Dashboard
- [ ] Define persona test cases in JSON/YAML (prompts, expected tool calls, expected DB assertions).
- [ ] Write `runner.py`: automates simulated turns against the MCP server and checks DB post-conditions.
- [ ] Build `/eval-dashboard` route to display test runs, transcript logs, and pass/fail metrics.

### Phase 4: Deployment & Production Hardening
- [ ] Spin up an Ubuntu/Debian VM (AWS / DigitalOcean / Hetzner).
- [ ] Configure DNS domain (e.g. `sewasetu.<your-domain>.com` or `*.nip.io`).
- [ ] Configure Caddy/Nginx for automatic HTTPS.
- [ ] Set `PUBLIC_BASE_URL=https://<your-domain>`.
- [ ] Verify Claude Code can connect to both `/mcp/citizen` and `/mcp/officer` over HTTPS.

### Phase 5: Submission Deliverables
- [ ] Verify VM is stable and accessible.
- [ ] Verify admin credentials for evaluators work (`admin` / password).
- [ ] Record 3-minute Loom video (face & screen: walkthrough of architecture, personas, evals, learnings).
- [ ] Write 1-page Design Note:
  * 3 key decisions that mattered most (e.g., Portal as system of record, AI safety guardrails against bulk rejection, OAuth 2.1 identity segregation).
  * 1 decision you would make differently with more time.
- [ ] Invite `harshnisar` to the private GitHub repository.
- [ ] Package repository zip (including `.git`) and submit the form.

---

## 6. Useful Local URLs & Commands Reference

| Service | Local URL |
| :--- | :--- |
| **Portal** | http://localhost:8000 |
| **Status Portal** | http://localhost:8000/status |
| **Admin Portal** | http://localhost:8000/admin |
| **Program Tokens** | http://localhost:8000/admin/tokens |
| **SMS Gateway Console** | http://localhost:8000/__gateway/ |
| **SMS Messages API** | http://localhost:8000/__gateway/api/messages?to=<mobile> |
| **OAuth Discovery** | http://localhost:8000/.well-known/oauth-authorization-server |
| **JWKS Public Keys** | http://localhost:8000/.well-known/jwks.json |

**Run docker containers locally:**
```powershell
$env:ADMIN_PASSWORD="1234"
docker compose up -d
```
