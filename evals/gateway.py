"""Read the simulated SMS gateway's inbox (the person's phone)."""

import re
import time

import requests

from .config import BASE_URL

OTP_RE = re.compile(r"OTP is (\d{6})")


def messages(mobile):
    r = requests.get(BASE_URL + "/__gateway/api/messages", params={"to": mobile}, timeout=10)
    r.raise_for_status()
    return r.json()["messages"]


def last_id(mobile):
    """Highest message id for this mobile so far; wait_for() looks only at newer ones."""
    return max((m["id"] for m in messages(mobile)), default=0)


def wait_for(mobile, after_id, pattern=None, timeout=15.0):
    """First delivered message to `mobile` with id > after_id (matching `pattern` if given)."""
    rx = re.compile(pattern) if pattern else None
    end = time.time() + timeout
    while time.time() < end:
        for m in messages(mobile):
            if m["id"] > after_id and m["delivered"] and (rx is None or rx.search(m["text"])):
                return m
        time.sleep(0.5)
    raise TimeoutError("no SMS to %s within %ss" % (mobile, timeout))


def wait_otp(mobile, after_id, timeout=15.0):
    return OTP_RE.search(wait_for(mobile, after_id, OTP_RE.pattern, timeout)["text"]).group(1)
