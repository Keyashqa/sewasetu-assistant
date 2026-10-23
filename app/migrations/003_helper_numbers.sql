-- A helper files for several applicants in one sign-in. Idempotent, applied at every mcp boot.
--
-- NOT purely additive: agent_drafts' primary key changes from (mobile) to (owner, mobile),
-- so code from before this migration (ON CONFLICT (mobile)) cannot write drafts against it.
-- Rolling back across it: see DEPLOY.md §4.

-- Drafts belong to the signed-in mobile (owner) and are for one applicant mobile.
-- The existing single-applicant draft is the case owner = mobile.
ALTER TABLE agent_drafts ADD COLUMN IF NOT EXISTS owner VARCHAR(15);
UPDATE agent_drafts SET owner = mobile WHERE owner IS NULL;
ALTER TABLE agent_drafts ALTER COLUMN owner SET NOT NULL;
DO $$
BEGIN
    IF (SELECT array_length(conkey, 1) FROM pg_constraint
        WHERE conname = 'agent_drafts_pkey') = 1 THEN
        ALTER TABLE agent_drafts DROP CONSTRAINT agent_drafts_pkey;
        ALTER TABLE agent_drafts ADD PRIMARY KEY (owner, mobile);
    END IF;
END $$;

-- /verify-number/<token>: a short-lived, single-use link issued to a signed-in helper.
-- The helper enters the applicant's mobile on the portal page, the portal sends the OTP to
-- that mobile, the helper types it on the same page. The code is stored only as a hash and
-- never leaves the portal: no tool reads this table's code columns.
CREATE TABLE IF NOT EXISTS number_verifications (
    id             SERIAL PRIMARY KEY,
    helper         VARCHAR(15) NOT NULL,         -- the signed-in mobile the link was issued to
    token          VARCHAR(64) NOT NULL UNIQUE,
    token_expires  TIMESTAMP   NOT NULL,
    session_ends   TIMESTAMP   NOT NULL,         -- the helper's sign-in end; verification lasts until then
    mobile         VARCHAR(15),                  -- the number being verified
    code_hash      CHAR(64),
    code_sent_at   TIMESTAMP,
    sends          INTEGER     NOT NULL DEFAULT 0,
    attempts       INTEGER     NOT NULL DEFAULT 0,   -- wrong codes, across all sends
    used_at        TIMESTAMP,                    -- set on success: the link is single-use
    created_at     TIMESTAMP   NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_numver_helper ON number_verifications(helper);

-- Numbers a helper has proved by OTP, valid until that helper's sign-in ends.
CREATE TABLE IF NOT EXISTS verified_numbers (
    helper       VARCHAR(15) NOT NULL,
    mobile       VARCHAR(15) NOT NULL,
    verified_at  TIMESTAMP   NOT NULL,
    expires_at   TIMESTAMP   NOT NULL,
    PRIMARY KEY (helper, mobile)
);

-- Applications a helper filed on another person's mobile (get_my_application lists them).
CREATE TABLE IF NOT EXISTS helper_filings (
    application_id INTEGER     PRIMARY KEY,
    helper         VARCHAR(15) NOT NULL,
    mobile         VARCHAR(15) NOT NULL,
    filed_at       TIMESTAMP   NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_helper_filings_helper ON helper_filings(helper);
