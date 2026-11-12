"""Transient trusted-host PubMed pilot configuration for the isolated GUI.

No browser form, project database, logs, recent-project history or provider
payload contains the contact/API key. Environment ingestion is a *prototype*
hook only, not an approved production credential-management design.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import re


class PubMedHostProfileError(ValueError):
    def __init__(self):
        super().__init__("pubmed_profile_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class PubMedHostProfile:
    contact_email: str = field(repr=False)
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self):
        email = self.contact_email
        key = self.api_key
        if (type(email) is not str or len(email) > 254 or
                not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or
                not email.isascii() or
                any(ord(c) < 33 or ord(c) > 126 for c in email)):
            raise PubMedHostProfileError()
        if key is not None and (type(key) is not str or not 1 <= len(key) <= 4096
                                or not key.isascii() or
                                any(ord(c) < 33 or ord(c) > 126 for c in key)):
            raise PubMedHostProfileError()

    def __repr__(self):
        return "PubMedHostProfile(configured=True)"

    @classmethod
    def from_prototype_environment(cls):
        """Pop host-only settings before any untrusted/browser activity begins."""
        email = os.environ.pop("RESEARCHY_GUI_PUBMED_CONTACT_EMAIL", "")
        key = os.environ.pop("RESEARCHY_GUI_PUBMED_API_KEY", "")
        if not email:
            if key:
                raise PubMedHostProfileError()
            return None
        return cls(contact_email=email, api_key=key or None)
