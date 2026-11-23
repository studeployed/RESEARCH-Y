"""Read only RESEARCH-Y's two named source settings from Windows Credential Manager."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
from threading import Lock

from research_y.desktop.pubmed_profile import PubMedHostProfile
from research_y.desktop.wos_profile import WoSHostProfile

PUBMED_TARGET = 'RESEARCH-Y/PubMed'
STARTER_TARGET = 'RESEARCH-Y/WoS-Starter'
CLOUD_TARGET = 'RESEARCH-Y/Anthropic'


def open_credential_manager():
    """Open the Windows control panel with fixed arguments and no project-controlled path."""
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer,len(buffer))
    if not 0<size<len(buffer):
        raise OSError("Windows Credential Manager could not be opened")
    subprocess.Popen([str(Path(buffer.value)/"control.exe"),"/name","Microsoft.CredentialManager"],
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


class PubMedConnectionTest:
    query = "1[uid]"

    def __init__(self,profile,*,transport=None):
        from research_y.pubmed_probe import PubMedESearchProbeClient
        self._client = PubMedESearchProbeClient(email=profile.contact_email,api_key=profile.api_key,transport=transport)
        self._lock = Lock()

    def check(self,project=None):
        from research_y.pubmed_cooldown import project_requests
        from research_y.pubmed_probe import PubMedProbeError, PubMedRetryNotDue
        if not self._lock.acquire(blocking=False):
            return "A PubMed connection test is already running."
        try:
            @project_requests
            def probe(selected_project):
                return self._client.probe(self.query)
            try:
                probe(project)
            except PubMedRetryNotDue:
                return "PubMed requested a pause. Retry after the provider deadline."
            except PubMedProbeError as error:
                if error.http_status in (400,401,403):
                    return "PubMed rejected the request. Check the NCBI contact and optional API key in Windows Credential Manager, then restart."
                if error.http_status==429:
                    return "PubMed is limiting requests. Wait before trying the connection test again."
                return "PubMed did not return a valid count. Check your network, NCBI service availability and saved settings."
            return "PubMed returned a valid count for the connection test."
        finally:
            self._lock.release()


def render_settings(ui,flow):
    import asyncio
    from research_y.desktop.flow import ProjectFlowError
    state=flow.state()
    with ui.expansion("Application and source settings").props("data-testid=desktop-settings"):
        ui.label('Connect your databases').classes('section-title')
        ui.label('1. Open Credential Manager. Choose Windows Credentials, then Add a generic credential.')
        async def credentials():
            try:
                await asyncio.to_thread(open_credential_manager)
            except OSError:
                ui.notify("Open Credential Manager from the Windows Start menu.")
        ui.button("Open Windows Credential Manager",on_click=credentials)
        ui.label('2. Add an entry for each database. Copy the exact address shown below.')
        with ui.expansion('PubMed credential fields'):
            ui.label('Internet or network address: ' + PUBMED_TARGET).classes('query-text')
            ui.label('User name: your NCBI contact email. Password: your NCBI API key, if you have one; otherwise leave it blank.')
        with ui.expansion('Web of Science credential fields'):
            ui.label('Internet or network address: ' + STARTER_TARGET).classes('query-text')
            ui.label('User name: a label such as Web of Science. Password: your institutional Starter API key.')
        ui.label('3. Save the entries, close RESEARCH-Y and reopen it. Your projects remain saved.')
        ui.label("PubMed · "+("settings found" if state["pubmed_profile_configured"] else "needs setup")).classes('message info')
        ui.label("Web of Science · "+("settings found" if state["wos_profile_configured"] else "needs setup")).classes('message info')
        ui.label("The PubMed test sends one count-only request for 1[uid] with your NCBI tool, contact and configured key.")
        result=ui.label("")
        async def check():
            result.set_text("Checking PubMed…")
            try:
                message=await asyncio.to_thread(flow.test_pubmed_connection)
            except (ProjectFlowError,OSError,ValueError):
                message="Check the saved PubMed settings and restart RESEARCH-Y."
            result.set_text(message)
        ui.button("Test PubMed connection",on_click=check).set_enabled(state["pubmed_profile_configured"])
        ui.label("To verify Web of Science access and current quota, select a saved run and use its Starter pilot.")
        ui.label("If Starter refuses access, check the institutional key and Starter entitlement. If a quota is exhausted, check its recorded reset before resuming.")


def source_error_help(code):
    if "auth" in code or "forbidden" in code or "unauthor" in code:
        return "Access was refused. Verify the source key and entitlement in Windows Credential Manager, then restart."
    if any(part in code for part in ("limit","quota","hold")):
        return "The source is limiting requests. Inspect the recorded quota or retry deadline before resuming."
    return "The source request failed. Check connectivity and provider status, then inspect the saved checkpoint."


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
