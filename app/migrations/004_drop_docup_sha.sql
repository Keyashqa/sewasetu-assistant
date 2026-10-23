-- The officer's same-document warning looks documents up by hash.
CREATE INDEX IF NOT EXISTS idx_docup_sha ON document_uploads(sha256);
