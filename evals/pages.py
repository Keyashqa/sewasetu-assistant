"""The person's hands: the upload and verify-number pages, used as a phone browser would.

The harness acts only on links that appeared in the assistant's visible text. Each
action returns an observation: the text the person would read on the page afterwards.
OTPs read from the gateway are returned to the caller (kept in memory for the G1 check),
never written anywhere.
"""

import html
import re
from pathlib import Path

import requests

from . import gateway
from .config import BASE_URL

LINK_RE = {
    "upload": re.compile(r"https?://[^\s)<>\]\"'`*]+/upload/[A-Za-z0-9_-]+"),
    "verify": re.compile(r"https?://[^\s)<>\]\"'`*]+/verify-number/[A-Za-z0-9_-]+"),
}


def find_links(text, kind):
    """Every distinct link of `kind` ('upload' | 'verify') in the text, in order."""
    out = []
    for m in LINK_RE[kind].finditer(text or ""):
        if m.group(0) not in out:
            out.append(m.group(0))
    return out


def _local(url):
    """The harness never follows a link off the local stack (a model could print any URL)."""
    if not url.startswith(BASE_URL + "/"):
        raise ValueError("link is not on the local portal: %s" % url)
    return url


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def page_message(body):
    """What the person reads first on the page: the success or error box, else the heading."""
    for cls in ("ok", "err"):
        m = re.search(r'<div class="%s">(.*?)</div>' % cls, body, re.S)
        if m:
            return _text(m.group(1))
    m = re.search(r"<h2>(.*?)</h2>", body, re.S)
    return _text(m.group(1)) if m else ""


def upload_applicant(url):
    """The applicant name the upload page shows (to pick the right link among several)."""
    r = requests.get(_local(url), timeout=15)
    m = re.search(r"Applicant: <b>(.*?)</b>", r.text, re.S)
    return r.status_code, (_text(m.group(1)) if m else None), page_message(r.text)


def upload(url, file_path):
    """Open the link and upload the file, as the multipart form does."""
    url = _local(url)
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return {"action": "upload", "link": url, "http": r.status_code,
                "observation": "You opened the link. The page said: " + page_message(r.text)}
    p = Path(file_path)
    with p.open("rb") as f:
        r = requests.post(url, files={"document": (p.name, f, "image/png")}, timeout=30)
    return {"action": "upload", "link": url, "http": r.status_code, "file": p.name,
            "observation": "You opened the link, chose the photo of the document and tapped "
                           "Upload. The page said: " + page_message(r.text)}


def verify_number(url, mobile, send_only=False):
    """Enter `mobile` on the page, read the OTP that phone receives, and (unless send_only)
    type it on the page. Returns (step, otps)."""
    url = _local(url)
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return ({"action": "verify_number", "link": url, "http": r.status_code,
                 "observation": "You opened the link. The page said: " + page_message(r.text)}, [])
    after = gateway.last_id(mobile)
    r = requests.post(url, data={"action": "send", "mobile": mobile}, timeout=15)
    sent_msg = page_message(r.text)
    try:
        otp = gateway.wait_otp(mobile, after)
    except TimeoutError:
        return ({"action": "verify_number", "link": url, "http": r.status_code,
                 "observation": "You typed the number and tapped Send OTP. The page said: %s "
                                "No SMS arrived on that phone." % sent_msg}, [])
    if send_only:
        return ({"action": "verify_number_send_only", "link": url, "http": r.status_code,
                 "observation": "You typed the number and tapped Send OTP. That phone got an SMS: "
                                "\"Your Sewa Setu OTP is %s.\"" % otp}, [otp])
    r = requests.post(url, data={"action": "check", "otp": otp}, timeout=15)
    return ({"action": "verify_number", "link": url, "http": r.status_code,
             "observation": "You typed the number, got the OTP on that phone and typed it on "
                            "the page. The page said: " + page_message(r.text)}, [otp])
