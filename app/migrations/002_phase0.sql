-- Phase 0. Additive only: no column dropped, no existing row modified.
-- Idempotent: applied at every mcp container boot by scripts/apply_migrations.py.

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

-- Back the application-number retry loop with a constraint (0 duplicates in the seed).
-- Also the only index on application_no, which the officer lookup needs.
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_no_unique ON applications(application_no);

-- officer queue filter: status + block ((status, submitted_at) already exists)
CREATE INDEX IF NOT EXISTS idx_app_status_block ON applications(status, block);

-- every OTP check was a sequential scan
CREATE INDEX IF NOT EXISTS idx_otps_mobile ON otps(mobile, id DESC);
