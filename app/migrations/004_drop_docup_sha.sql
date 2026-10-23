-- The same-document warning was removed (officer warnings are the portal's rules only),
-- so the hash index it needed goes too.
DROP INDEX IF EXISTS idx_docup_sha;
