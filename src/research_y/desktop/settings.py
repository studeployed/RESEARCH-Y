"""Read only RESEARCH-Y's two named source settings from Windows Credential Manager."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from research_y.desktop.pubmed_profile import PubMedHostProfile
from research_y.desktop.wos_profile import WoSHostProfile

PUBMED_TARGET = 'RESEARCH-Y/PubMed'
STARTER_TARGET = 'RESEARCH-Y/WoS-Starter'
CLOUD_TARGET = 'RESEARCH-Y/Anthropic'


class _Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.c_void_p), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR),
    ]


def _read(target):
    if target not in (PUBMED_TARGET, STARTER_TARGET, CLOUD_TARGET):
        raise ValueError('unknown_source_setting')
    library = ctypes.WinDLL('Advapi32.dll', use_last_error=True, winmode=0x800)
    pointer = ctypes.POINTER(_Credential)()
    library.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(type(pointer))]
    library.CredReadW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    library.CredFree.restype = None
    if not library.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return None
        raise OSError('source_settings_unavailable')
    try:
        entry = pointer.contents
        size = entry.CredentialBlobSize
        if size > 8192 or size % 2 or (size and not entry.CredentialBlob):
            raise ValueError('source_setting_invalid')
        key = ctypes.string_at(entry.CredentialBlob, size).decode('utf-16-le') if size else ''
        return entry.UserName or '', key
    finally:
        library.CredFree(pointer)


def source_profiles():
    """Return configured host-only profiles and public, source-specific errors."""
    warnings = []
    pubmed = starter = None
    try:
        item = _read(PUBMED_TARGET)
        if item:
            pubmed = PubMedHostProfile(contact_email=item[0], api_key=item[1] or None)
    except (ValueError, OSError):
        warnings.append('PubMed settings could not be loaded.')
    try:
        item = _read(STARTER_TARGET)
        if item:
            starter = WoSHostProfile(api_key=item[1])
    except (ValueError, OSError):
        warnings.append('Web of Science settings could not be loaded.')
    return pubmed, starter, tuple(warnings)


def cloud_profile():
    from research_y.cloud_terms import CloudTerms
    try:
        entry = _read(CLOUD_TARGET)
        return (CloudTerms(*entry) if entry else None), ()
    except (ValueError, OSError):
        return None, ("Optional cloud settings could not be loaded.",)
