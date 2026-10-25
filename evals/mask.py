"""Redaction before anything is written (EVAL_PLAN §5).

- Every OTP the harness handled becomes [OTP], wherever it appears: an observation, the
  persona's own message (P06 pastes one into the chat), assistant text, tool inputs.
- Bearer/JWTs become [JWT]; refresh tokens and other in-memory secrets become [SECRET].
- /upload/<token> and /verify-number/<token> keep 4 characters: /upload/ab12….
A final scan refuses to write anything that still contains a secret.
"""

import json
import re

JWT_RE = re.compile(r"eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]+")
LINK_RE = re.compile(r"(/(?:upload|verify-number)/)([A-Za-z0-9_-]{4})[A-Za-z0-9_-]+")


class SecretLeak(Exception):
    pass


def _otp_re(otp):
    # an OTP inside a longer number (a bank account, a mobile) is not that OTP
    return re.compile(r"(?<!\d)%s(?!\d)" % re.escape(otp))


def mask_text(s, otps=(), secrets=()):
    for sec in secrets:
        if sec:
            s = s.replace(sec, "[SECRET]")
    s = JWT_RE.sub("[JWT]", s)
    for otp in otps:
        s = _otp_re(otp).sub("[OTP]", s)
    return LINK_RE.sub(lambda m: m.group(1) + m.group(2) + "…", s)


def mask(obj, otps=(), secrets=()):
    if isinstance(obj, str):
        return mask_text(obj, otps, secrets)
    if isinstance(obj, list):
        return [mask(x, otps, secrets) for x in obj]
    if isinstance(obj, dict):
        return {k: mask(v, otps, secrets) for k, v in obj.items()}
    return obj


def scan(text, otps=(), secrets=()):
    """Raise if `text` (the serialised output) still holds a secret."""
    if JWT_RE.search(text):
        raise SecretLeak("JWT")
    for sec in secrets:
        if sec and sec in text:
            raise SecretLeak("in-memory secret")
    for otp in otps:
        if _otp_re(otp).search(text):
            raise SecretLeak("OTP")
    if re.search(r"/(?:upload|verify-number)/[A-Za-z0-9_-]{5,}", text):
        raise SecretLeak("unmasked link token")


def dumps_safe(obj, otps=(), secrets=()):
    masked = mask(obj, otps, secrets)
    text = json.dumps(masked, ensure_ascii=False, indent=1)
    scan(text, otps, secrets)
    return text
