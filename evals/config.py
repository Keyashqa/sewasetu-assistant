"""Harness settings. The harness only ever talks to a local stack."""

import os
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
EVALS = REPO / "evals"
RESULTS = EVALS / "results"

BASE_URL = os.environ.get("EVAL_BASE_URL", "http://localhost:8000").rstrip("/")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}

CITIZEN_RESOURCE = BASE_URL + "/mcp/citizen"
OFFICER_RESOURCE = BASE_URL + "/mcp/officer"
REDIRECT_URI = "http://127.0.0.1:53682/callback"

CLIENT_MODEL = "claude-haiku-5-5"
SIM_MODEL_DEV = "claude-haiku-5-5"
SIM_MODEL_PUBLISHED = "claude-sonnet-5-5"

MAX_TURNS_PER_MESSAGE = 6


def assert_local(url=BASE_URL):
    host = urlparse(url).hostname
    if host not in LOCAL_HOSTS:
        raise SystemExit("refusing to run against %r: the eval harness is local only" % url)


def _dotenv():
    out = {}
    path = REPO / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def admin_password():
    pw = os.environ.get("ADMIN_PASSWORD") or _dotenv().get("ADMIN_PASSWORD")
    if not pw:
        raise SystemExit("ADMIN_PASSWORD not set (env or .env)")
    return pw


assert_local()
