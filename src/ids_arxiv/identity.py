"""Transparent operator identity, not a mechanism for obtaining extra quota."""

import os


def user_agent(contact_email=None):
    runner = os.environ.get("IDS_RUNNER_ID", "local").strip()
    email = (contact_email if contact_email is not None else os.environ.get("ARXIV_CONTACT_EMAIL", "")).strip()
    if any(character in runner + email for character in "\r\n"):
        raise ValueError("HTTP identity must not contain newlines")
    return f"FIT-HCMUS-IDS-Group13/4.0 (runner: {runner}; contact: {email or 'not-configured'})"
