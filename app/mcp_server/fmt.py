# -*- coding: utf-8 -*-
"""Plain-language wording shared by the MCP tools. Times arrive pre-formatted in IST
from services; this module only words things."""

STATUS_MEANING = {
    "PENDING": "The block officer has not decided yet. This is normal.",
    "APPROVED": "Approved. Rs 250 per month will be credited to the bank account by DBT.",
    "DEEMED_APPROVED": "Nobody decided within 15 days, so by law it is approved. Rs 250 per "
                       "month will be credited to the bank account by DBT.",
    "REJECTED": "Rejected by the block officer.",
    "WITHDRAWN": "Withdrawn by the applicant. You may apply again.",
}


def window_text(win):
    """{open, closes, time_left} for a window_status() dict."""
    out = {"open": win["open"], "closes": win["deadline_ist"]}
    if win["open"]:
        out["time_left"] = win["time_left"]
    else:
        out["note"] = "The application window closed on %s. Nothing can be filed now." \
                      % win["deadline_ist"]
    return out


def window_closed_message(win):
    return ("The application window has closed (it closed on %s). No application can be "
            "filed through the portal now, by the assistant or at the counter."
            % win["deadline_ist"])


def existing_application_message(existing):
    return ("This mobile number already has an active application, %s (%s). If that "
            "application is for this same applicant, there is nothing new to file — use "
            "get_my_application to see where it stands. A different applicant cannot be filed "
            "on this mobile number while that one is active (one active application per mobile "
            "number); they can apply on another mobile number, such as their own or another "
            "family member's (verify it with get_number_verification_link and pass it as "
            "applicant_mobile), or at the block office." % (existing["application_no"],
                                                   existing["status"]))
