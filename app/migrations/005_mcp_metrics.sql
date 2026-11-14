-- MCP efficiency metrics (/admin/mcp-metrics). Additive and idempotent.
--
-- One row per tool call, written in batches by the mcp container (mcp_server/metrics.py).
-- No personal data by construction: no argument values and no free text. Identities and
-- arguments are stored only as truncated keyed hashes (HMAC with a key derived from
-- SECRET_KEY), and tool / reason only take values from code whitelists.
-- Kept 30 days; the mcp container deletes older rows once a day.
CREATE TABLE IF NOT EXISTS mcp_calls (
    id            BIGSERIAL   PRIMARY KEY,
    at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    server        VARCHAR(8)  NOT NULL,          -- citizen | officer
    tool          VARCHAR(48) NOT NULL,          -- a tool of that server, else 'unknown'
    session_key   CHAR(16)    NOT NULL,          -- one sign-in (access) or one program token
    principal_key CHAR(16)    NOT NULL,          -- the signed-in subject
    token_kind    VARCHAR(8)  NOT NULL,          -- access | program
    args_key      CHAR(16)    NOT NULL,          -- the call's arguments; repeat detection only
    outcome       VARCHAR(10) NOT NULL,          -- ok | refused | error
    reason        VARCHAR(24),                   -- whitelisted code, else 'other'
    completion    VARCHAR(8),                    -- apply | decision | status
    duration_ms   INTEGER     NOT NULL,
    resp_chars    INTEGER     NOT NULL           -- length of the text the client receives
);
CREATE INDEX IF NOT EXISTS idx_mcp_calls_at ON mcp_calls(at);
CREATE INDEX IF NOT EXISTS idx_mcp_calls_session ON mcp_calls(session_key, at);

-- The size of what each server sends a client before any call: one row per server,
-- replaced every time the mcp container starts. tools = [{"name", "chars"}].
CREATE TABLE IF NOT EXISTS mcp_footprint (
    server             VARCHAR(8)  PRIMARY KEY,
    computed_at        TIMESTAMPTZ NOT NULL,
    instructions_chars INTEGER     NOT NULL,
    tools              JSONB       NOT NULL
);
