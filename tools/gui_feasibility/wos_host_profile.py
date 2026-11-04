"""Trusted-host Starter key for the isolated local GUI feasibility adapter.

Prototype environment ingress is NOT product credential storage. Never make
keys available to the browser, project storage, recent history or audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os


class WoSHostProfileError(ValueError):
    def __init__(self):
        super().__init__('wos_profile_invalid')


@dataclass(frozen=True, slots=True, repr=False)
class WoSHostProfile:
    api_key: str = field(repr=False)

    def __post_init__(self):
        key = self.api_key
        if (type(key) is not str or not 1 <= len(key) <= 4096 or
                not key.isascii() or
                any(ord(char) < 33 or ord(char) > 126 for char in key)):
            raise WoSHostProfileError()

    def __repr__(self):
        return 'WoSHostProfile(configured=True)'

    @classmethod
    def from_prototype_environment(cls):
        """Pop the host-only key before creating any browser session."""
        key = os.environ.pop('RESEARCHY_GUI_WOS_API_KEY', None)
        return None if key is None else cls(api_key=key)
